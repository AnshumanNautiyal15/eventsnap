"""JSON API used by the React (Material UI) frontend in frontend/."""
import json
from functools import wraps

from django.contrib.auth import authenticate, login, logout
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from . import drive, faces, indexing, quota, ratelimit, storage
from .forms import EventForm, SelfieForm
from .models import Event, GoogleAccount, Photo
from .views import SESSION_KEY, guest_url, matched_ids


def drive_feature(view):
    """Drive endpoints answer 404 while Google Drive linking is switched off (GOOGLE_DRIVE_ENABLED)."""
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not drive.enabled():
            return _error("Google Drive linking isn't available.", status=404)
        return view(request, *args, **kwargs)
    return wrapper


def api_login_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"error": "Please log in."}, status=401)
        return view(request, *args, **kwargs)
    return wrapper


def _body(request):
    try:
        return json.loads(request.body or b"{}")
    except ValueError:
        return {}


def _error(message, status=400, **extra):
    return JsonResponse({"error": message, **extra}, status=status)


def _form_errors(form):
    return {field: [str(e) for e in errors] for field, errors in form.errors.items()}


def _own_event(request, slug):
    return get_object_or_404(Event, slug=slug, owner=request.user)


def _user_json(user):
    return {"username": user.username, "is_admin": user.is_superuser}


# --- Auth ----------------------------------------------------------------------

@require_GET
@ensure_csrf_cookie
def me(request):
    user = request.user
    return JsonResponse({"user": _user_json(user) if user.is_authenticated else None})


@require_POST
def login_view(request):
    data = _body(request)
    if not ratelimit.allow("login", f"{ratelimit.client_ip(request)}|{str(data.get('username', '')).lower()}"):
        return ratelimit.too_many()
    user = authenticate(request, username=data.get("username", ""), password=data.get("password", ""))
    if user is None:
        return _error("Username or password is incorrect.")
    login(request, user)
    return JsonResponse({"user": _user_json(user)})


@require_POST
def logout_view(request):
    logout(request)
    return JsonResponse({"user": None})


# --- Events (photographer) ---------------------------------------------------------

def _stats(event):
    photos = event.photos.exclude(status=Photo.REMOVED)
    counts = dict(photos.values_list("status").annotate(n=Count("pk")))
    blocked = photos.filter(status=Photo.FAILED, error__startswith=quota.STORAGE_FULL).count()
    return {
        "total": sum(counts.values()),
        "done": counts.get(Photo.DONE, 0),
        "pending": counts.get(Photo.PENDING, 0),  # not indexed yet: waiting for "Index photos"
        "queued": counts.get(Photo.QUEUED, 0),  # indexing in progress
        "failed": counts.get(Photo.FAILED, 0) - blocked,
        "storage_blocked": blocked,  # failed only because the photographer's storage is full
        "no_faces": photos.filter(status=Photo.DONE, face_count=0).count(),
        "faces": event.faces.count(),
    }


def _photo_json(photo):
    return {
        "id": str(photo.pk),
        "name": photo.original_name,
        "folder": photo.folder_path,
        "status": photo.status,
        "status_label": photo.get_status_display(),
        "face_count": photo.face_count,
        "from_drive": photo.from_drive,
        "error": photo.error,
        "thumb": reverse("photo_file", args=[photo.pk, "thumb"]) if photo.thumbnail else None,
        "full": reverse("photo_file", args=[photo.pk, "full"]),
        "download": reverse("photo_file", args=[photo.pk, "download"]),
    }


@api_login_required
@require_http_methods(["GET", "POST"])
def events(request):
    if request.method == "POST":
        form = EventForm(_body(request))
        if not form.is_valid():
            return _error("Please fix the highlighted fields.", errors=_form_errors(form))
        event = form.save(commit=False)
        event.owner = request.user
        event.save()
        if storage.is_local():
            event.originals_dir.mkdir(parents=True, exist_ok=True)
        return JsonResponse({"slug": event.slug}, status=201)

    qs = request.user.events.annotate(
        n_photos=Count("photos", filter=~Q(photos__status=Photo.REMOVED)),
        n_done=Count("photos", filter=Q(photos__status=Photo.DONE)),
    )
    return JsonResponse({"storage": quota.summary(request.user), "events": [
        {"slug": e.slug, "name": e.name, "date": e.date, "is_active": e.is_active,
         "photos": e.n_photos, "indexed": e.n_done, "drive_folder": e.drive_folder_name}
        for e in qs
    ]})


@api_login_required
@require_GET
def event_detail(request, slug):
    event = _own_event(request, slug)
    indexing.maybe_auto_sync(event)
    account = GoogleAccount.objects.filter(user=request.user).first()
    return JsonResponse({
        "event": {
            "slug": event.slug,
            "name": event.name,
            "date": event.date,
            "is_active": event.is_active,
            "guest_url": guest_url(request, event),
            "qr_url": reverse("event_qr", args=[event.slug]),
            # Copying files onto the server only makes sense with local storage.
            "folder": str(event.originals_dir) if storage.is_local() else None,
        },
        "stats": _stats(event),
        "storage": quota.summary(request.user),
        "recent": [_photo_json(p) for p in event.photos.exclude(status=Photo.REMOVED).order_by("-uploaded_at")[:24]],
        "drive": {
            "enabled": drive.enabled(),
            "public_configured": drive.public_configured(),
            "oauth_configured": drive.oauth_configured(),
            "account_email": account.email if account else None,
            "connected": account is not None,
            "connect_url": reverse("google_connect"),
            "folder_id": event.drive_folder_id,
            "folder_name": event.drive_folder_name,
            "access": event.get_drive_access_display() if event.drive_access else "",
            "synced_at": event.drive_synced_at,
            "syncing": indexing.is_syncing(event),
            "error": event.drive_sync_error,
            # Private-folder access lapsed (revoked, or Google's 7-day expiry for apps in Testing mode).
            "needs_reconnect": event.drive_access == drive.ACCOUNT and drive.oauth_configured() and (
                account is None or "reconnect" in event.drive_sync_error.lower()
            ),
            "video_count": event.drive_video_count,
        },
    })


@api_login_required
@require_GET
def event_status(request, slug):
    event = _own_event(request, slug)
    return JsonResponse({
        **_stats(event),
        "drive_syncing": indexing.is_syncing(event),
        "drive_error": event.drive_sync_error,
        "drive_synced_at": event.drive_synced_at,
    })


@api_login_required
@require_POST
@ratelimit.limit("upload", lambda request, **kw: f"user:{request.user.pk}")
def event_upload(request, slug):
    event = _own_event(request, slug)
    limit, used = quota.limit_bytes(request.user), quota.usage_bytes(request.user)
    added = skipped = rejected = 0
    for f in request.FILES.getlist("photos"):
        if not indexing.is_image_name(f.name):
            skipped += 1
        elif limit is not None and used + f.size > limit:
            rejected += 1
        else:
            indexing.add_upload(event, f)
            used += f.size
            added += 1
    body = {"added": added, "skipped": skipped, "rejected": rejected, "storage": quota.summary(request.user)}
    if rejected:
        body["error"] = (f"Storage full: {quota.format_bytes(used)} of {quota.format_bytes(limit)} used. "
                         "Ask the admin for more storage to upload the rest.")
    return JsonResponse(body)


@api_login_required
@require_POST
def event_scan_folder(request, slug):
    event = _own_event(request, slug)
    if not storage.is_local():
        return _error("Scanning a server folder isn't available with cloud storage. Upload the photos instead.")
    n = indexing.sync_folder(event)
    return JsonResponse({"message": f"Found {n} new photos in the folder. Press Index photos to make them searchable."
                                    if n else "No new photos in the folder."})


@api_login_required
@require_POST
def event_reprocess(request, slug):
    event = _own_event(request, slug)
    n = indexing.start_indexing(event, retry_failed=True)
    return JsonResponse({"message": f"Indexing {n} photo{'s' if n != 1 else ''}."})


@api_login_required
@require_POST
def event_index(request, slug):
    """The "Index photos" button: find faces in every photo that hasn't been indexed yet."""
    event = _own_event(request, slug)
    n = indexing.start_indexing(event)
    if not n:
        return JsonResponse({"queued": 0, "message": "Everything is already indexed."})
    return JsonResponse({"queued": n, "message": f"Indexing {n} photo{'s' if n != 1 else ''}. "
                                                 "They become searchable as each one finishes."})


@api_login_required
@require_POST
def event_delete(request, slug):
    event = _own_event(request, slug)
    name = event.name
    event.delete()  # its stored files are removed in the background (see signals.py)
    return JsonResponse({"message": f"Deleted “{name}”. Its QR code no longer works."})


@api_login_required
@require_GET
def event_no_face_photos(request, slug):
    """Photos where no faces were found: guests can never match them, so they only use storage."""
    event = _own_event(request, slug)
    photos = event.photos.filter(status=Photo.DONE, face_count=0).order_by("folder_path", "original_name")
    return JsonResponse({"photos": [
        {"id": str(p.pk), "name": p.original_name, "folder": p.folder_path, "from_drive": p.from_drive,
         "bytes": p.original_bytes + p.thumb_bytes, "thumb": _photo_json(p)["thumb"], "full": _photo_json(p)["full"]}
        for p in photos
    ]})


@api_login_required
@require_POST
def event_remove_photos(request, slug):
    event = _own_event(request, slug)
    ids = _body(request).get("ids") or []
    try:
        photos = list(event.photos.filter(pk__in=ids).exclude(status=Photo.REMOVED))
    except Exception:  # malformed ids
        return _error("Invalid photo selection.")
    freed = sum(p.original_bytes + p.thumb_bytes for p in photos)
    removed = indexing.remove_photos(photos)
    return JsonResponse({
        "removed": removed,
        "message": f"Removed {removed} photo{'s' if removed != 1 else ''}, freeing {quota.format_bytes(freed)}.",
        "storage": quota.summary(request.user),
    })


@api_login_required
@require_POST
def event_toggle(request, slug):
    event = _own_event(request, slug)
    event.is_active = not event.is_active
    event.save(update_fields=["is_active"])
    return JsonResponse({"is_active": event.is_active})


# --- Google Drive ------------------------------------------------------------------

@api_login_required
@drive_feature
@require_POST
def event_drive_folder(request, slug):
    event = _own_event(request, slug)
    folder_id, resource_key = drive.parse_folder_link(_body(request).get("folder_link"))
    if not folder_id:
        return _error("That doesn't look like a Google Drive folder link.")

    # Prefer the public link (nothing to connect); fall back to the photographer's Google account.
    keys = {folder_id: resource_key} if resource_key else {}
    attempts = []
    if drive.public_configured():
        attempts.append(drive.Access(drive.PUBLIC, request.user, keys))
    if drive.oauth_configured() and GoogleAccount.objects.filter(user=request.user).exists():
        attempts.append(drive.Access(drive.ACCOUNT, request.user, keys))
    if not attempts:
        if drive.oauth_configured():
            return _error("Connect your Google account first, then link the folder.")
        return _error("Google Drive isn't set up on this server yet (missing GOOGLE_API_KEY).")
    for access in attempts:
        try:
            folder = drive.get_folder(access, folder_id)
            break
        except drive.DriveError as exc:
            error = exc
    else:
        return _error(str(error) if len(attempts) == 1 else f"{error} (Tried the public link and your connected account.)")

    if folder_id != event.drive_folder_id:
        indexing.delete_photos(event.photos.exclude(drive_file_id=""))
    event.drive_folder_id, event.drive_folder_name = folder_id, folder["name"]
    event.drive_resource_key, event.drive_access = resource_key, access.mode
    event.drive_synced_at, event.drive_sync_error = None, ""
    event.save()
    indexing.start_drive_sync(event)
    return JsonResponse({"message": f"Linked “{folder['name']}”. Reading all its subfolders now. Press Index photos once they're listed."})


@api_login_required
@drive_feature
@require_POST
def event_drive_sync(request, slug):
    event = _own_event(request, slug)
    started = bool(event.drive_folder_id) and indexing.start_drive_sync(event)
    return JsonResponse({"started": started})


@api_login_required
@drive_feature
@require_POST
def event_drive_unlink(request, slug):
    event = _own_event(request, slug)
    indexing.delete_photos(event.photos.exclude(drive_file_id=""))
    event.drive_folder_id = event.drive_folder_name = event.drive_sync_error = ""
    event.drive_resource_key = event.drive_access = ""
    event.drive_synced_at = None
    event.save()
    return JsonResponse({"message": "Drive folder unlinked. Its photos were removed from this event (nothing was deleted in Drive)."})


@api_login_required
@drive_feature
@require_POST
def google_disconnect(request):
    drive.disconnect(request.user)
    return JsonResponse({"message": "Google Drive disconnected. Already-indexed photos stay searchable, but guests "
                                    "can't download originals from private folders until you reconnect."})


# --- Guests ------------------------------------------------------------------------

@require_GET
@ensure_csrf_cookie
def guest_event(request, slug):
    event = get_object_or_404(Event, slug=slug)
    if event.is_active:
        indexing.maybe_auto_sync(event)
    return JsonResponse({
        "name": event.name,
        "date": event.date,
        "is_active": event.is_active,
        "indexed": event.photos.filter(status=Photo.DONE).count(),
    })


@require_POST
@ratelimit.limit("guest_search", lambda request, slug: f"{ratelimit.client_ip(request)}|{slug}")
def guest_search(request, slug):
    event = get_object_or_404(Event, slug=slug)
    if not event.is_active:
        return _error("Photo search for this event is closed.", status=403)
    form = SelfieForm(request.POST, request.FILES)
    if not form.is_valid():
        return _error("Please choose a photo of yourself.")
    try:
        # The selfie is only held in memory for matching; it is never saved.
        vec = faces.selfie_embedding(faces.load_image(form.cleaned_data["selfie"]))
    except faces.NoFaceFound:
        return _error("We couldn't see a face in that photo. Try again facing the camera in good light.")
    matches = indexing.find_matches(event, vec)
    store = request.session.get(SESSION_KEY, {})
    store[event.slug] = [str(pid) for pid, _ in matches]
    request.session[SESSION_KEY] = store
    return JsonResponse({"count": len(matches)})


@require_GET
def guest_results(request, slug):
    event = get_object_or_404(Event, slug=slug)
    ids = matched_ids(request, event)
    if ids is None:
        return _error("Take a selfie first.", status=404)
    sections = {}
    for photo in event.photos.filter(pk__in=ids).order_by("folder_path", "original_name"):
        sections.setdefault(photo.folder_path, []).append({
            "id": str(photo.pk),
            "thumb": reverse("photo_file", args=[photo.pk, "thumb"]),
            "download": reverse("photo_file", args=[photo.pk, "download"]),
        })
    return JsonResponse({
        "event": {"name": event.name, "date": event.date},
        "count": sum(len(p) for p in sections.values()),
        "sections": [{"folder": folder, "photos": photos} for folder, photos in sections.items()],
        "zip_url": reverse("guest_download_all", args=[event.slug]),
    })
