"""Non-JSON endpoints (QR image, photo files, zip, Google sign-in redirects) and the React app shell.

The JSON API used by the Material UI frontend lives in api.py.
"""
import io
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode

import qrcode
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404, HttpResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.csrf import ensure_csrf_cookie

from . import drive, indexing, storage
from .models import Event, Photo

SESSION_KEY = "matched_photos"  # {event_slug: [photo_id, ...]}
SPA_INDEX = settings.BASE_DIR / "frontend" / "dist" / "index.html"


def guest_url(request, event):
    path = reverse("guest_event", args=[event.slug])
    return f"{settings.PUBLIC_BASE_URL}{path}" if settings.PUBLIC_BASE_URL else request.build_absolute_uri(path)


def matched_ids(request, event):
    return request.session.get(SESSION_KEY, {}).get(event.slug)


def healthz(request):
    """For uptime monitors: the app and its database answer."""
    from django.db import connection
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
    return HttpResponse("ok", content_type="text/plain")


@ensure_csrf_cookie
def spa(request, **kwargs):
    """Every page is rendered by the React app; React Router picks the screen from the URL."""
    try:
        return HttpResponse(SPA_INDEX.read_bytes())
    except FileNotFoundError:
        return HttpResponse(
            "<h1>Frontend not built</h1><p>Run <code>cd frontend &amp;&amp; npm install &amp;&amp; npm run build</code>, "
            "then reload.</p>", status=503,
        )


@login_required
def event_qr(request, slug):
    event = get_object_or_404(Event, slug=slug, owner=request.user)
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=16, border=2)
    qr.add_data(guest_url(request, event))
    buf = io.BytesIO()
    qr.make_image(fill_color="black", back_color="white").save(buf, "PNG")
    response = HttpResponse(buf.getvalue(), content_type="image/png")
    if "download" in request.GET:
        response["Content-Disposition"] = f'attachment; filename="{event.slug}-qr.png"'
    return response


# --- Google Drive -------------------------------------------------------------

OAUTH_SESSION_KEY = "google_oauth"


def _back(next_url, **params):
    """Redirect to a frontend page; the page shows `drive_error` / `drive=connected` as a notification."""
    next_url = next_url if next_url.startswith("/") and not next_url.startswith("//") else "/"
    return redirect(f"{next_url}?{urlencode(params)}")


@login_required
def google_connect(request):
    next_url = request.GET.get("next") or "/"
    if not drive.enabled():
        raise Http404
    if not drive.oauth_configured():
        return _back(next_url, drive_error="Google sign-in isn't set up on this server (missing GOOGLE_OAUTH_CLIENT_ID/SECRET).")
    flow = drive.make_flow(request.build_absolute_uri(reverse("google_callback")))
    # offline + consent so Google returns a refresh token, letting syncs run without the photographer present.
    auth_url, state = flow.authorization_url(access_type="offline", prompt="consent", include_granted_scopes="true")
    request.session[OAUTH_SESSION_KEY] = {"state": state, "verifier": flow.code_verifier, "next": next_url}
    return redirect(auth_url)


@login_required
def google_callback(request):
    pending = request.session.pop(OAUTH_SESSION_KEY, None)
    if not pending or request.GET.get("state") != pending["state"]:
        return _back("/", drive_error="Google sign-in expired. Please try connecting again.")
    if "error" in request.GET:
        return _back(pending["next"], drive_error="Google Drive was not connected (access was not granted).")
    flow = drive.make_flow(
        request.build_absolute_uri(reverse("google_callback")), state=pending["state"], code_verifier=pending["verifier"]
    )
    try:
        flow.fetch_token(authorization_response=request.build_absolute_uri())
        drive.save_connection(request.user, flow.credentials)
    except Exception as exc:  # oauthlib raises several unrelated exception types
        return _back(pending["next"], drive_error=f"Couldn't connect Google Drive: {exc}")
    # Events whose sync failed because access had lapsed can sync again right away.
    for event in request.user.events.filter(drive_access=drive.ACCOUNT).exclude(drive_sync_error=""):
        indexing.start_drive_sync(event)
    return _back(pending["next"], drive="connected")


# --- Guests -------------------------------------------------------------------

def guest_download_all(request, slug):
    event = get_object_or_404(Event, slug=slug)
    ids = matched_ids(request, event)
    if not ids:
        raise Http404
    photos = list(event.photos.filter(pk__in=ids))
    access = drive.Access.for_event(event)

    def fetch(photo):
        try:
            if photo.from_drive:
                return drive.download(access, photo.drive_file_id, photo.drive_resource_key)
            with photo.image.open("rb") as fh:
                return fh.read()
        except (drive.DriveError, OSError):
            return None  # deleted from Drive or access revoked; skip rather than fail the whole zip

    tmp = tempfile.TemporaryFile()
    step = settings.ZIP_PARALLEL
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as zf, ThreadPoolExecutor(max_workers=step) as pool:
        used = set()
        # Originals download ZIP_PARALLEL at a time, which also caps how many are held in memory.
        for start in range(0, len(photos), step):
            batch = photos[start:start + step]
            for photo, data in zip(batch, pool.map(fetch, batch)):
                if data is None:
                    continue
                name = f"{photo.folder_path}/{photo.original_name}" if photo.folder_path else photo.original_name
                if name in used:
                    name = f"{photo.pk.hex[:8]}-{name}"
                used.add(name)
                zf.writestr(name, data)
    tmp.seek(0)
    return FileResponse(tmp, as_attachment=True, filename=f"{event.slug}-my-photos.zip")


def photo_file(request, photo_id, kind):
    """Serve a photo only to its photographer or to a guest whose selfie matched it."""
    photo = get_object_or_404(Photo.objects.select_related("event"), pk=photo_id)
    is_owner = request.user.is_authenticated and photo.event.owner_id == request.user.pk
    if not is_owner and str(photo.pk) not in (matched_ids(request, photo.event) or []):
        raise PermissionDenied
    if photo.status == Photo.REMOVED:
        raise Http404
    if kind == "thumb" and photo.thumbnail:
        return storage.serve(photo.thumbnail)
    if not photo.from_drive:
        return storage.serve(photo.image, photo.original_name, download=kind == "download")

    access = drive.Access.for_event(photo.event)
    if access.mode == drive.PUBLIC and kind == "download":
        # Public folder: send the guest straight to Google, so big originals never pass through this server.
        return redirect(drive.public_download_url(photo.drive_file_id, photo.drive_resource_key))

    # Private folder: stream it through without storing it here.
    try:
        upstream = drive.open_stream(access, photo.drive_file_id, photo.drive_resource_key)
    except drive.DriveError:
        raise Http404("This photo is no longer available in Google Drive.")
    response = StreamingHttpResponse(upstream.iter_content(256 * 1024), content_type=photo.mime_type or "image/jpeg")
    if upstream.headers.get("Content-Length"):
        response["Content-Length"] = upstream.headers["Content-Length"]
    disposition = "attachment" if kind == "download" else "inline"
    response["Content-Disposition"] = f'{disposition}; filename="{photo.original_name.replace(chr(34), "")}"'
    return response
