"""Indexing photos into face embeddings, plus matching a guest's selfie against an event."""
import logging
import os
import queue
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

import numpy as np
from django.conf import settings
from django.core.files.base import ContentFile
from django.db import close_old_connections, transaction
from django.db.models import Count, Max, Sum
from django.utils import timezone

from . import drive, faces, quota, storage
from .faces import IMAGE_EXTENSIONS
from .models import Face, Photo

log = logging.getLogger(__name__)

# Downloads run in many threads at once; face detection is CPU-bound and only gets this many slots.
_cpu_slots = threading.BoundedSemaphore(settings.INDEX_CPU_SLOTS)


def _fetch_drive_photo(photo):
    """Bytes to index for a Drive photo: Drive's rendered preview if possible, else the original."""
    access = drive.Access.for_event(photo.event)
    try:
        return drive.preview(access, photo.drive_file_id, photo.drive_resource_key, settings.DRIVE_PREVIEW_SIZE), True
    except drive.NoPreview:
        return drive.download(access, photo.drive_file_id, photo.drive_resource_key), False


class StorageFull(Exception):
    pass


def index_photo(photo):
    """Detect faces in one photo, store their embeddings and build a preview thumbnail."""
    try:
        if photo.from_drive:
            # Only held in memory: Drive stays the storage for originals.
            data, is_preview = _fetch_drive_photo(photo)
        else:
            with photo.image.open("rb") as fh:
                data, is_preview = fh.read(), False
        with _cpu_slots:
            try:
                img = faces.load_image(data)
            except Exception:
                if not is_preview:
                    raise
                # Drive's preview was unusable; fall back to decoding the original ourselves.
                data = drive.download(drive.Access.for_event(photo.event), photo.drive_file_id, photo.drive_resource_key)
                img = faces.load_image(data)
            found = faces.detect_faces(img)
            thumb = faces.make_thumbnail(img)
        # Uploaded photos were checked against the limit on upload; Drive previews are checked here.
        if photo.from_drive and not quota.has_room(photo.event.owner, len(thumb) - photo.thumb_bytes):
            raise StorageFull(f"{quota.STORAGE_FULL}: ask the admin for more storage, then press Retry.")
    except Exception as exc:  # corrupt file, unsupported format, Drive access lost, storage full...
        log.warning("Indexing failed for %s (%s): %s", photo.pk, photo.original_name, exc)
        photo.status, photo.error = Photo.FAILED, str(exc)[:1000]
        photo.save(update_fields=["status", "error"])
        return

    with transaction.atomic():
        photo.faces.all().delete()
        Face.objects.bulk_create(
            Face(photo=photo, event_id=photo.event_id, embedding=vec.tobytes(), box=box) for vec, box in found
        )
        if photo.thumbnail:
            photo.thumbnail.delete(save=False)
        photo.thumbnail.save(f"{photo.pk}.jpg", ContentFile(thumb), save=False)
        photo.face_count, photo.status, photo.error, photo.thumb_bytes = len(found), Photo.DONE, "", len(thumb)
        photo.save(update_fields=["thumbnail", "face_count", "status", "error", "thumb_bytes"])


# --- Background indexing, in batches ---------------------------------------------
# One dispatcher thread takes up to INDEX_BATCH_SIZE queued photos, indexes them with INDEX_DOWNLOADS
# low-priority threads (of which only INDEX_CPU_SLOTS analyse at once), pauses INDEX_BATCH_PAUSE seconds
# so web requests get the CPU, then takes the next batch. Memory stays bounded: at most INDEX_DOWNLOADS
# photos are held at a time. Photos left QUEUED by a restart resume when "Index photos" is pressed again
# or `index_photos` runs.

_queue = queue.Queue()
_queued = set()
_lock = threading.Lock()
_dispatcher = None


def lower_thread_priority():
    """Make the calling thread yield the CPU to web requests (Linux, where each thread has its own nice value)."""
    if sys.platform.startswith("linux") and settings.INDEX_NICE:
        try:
            os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), settings.INDEX_NICE)
        except OSError:
            pass


def release_memory():
    """Hand freed memory back to the OS between batches (glibc keeps it otherwise; Linux only)."""
    if sys.platform.startswith("linux"):
        try:
            import ctypes
            ctypes.CDLL("libc.so.6").malloc_trim(0)
        except (OSError, AttributeError):
            pass


def take_batch(source, size):
    """Block for the first photo id, then take whatever else is waiting, up to `size`."""
    batch = [source.get()]
    while len(batch) < size:
        try:
            batch.append(source.get_nowait())
        except queue.Empty:
            break
    return batch


def _index_by_id(photo_id):
    close_old_connections()
    try:
        photo = Photo.objects.select_related("event__owner").filter(pk=photo_id, status=Photo.QUEUED).first()
        if photo:
            index_photo(photo)
    except Exception:
        log.exception("Indexing error on %s", photo_id)
    finally:
        with _lock:
            _queued.discard(photo_id)
        close_old_connections()


def _dispatch():
    lower_thread_priority()
    with ThreadPoolExecutor(settings.INDEX_DOWNLOADS, thread_name_prefix="face-indexer",
                            initializer=lower_thread_priority) as pool:
        while True:
            batch = take_batch(_queue, settings.INDEX_BATCH_SIZE)
            list(pool.map(_index_by_id, batch))
            release_memory()
            if settings.INDEX_BATCH_PAUSE and not _queue.empty():
                time.sleep(settings.INDEX_BATCH_PAUSE)


def enqueue(photo_ids):
    global _dispatcher
    with _lock:
        if _dispatcher is None or not _dispatcher.is_alive():
            _dispatcher = threading.Thread(target=_dispatch, name="face-index-dispatcher", daemon=True)
            _dispatcher.start()
        for pid in photo_ids:
            if pid not in _queued:
                _queued.add(pid)
                _queue.put(pid)


def start_indexing(event, retry_failed=False):
    """The photographer pressed "Index photos": queue everything not indexed yet (and failed ones on retry).

    Photos already QUEUED are queued again too, so pressing it after a server restart resumes the work.
    Returns how many photos are now being indexed.
    """
    statuses = [Photo.PENDING] + ([Photo.FAILED] if retry_failed else [])
    event.photos.filter(status__in=statuses).update(status=Photo.QUEUED, error="")
    ids = list(event.photos.filter(status=Photo.QUEUED).values_list("pk", flat=True))
    enqueue(ids)
    return len(ids)


def sync_folder(event):
    """Register image files dropped straight into the event's originals folder (e.g. via Finder/FTP).

    Only with local storage; with R2 use the `import_photos` command or the uploader.
    """
    if not storage.is_local():
        return 0
    folder = event.originals_dir
    folder.mkdir(parents=True, exist_ok=True)
    known = set(event.photos.values_list("image", flat=True))
    created = []
    for path in sorted(folder.rglob("*")):
        if path.suffix.lower() not in IMAGE_EXTENSIONS or not path.is_file() or path.name.startswith("."):
            continue
        rel = path.relative_to(settings.MEDIA_ROOT).as_posix()
        if rel in known:
            continue
        photo = Photo(event=event, original_name=path.name, original_bytes=path.stat().st_size)
        photo.image.name = rel
        photo.save()
        created.append(photo.pk)
    return len(created)  # left PENDING until the photographer presses "Index photos"


# --- Google Drive sync -------------------------------------------------------

def sync_drive(event):
    """Mirror the event's Drive folder (recursively): add new photos, re-index edited ones, drop deleted ones.

    Returns (added, updated, removed). Raises drive.DriveError on access problems.
    """
    try:
        listing = drive.list_images(drive.Access.for_event(event), event.drive_folder_id)
    except drive.DriveError as exc:
        event.drive_sync_error = str(exc)
        event.save(update_fields=["drive_sync_error"])
        raise

    existing = {p.drive_file_id: p for p in event.photos.exclude(drive_file_id="")}
    new_photos, changed_ids, renamed = [], [], []
    for f in listing.images:
        md5, modified = f.get("md5Checksum", ""), f.get("modifiedTime", "")
        photo = existing.get(f["id"])
        if photo is not None and photo.status == Photo.REMOVED:
            continue  # the photographer removed it from the event; keep it out
        if photo is None:
            new_photos.append(Photo(
                event=event, drive_file_id=f["id"], drive_md5=md5, drive_modified=modified,
                drive_resource_key=f.get("resourceKey", ""), mime_type=f["mimeType"],
                original_name=f["name"], folder_path=f["path"],
            ))
            continue
        content_changed = (md5 != photo.drive_md5) if md5 else (modified != photo.drive_modified)
        if content_changed or photo.original_name != f["name"] or photo.folder_path != f["path"]:
            photo.original_name, photo.folder_path = f["name"], f["path"]
            photo.drive_md5, photo.drive_modified = md5, modified
            if content_changed:
                photo.status = Photo.PENDING
                changed_ids.append(photo.pk)
            renamed.append(photo)

    listed = {f["id"] for f in listing.images}
    removed = [p for fid, p in existing.items() if fid not in listed]
    with transaction.atomic():
        Photo.objects.bulk_create(new_photos, batch_size=500)
        Photo.objects.bulk_update(
            renamed, ["original_name", "folder_path", "drive_md5", "drive_modified", "status"], batch_size=500
        )
        delete_photos(removed)
        event.drive_synced_at, event.drive_sync_error = timezone.now(), ""
        event.drive_video_count = listing.videos
        event.save(update_fields=["drive_synced_at", "drive_sync_error", "drive_video_count"])

    # New and changed photos stay PENDING until the photographer presses "Index photos".
    return len(new_photos), len(changed_ids), len(removed)


_syncing = set()  # event ids with a background sync running in this process
_last_attempt = {}  # event id -> when a sync last started (successful or not), for auto-sync backoff


def is_syncing(event):
    return event.pk in _syncing


def start_drive_sync(event):
    """Sync in a background thread so neither photographers nor guests wait. Returns False if already running."""
    with _lock:
        if event.pk in _syncing or not event.drive_folder_id:
            return False
        _syncing.add(event.pk)
        _last_attempt[event.pk] = timezone.now()

    def run():
        close_old_connections()
        try:
            sync_drive(event)
        except drive.DriveError:
            pass  # stored on event.drive_sync_error and shown on the event page
        except Exception:
            log.exception("Drive sync failed for %s", event.slug)
        finally:
            _syncing.discard(event.pk)
            close_old_connections()

    threading.Thread(target=run, name=f"drive-sync-{event.slug}", daemon=True).start()
    return True


def maybe_auto_sync(event):
    """Keep the index fresh while the photographer is still adding photos to Drive, without cron."""
    if not drive.enabled() or not event.drive_folder_id or not event.is_active:
        return
    stale = timezone.now() - timedelta(minutes=settings.DRIVE_AUTO_SYNC_MINUTES)
    last = max(filter(None, [event.drive_synced_at, _last_attempt.get(event.pk)]), default=None)
    if last is None or last < stale:
        start_drive_sync(event)


def delete_photos(photos):
    """Delete photos and their stored files outright."""
    for photo in photos:
        if photo.thumbnail:
            photo.thumbnail.delete(save=False)
        if photo.image and not photo.from_drive:
            photo.image.delete(save=False)
        photo.delete()


def remove_photos(photos):
    """Photographer removing photos from an event: frees their storage and takes them out of guest search.

    Uploaded photos are deleted. Drive photos stay in Drive (we only have read access), so they're kept
    as REMOVED markers, which stops the next sync from adding them back.
    """
    uploads = [p for p in photos if not p.from_drive]
    delete_photos(uploads)
    for photo in photos:
        if photo.from_drive:
            if photo.thumbnail:
                photo.thumbnail.delete(save=False)
            photo.faces.all().delete()
            photo.status, photo.face_count, photo.thumb_bytes, photo.error = Photo.REMOVED, 0, 0, ""
            photo.save(update_fields=["thumbnail", "status", "face_count", "thumb_bytes", "error"])
    return len(photos)


def add_upload(event, uploaded_file):
    photo = Photo(event=event, original_name=os.path.basename(uploaded_file.name), original_bytes=uploaded_file.size)
    photo.image.save(photo.original_name, uploaded_file, save=True)
    return photo  # indexed later, when the photographer presses "Index photos"


def is_image_name(name):
    return Path(name).suffix.lower() in IMAGE_EXTENSIONS


# --- Matching ----------------------------------------------------------------

_matrix_cache = {}  # (event id, slug) -> (stamp, photo ids, matrix); only the most recently searched events
MATRIX_CACHE_EVENTS = 4


def _event_matrix(event):
    """All face embeddings for an event as one (N, 128) matrix, cached until faces change."""
    qs = Face.objects.filter(event=event)
    # Count + max + sum of ids changes whenever faces are added or removed, even if the database reuses
    # ids after deletions; keying by slug too keeps a recreated event id from hitting an old entry.
    stamp = tuple(qs.aggregate(n=Count("pk"), top=Max("pk"), total=Sum("pk")).values())
    key = (event.pk, event.slug)
    cached = _matrix_cache.get(key)
    if cached and cached[0] == stamp:
        return cached[1], cached[2]
    rows = list(qs.values_list("photo_id", "embedding"))
    photo_ids = np.array([r[0] for r in rows], dtype=object)
    matrix = (
        np.frombuffer(b"".join(r[1] for r in rows), dtype=np.float32).reshape(len(rows), -1)
        if rows else np.zeros((0, 128), dtype=np.float32)
    )
    _matrix_cache.pop(key, None)
    _matrix_cache[key] = (stamp, photo_ids, matrix)
    while len(_matrix_cache) > MATRIX_CACHE_EVENTS:  # dicts keep insertion order: drop the oldest
        _matrix_cache.pop(next(iter(_matrix_cache)))
    return photo_ids, matrix


def find_matches(event, selfie_vec, threshold=None):
    """Return [(photo_id, similarity)] for photos containing the selfie's face, best first."""
    threshold = threshold if threshold is not None else settings.FACE_MATCH_THRESHOLD
    photo_ids, matrix = _event_matrix(event)
    if not len(photo_ids):
        return []
    scores = matrix @ selfie_vec  # one matrix multiply: ~1 ms even for 100k faces
    best = {}
    for i in np.nonzero(scores >= threshold)[0]:
        pid, score = photo_ids[i], float(scores[i])
        if score > best.get(pid, -1):
            best[pid] = score
    return sorted(best.items(), key=lambda kv: kv[1], reverse=True)
