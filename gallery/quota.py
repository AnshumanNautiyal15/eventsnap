"""Per-photographer storage limits, set by the admin."""
from decimal import Decimal

from django.db.models import F, Sum

from .models import Photo, PhotographerProfile, default_storage_limit

GB = 1_000_000_000
STORAGE_FULL = "Storage limit reached"  # prefix of Photo.error when indexing was blocked by the limit


def limit_bytes(user):
    """None means unlimited (admins)."""
    if user.is_superuser:
        return None
    profile = PhotographerProfile.objects.filter(user=user).first()
    gb = profile.storage_limit_gb if profile else default_storage_limit()
    return int(Decimal(gb) * GB)


def usage_bytes(user):
    total = Photo.objects.filter(event__owner=user).aggregate(t=Sum(F("original_bytes") + F("thumb_bytes")))["t"]
    return total or 0


def has_room(user, extra_bytes):
    limit = limit_bytes(user)
    return limit is None or usage_bytes(user) + extra_bytes <= limit


def summary(user):
    limit = limit_bytes(user)
    used = usage_bytes(user)
    return {
        "used": used,
        "limit": limit,  # null = unlimited
        "available": None if limit is None else max(limit - used, 0),
    }


def format_bytes(n):
    if n is None:
        return "Unlimited"
    for unit, size in (("GB", GB), ("MB", 1_000_000), ("KB", 1_000)):
        if n >= size:
            return f"{n / size:.2f}".rstrip("0").rstrip(".") + f" {unit}"
    return f"{n} bytes"
