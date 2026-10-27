import gzip
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = ("Back up the database (consistent copy, safe while the app runs), keep the last N locally in "
            "backups/, and upload it to the R2 bucket BACKUP_R2_BUCKET when set. Run nightly (deploy/ does this).")

    def add_arguments(self, parser):
        parser.add_argument("--keep", type=int, default=14, help="Local backups to keep (default 14)")
        parser.add_argument("--dir", default=str(settings.BASE_DIR / "backups"))

    def handle(self, keep=14, dir=None, **opts):
        if connection.vendor != "sqlite":
            raise CommandError("backup_db handles SQLite; use your database provider's backups instead.")
        out_dir = Path(dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")
        target = out_dir / f"weddingsnap-{stamp}.sqlite3.gz"

        connection.ensure_connection()
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "db.sqlite3"
            dest = sqlite3.connect(copy)
            connection.connection.backup(dest)  # SQLite online backup: consistent even during writes
            dest.close()
            with copy.open("rb") as src, gzip.open(target, "wb") as gz:
                shutil.copyfileobj(src, gz)
        self.stdout.write(f"Saved {target} ({target.stat().st_size / 1e6:.1f} MB)")

        for old in sorted(out_dir.glob("weddingsnap-*.sqlite3.gz"))[:-keep or None]:
            old.unlink()

        if settings.BACKUP_R2_BUCKET:
            if not (settings.R2_ENDPOINT and settings.R2_ACCESS_KEY_ID and settings.R2_SECRET_ACCESS_KEY):
                raise CommandError("BACKUP_R2_BUCKET is set but the R2_* credentials aren't.")
            import boto3
            from botocore.config import Config
            client = boto3.client(
                "s3", endpoint_url=settings.R2_ENDPOINT, region_name="auto",
                aws_access_key_id=settings.R2_ACCESS_KEY_ID, aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
                config=Config(request_checksum_calculation="when_required", response_checksum_validation="when_required"),
            )
            key = f"db/{target.name}"
            client.upload_file(str(target), settings.BACKUP_R2_BUCKET, key)
            self.stdout.write(self.style.SUCCESS(f"Uploaded to r2://{settings.BACKUP_R2_BUCKET}/{key}"))
        else:
            self.stdout.write(self.style.WARNING("BACKUP_R2_BUCKET not set: backup kept on this server only."))
