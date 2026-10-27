import io
import os
import re
import shutil
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from decimal import Decimal

import numpy as np
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import CommandError, call_command
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from PIL import Image, ImageEnhance

from . import drive, faces, indexing, quota, storage
from .models import Event, Face, GoogleAccount, Photo, Photographer, PhotographerProfile

# Folder holding OpenCV's sample images lena.jpg and messi5.jpg (two different people).
SAMPLE_DIR = Path(os.environ.get("FACE_SAMPLE_DIR", "")) if os.environ.get("FACE_SAMPLE_DIR") else None


def index_now(*args, **kwargs):
    """Run the index_photos command in this thread (tests can't see uncommitted rows from other threads)."""
    call_command("index_photos", *args, workers=1, **kwargs)


def jpeg(img, exif_orientation=None):
    buf = io.BytesIO()
    if exif_orientation:
        exif = Image.Exif()
        exif[0x0112] = exif_orientation
        img.save(buf, "JPEG", quality=92, exif=exif)
    else:
        img.save(buf, "JPEG", quality=92)
    return buf.getvalue()


class MediaTestCase(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=Path(self.media))
        self.override.enable()
        self.user = User.objects.create_user("photog", password="pw-for-tests-only")
        self.event = Event.objects.create(owner=self.user, name="Test Wedding")

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)


class MatchingTests(MediaTestCase):
    def _photo_with(self, *vectors):
        photo = Photo.objects.create(event=self.event, original_name="x.jpg", image="x.jpg", status=Photo.DONE)
        for v in vectors:
            v = np.asarray(v, dtype=np.float32)
            Face.objects.create(photo=photo, event=self.event, embedding=(v / np.linalg.norm(v)).tobytes(), box=[0, 0, 1, 1])
        return photo

    def test_returns_only_photos_above_threshold(self):
        rng = np.random.default_rng(0)
        me = rng.normal(size=128)
        stranger = rng.normal(size=128)
        mine = self._photo_with(me + rng.normal(scale=0.3, size=128), stranger)
        theirs = self._photo_with(stranger)
        selfie = (me / np.linalg.norm(me)).astype(np.float32)

        ids = [pid for pid, _ in indexing.find_matches(self.event, selfie)]
        self.assertEqual(ids, [mine.pk])
        self.assertNotIn(theirs.pk, ids)

    def test_guest_cannot_fetch_unmatched_photo(self):
        photo = self._photo_with([1] * 128)
        url = reverse("photo_file", args=[photo.pk, "full"])
        self.assertEqual(self.client.get(url).status_code, 403)


@unittest.skipUnless(SAMPLE_DIR, "set FACE_SAMPLE_DIR to a folder with OpenCV's lena.jpg and messi5.jpg")
class EndToEndTests(MediaTestCase):
    def test_guest_finds_only_their_photos(self):
        lena = Image.open(SAMPLE_DIR / "lena.jpg").convert("RGB")
        messi = Image.open(SAMPLE_DIR / "messi5.jpg").convert("RGB")

        # A big "group photo": Lena small, slightly rotated and darker, next to Messi's scene.
        group = Image.new("RGB", (4000, 2600), (200, 190, 180))
        group.paste(messi.resize((messi.width * 3, messi.height * 3)), (0, 900))
        small_lena = ImageEnhance.Brightness(lena.rotate(8, expand=True, fillcolor=(200, 190, 180))).enhance(0.75)
        group.paste(small_lena.resize((600, 600)), (3100, 300))

        files = {
            "group.jpg": jpeg(group),
            "lena_mirrored.jpg": jpeg(lena.transpose(Image.FLIP_LEFT_RIGHT)),
            "messi_only.jpg": jpeg(messi),
        }

        self.client.force_login(self.user)
        with mock.patch.object(indexing, "enqueue"):  # index synchronously below instead of in a thread
            r = self.client.post(
                reverse("api_event_upload", args=[self.event.slug]),
                {"photos": [SimpleUploadedFile(n, b, "image/jpeg") for n, b in files.items()]},
            )
        self.assertEqual((r.json()["added"], r.json()["skipped"]), (3, 0))
        index_now(self.event.slug, stdout=io.StringIO())
        self.assertFalse(self.event.photos.exclude(status=Photo.DONE).exists())

        # Guest on their phone: selfie stored sideways with an EXIF rotation tag, like an iPhone does.
        self.client.logout()
        selfie = ImageEnhance.Brightness(lena.crop((60, 60, 450, 480))).enhance(1.15).rotate(90, expand=True)
        r = self.client.post(
            reverse("api_guest_search", args=[self.event.slug]),
            {"selfie": SimpleUploadedFile("selfie.jpg", jpeg(selfie, exif_orientation=6), "image/jpeg")},
        )
        self.assertEqual(r.json(), {"count": 2})

        result = self.client.get(reverse("api_guest_results", args=[self.event.slug])).json()
        photos = [p for section in result["sections"] for p in section["photos"]]
        found = sorted(self.event.photos.get(pk=p["id"]).original_name for p in photos)
        self.assertEqual(found, ["group.jpg", "lena_mirrored.jpg"])

        # Matched photos are viewable; the unmatched one is not.
        for p in photos:
            self.assertEqual(self.client.get(p["thumb"]).status_code, 200)
        other = self.event.photos.get(original_name="messi_only.jpg")
        self.assertEqual(self.client.get(reverse("photo_file", args=[other.pk, "full"])).status_code, 403)

        zip_resp = self.client.get(result["zip_url"])
        self.assertEqual(zip_resp.status_code, 200)

    def test_selfie_without_face_shows_error(self):
        Photo.objects.create(event=self.event, original_name="x.jpg", image="x.jpg", status=Photo.DONE)
        blank = SimpleUploadedFile("s.jpg", jpeg(Image.new("RGB", (400, 400), "white")), "image/jpeg")
        r = self.client.post(reverse("api_guest_search", args=[self.event.slug]), {"selfie": blank})
        self.assertEqual(r.status_code, 400)
        self.assertIn("see a face in that photo", r.json()["error"])


class FakeResponse:
    def __init__(self, status=200, content=b"", json_data=None, content_type="application/json"):
        self.status_code, self.ok = status, status < 400
        self.content = content
        self._json = json_data
        self.text = content.decode("latin-1") if content else str(json_data)
        self.headers = {"Content-Type": content_type, "Content-Length": str(len(content))}

    def json(self):
        return self._json

    def iter_content(self, size):
        return [self.content]


class FakeDrive:
    """Fake Google Drive answering at the HTTP level, so drive.py's real request code is exercised."""

    def __init__(self, api_key="test-api-key"):
        self.api_key = api_key
        self.items = {"root": {"id": "root", "name": "Wedding", "mimeType": drive.FOLDER_MIME, "parent": None}}
        self.calls = []
        self.fail_next = []  # status codes to return before succeeding (rate-limit simulation)

    def folder(self, fid, name, parent="root"):
        self.items[fid] = {"id": fid, "name": name, "mimeType": drive.FOLDER_MIME, "parent": parent}

    def file(self, fid, name, data, parent="root", mime="image/jpeg", preview=True, resource_key=""):
        import hashlib
        self.items[fid] = {"id": fid, "name": name, "mimeType": mime, "parent": parent, "data": data,
                           "md5Checksum": hashlib.md5(data).hexdigest(), "modifiedTime": "2026-10-08T10:00:00Z",
                           "preview": preview, "resourceKey": resource_key}

    def _public(self, item):
        meta = {k: v for k, v in item.items() if k not in ("data", "preview", "parent")}
        if item.get("preview"):
            meta["hasThumbnail"], meta["thumbnailLink"] = True, f"https://lh3.fake/{item['id']}=s220"
        return meta

    def get(self, url, params=None, headers=None, stream=False, timeout=None):
        params = params or {}
        self.calls.append((url, dict(params), dict(headers or {})))
        if self.fail_next:
            return FakeResponse(self.fail_next.pop(0), json_data={"error": {"message": "rateLimitExceeded"}})
        if url.startswith("https://lh3.fake/"):
            fid, size = url[len("https://lh3.fake/"):].split("=s")
            img = faces.load_image(self.items[fid]["data"])
            img.thumbnail((int(size), int(size)))
            return FakeResponse(content=jpeg(img), content_type="image/jpeg")
        if params.get("key") != self.api_key:
            return FakeResponse(403, json_data={"error": {"message": "The caller does not have permission"}})
        if url == f"{drive.API}/files":
            parent = re.match(r"'([^']+)' in parents", params["q"]).group(1)
            kids = [self._public(i) for i in self.items.values() if i["parent"] == parent]
            return FakeResponse(json_data={"files": kids})
        fid = url.rsplit("/", 1)[1]
        item = self.items.get(fid)
        if item is None:
            return FakeResponse(404, json_data={"error": {"message": "File not found"}})
        if params.get("alt") == "media":
            return FakeResponse(content=item["data"], content_type=item["mimeType"])
        return FakeResponse(json_data={**self._public(item), "trashed": False})

    def original_downloads(self):
        return [c for c in self.calls if c[1].get("alt") == "media"]

    def install(self, test):
        for p in (mock.patch.object(drive, "_public_session", lambda: self),
                  mock.patch.object(drive, "_account_session", lambda user: self),
                  mock.patch.object(drive.time, "sleep", lambda s: None),
                  override_settings(GOOGLE_API_KEY=self.api_key, GOOGLE_DRIVE_ENABLED=True)):
            p.start() if hasattr(p, "start") else p.enable()
            test.addCleanup(p.stop if hasattr(p, "stop") else p.disable)


class DriveHelpersTests(TestCase):
    def test_parse_folder_link(self):
        fid = "1AbCdEfGhIjKlMnOpQrStUv"
        for link in [
            f"https://drive.google.com/drive/folders/{fid}?usp=sharing",
            f"https://drive.google.com/drive/u/1/folders/{fid}",
            f"https://drive.google.com/open?id={fid}",
            fid,
        ]:
            self.assertEqual(drive.parse_folder_link(link), (fid, ""), link)
        self.assertEqual(
            drive.parse_folder_link(f"https://drive.google.com/drive/folders/{fid}?resourcekey=0-AbC_d&usp=sharing"),
            (fid, "0-AbC_d"),
        )
        self.assertEqual(drive.parse_folder_link("https://example.com/nope"), (None, ""))

    def test_recognises_every_image_type(self):
        for name, mime in [("a.CR2", "application/octet-stream"), ("b.nef", "image/x-nikon-nef"), ("c.heic", "image/heif"),
                           ("d.avif", "image/avif"), ("e.dng", ""), ("f.gif", "image/gif"), ("g.arw", "application/octet-stream")]:
            self.assertTrue(drive.is_image(name, mime), name)
        self.assertFalse(drive.is_image("notes.pdf", "application/pdf"))


class FormatTests(TestCase):
    @unittest.skipUnless(SAMPLE_DIR, "needs FACE_SAMPLE_DIR")
    def test_faces_found_in_all_common_formats(self):
        import pillow_heif  # noqa: F401  (registers HEIF writer)
        lena = Image.open(SAMPLE_DIR / "lena.jpg").convert("RGB")
        for fmt in ["JPEG", "PNG", "WEBP", "TIFF", "BMP", "GIF", "AVIF", "HEIF"]:
            buf = io.BytesIO()
            lena.save(buf, fmt)
            self.assertEqual(len(faces.detect_faces(faces.load_image(buf.getvalue()))), 1, fmt)


class DriveSyncTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.drive = FakeDrive()
        self.drive.install(self)
        self.event.drive_folder_id, self.event.drive_folder_name, self.event.drive_access = "root", "Wedding", drive.PUBLIC
        self.event.save()

    def sync(self):
        result = indexing.sync_drive(self.event)
        index_now(stdout=io.StringIO())
        return result

    def test_lists_subfolders_shortcuts_and_counts_videos(self):
        img = jpeg(Image.new("RGB", (300, 200), "red"))
        self.drive.folder("f1", "Haldi")
        self.drive.folder("f2", "Candids", parent="f1")
        self.drive.file("a", "a.jpg", img)
        self.drive.file("b", "b.CR2", img, parent="f1", mime="application/octet-stream")
        self.drive.file("c", "c.heic", img, parent="f2", mime="image/heif")
        self.drive.file("v", "first-dance.mp4", b"video", mime="video/mp4")
        self.drive.file("n", "notes.pdf", b"pdf", mime="application/pdf")
        listing = drive.list_images(drive.Access.for_event(self.event), "root")
        self.assertEqual({f["name"]: f["path"] for f in listing.images},
                         {"a.jpg": "", "b.CR2": "Haldi", "c.heic": "Haldi/Candids"})
        self.assertEqual((listing.videos, listing.other), (1, 1))

    def test_indexes_from_drive_preview_without_downloading_originals(self):
        self.drive.file("1", "a.jpg", jpeg(Image.new("RGB", (3000, 2000), "red")))
        self.sync()
        self.assertEqual(self.event.photos.get().status, Photo.DONE)
        self.assertEqual(self.drive.original_downloads(), [])
        self.assertTrue(all(c[1].get("key") == "test-api-key" for c in self.drive.calls if c[0].startswith(drive.API)))

    def test_falls_back_to_original_when_drive_has_no_preview(self):
        self.drive.file("1", "a.jpg", jpeg(Image.new("RGB", (300, 200), "red")), preview=False)
        self.sync()
        self.assertEqual(self.event.photos.get().status, Photo.DONE)
        self.assertEqual(len(self.drive.original_downloads()), 1)

    def test_unreadable_file_is_reported_not_skipped(self):
        self.drive.file("1", "broken.jpg", b"not an image", preview=False)
        self.sync()
        photo = self.event.photos.get()
        self.assertEqual(photo.status, Photo.FAILED)
        self.assertTrue(photo.error)

    def test_retries_rate_limits(self):
        self.drive.file("1", "a.jpg", jpeg(Image.new("RGB", (300, 200), "red")))
        self.drive.fail_next = [429, 403, 503]
        self.assertEqual(self.sync(), (1, 0, 0))

    def test_resource_key_sent_for_older_shared_links(self):
        self.event.drive_resource_key = "0-rk"
        self.event.save()
        indexing.sync_drive(self.event)
        listing_call = next(c for c in self.drive.calls if c[0] == f"{drive.API}/files")
        self.assertEqual(listing_call[2]["X-Goog-Drive-Resource-Keys"], "root/0-rk")

    def test_sync_adds_changes_and_removes(self):
        img = lambda color: jpeg(Image.new("RGB", (300, 200), color))
        self.drive.file("1", "a.jpg", img("red"))
        self.drive.folder("f1", "Reception")
        self.drive.file("2", "b.jpg", img("blue"), parent="f1")
        self.assertEqual(self.sync(), (2, 0, 0))
        b = self.event.photos.get(drive_file_id="2")
        self.assertEqual((b.status, b.folder_path, b.image.name), (Photo.DONE, "Reception", ""))
        self.assertTrue(b.thumbnail)  # only the small preview is stored locally

        self.assertEqual(self.sync(), (0, 0, 0))  # nothing changed in Drive

        self.drive.file("2", "b.jpg", img("green"), parent="f1")  # photo edited in Drive
        del self.drive.items["1"]                                # photo deleted from Drive
        self.drive.file("3", "c.jpg", img("white"), parent="f1")
        self.assertEqual(self.sync(), (1, 1, 1))
        self.assertEqual(sorted(self.event.photos.values_list("drive_file_id", flat=True)), ["2", "3"])

    def test_link_folder_view_uses_public_link(self):
        self.client.force_login(self.user)
        self.event.drive_folder_id = ""
        self.event.save()
        url = reverse("api_drive_folder", args=[self.event.slug])
        link = {"folder_link": "https://drive.google.com/drive/folders/root1234567890?usp=sharing"}
        with mock.patch.object(indexing, "start_drive_sync") as start:
            r = self.client.post(url, link, content_type="application/json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Anyone with the link", r.json()["error"])
        self.event.refresh_from_db()
        self.assertEqual(self.event.drive_folder_id, "")  # "root1234567890" doesn't exist in the fake Drive

        self.drive.folder("root1234567890", "Priya Arjun", parent=None)
        with mock.patch.object(indexing, "start_drive_sync") as start:
            r = self.client.post(url, link, content_type="application/json")
        self.assertEqual(r.status_code, 200)
        self.event.refresh_from_db()
        self.assertEqual((self.event.drive_folder_name, self.event.drive_access), ("Priya Arjun", drive.PUBLIC))
        start.assert_called_once()

    def test_guest_download_goes_straight_to_google_for_public_folders(self):
        self.drive.file("1", "a.jpg", jpeg(Image.new("RGB", (300, 200), "red")))
        self.sync()
        photo = self.event.photos.get()
        self.client.force_login(self.user)
        r = self.client.get(reverse("photo_file", args=[photo.pk, "download"]))
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r["Location"].startswith("https://drive.usercontent.google.com/download?id=1"))

    def test_private_folder_original_is_streamed(self):
        data = jpeg(Image.new("RGB", (300, 200), "red"))
        self.drive.file("1", "a.jpg", data)
        self.sync()
        self.event.drive_access = drive.ACCOUNT
        self.event.save()
        with override_settings(GOOGLE_API_KEY=""), mock.patch.object(drive, "_account_session", lambda user: self._keyed()):
            self.client.force_login(self.user)
            r = self.client.get(reverse("photo_file", args=[self.event.photos.get().pk, "download"]))
            self.assertEqual(b"".join(r.streaming_content), data)

    def _keyed(self):
        # OAuth requests carry no API key; let the fake accept them as if authorised.
        fake = self.drive
        return mock.Mock(get=lambda url, params=None, **kw: fake.get(url, {**(params or {}), "key": fake.api_key}, **kw))

    def test_auto_sync_backs_off_after_a_failed_attempt(self):
        with mock.patch.object(indexing.threading, "Thread") as thread:
            indexing.maybe_auto_sync(self.event)
            indexing._syncing.discard(self.event.pk)  # pretend it finished (and failed: drive_synced_at unchanged)
            indexing.maybe_auto_sync(self.event)
        self.assertEqual(thread.call_count, 1)
        indexing._last_attempt.pop(self.event.pk, None)

    @unittest.skipUnless(SAMPLE_DIR, "set FACE_SAMPLE_DIR to a folder with OpenCV's lena.jpg and messi5.jpg")
    def test_guest_matches_drive_photos_grouped_by_folder(self):
        lena = Image.open(SAMPLE_DIR / "lena.jpg").convert("RGB")
        messi = Image.open(SAMPLE_DIR / "messi5.jpg").convert("RGB")
        self.drive.folder("h", "Haldi")
        self.drive.folder("r", "Reception")
        self.drive.folder("rc", "Candids", parent="r")
        self.drive.file("1", "portrait.jpg", jpeg(lena), parent="h")
        self.drive.file("2", "mirror.jpg", jpeg(lena.transpose(Image.FLIP_LEFT_RIGHT)), parent="rc")
        self.drive.file("3", "messi.jpg", jpeg(messi), parent="r")
        self.sync()

        selfie = SimpleUploadedFile("s.jpg", jpeg(lena.crop((60, 60, 450, 480))), "image/jpeg")
        self.client.post(reverse("api_guest_search", args=[self.event.slug]), {"selfie": selfie})
        result = self.client.get(reverse("api_guest_results", args=[self.event.slug])).json()
        self.assertEqual(
            [(s["folder"], [self.event.photos.get(pk=p["id"]).original_name for p in s["photos"]]) for s in result["sections"]],
            [("Haldi", ["portrait.jpg"]), ("Reception/Candids", ["mirror.jpg"])],
        )

        r = self.client.get(result["zip_url"])
        names = zipfile.ZipFile(io.BytesIO(b"".join(r.streaming_content))).namelist()
        self.assertEqual(sorted(names), ["Haldi/portrait.jpg", "Reception/Candids/mirror.jpg"])


@override_settings(GOOGLE_DRIVE_ENABLED=True)
class GoogleOAuthTests(MediaTestCase):
    def test_callback_rejects_mismatched_state(self):
        self.client.force_login(self.user)
        session = self.client.session
        session["google_oauth"] = {"state": "good", "verifier": "v", "next": "/"}
        session.save()
        r = self.client.get(reverse("google_callback"), {"state": "evil", "code": "x"})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r["Location"].startswith("/?drive_error="))
        self.assertFalse(GoogleAccount.objects.exists())

    @override_settings(GOOGLE_OAUTH_CLIENT_ID="cid.apps.googleusercontent.com", GOOGLE_OAUTH_CLIENT_SECRET="test-secret",
                       GOOGLE_DRIVE_ENABLED=True)
    def test_connect_redirects_to_google_for_offline_readonly_access(self):
        self.client.force_login(self.user)
        r = self.client.get(reverse("google_connect"))
        self.assertTrue(r["Location"].startswith("https://accounts.google.com/o/oauth2/auth"))
        for part in ("drive.readonly", "access_type=offline", "code_challenge="):
            self.assertIn(part, r["Location"])


class ApiTests(MediaTestCase):
    def post(self, name, data=None, args=()):
        return self.client.post(reverse(name, args=args), data or {}, content_type="application/json")

    def test_login_logout(self):
        r = self.post("api_login", {"username": "photog", "password": "wrong"})
        self.assertEqual(r.status_code, 400)
        r = self.post("api_login", {"username": "photog", "password": "pw-for-tests-only"})
        self.assertEqual(r.json(), {"user": {"username": "photog", "is_admin": False}})
        self.assertEqual(self.client.get(reverse("api_me")).json()["user"]["username"], "photog")
        self.post("api_logout")
        self.assertEqual(self.client.get(reverse("api_me")).json(), {"user": None})

    def test_no_public_signup(self):
        self.assertEqual(self.client.post("/api/auth/signup/", {}).status_code, 404)
        self.assertEqual(self.client.get("/signup/").status_code, 404)

    def test_photographer_api_requires_login(self):
        self.assertEqual(self.client.get(reverse("api_events")).status_code, 401)
        self.assertEqual(self.client.get(reverse("api_event", args=[self.event.slug])).status_code, 401)

    def test_cannot_open_someone_elses_event(self):
        User.objects.create_user("other", password="pw-for-tests-only")
        self.client.login(username="other", password="pw-for-tests-only")
        self.assertEqual(self.client.get(reverse("api_event", args=[self.event.slug])).status_code, 404)
        self.assertEqual(self.post("api_event_toggle", args=[self.event.slug]).status_code, 404)

    def test_create_list_and_detail(self):
        self.client.force_login(self.user)
        r = self.post("api_events", {"name": "Riya & Kabir", "date": "2026-12-01"})
        slug = r.json()["slug"]
        names = [e["name"] for e in self.client.get(reverse("api_events")).json()["events"]]
        self.assertIn("Riya & Kabir", names)
        detail = self.client.get(reverse("api_event", args=[slug])).json()
        self.assertEqual(detail["event"]["date"], "2026-12-01")
        self.assertTrue(detail["event"]["guest_url"].endswith(f"/e/{slug}/"))
        self.assertEqual(detail["stats"]["total"], 0)
        self.assertEqual(self.post("api_event_toggle", args=[slug]).json(), {"is_active": False})

    def test_create_requires_name(self):
        self.client.force_login(self.user)
        r = self.post("api_events", {"name": ""})
        self.assertEqual(r.status_code, 400)
        self.assertIn("name", r.json()["errors"])

    def test_guest_cannot_search_closed_event(self):
        self.event.is_active = False
        self.event.save()
        self.assertFalse(self.client.get(reverse("api_guest_event", args=[self.event.slug])).json()["is_active"])
        selfie = SimpleUploadedFile("s.jpg", jpeg(Image.new("RGB", (100, 100))), "image/jpeg")
        r = self.client.post(reverse("api_guest_search", args=[self.event.slug]), {"selfie": selfie})
        self.assertEqual(r.status_code, 403)

    def test_results_require_a_selfie_first(self):
        self.assertEqual(self.client.get(reverse("api_guest_results", args=[self.event.slug])).status_code, 404)

    def test_pages_are_served_by_the_react_app(self):
        from . import views
        index = Path(self.media) / "index.html"
        index.write_text("<div id=root></div>")
        with mock.patch.object(views, "SPA_INDEX", index):
            for url in ["/", "/login/", f"/events/{self.event.slug}/", f"/e/{self.event.slug}/", f"/e/{self.event.slug}/my-photos/"]:
                r = self.client.get(url)
                self.assertContains(r, "<div id=root>", msg_prefix=url)
                self.assertIn("csrftoken", r.cookies)
        with mock.patch.object(views, "SPA_INDEX", Path(self.media) / "missing.html"):
            self.assertContains(self.client.get("/"), "npm run build", status_code=503)


def small_jpeg(color="red", size=(300, 200)):
    return jpeg(Image.new("RGB", size, color))


class QuotaTests(MediaTestCase):
    def set_limit(self, gb):
        PhotographerProfile.objects.update_or_create(user=self.user, defaults={"storage_limit_gb": gb})

    def upload(self, *files):
        self.client.force_login(self.user)
        with mock.patch.object(indexing, "enqueue"):
            return self.client.post(reverse("api_event_upload", args=[self.event.slug]),
                                    {"photos": [SimpleUploadedFile(f"p{i}.jpg", b, "image/jpeg") for i, b in enumerate(files)]})

    def test_upload_stops_at_the_limit(self):
        data = small_jpeg()
        self.set_limit(1)
        # Already using all but room for exactly two more photos.
        Photo.objects.create(event=self.event, original_name="old.jpg", original_bytes=quota.GB - len(data) * 2)
        r = self.upload(data, data, data).json()
        self.assertEqual((r["added"], r["rejected"]), (2, 1))
        self.assertIn("Storage full", r["error"])
        self.assertEqual(r["storage"]["used"], quota.GB)
        self.assertEqual(self.event.photos.count(), 3)

    def test_default_limit_and_admin_unlimited(self):
        with override_settings(DEFAULT_STORAGE_GB="2.5"):
            self.assertEqual(quota.limit_bytes(self.user), 2_500_000_000)
        admin_user = User.objects.create_superuser("boss", password="pw-for-tests-only")
        self.assertIsNone(quota.limit_bytes(admin_user))

    def test_usage_counts_originals_and_previews(self):
        self.upload(small_jpeg())
        index_now(stdout=io.StringIO())
        photo = self.event.photos.get()
        self.assertGreater(photo.thumb_bytes, 0)
        self.assertEqual(quota.usage_bytes(self.user), photo.original_bytes + photo.thumb_bytes)


class DriveQuotaTests(MediaTestCase):
    def test_drive_previews_wait_for_storage_then_resume(self):
        fake = FakeDrive()
        fake.install(self)
        fake.file("1", "a.jpg", small_jpeg())
        self.event.drive_folder_id, self.event.drive_access = "root", drive.PUBLIC
        self.event.save()
        PhotographerProfile.objects.create(user=self.user, storage_limit_gb=0)

        indexing.sync_drive(self.event)
        index_now(stdout=io.StringIO())
        photo = self.event.photos.get()
        self.assertEqual(photo.status, Photo.FAILED)
        self.assertTrue(photo.error.startswith(quota.STORAGE_FULL))
        self.client.force_login(self.user)
        stats = self.client.get(reverse("api_event", args=[self.event.slug])).json()["stats"]
        self.assertEqual((stats["storage_blocked"], stats["failed"]), (1, 0))

        # Admin raises the limit, photographer presses Retry.
        PhotographerProfile.objects.filter(user=self.user).update(storage_limit_gb=1)
        with mock.patch.object(indexing, "enqueue"):
            self.client.post(reverse("api_event_reprocess", args=[self.event.slug]))
        index_now(stdout=io.StringIO())
        photo.refresh_from_db()
        self.assertEqual(photo.status, Photo.DONE)

    def test_removed_drive_photo_stays_out_after_sync(self):
        fake = FakeDrive()
        fake.install(self)
        fake.file("1", "empty-hall.jpg", small_jpeg())
        self.event.drive_folder_id, self.event.drive_access = "root", drive.PUBLIC
        self.event.save()
        indexing.sync_drive(self.event)
        index_now(stdout=io.StringIO())
        indexing.remove_photos(list(self.event.photos.all()))
        self.assertEqual(indexing.sync_drive(self.event), (0, 0, 0))
        self.assertEqual(self.event.photos.get().status, Photo.REMOVED)


class DeletionTests(MediaTestCase):
    def add_photo(self, faces_found=0, drive_id=""):
        self.client.force_login(self.user)
        photo = Photo.objects.create(event=self.event, original_name="x.jpg", status=Photo.DONE,
                                     face_count=faces_found, drive_file_id=drive_id, thumb_bytes=10)
        photo.thumbnail.save("t.jpg", ContentFile(b"thumb"), save=True)
        if not drive_id:
            photo.image.save("x.jpg", ContentFile(b"original"), save=True)
            photo.original_bytes = 8
            photo.save()
        return photo

    def test_delete_event_removes_its_files(self):
        photo = self.add_photo()
        folder = Path(self.media) / "events" / self.event.slug
        self.assertTrue(folder.exists())
        with mock.patch.object(storage, "delete_prefix_in_background", storage.delete_prefix), \
                self.captureOnCommitCallbacks(execute=True):
            r = self.client.post(reverse("api_event_delete", args=[self.event.slug]))
        self.assertIn("Deleted", r.json()["message"])
        self.assertFalse(Event.objects.exists())
        self.assertFalse(Photo.objects.filter(pk=photo.pk).exists())
        self.assertFalse(folder.exists())

    def test_cannot_delete_someone_elses_event(self):
        User.objects.create_user("other", password="pw-for-tests-only")
        self.client.login(username="other", password="pw-for-tests-only")
        self.assertEqual(self.client.post(reverse("api_event_delete", args=[self.event.slug])).status_code, 404)
        self.assertTrue(Event.objects.exists())

    def test_list_and_remove_photos_without_faces(self):
        empty_upload = self.add_photo(faces_found=0)
        empty_drive = self.add_photo(faces_found=0, drive_id="d1")
        with_faces = self.add_photo(faces_found=3)
        listed = self.client.get(reverse("api_no_face_photos", args=[self.event.slug])).json()["photos"]
        self.assertEqual({p["id"] for p in listed}, {str(empty_upload.pk), str(empty_drive.pk)})
        before = quota.usage_bytes(self.user)

        r = self.client.post(reverse("api_remove_photos", args=[self.event.slug]),
                             {"ids": [p["id"] for p in listed]}, content_type="application/json").json()
        self.assertEqual(r["removed"], 2)
        self.assertEqual(r["storage"]["used"], before - (8 + 10) - 10)
        self.assertFalse(Photo.objects.filter(pk=empty_upload.pk).exists())  # upload: gone
        empty_drive.refresh_from_db()
        self.assertEqual(empty_drive.status, Photo.REMOVED)  # Drive: kept as a marker so sync won't re-add it
        self.assertTrue(Photo.objects.filter(pk=with_faces.pk, status=Photo.DONE).exists())
        self.assertEqual(self.client.get(reverse("api_event", args=[self.event.slug])).json()["stats"]["total"], 1)

    def test_remove_ignores_other_events_photos(self):
        other = Event.objects.create(owner=User.objects.create_user("o", password="x-pw-for-tests"), name="Other")
        theirs = Photo.objects.create(event=other, original_name="y.jpg", status=Photo.DONE)
        self.client.force_login(self.user)
        r = self.client.post(reverse("api_remove_photos", args=[self.event.slug]),
                             {"ids": [str(theirs.pk)]}, content_type="application/json").json()
        self.assertEqual(r["removed"], 0)
        self.assertTrue(Photo.objects.filter(pk=theirs.pk).exists())


class AdminTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_superuser("boss", password="pw-for-tests-only")
        self.client.force_login(self.admin)

    def test_admin_creates_photographer_with_storage(self):
        url = reverse("admin:gallery_photographer_add")
        page = self.client.get(url)
        self.assertContains(page, "storage_limit_gb")
        r = self.client.post(url, {
            "username": "studio-lens", "password1": "Sup3r-Secret-pw!", "password2": "Sup3r-Secret-pw!",
            "photographer-TOTAL_FORMS": "1", "photographer-INITIAL_FORMS": "0",
            "photographer-MIN_NUM_FORMS": "1", "photographer-MAX_NUM_FORMS": "1",
            "photographer-0-storage_limit_gb": "25", "photographer-0-notes": "₹2,000/month plan",
        })
        self.assertEqual(r.status_code, 302, r.content[:2000])
        user = User.objects.get(username="studio-lens")
        self.assertEqual(quota.limit_bytes(user), 25 * quota.GB)
        self.assertTrue(self.client.login(username="studio-lens", password="Sup3r-Secret-pw!"))

    def test_admin_lists_photographers_with_usage(self):
        Photo.objects.create(event=self.event, original_name="a.jpg", original_bytes=600_000_000, thumb_bytes=0)
        page = self.client.get(reverse("admin:gallery_photographer_changelist"))
        self.assertContains(page, "photog")
        self.assertContains(page, "600 MB of 1 GB (60%)")
        self.assertContains(self.client.get(reverse("admin:gallery_photographer_change", args=[self.user.pk])), "600 MB")

    def test_photographers_cannot_open_admin(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get("/admin/").status_code, 302)


try:
    from moto.server import ThreadedMotoServer
except ImportError:  # moto is only needed for this test
    ThreadedMotoServer = None


@unittest.skipUnless(ThreadedMotoServer, "pip install 'moto[server]' to test the R2 storage path")
class R2StorageTests(MediaTestCase):
    """Runs the R2 code path against a local S3-compatible server (R2 speaks the S3 API)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.server = ThreadedMotoServer(ip_address="127.0.0.1", port=0)
        cls.server.start()
        host, port = cls.server.get_host_and_port()
        cls.endpoint = f"http://{host}:{port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        import boto3
        from weddingsnap.settings import r2_storage_options
        options = r2_storage_options(self.endpoint, "weddingsnap-test", "test-key", "test-secret")
        boto3.client("s3", endpoint_url=self.endpoint, region_name="us-east-1",
                     aws_access_key_id="test-key", aws_secret_access_key="test-secret").create_bucket(Bucket="weddingsnap-test")
        self.r2 = override_settings(STORAGES={
            "default": {"BACKEND": "storages.backends.s3.S3Storage", "OPTIONS": options},
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
        })
        self.r2.enable()
        self.addCleanup(self.r2.disable)

    def test_upload_index_serve_and_delete(self):
        from django.core.files.storage import default_storage
        self.assertFalse(storage.is_local())
        self.client.force_login(self.user)
        with mock.patch.object(indexing, "enqueue"):
            r = self.client.post(reverse("api_event_upload", args=[self.event.slug]),
                                 {"photos": [SimpleUploadedFile("Bride & Groom.jpg", small_jpeg(), "image/jpeg")]})
        self.assertEqual(r.json()["added"], 1)
        index_now(stdout=io.StringIO())
        photo = self.event.photos.get()
        self.assertEqual(photo.status, Photo.DONE)
        self.assertTrue(default_storage.exists(photo.image.name))
        self.assertTrue(default_storage.exists(photo.thumbnail.name))

        # Access is checked by the app, then the browser is sent to a signed, expiring link.
        r = self.client.get(reverse("photo_file", args=[photo.pk, "download"]))
        self.assertEqual(r.status_code, 302)
        self.assertIn("X-Amz-Signature=", r["Location"])
        self.assertIn("response-content-disposition=attachment", r["Location"])
        import requests
        self.assertEqual(requests.get(r["Location"], timeout=10).content, default_storage.open(photo.image.name).read())

        self.client.logout()
        self.assertEqual(self.client.get(reverse("photo_file", args=[photo.pk, "thumb"])).status_code, 403)

        # Guests' zip reads the originals back from R2.
        self.client.force_login(self.user)
        detail = self.client.get(reverse("api_event", args=[self.event.slug])).json()
        self.assertIsNone(detail["event"]["folder"])  # no "copy to server folder" option with R2

        storage.delete_prefix(f"events/{self.event.slug}/")
        self.assertFalse(default_storage.exists(photo.image.name))
        self.assertFalse(default_storage.exists(photo.thumbnail.name))

    def test_copy_existing_local_files_to_r2(self):
        from django.core.files.storage import default_storage
        local = Path(self.media) / "events" / self.event.slug / "thumbs" / "old.jpg"
        local.parent.mkdir(parents=True)
        local.write_bytes(b"old preview")
        Photo.objects.create(event=self.event, original_name="old.jpg", status=Photo.DONE,
                             thumbnail=f"events/{self.event.slug}/thumbs/old.jpg")
        out = io.StringIO()
        call_command("copy_media_to_r2", stdout=out)
        self.assertIn("Uploaded 1 files", out.getvalue())
        self.assertEqual(default_storage.open(f"events/{self.event.slug}/thumbs/old.jpg").read(), b"old preview")
        out = io.StringIO()
        call_command("copy_media_to_r2", stdout=out)  # safe to run twice
        self.assertIn("Uploaded 0 files", out.getvalue())


class IndexOnRequestTests(MediaTestCase):
    def test_upload_waits_for_index_button(self):
        self.client.force_login(self.user)
        with mock.patch.object(indexing, "enqueue") as enqueue:
            self.client.post(reverse("api_event_upload", args=[self.event.slug]),
                             {"photos": [SimpleUploadedFile("a.jpg", small_jpeg(), "image/jpeg")]})
            enqueue.assert_not_called()
            stats = self.client.get(reverse("api_event", args=[self.event.slug])).json()["stats"]
            self.assertEqual((stats["pending"], stats["queued"], stats["done"]), (1, 0, 0))

            r = self.client.post(reverse("api_event_index", args=[self.event.slug])).json()
            self.assertEqual(r["queued"], 1)
            enqueue.assert_called_once()
        photo = self.event.photos.get()
        self.assertEqual(photo.status, Photo.QUEUED)
        self.assertEqual(enqueue.call_args.args[0], [photo.pk])

        indexing.index_photo(Photo.objects.select_related("event__owner").get(pk=photo.pk))
        r = self.client.post(reverse("api_event_index", args=[self.event.slug])).json()
        self.assertEqual(r["queued"], 0)

    def test_drive_sync_does_not_index(self):
        fake = FakeDrive()
        fake.install(self)
        fake.file("1", "a.jpg", small_jpeg())
        self.event.drive_folder_id, self.event.drive_access = "root", drive.PUBLIC
        self.event.save()
        with mock.patch.object(indexing, "enqueue") as enqueue:
            indexing.sync_drive(self.event)
        enqueue.assert_not_called()
        self.assertEqual(self.event.photos.get().status, Photo.PENDING)

    def test_command_filters_by_photographer_and_dry_run(self):
        other = User.objects.create_user("other", password="pw-for-tests-only")
        theirs = Event.objects.create(owner=other, name="Theirs")
        for event in (self.event, theirs):
            photo = Photo.objects.create(event=event, original_name="a.jpg")
            photo.image.save("a.jpg", ContentFile(small_jpeg()), save=True)

        out = io.StringIO()
        index_now(photographer="photog", dry_run=True, stdout=out)
        self.assertIn("1 photos to index in 1 event", out.getvalue())

        index_now(photographer="photog", stdout=io.StringIO())
        self.assertEqual(self.event.photos.get().status, Photo.DONE)
        self.assertEqual(theirs.photos.get().status, Photo.PENDING)

        index_now(theirs.slug, stdout=io.StringIO())
        self.assertEqual(theirs.photos.get().status, Photo.DONE)
        with self.assertRaises(CommandError):
            index_now("no-such-event", stdout=io.StringIO())


class LowResourceTests(TestCase):
    def test_model_copies_are_capped_and_shared(self):
        import queue as queue_mod
        import threading
        from concurrent.futures import ThreadPoolExecutor
        loads = []
        with mock.patch.object(faces, "_idle", queue_mod.LifoQueue()), mock.patch.object(faces, "_created", 0), \
                mock.patch.object(faces, "_load_models", lambda: loads.append(1) or (object(), object())), \
                override_settings(FACE_MODEL_COPIES=2):
            busy, peak, lock = [0], [0], threading.Lock()

            def use(_):
                with faces._models():
                    with lock:
                        busy[0] += 1
                        peak[0] = max(peak[0], busy[0])
                    time.sleep(0.01)
                    with lock:
                        busy[0] -= 1

            with ThreadPoolExecutor(8) as pool:
                list(pool.map(use, range(40)))
        self.assertEqual(len(loads), 2)  # 8 threads, 40 uses, only 2 copies ever loaded
        self.assertLessEqual(peak[0], 2)

    def test_take_batch(self):
        import queue as queue_mod
        q = queue_mod.Queue()
        for i in range(25):
            q.put(i)
        self.assertEqual(indexing.take_batch(q, 10), list(range(10)))
        self.assertEqual(indexing.take_batch(q, 10), list(range(10, 20)))
        self.assertEqual(indexing.take_batch(q, 10), list(range(20, 25)))

    def test_search_cache_keeps_only_recent_events(self):
        user = User.objects.create_user("p", password="pw-for-tests-only")
        events = [Event.objects.create(owner=user, name=f"E{i}") for i in range(indexing.MATRIX_CACHE_EVENTS + 3)]
        indexing._matrix_cache.clear()
        for e in events:
            indexing.find_matches(e, np.ones(128, dtype=np.float32))
        self.assertEqual(len(indexing._matrix_cache), indexing.MATRIX_CACHE_EVENTS)
        self.assertIn((events[-1].pk, events[-1].slug), indexing._matrix_cache)



class DriveSwitchedOffTests(MediaTestCase):
    @override_settings(GOOGLE_API_KEY="k", GOOGLE_OAUTH_CLIENT_ID="c", GOOGLE_OAUTH_CLIENT_SECRET="s")
    def test_drive_hidden_by_default_even_with_keys(self):
        self.client.force_login(self.user)
        d = self.client.get(reverse("api_event", args=[self.event.slug])).json()["drive"]
        self.assertEqual((d["enabled"], d["public_configured"], d["oauth_configured"]), (False, False, False))
        for name in ["api_drive_folder", "api_drive_sync", "api_drive_unlink"]:
            self.assertEqual(self.client.post(reverse(name, args=[self.event.slug])).status_code, 404, name)
        self.assertEqual(self.client.get(reverse("google_connect")).status_code, 404)
        self.event.drive_folder_id = "abc"
        with mock.patch.object(indexing, "start_drive_sync") as start:
            indexing.maybe_auto_sync(self.event)
        start.assert_not_called()


@unittest.skipUnless(ThreadedMotoServer, "pip install 'moto[server]' to test R2 backups")
class BackupTests(TransactionTestCase):  # backup needs no open test transaction
    def test_backup_db_saves_locally_and_uploads_to_r2(self):
        import boto3
        import gzip as gzip_mod
        import sqlite3
        server = ThreadedMotoServer(ip_address="127.0.0.1", port=0)
        server.start()
        self.addCleanup(server.stop)
        host, port = server.get_host_and_port()
        endpoint = f"http://{host}:{port}"
        s3 = boto3.client("s3", endpoint_url=endpoint, region_name="us-east-1",
                          aws_access_key_id="k", aws_secret_access_key="s")
        s3.create_bucket(Bucket="backups")
        User.objects.create_user("in-the-backup", password="pw-for-tests-only")
        out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, out, True)
        with override_settings(BACKUP_R2_BUCKET="backups", R2_ENDPOINT=endpoint, R2_ACCESS_KEY_ID="k",
                               R2_SECRET_ACCESS_KEY="s"):
            for _ in range(3):
                call_command("backup_db", dir=out, keep=2, stdout=io.StringIO())
        files = sorted(Path(out).glob("*.gz"))
        self.assertLessEqual(len(files), 2)
        restored = Path(out) / "restored.sqlite3"
        restored.write_bytes(gzip_mod.open(files[-1]).read())
        names = [r[0] for r in sqlite3.connect(restored).execute("select username from auth_user")]
        self.assertIn("in-the-backup", names)
        keys = [o["Key"] for o in s3.list_objects_v2(Bucket="backups")["Contents"]]
        self.assertTrue(all(k.startswith("db/weddingsnap-") for k in keys))
