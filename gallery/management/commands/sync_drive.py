from django.core.management import call_command
from django.core.management.base import BaseCommand

from gallery import drive, indexing
from gallery.models import Event


class Command(BaseCommand):
    help = ("Pick up new, changed and deleted photos from Google Drive folders. New photos wait for "
            "\"Index photos\" unless you pass --index.")

    def add_arguments(self, parser):
        parser.add_argument("event_slug", nargs="?", help="Only this event (default: every active event with a Drive folder)")
        parser.add_argument("--index", action="store_true", help="Also index the new photos right away")

    def handle(self, event_slug=None, **opts):
        if not drive.enabled():
            self.stdout.write("Google Drive linking is switched off (GOOGLE_DRIVE_ENABLED=0); nothing to sync.")
            return
        events = Event.objects.exclude(drive_folder_id="").select_related("owner")
        events = events.filter(slug=event_slug) if event_slug else events.filter(is_active=True)
        for event in events:
            try:
                added, updated, removed = indexing.sync_drive(event)
            except drive.DriveError as exc:
                self.stderr.write(f"{event.slug}: {exc}")
                continue
            self.stdout.write(f"{event.slug}: {added} new, {updated} changed, {removed} removed")
            if (added or updated) and opts["index"]:
                call_command("index_photos", event.slug, stdout=self.stdout)
