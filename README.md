# WeddingSnap

Guests scan a QR code at the wedding, take a selfie, and get back only the photos they appear in.

## How it works

1. The **admin** (you) creates a login for each photographer and decides how much storage they get.
2. The **photographer** logs in, creates an event and either links a **Google Drive folder** (see below)
   or uploads photos (stored in Cloudflare R2, or on this machine if R2 isn't set up).
3. When ready, the photographer presses **Index photos** (or you run `python manage.py index_photos`). Nothing is
   indexed automatically on upload or Drive sync. Each photo is then processed in the background: faces are detected (OpenCV **YuNet**) and turned into
   128-number "face fingerprints" (OpenCV **SFace**), which are stored in the database.
4. The event page shows a **QR code**. Print the poster and put it up at the venue.
5. A **guest** scans it, takes a selfie and gets every photo whose faces match theirs. They can view,
   download one photo, or download all of them as a zip.

Privacy: selfies are processed in memory and never saved. A guest can only open photos that matched
their selfie, and photo URLs are random UUIDs. `media/` is not served publicly.

## Project layout

- `gallery/`: Django app. Face engine (`faces.py`), indexing/sync (`indexing.py`), Google Drive (`drive.py`),
  JSON API for the UI (`api.py`), and file endpoints (QR, photos, zip, Google sign-in) in `views.py`.
- `frontend/`: the UI, built with **React + Material UI (MUI)** and Vite. Django serves the built app for every
  page URL (`/`, `/events/<slug>/`, the guest link `/e/<slug>/`, …), so there's still only one server to run.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# Face models (OpenCV model zoo), go in ml_models/
mkdir -p ml_models
curl -L -o ml_models/face_detection_yunet_2023mar.onnx https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx
curl -L -o ml_models/face_recognition_sface_2021dec.onnx https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx
python manage.py migrate
python manage.py createsuperuser      # your admin login (see "Admin & photographer accounts")

# UI (needs Node 20.19+): build once, and again after changing anything in frontend/
cd frontend && npm install && npm run build && cd ..

python manage.py runserver 0.0.0.0:8010
```

### Working on the UI

`npm run dev` in `frontend/` starts Vite on <http://localhost:5173> with instant reload, proxying the API to
Django on port 8010 (keep `runserver` running too). Use port 8010 when connecting Google Drive, since
that's the redirect URI registered with Google. Run `npm run build` when you're done so Django serves the new version.

To test with phones on the same Wi-Fi, open the dashboard using your computer's LAN IP
(e.g. `http://192.168.1.20:8010`) so the QR code contains an address phones can reach, or set
`PUBLIC_BASE_URL`.

## Google Drive (switched off)

> **Currently disabled.** Photographers upload photos, which are stored in Cloudflare R2. The Drive integration
> below is kept in the code; set `GOOGLE_DRIVE_ENABLED=1` in `.env` to offer it again.

The photographer shares the event folder as **Anyone with the link**, then pastes the link on the event page.
That's it: no Google sign-in for photographers. Every image in the folder **and all subfolders** is indexed.
Shortcuts are followed, Shared drives work, and older links with a `resourcekey` work too.

- **All photo formats:** JPEG, PNG, HEIC/HEIF, AVIF, WebP, TIFF, GIF, BMP, PSD and camera RAW (CR2, CR3, NEF, ARW,
  DNG, RAF, ORF, RW2, PEF, SRW…). A file that can't be read shows up as *failed* with the reason, so nothing is
  silently skipped. Videos are counted and reported, but not searched.
- **Nothing big is stored here.** For indexing, the app asks Drive for a ready-made 2048px JPEG preview of each
  photo (~0.3 MB, and Drive converts HEIC/RAW for us) instead of downloading the original (10–60 MB). It only
  falls back to the original if Drive has no preview yet. Only face data and a ~100 KB preview per photo are kept.
- **Guest downloads go straight from Google** for public folders, so originals never pass through this server.
- **Stays up to date by itself:** after the first sync, the folder is re-checked in the background whenever the
  event page or the guest page is opened and the last check is more than 5 minutes old. *Sync now* forces it.
  With cron, `python manage.py sync_drive` does the same.
- Guests see results grouped by subfolder (e.g. *Haldi*, *Reception/Candids*), and the zip keeps that structure.

Private folders also work: the photographer clicks *Connect your Google account* (OAuth, read-only). See below.

### Setup: API key (for "Anyone with the link" folders), one-time, ~2 minutes

1. <https://console.cloud.google.com/> → create a project.
2. **APIs & Services → Library** → enable **Google Drive API**.
3. **APIs & Services → Credentials → Create credentials → API key**. Edit the key → *API restrictions* →
   *Restrict key* → **Google Drive API** (and, in production, an application restriction such as the server's IP).
4. Put it in `.env` as `GOOGLE_API_KEY=…` (start from `.env.example`) and restart.

No consent screen, test users or Google verification are needed for this mode. The API key is free; Drive API
quota is generous (thousands of requests per minute per project).

### Optional setup: private folders (OAuth)

1. In the same project: **OAuth consent screen** → *External*, add the photographers' Google accounts as **test
   users**, and add the scope `https://www.googleapis.com/auth/drive.readonly`.
2. **Credentials → Create credentials → OAuth client ID** → *Web application*, redirect URI
   `http://localhost:8010/google/callback/` (and later `https://your-domain/google/callback/`).
3. Put the ID and secret in `.env` as `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET`.

Open the app at exactly `http://localhost:8010` when connecting (Google only accepts registered redirect URIs).
In *Testing* mode, at most 100 test users can connect and may have to reconnect every 7 days. Opening it to everyone
requires Google's verification of the restricted `drive.readonly` scope.

## Speed

Measured on an 8-core Mac. Network was simulated as 100 Mbps with 100 ms per request.

| | 1,000 photos |
|---|---|
| Downloading originals, 3 workers | ~16 min |
| **Drive previews + 16 parallel downloads + 4 CPU slots (current)** | **~2.5 min** |

What makes it fast:
- Drive-rendered 2048px previews instead of originals: ~40× less data, and no RAW/HEIC decoding on our side.
- A download/CPU pipeline: 16 threads fetch while at most half the cores run face detection. More CPU threads
  than that made it *slower* in benchmarks.
- Reused HTTPS connections, parallel listing of subfolders, and only changed files are re-indexed (md5 /
  modified time). Rate-limit errors are retried with backoff.
- Big JPEG originals (fallback path, uploads) are decoded at reduced size directly (`draft` mode); RAW files use
  their embedded JPEG instead of a full demosaic.
- Guest search is one matrix multiplication over all faces (~1 ms for 100k faces).

To go faster still, run on a machine with more cores and raise `INDEX_CPU_SLOTS`. Beyond that, move indexing to
a separate worker process/queue (Celery/RQ) on several machines.

## Admin & photographer accounts

There is no public sign-up. You run `python manage.py createsuperuser` once to create **your admin login**,
then manage everything at **`/admin/`** (or the *Admin* button in the app's top bar):

- **Photographers → Add photographer**: choose their username and password, and set their **Storage limit (GB)**.
  Share the username and password with them; they log in on the main site.
- The **Photographers** list shows each photographer's storage as a bar (e.g. *1.2 GB of 5 GB (24%)*) and their
  number of events. Open one to raise their limit, keep **notes** on your terms with them (only admins see these),
  reset their password, or untick **Active** to block their login without deleting anything.
- **Events** and **Photos** lists let you see and delete anything; stored files are removed along with them.
- Admins have unlimited storage. New photographers start with `DEFAULT_STORAGE_GB` (1 GB) until you change it.

### What counts towards a photographer's storage

Uploaded photos (full size) plus the ~100 KB preview made for every photo. Photos kept in **Google Drive** only use
the preview, since the originals stay in Drive. When the limit is reached:
- uploads stop with a "Storage full, ask the admin" message;
- new Drive photos wait with "Storage limit reached". After you raise the limit, the photographer presses
  **Retry** on the event page.

### Photographers deleting things

From the **⋮** menu on an event page:
- **Remove photos with no faces**: shows every photo where no face was found (guests can never find those) as a
  grid, all ticked. Untick any to keep, then remove the rest to free storage. Photos from Google Drive stay in
  Drive; they're just taken out of the event and won't come back on the next sync.
- **Delete event**: after typing the event name to confirm, deletes the event, its uploaded photos and previews
  (from R2 or disk). The QR code stops working. Nothing in Google Drive is touched.

## Cloudflare R2 storage

With R2 configured, uploaded photos and previews are stored in your R2 bucket instead of on the server. The bucket
stays private: the app checks that a visitor may see a photo, then redirects them to a signed link that expires
after an hour. R2 doesn't charge for downloads, so guests downloading photos costs nothing extra.

1. Cloudflare dashboard → **R2** → **Create bucket** (e.g. `weddingsnap-photos`). Keep public access **off**.
2. **R2 → Manage API tokens → Create API token**: permission *Object Read & Write*, limited to that bucket.
   Copy the **Access Key ID** and **Secret Access Key** (shown once) and your **Account ID**.
3. Put them in `.env`:
   ```
   R2_ACCOUNT_ID=…
   R2_ACCESS_KEY_ID=…
   R2_SECRET_ACCESS_KEY=…
   R2_BUCKET=weddingsnap-photos
   ```
   For an EU-jurisdiction bucket, also set `R2_ENDPOINT=https://<account id>.eu.r2.cloudflarestorage.com`.
4. **Move files you already have** (one time), then restart the server:
   ```bash
   python manage.py copy_media_to_r2 --dry-run   # shows what will be uploaded
   python manage.py copy_media_to_r2
   ```
   It's safe to run again; files already in R2 are skipped. Once everything works you can delete `media/`.

If only some R2 settings are filled in, the server refuses to start and names the missing ones. The per-photographer
limits are enforced by the app (R2 has no per-folder quotas); all photographers share one bucket, with each event
under `events/<event>/`.

## Bulk import from a folder

```bash
python manage.py import_photos <event-slug> /Volumes/SDCARD/DCIM   # uploads (to R2 or disk) + indexes, keeps subfolders
```

## Indexing (finding faces)

Uploads, Drive syncs and folder scans only *add* photos; they show as **Not indexed** and guests can't find them yet.
Indexing starts when the photographer presses **Index N photos** on the event page (progress shows live), or from
the command line:

```bash
python manage.py index_photos                         # everything not indexed yet, all events
python manage.py index_photos <event-slug> [<slug>…]  # only these events
python manage.py index_photos --photographer USERNAME # only one photographer's events
python manage.py index_photos --retry-failed          # also retry photos that failed (e.g. storage was full)
python manage.py index_photos --all                   # re-index everything (e.g. after changing face settings)
python manage.py index_photos --dry-run               # just count
python manage.py index_photos --batch-size 10 --pause 2 --workers 1   # gentler on a small server
python manage.py sync_drive [--index]                 # pick up Drive changes; --index also indexes them
```

If the server restarts while indexing, press **Index photos** again (or run the command) to finish the rest.

### Batches, so the server doesn't hang

Indexing never grabs the whole machine. It takes a **batch** of photos, works through them with a few low-priority
threads, **pauses**, then takes the next batch, so guests' selfie searches and page loads always get CPU time.
Memory stays bounded too: only a few photos are held at once, big JPEGs are decoded at reduced size, and the face
models (~60 MB per copy) are shared instead of loaded per thread. The command does the same (`--batch-size`,
`--pause`, `--workers`) and runs at low priority.

Defaults come from the machine, so there's nothing to tune:

| Machine | Photos analysed at once | In memory at once | Batch / pause | Face-model copies |
|---|---|---|---|---|
| Under 1.5 GB RAM (e.g. $4 / $6 droplet) | 1 | 1 | 10 / 1 s | 1, shared with guest searches |
| 1–2 CPUs, more RAM | 1 | 2 | 10 / 1 s | 2 (one always free for guests) |
| Bigger | half the cores | 6 | 24 / 0.2 s | slots + 1 |

Override any of them in `.env` (`INDEX_BATCH_SIZE`, `INDEX_BATCH_PAUSE`, `INDEX_CPU_SLOTS`, `INDEX_DOWNLOADS`,
`FACE_MODEL_COPIES`, `ZIP_PARALLEL`). Face detection stays at 2000 px on every machine: at 1600 px it missed
2 of 40 faces in a group-photo test, and at 1280 px 18 of 40.

## Hosting on a small DigitalOcean droplet

Measured with the "under 1.5 GB" settings while indexing 24 MP photos: about **550 MB peak** (app ~100 MB +
face models ~160 MB + one photo being analysed ~250 MB). A guest's selfie search took ~0.2 s during indexing.

- **$4 droplet (512 MB, 1 vCPU, 10 GB)**: works, but only with a **swap file** to absorb that peak, and with
  **R2** for photos (10 GB of disk won't hold originals). Expect ~1 photo every 1–2 s, and slowdowns while swapping.
- **$6 droplet (1 GB, 1 vCPU, 25 GB)**: recommended. Same settings, but it fits in memory without relying on swap.

Setup outline (Ubuntu):

```bash
# 2 GB swap (do this first on 512 MB / 1 GB droplets)
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

sudo apt install -y python3-venv nginx
# copy the project (with frontend/dist already built on your computer: `npm run build`; building on a
# 512 MB droplet can run out of memory), then:
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt gunicorn
.venv/bin/python manage.py migrate && .venv/bin/python manage.py collectstatic --noinput
```

Run the app with **one** gunicorn worker (indexing lives inside it) and fewer memory arenas:

```bash
MALLOC_ARENA_MAX=2 DJANGO_DEBUG=0 .venv/bin/gunicorn weddingsnap.wsgi -w 1 --threads 4 --timeout 120 -b 127.0.0.1:8000
```

Put that in a systemd service, have nginx serve `/static/` and proxy everything else to port 8000, add HTTPS
(certbot), and set `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `PUBLIC_BASE_URL` and the R2 settings in `.env`.
Don't run the `index_photos` command while the app is also indexing on a 512 MB droplet; that loads a second
copy of the models.

Without R2 you can also copy files straight into `media/events/<event-slug>/originals/` and press **Scan folder**
on the event page.

## Settings (environment variables or `.env`)

| Variable | Default | Purpose |
|---|---|---|
| `PUBLIC_BASE_URL` | (request host) | Address encoded in QR codes, e.g. `https://photos.example.com` |
| `FACE_MATCH_THRESHOLD` | `0.40` | Similarity needed for a match. Raise it if strangers show up, lower it if photos are missed |
| `GOOGLE_API_KEY` | — | Enables Google Drive "Anyone with the link" folders |
| `GOOGLE_OAUTH_CLIENT_ID` / `_SECRET` | — | Optional: private Drive folders via Google sign-in |
| `INDEX_BATCH_SIZE`, `INDEX_BATCH_PAUSE`, `INDEX_CPU_SLOTS`, `INDEX_DOWNLOADS`, `FACE_MODEL_COPIES`, `ZIP_PARALLEL` | from the machine | Indexing batches and limits (see "Batches") |
| `DRIVE_AUTO_SYNC_MINUTES` | `5` | Background re-check of Drive folders |
| `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET` | — | Store photos in Cloudflare R2 (see above) |
| `R2_ENDPOINT` | from account ID | Only for EU-jurisdiction buckets |
| `DEFAULT_STORAGE_GB` | `1` | Storage for a new photographer until you change it in the admin |
| `DJANGO_SECRET_KEY` | dev key | **Set in production** |
| `DJANGO_DEBUG` | `1` | Set to `0` in production |
| `DJANGO_ALLOWED_HOSTS` | `*` | Comma-separated hostnames |

## Production notes

- Guests' phones need to reach the server, so deploy it on a public host with HTTPS.
- Build the UI (`npm run build` in `frontend/`), then run `python manage.py collectstatic` and serve `/static/`
  from nginx (or add WhiteNoise). Do **not** expose `media/`;
  photos are served through the app's permission check.
- Indexing runs in a background thread inside the web process, so use **one** gunicorn worker process
  (threads are fine: `gunicorn weddingsnap.wsgi -w 1 --threads 8`). If the server restarts mid-batch,
  press *Index photos* again or run `index_photos`.
- Google refresh tokens are stored in the database. Protect it, and consider encrypting that column in production.
- Speed: roughly 0.1–0.3 s per photo on a laptop CPU, so ~1,000 photos take a few minutes.

## Tests

```bash
python manage.py test gallery
# End-to-end test with real faces: put OpenCV's samples/data/lena.jpg and messi5.jpg in a folder
FACE_SAMPLE_DIR=/path/to/folder python manage.py test gallery
```

The R2 tests run against a local S3-compatible server and need `pip install "moto[server]"` (test-only; they're
skipped without it).
