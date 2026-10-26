from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError

from gallery import storage
from gallery.models import Photo


class Command(BaseCommand):
    help = ("One-time move to Cloudflare R2: upload the photos and previews already stored on this machine "
            "(MEDIA_ROOT) to R2, keeping the same names so existing events keep working.")

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Only report what would be uploaded")

    def handle(self, dry_run=False, **opts):
        if storage.is_local():
            raise CommandError("R2 isn't configured yet. Put the R2_* settings in .env first (see README).")
        root = Path(settings.MEDIA_ROOT)
        names = set()
        for photo in Photo.objects.exclude(status=Photo.REMOVED).only("image", "thumbnail").iterator():
            names.update(n for n in (photo.image.name, photo.thumbnail.name) if n)

        uploaded = skipped = missing = size = 0
        for i, name in enumerate(sorted(names), 1):
            local = root / name
            if not local.is_file():
                missing += 1
                continue
            if default_storage.exists(name):
                skipped += 1
                continue
            size += local.stat().st_size
            if not dry_run:
                with local.open("rb") as fh:
                    saved = default_storage.save(name, File(fh))
                if saved != name:  # never expected since we checked exists(); keep the DB pointing at the right file
                    raise CommandError(f"R2 stored {name} as {saved}; stopping so nothing gets mismatched.")
            uploaded += 1
            if uploaded % 100 == 0:
                self.stdout.write(f"  {uploaded} files uploaded…")

        verb = "Would upload" if dry_run else "Uploaded"
        self.stdout.write(self.style.SUCCESS(
            f"{verb} {uploaded} files ({size / 1e6:.1f} MB); {skipped} already in R2; {missing} missing on disk."
        ))
        if not dry_run and uploaded:
            self.stdout.write(f"Once you've checked the app works, you can delete {root} to free disk space.")
