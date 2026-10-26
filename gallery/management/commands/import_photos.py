from pathlib import Path

from django.core.files import File
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from gallery import faces, quota
from gallery.models import Event, Photo


class Command(BaseCommand):
    help = "Upload every image in a folder (recursively) into an event and index the faces. Works with R2 and local storage."

    def add_arguments(self, parser):
        parser.add_argument("event_slug")
        parser.add_argument("folder")

    def handle(self, event_slug, folder, **opts):
        event = Event.objects.filter(slug=event_slug).select_related("owner").first()
        if not event:
            raise CommandError(f"No event with slug {event_slug!r}")
        src = Path(folder).expanduser()
        if not src.is_dir():
            raise CommandError(f"{src} is not a folder")

        paths = [p for p in sorted(src.rglob("*"))
                 if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in faces.IMAGE_EXTENSIONS]
        total = sum(p.stat().st_size for p in paths)
        if not quota.has_room(event.owner, total):
            self.stderr.write(self.style.WARNING(
                f"{quota.format_bytes(total)} goes over {event.owner}'s storage limit "
                f"({quota.format_bytes(quota.usage_bytes(event.owner))} of {quota.format_bytes(quota.limit_bytes(event.owner))} used). "
                "Importing anyway, since you're running this as the server admin."
            ))

        for i, path in enumerate(paths, 1):
            rel = path.relative_to(src)
            photo = Photo(event=event, original_name=path.name, original_bytes=path.stat().st_size,
                          folder_path=rel.parent.as_posix() if rel.parent != Path(".") else "")
            with path.open("rb") as fh:
                photo.image.save(path.name, File(fh), save=True)
            self.stdout.write(f"[{i}/{len(paths)}] uploaded {rel}")
        self.stdout.write(f"Uploaded {len(paths)} images ({quota.format_bytes(total)})")
        call_command("index_photos", event.slug, stdout=self.stdout)
