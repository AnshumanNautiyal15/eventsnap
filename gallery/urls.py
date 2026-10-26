from django.urls import path

from . import api, views

api_patterns = [
    path("api/auth/me/", api.me, name="api_me"),
    path("api/auth/login/", api.login_view, name="api_login"),
    path("api/auth/logout/", api.logout_view, name="api_logout"),
    path("api/events/", api.events, name="api_events"),
    path("api/events/<slug:slug>/", api.event_detail, name="api_event"),
    path("api/events/<slug:slug>/status/", api.event_status, name="api_event_status"),
    path("api/events/<slug:slug>/upload/", api.event_upload, name="api_event_upload"),
    path("api/events/<slug:slug>/scan-folder/", api.event_scan_folder, name="api_event_scan_folder"),
    path("api/events/<slug:slug>/index/", api.event_index, name="api_event_index"),
    path("api/events/<slug:slug>/reprocess/", api.event_reprocess, name="api_event_reprocess"),
    path("api/events/<slug:slug>/toggle/", api.event_toggle, name="api_event_toggle"),
    path("api/events/<slug:slug>/delete/", api.event_delete, name="api_event_delete"),
    path("api/events/<slug:slug>/no-face-photos/", api.event_no_face_photos, name="api_no_face_photos"),
    path("api/events/<slug:slug>/remove-photos/", api.event_remove_photos, name="api_remove_photos"),
    path("api/events/<slug:slug>/drive/folder/", api.event_drive_folder, name="api_drive_folder"),
    path("api/events/<slug:slug>/drive/sync/", api.event_drive_sync, name="api_drive_sync"),
    path("api/events/<slug:slug>/drive/unlink/", api.event_drive_unlink, name="api_drive_unlink"),
    path("api/google/disconnect/", api.google_disconnect, name="api_google_disconnect"),
    path("api/e/<slug:slug>/", api.guest_event, name="api_guest_event"),
    path("api/e/<slug:slug>/search/", api.guest_search, name="api_guest_search"),
    path("api/e/<slug:slug>/my-photos/", api.guest_results, name="api_guest_results"),
]

file_patterns = [
    path("healthz", views.healthz, name="healthz"),
    path("events/<slug:slug>/qr.png", views.event_qr, name="event_qr"),
    path("e/<slug:slug>/my-photos.zip", views.guest_download_all, name="guest_download_all"),
    path("p/<uuid:photo_id>/<str:kind>/", views.photo_file, name="photo_file"),
    path("google/connect/", views.google_connect, name="google_connect"),
    path("google/callback/", views.google_callback, name="google_callback"),
]

# Pages rendered by the React app (frontend/). Names are kept so reverse() and QR codes keep working.
page_patterns = [
    path("", views.spa, name="dashboard"),
    path("login/", views.spa, name="login"),
    path("events/<slug:slug>/", views.spa, name="event_detail"),
    path("events/<slug:slug>/poster/", views.spa, name="event_poster"),
    path("e/<slug:slug>/", views.spa, name="guest_event"),  # the QR code points here
    path("e/<slug:slug>/my-photos/", views.spa, name="guest_results"),
]

urlpatterns = api_patterns + file_patterns + page_patterns
