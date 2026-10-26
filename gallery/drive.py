"""Google Drive access: folder listing, previews and originals.

Two ways in:
- "public": the folder is shared as *Anyone with the link*. Read with the app's API key; the photographer
  only pastes the link.
- "account": a private folder, read with the photographer's connected Google account (OAuth).

Photos stay in Drive. For indexing we fetch a Drive-rendered JPEG preview (a few hundred KB, and Drive
converts HEIC/RAW for us) instead of the original (10-60 MB), and only fall back to the original when
Drive has no preview.
"""
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import requests
from django.conf import settings
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import AuthorizedSession
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from requests.adapters import HTTPAdapter

from .faces import IMAGE_EXTENSIONS
from .models import GoogleAccount

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
TOKEN_URI = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/drive/v3"
FOLDER_MIME = "application/vnd.google-apps.folder"
SHORTCUT_MIME = "application/vnd.google-apps.shortcut"
FILE_FIELDS = "id,name,mimeType,md5Checksum,size,modifiedTime,resourceKey,hasThumbnail,thumbnailLink,shortcutDetails"

PUBLIC, ACCOUNT = "public", "account"


class DriveError(Exception):
    pass


class DriveNotConnected(DriveError):
    pass


class NoPreview(DriveError):
    pass


def enabled():
    return settings.GOOGLE_DRIVE_ENABLED


def public_configured():
    return enabled() and bool(settings.GOOGLE_API_KEY)


def oauth_configured():
    return enabled() and bool(settings.GOOGLE_OAUTH_CLIENT_ID and settings.GOOGLE_OAUTH_CLIENT_SECRET)


def is_image(name, mime_type):
    ext = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
    return mime_type.startswith("image/") or ext in IMAGE_EXTENSIONS


def is_video(name, mime_type):
    return mime_type.startswith("video/")


@dataclass
class Access:
    """How to read one event's folder: public API key, or a photographer's Google account."""
    mode: str
    user: object = None
    # Older "anyone with the link" files need their resource key sent along (Drive's 2021 security update).
    resource_keys: dict = field(default_factory=dict)

    @classmethod
    def for_event(cls, event):
        keys = {event.drive_folder_id: event.drive_resource_key} if event.drive_resource_key else {}
        return cls(mode=event.drive_access or PUBLIC, user=event.owner, resource_keys=keys)


# --- OAuth (private folders) ------------------------------------------------------

def make_flow(redirect_uri, state=None, code_verifier=None):
    config = {
        "web": {
            "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
            "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": TOKEN_URI,
        }
    }
    flow = Flow.from_client_config(config, scopes=SCOPES, state=state, redirect_uri=redirect_uri)
    if code_verifier:
        flow.code_verifier = code_verifier
    return flow


def save_connection(user, credentials):
    if not credentials.refresh_token:
        raise DriveError("Google didn't return a refresh token. Remove the app's access in your Google account and connect again.")
    account = GoogleAccount.objects.filter(user=user).first() or GoogleAccount(user=user)
    account.token = credentials.refresh_token
    account.save()
    _forget_user(user)
    try:
        about = _get(Access(ACCOUNT, user), f"{API}/about", {"fields": "user(emailAddress)"}).json()
        account.email = about.get("user", {}).get("emailAddress", "")
        account.save(update_fields=["email"])
    except DriveError:
        pass
    return account


def disconnect(user):
    account = GoogleAccount.objects.filter(user=user).first()
    if account:
        try:  # revoke at Google too, so the access disappears from the user's Google account
            requests.post("https://oauth2.googleapis.com/revoke", params={"token": account.token}, timeout=10)
        except requests.RequestException:
            pass
        account.delete()
    _forget_user(user)


# --- HTTP sessions ----------------------------------------------------------------
# Re-using connections matters a lot when fetching thousands of files: it skips a TLS handshake per request.
# Sessions are per thread because requests.Session isn't guaranteed thread-safe.

_local = threading.local()
_creds_cache = {}  # user_id -> Credentials, shared so all threads reuse one access token (~1 hour lifetime)
_creds_lock = threading.Lock()


def _mount(session):
    adapter = HTTPAdapter(pool_connections=4, pool_maxsize=32)
    session.mount("https://", adapter)
    return session


def _public_session():
    if not hasattr(_local, "public"):
        _local.public = _mount(requests.Session())
    return _local.public


def _account_session(user):
    sessions = _local.__dict__.setdefault("accounts", {})
    with _creds_lock:
        creds = _creds_cache.get(user.pk)
        if creds is None:
            account = GoogleAccount.objects.filter(user=user).first()
            if not account or not account.token:
                raise DriveNotConnected("Google Drive is not connected.")
            creds = Credentials(
                None, refresh_token=account.token, token_uri=TOKEN_URI, scopes=SCOPES,
                client_id=settings.GOOGLE_OAUTH_CLIENT_ID, client_secret=settings.GOOGLE_OAUTH_CLIENT_SECRET,
            )
            _creds_cache[user.pk] = creds
            sessions.pop(user.pk, None)
    session = sessions.get(user.pk)
    if session is None or session.credentials is not creds:
        session = sessions[user.pk] = _mount(AuthorizedSession(creds))
    return session


def _forget_user(user):
    with _creds_lock:
        _creds_cache.pop(user.pk, None)


def _request(access, url, params=None, stream=False, extra_keys=None):
    params = dict(params or {})
    headers = {}
    keys = {**access.resource_keys, **(extra_keys or {})}
    if keys:
        headers["X-Goog-Drive-Resource-Keys"] = ",".join(f"{fid}/{key}" for fid, key in keys.items())
    if url.startswith(API):
        params["supportsAllDrives"] = "true"
        if access.mode == PUBLIC:
            params["key"] = settings.GOOGLE_API_KEY
    session = _public_session() if access.mode == PUBLIC else _account_session(access.user)
    return session.get(url, params=params, headers=headers, stream=stream, timeout=(10, 120))


def _get(access, url, params=None, stream=False, extra_keys=None, attempts=6):
    """GET with exponential backoff for Drive's rate limits (403/429) and transient 5xx errors."""
    for attempt in range(attempts):
        try:
            resp = _request(access, url, params, stream, extra_keys)
        except RefreshError as exc:
            _forget_user(access.user)
            raise DriveNotConnected("Google Drive access was revoked or expired. Please reconnect.") from exc
        except requests.RequestException as exc:
            if attempt == attempts - 1:
                raise DriveError(f"Network error talking to Google Drive: {exc}") from exc
        else:
            if resp.ok:
                return resp
            retryable = resp.status_code in (429, 500, 502, 503, 504) or (
                resp.status_code == 403 and "ateLimitExceeded" in resp.text
            )
            if not retryable or attempt == attempts - 1:
                raise DriveError(_error_message(access, resp))
        time.sleep(min(2 ** attempt, 30) * (0.75 + 0.5 * (time.monotonic() % 1)))  # backoff with jitter


def _error_message(access, resp):
    try:
        message = resp.json()["error"]["message"]
    except (ValueError, KeyError, TypeError):
        message = resp.text[:200]
    if resp.status_code in (403, 404) and access.mode == PUBLIC and "key" not in message.lower():
        return ("Can't open that folder. In Google Drive: Share → General access → \"Anyone with the link\" (Viewer), "
                "then try again. For a private folder, connect your Google account instead.")
    if resp.status_code == 404:
        return "Folder or file not found. Check the link and that your connected Google account can open it."
    if resp.status_code == 403 and "downloadQuotaExceeded" in resp.text:
        return "Google's download limit for this file was reached. Try again later."
    return f"Google Drive error {resp.status_code}: {message}"


# --- Folders & files -------------------------------------------------------------

_FOLDER_ID_PATTERNS = [r"/folders/([A-Za-z0-9_-]{10,})", r"[?&]id=([A-Za-z0-9_-]{10,})", r"^([A-Za-z0-9_-]{10,})$"]


def parse_folder_link(link):
    """Return (folder_id, resource_key) from a Drive folder URL (any of its forms) or a bare folder ID."""
    link = (link or "").strip()
    for pattern in _FOLDER_ID_PATTERNS:
        m = re.search(pattern, link)
        if m:
            rk = re.search(r"[?&]resourcekey=([A-Za-z0-9_-]+)", link)
            return m.group(1), rk.group(1) if rk else ""
    return None, ""


def parse_folder_id(link):
    return parse_folder_link(link)[0]


def get_folder(access, folder_id):
    meta = _get(access, f"{API}/files/{folder_id}", {"fields": "id,name,mimeType,trashed"}).json()
    if meta.get("mimeType") != FOLDER_MIME:
        raise DriveError("That link is a file, not a folder.")
    if meta.get("trashed"):
        raise DriveError("That folder is in the trash.")
    return meta


def _children(access, folder_id, resource_key=""):
    page_token = None
    extra = {folder_id: resource_key} if resource_key else None
    while True:
        params = {
            "q": f"'{folder_id}' in parents and trashed = false",
            "fields": f"nextPageToken, files({FILE_FIELDS})",
            "pageSize": 1000,
            "includeItemsFromAllDrives": "true",
        }
        if page_token:
            params["pageToken"] = page_token
        data = _get(access, f"{API}/files", params, extra_keys=extra).json()
        yield from data.get("files", [])
        page_token = data.get("nextPageToken")
        if not page_token:
            return


@dataclass
class Listing:
    images: list
    videos: int = 0
    other: int = 0


def list_images(access, root_folder_id, workers=8):
    """Every image under a folder, recursing into subfolders (listed in parallel, level by level).

    Each item is the Drive file dict plus "path": the subfolder it's in ("" for the root folder).
    Shortcuts to images/folders are followed.
    """
    listing = Listing(images=[])
    seen = {root_folder_id}
    level = [(root_folder_id, access.resource_keys.get(root_folder_id, ""), "")]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        while level:
            results = pool.map(lambda f: (f, list(_children(access, f[0], f[1]))), level)
            next_level = []
            for (folder_id, _, path), children in results:
                for f in children:
                    if f["mimeType"] == SHORTCUT_MIME:
                        target = f.get("shortcutDetails", {})
                        f = {**f, "id": target.get("targetId"), "mimeType": target.get("targetMimeType", ""),
                             "resourceKey": target.get("targetResourceKey", "")}
                        if not f["id"]:
                            continue
                    if f["mimeType"] == FOLDER_MIME:
                        if f["id"] not in seen:  # guard against loops via shortcuts
                            seen.add(f["id"])
                            next_level.append((f["id"], f.get("resourceKey", ""), f"{path}/{f['name']}" if path else f["name"]))
                    elif is_image(f["name"], f["mimeType"]):
                        if f["id"] not in seen:
                            seen.add(f["id"])
                            listing.images.append({**f, "path": path})
                    elif is_video(f["name"], f["mimeType"]):
                        listing.videos += 1
                    else:
                        listing.other += 1
            level = next_level
    return listing


def _keys_for(file_id, resource_key):
    return {file_id: resource_key} if resource_key else None


def preview(access, file_id, resource_key="", size=2048):
    """A Drive-rendered JPEG of the photo, longest side `size`. Works for HEIC and most RAW formats too.

    Raises NoPreview if Drive hasn't generated one (brand-new uploads, unusual formats).
    """
    meta = _get(access, f"{API}/files/{file_id}", {"fields": "hasThumbnail,thumbnailLink"},
                extra_keys=_keys_for(file_id, resource_key)).json()
    link = meta.get("thumbnailLink")
    if not link:
        raise NoPreview(file_id)
    url = re.sub(r"=s\d+(-[a-z0-9-]+)?$", f"=s{size}", link)
    try:
        resp = _request(access, url)
    except requests.RequestException as exc:
        raise NoPreview(file_id) from exc
    if not resp.ok or not resp.headers.get("Content-Type", "").startswith("image/"):
        raise NoPreview(file_id)
    return resp.content


def download(access, file_id, resource_key=""):
    return _get(access, f"{API}/files/{file_id}", {"alt": "media"}, extra_keys=_keys_for(file_id, resource_key)).content


def open_stream(access, file_id, resource_key=""):
    """Streaming response for passing an original straight through to a guest."""
    return _get(access, f"{API}/files/{file_id}", {"alt": "media"}, stream=True,
                extra_keys=_keys_for(file_id, resource_key))


def public_download_url(file_id, resource_key=""):
    """Direct Google download link for a publicly shared file, so guest downloads don't pass through our server."""
    url = f"https://drive.usercontent.google.com/download?id={file_id}&export=download&confirm=t"
    return f"{url}&resourcekey={resource_key}" if resource_key else url
