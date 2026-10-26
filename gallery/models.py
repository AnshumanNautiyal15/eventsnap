import uuid
from decimal import Decimal

import numpy as np
from django.conf import settings
from django.contrib.auth.models import User
from django.db import models
from django.utils.crypto import get_random_string
from django.utils.text import slugify


def photo_upload_path(instance, filename):
    return f"events/{instance.event.slug}/originals/{filename}"


def thumb_upload_path(instance, filename):
    return f"events/{instance.event.slug}/thumbs/{filename}"


class Event(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="events")
    name = models.CharField(max_length=200)
    date = models.DateField(null=True, blank=True)
    # Random suffix so guests can't guess other events' links.
    slug = models.SlugField(max_length=80, unique=True, editable=False)
    is_active = models.BooleanField(default=True, help_text="Guests can only search while the event is active.")
    created_at = models.DateTimeField(auto_now_add=True)
    # Google Drive folder the photos live in (searched recursively, files stay in Drive).
    drive_folder_id = models.CharField(max_length=200, blank=True)
    drive_folder_name = models.CharField(max_length=300, blank=True)
    drive_resource_key = models.CharField(max_length=200, blank=True)  # from older "anyone with the link" URLs
    drive_access = models.CharField(
        max_length=10, blank=True,
        choices=[("public", "Anyone with the link"), ("account", "Connected Google account")],
    )
    drive_synced_at = models.DateTimeField(null=True, blank=True)
    drive_sync_error = models.TextField(blank=True)
    drive_video_count = models.PositiveIntegerField(default=0)  # videos aren't searched, but we tell the photographer

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name)[:60] or "event"
            self.slug = f"{base}-{get_random_string(6, 'abcdefghjkmnpqrstuvwxyz23456789')}"
        super().save(*args, **kwargs)

    @property
    def originals_dir(self):
        return settings.MEDIA_ROOT / "events" / self.slug / "originals"


class Photo(models.Model):
    PENDING, QUEUED, DONE, FAILED, REMOVED = "pending", "queued", "done", "failed", "removed"
    # PENDING: added but not indexed yet; indexing starts only when the photographer presses "Index photos"
    # (or the `index_photos` command runs). QUEUED: indexing requested, waiting for / being processed by a worker.
    # REMOVED: a Drive photo the photographer deleted from the event. The row stays (without faces or
    # preview) so the next Drive sync doesn't add it back.
    STATUS_CHOICES = [(PENDING, "Not indexed"), (QUEUED, "Indexing"), (DONE, "Indexed"), (FAILED, "Failed"),
                      (REMOVED, "Removed")]

    # UUID keeps photo URLs unguessable, so guests only reach photos they matched.
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="photos")
    # Uploaded photos live in `image`; Drive photos stay in Drive and only keep `thumbnail` locally.
    image = models.ImageField(upload_to=photo_upload_path, max_length=500, blank=True)
    thumbnail = models.ImageField(upload_to=thumb_upload_path, max_length=500, blank=True)
    original_name = models.CharField(max_length=255)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=PENDING, db_index=True)
    face_count = models.PositiveIntegerField(default=0)
    error = models.TextField(blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    drive_file_id = models.CharField(max_length=200, blank=True, db_index=True)
    drive_md5 = models.CharField(max_length=64, blank=True)  # detects files replaced/edited in Drive
    drive_modified = models.CharField(max_length=40, blank=True)  # fallback change marker when Drive has no md5
    drive_resource_key = models.CharField(max_length=200, blank=True)
    mime_type = models.CharField(max_length=100, blank=True)
    folder_path = models.CharField(max_length=500, blank=True)  # subfolder inside the event folder, e.g. "Reception/Candids"
    # Bytes this photo takes in our storage (R2 or disk), counted against the photographer's limit.
    original_bytes = models.BigIntegerField(default=0)  # uploaded originals only; Drive originals stay in Drive
    thumb_bytes = models.BigIntegerField(default=0)

    class Meta:
        ordering = ["uploaded_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["event", "drive_file_id"], condition=~models.Q(drive_file_id=""), name="unique_drive_file_per_event"
            ),
        ]

    def __str__(self):
        return self.original_name

    @property
    def from_drive(self):
        return bool(self.drive_file_id)


class Face(models.Model):
    photo = models.ForeignKey(Photo, on_delete=models.CASCADE, related_name="faces")
    # Same denormalised event FK makes "all faces of an event" a single indexed query.
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="faces")
    embedding = models.BinaryField()  # 128 float32 values, L2-normalised
    box = models.JSONField()  # [x, y, w, h] in original image pixels

    def vector(self):
        return np.frombuffer(self.embedding, dtype=np.float32)


class GoogleAccount(models.Model):
    """A photographer's connected Google Drive (read-only)."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="google_account")
    email = models.EmailField(blank=True)
    refresh_token = models.TextField()  # encrypted (see crypto.py); use .token to read/write
    connected_at = models.DateTimeField(auto_now=True)

    @property
    def token(self):
        from .crypto import decrypt
        return decrypt(self.refresh_token)

    @token.setter
    def token(self, value):
        from .crypto import encrypt
        self.refresh_token = encrypt(value)

    def __str__(self):
        return self.email or str(self.user)


class Photographer(User):
    """Photographer logins in the admin (same accounts as Django users, with storage settings attached)."""

    class Meta:
        proxy = True
        verbose_name = "photographer"


def default_storage_limit():
    return Decimal(settings.DEFAULT_STORAGE_GB)


class PhotographerProfile(models.Model):
    """Per-photographer settings managed by the admin."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="photographer")
    storage_limit_gb = models.DecimalField(
        "storage limit (GB)", max_digits=9, decimal_places=2, default=default_storage_limit,
        help_text="Uploaded photos and previews count towards this. 1 GB = 1,000,000,000 bytes.",
    )
    notes = models.TextField(blank=True, help_text="Your terms with this photographer. Only admins see this.")

    def __str__(self):
        return f"Storage for {self.user}"
