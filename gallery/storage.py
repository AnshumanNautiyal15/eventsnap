"""Helpers that work the same for local disk and Cloudflare R2 storage."""
import hashlib
import logging
import shutil
import threading
from pathlib import Path

from django.core.cache import cache
from django.core.files.storage import default_storage
from django.http import FileResponse
from django.shortcuts import redirect
from django.utils.http import content_disposition_header

log = logging.getLogger(__name__)

SIGNED_URL_TTL = 3600  # R2 links stop working after an hour
SIGNED_URL_REUSE = 3000  # hand out the same link for ~50 min so browsers can cache the image


def is_local():
    try:
        default_storage.path("")
        return True
    except NotImplementedError:
        return False


def signed_url(name, download_name=None):
    """Short-lived R2 link to a private file; with download_name the browser saves it under that name."""
    key = "signed:" + hashlib.sha1(f"{name}|{download_name}".encode()).hexdigest()
    url = cache.get(key)
    if url is None:
        params = {"ResponseContentDisposition": content_disposition_header(True, download_name)} if download_name else None
        url = default_storage.url(name, parameters=params, expire=SIGNED_URL_TTL)
        cache.set(key, url, SIGNED_URL_REUSE)
    return url


def serve(field, filename=None, download=False):
    """Response for a stored file, after the caller has checked the visitor may see it."""
    if is_local():
        return FileResponse(field.open("rb"), as_attachment=download, filename=filename or Path(field.name).name)
    return redirect(signed_url(field.name, filename if download else None))


def delete_prefix(prefix):
    """Delete every stored file under a folder, e.g. "events/<slug>/"."""
    prefix = prefix.rstrip("/") + "/"
    if is_local():
        shutil.rmtree(default_storage.path(prefix), ignore_errors=True)
        return
    bucket = getattr(default_storage, "bucket", None)
    if bucket is not None:
        try:
            bucket.objects.filter(Prefix=prefix).delete()  # batched: up to 1,000 files per request
            return
        except Exception:
            log.warning("Batch delete of %s failed; deleting one by one", prefix, exc_info=True)
    _delete_tree(prefix)


def _delete_tree(prefix):
    dirs, files = default_storage.listdir(prefix)
    for name in files:
        default_storage.delete(prefix + name)
    for d in dirs:
        _delete_tree(f"{prefix}{d}/")


def delete_prefix_in_background(prefix):
    def run():
        try:
            delete_prefix(prefix)
        except Exception:
            log.exception("Couldn't delete stored files under %s", prefix)

    threading.Thread(target=run, name="storage-cleanup", daemon=True).start()
