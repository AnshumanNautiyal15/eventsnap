from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import Group, User
from django.db.models import Count, F, Q, Sum
from django.utils.html import format_html

from . import indexing, quota
from .models import Event, Photo, Photographer, PhotographerProfile

admin.site.site_header = "WeddingSnap admin"
admin.site.site_title = "WeddingSnap admin"
admin.site.index_title = "Photographers & events"
admin.site.unregister(Group)  # permissions groups aren't used


def _usage_bar(user, used):
    limit = quota.limit_bytes(user)
    if limit is None:
        return f"{quota.format_bytes(used)} (admin, unlimited)"
    pct = min(100, round(used / limit * 100)) if limit else 100
    color = "#ba2121" if pct >= 90 else "#d98c00" if pct >= 75 else "#417690"
    return format_html(
        '<div style="width:140px;background:#eee;border-radius:4px;height:8px;margin-bottom:3px">'
        '<div style="width:{}%;background:{};height:8px;border-radius:4px"></div></div>{} of {} ({}%)',
        pct, color, quota.format_bytes(used), quota.format_bytes(limit), pct,
    )


class PhotographerProfileInline(admin.StackedInline):
    model = PhotographerProfile
    can_delete = False
    min_num = max_num = 1  # exactly one storage section, also on the "add photographer" page
    extra = 0
    verbose_name = verbose_name_plural = "Storage"
    fields = ["storage_limit_gb", "storage_used", "notes"]
    readonly_fields = ["storage_used"]

    @admin.display(description="Currently using")
    def storage_used(self, obj):
        if not obj or not obj.user_id:
            return "—"
        return _usage_bar(obj.user, quota.usage_bytes(obj.user))


class PhotographerAdmin(BaseUserAdmin):
    """Photographer logins: the admin creates them and decides how much storage each one gets."""
    inlines = [PhotographerProfileInline]
    add_form = UserCreationForm  # plain username + password (no "password-based authentication" switch)
    add_fieldsets = ((None, {
        "classes": ("wide",),
        "fields": ("username", "password1", "password2"),
        "description": "Create the photographer's login and set their storage below. Share the username and password "
                       "with them; they log in on the main site, not here.",
    }),)
    list_display = ["username", "name", "email", "is_active", "storage", "event_count", "last_login"]
    list_filter = ["is_active", "is_superuser"]
    search_fields = ["username", "first_name", "last_name", "email"]
    ordering = ["username"]
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Contact", {"fields": ("first_name", "last_name", "email")}),
        ("Access", {
            "fields": ("is_active",),
            "description": "Untick to block this photographer from logging in. Their events and photos are kept.",
        }),
        ("Admin rights", {
            "classes": ("collapse",),
            "fields": ("is_staff", "is_superuser"),
            "description": "Only for people who should manage other photographers. Admins have unlimited storage.",
        }),
        ("Activity", {"classes": ("collapse",), "fields": ("last_login", "date_joined")}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            used_bytes=Sum(F("events__photos__original_bytes") + F("events__photos__thumb_bytes")),
            n_events=Count("events", distinct=True),
        )

    @admin.display(description="Name")
    def name(self, obj):
        return obj.get_full_name()

    @admin.display(description="Storage", ordering="used_bytes")
    def storage(self, obj):
        return _usage_bar(obj, obj.used_bytes or 0)

    @admin.display(description="Events", ordering="n_events")
    def event_count(self, obj):
        return obj.n_events


admin.site.unregister(User)  # managed as Photographers instead
admin.site.register(Photographer, PhotographerAdmin)


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ["name", "date", "owner", "is_active", "photo_count", "drive_folder_name", "created_at"]
    list_filter = ["is_active", "owner"]
    search_fields = ["name", "slug", "owner__username"]
    readonly_fields = ["slug", "drive_folder_id", "drive_folder_name", "drive_access", "drive_synced_at", "drive_sync_error"]
    fields = ["owner", "name", "date", "is_active", "slug", "drive_folder_name", "drive_folder_id", "drive_access",
              "drive_synced_at", "drive_sync_error"]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            n_photos=Count("photos", filter=~Q(photos__status=Photo.REMOVED))
        )

    @admin.display(description="Photos", ordering="n_photos")
    def photo_count(self, obj):
        return obj.n_photos


@admin.register(Photo)
class PhotoAdmin(admin.ModelAdmin):
    list_display = ["original_name", "event", "folder_path", "status", "face_count", "size", "uploaded_at"]
    list_filter = ["status", "event__owner", "event"]
    search_fields = ["original_name", "event__name"]
    readonly_fields = [f.name for f in Photo._meta.fields]

    def has_add_permission(self, request):
        return False  # photos come in through the app or Google Drive

    @admin.display(description="Stored")
    def size(self, obj):
        return quota.format_bytes(obj.original_bytes + obj.thumb_bytes)

    # Deleting here also removes the stored files (and keeps removed Drive photos from coming back).
    def delete_model(self, request, obj):
        indexing.remove_photos([obj])

    def delete_queryset(self, request, queryset):
        indexing.remove_photos(list(queryset))
