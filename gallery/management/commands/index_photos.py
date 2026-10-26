import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections

from gallery.indexing import index_photo, release_memory
from gallery.models import Event, Photo

_niced = False  # os.nice() adds up, so lower this process's priority only once


class Command(BaseCommand):
    help = ("Find faces in photos that haven't been indexed yet (the same as pressing \"Index photos\" in the app). "
            "Without arguments: every event.")

    def add_arguments(self, parser):
        parser.add_argument("event_slugs", nargs="*", metavar="event_slug", help="Only these events")
        parser.add_argument("--photographer", metavar="USERNAME", help="Only this photographer's events")
        parser.add_argument("--retry-failed", action="store_true", help="Also retry photos that failed before")
        parser.add_argument("--all", action="store_true", help="Re-index every photo, even ones already indexed")
        parser.add_argument("--workers", type=int, default=settings.INDEX_DOWNLOADS,
                            help=f"Photos fetched/processed in parallel (default {settings.INDEX_DOWNLOADS})")
        parser.add_argument("--batch-size", type=int, default=settings.INDEX_BATCH_SIZE,
                            help=f"Photos per batch (default {settings.INDEX_BATCH_SIZE})")
        parser.add_argument("--pause", type=float, default=settings.INDEX_BATCH_PAUSE,
                            help=f"Seconds to rest between batches so the site stays responsive (default {settings.INDEX_BATCH_PAUSE})")
        parser.add_argument("--dry-run", action="store_true", help="Only show how many photos would be indexed")

    def handle(self, event_slugs, photographer=None, retry_failed=False, all=False, workers=1, dry_run=False,
               batch_size=10, pause=0.0, **opts):
        photos = Photo.objects.exclude(status=Photo.REMOVED).select_related("event__owner")
        if event_slugs:
            found = set(Event.objects.filter(slug__in=event_slugs).values_list("slug", flat=True))
            if missing := set(event_slugs) - found:
                raise CommandError(f"No event with slug: {', '.join(sorted(missing))}")
            photos = photos.filter(event__slug__in=event_slugs)
        if photographer:
            if not User.objects.filter(username=photographer).exists():
                raise CommandError(f"No photographer {photographer!r}")
            photos = photos.filter(event__owner__username=photographer)
        if not all:
            statuses = [Photo.PENDING, Photo.QUEUED] + ([Photo.FAILED] if retry_failed else [])
            photos = photos.filter(status__in=statuses)

        photos = list(photos.order_by("event_id", "uploaded_at"))
        if dry_run or not photos:
            events = len({p.event_id for p in photos})
            self.stdout.write(f"{len(photos)} photos to index in {events} event{'s' if events != 1 else ''}.")
            return

        # Mark them as in progress so the app shows "Indexing…" for photos this command is working on.
        Photo.objects.filter(pk__in=[p.pk for p in photos]).update(status=Photo.QUEUED)
        for p in photos:
            p.status = Photo.QUEUED

        lock, counts, started = threading.Lock(), {"done": 0, "failed": 0, "faces": 0}, time.monotonic()

        def run(photo, threaded=True):
            if threaded:  # each worker thread has its own database connection
                close_old_connections()
            try:
                index_photo(photo)
            finally:
                if threaded:
                    close_old_connections()
            with lock:
                key = "done" if photo.status == Photo.DONE else "failed"
                counts[key] += 1
                counts["faces"] += photo.face_count
                n = counts["done"] + counts["failed"]
                note = f"{photo.face_count} faces" if key == "done" else f"FAILED: {photo.error[:80]}"
                self.stdout.write(f"[{n}/{len(photos)}] {photo.event.slug}/{photo.original_name}: {note}")

        # A separate process from the web server: lower its priority so guests' requests come first.
        global _niced
        if settings.INDEX_NICE and hasattr(os, "nice") and not _niced:
            os.nice(settings.INDEX_NICE)
            _niced = True
        batch_size = max(1, batch_size)
        batches = [photos[i:i + batch_size] for i in range(0, len(photos), batch_size)]
        pool = ThreadPoolExecutor(max_workers=workers) if workers > 1 else None
        try:
            for n, batch in enumerate(batches, 1):
                if pool:
                    list(pool.map(run, batch))
                else:
                    for photo in batch:
                        run(photo, threaded=False)
                release_memory()
                if len(batches) > 1:
                    self.stdout.write(f"-- batch {n}/{len(batches)} done")
                if pause and n < len(batches):
                    time.sleep(pause)
        finally:
            if pool:
                pool.shutdown()

        took = time.monotonic() - started
        self.stdout.write(self.style.SUCCESS(
            f"Indexed {counts['done']} photos ({counts['faces']} faces) in {took:.0f}s"
            + (f"; {counts['failed']} failed (run again with --retry-failed)" if counts["failed"] else "")
        ))
