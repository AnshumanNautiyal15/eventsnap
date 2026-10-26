"""Face detection (YuNet) and recognition (SFace) using OpenCV's bundled ONNX runtime."""
import io
import queue
import threading
from contextlib import contextmanager

import cv2
import numpy as np
import pillow_heif
from django.conf import settings
from PIL import Image, ImageOps

pillow_heif.register_heif_opener()  # HEIC/HEIF (iPhone); Pillow reads AVIF, WebP, TIFF, GIF etc. natively

# Camera RAW formats, decoded with LibRaw (rawpy) when Pillow can't open them.
RAW_EXTENSIONS = {
    ".cr2", ".cr3", ".crw", ".nef", ".nrw", ".arw", ".srf", ".sr2", ".dng", ".raf", ".orf", ".rw2",
    ".pef", ".srw", ".x3f", ".3fr", ".fff", ".iiq", ".mos", ".mrw", ".erf", ".kdc", ".dcr", ".rwl",
}
IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".jpe", ".jfif", ".png", ".webp", ".heic", ".heif", ".hif", ".avif", ".tif", ".tiff",
    ".bmp", ".gif", ".jp2", ".j2k", ".psd", ".ico", ".tga",
} | RAW_EXTENSIONS

DETECT_SCORE = 0.8
MIN_FACE_PX = 24  # smaller faces (in the downscaled image) are too blurry to recognise reliably

# Each OpenCV thread pool would otherwise spread one detection over every core; indexing already runs
# INDEX_CPU_SLOTS photos side by side, so one core per detection keeps the machine responsive.
cv2.setNumThreads(settings.FACE_CV_THREADS)


class NoFaceFound(Exception):
    pass


# --- Shared model copies ------------------------------------------------------------
# A loaded detector + recognizer pair takes ~60 MB (the first one ~160 MB with OpenCV's engine), and
# OpenCV DNN objects can't be used by two threads at once. So copies live in a small pool: a thread
# borrows one for a single detection and returns it. At most FACE_MODEL_COPIES exist; indexing can only
# hold INDEX_CPU_SLOTS of them, so guests' selfie searches always have one free.

_idle = queue.LifoQueue()
_created = 0
_create_lock = threading.Lock()


def _load_models():
    model_dir = settings.FACE_MODEL_DIR
    detector = cv2.FaceDetectorYN.create(
        str(model_dir / "face_detection_yunet_2023mar.onnx"), "", (320, 320), DETECT_SCORE, 0.3, 5000
    )
    recognizer = cv2.FaceRecognizerSF.create(str(model_dir / "face_recognition_sface_2021dec.onnx"), "")
    return detector, recognizer


@contextmanager
def _models():
    global _created
    try:
        pair = _idle.get_nowait()
    except queue.Empty:
        with _create_lock:
            make = _created < settings.FACE_MODEL_COPIES
            if make:
                _created += 1
        pair = _load_models() if make else _idle.get()  # at the cap: wait for a copy to come back
    try:
        yield pair
    finally:
        _idle.put(pair)


def load_image(source, min_side=None):
    """Open bytes or a file object in any supported format (incl. HEIC and camera RAW).

    Applies EXIF rotation (phone photos) and returns a PIL RGB image. JPEGs are decoded directly at
    1/2, 1/4 or 1/8 size when that still leaves at least `min_side` pixels on each side: face detection
    never looks at more than FACE_DETECT_MAX_SIDE, so a 24 MP original needs a quarter of the memory and time.
    """
    data = source if isinstance(source, bytes) else source.read()
    min_side = min_side or settings.FACE_DETECT_MAX_SIDE
    try:
        img = Image.open(io.BytesIO(data))
        img.draft("RGB", (min_side, min_side))
        img = ImageOps.exif_transpose(img)
    except Exception:
        img = _load_raw(data)
    return img.convert("RGB")


def _load_raw(data):
    import rawpy

    try:
        with rawpy.imread(io.BytesIO(data)) as raw:
            try:
                # Most RAW files embed a full-size JPEG preview: far faster than demosaicing.
                thumb = raw.extract_thumb()
                if thumb.format == rawpy.ThumbFormat.JPEG:
                    return ImageOps.exif_transpose(Image.open(io.BytesIO(thumb.data)))
                if thumb.format == rawpy.ThumbFormat.BITMAP:
                    return Image.fromarray(thumb.data)
            except (rawpy.LibRawNoThumbnailError, rawpy.LibRawUnsupportedThumbnailError):
                pass
            return Image.fromarray(raw.postprocess(half_size=True, use_camera_wb=True))
    except rawpy.LibRawError as exc:
        raise ValueError(f"Unsupported or corrupt image: {exc}") from exc


def detect_faces(pil_img, max_side=None):
    """Return a list of (embedding, box) for every face; box is [x, y, w, h] in pil_img pixels."""
    max_side = max_side or settings.FACE_DETECT_MAX_SIDE
    scale = min(1.0, max_side / max(pil_img.size))
    if scale < 1.0:
        pil_img = pil_img.resize((round(pil_img.width * scale), round(pil_img.height * scale)), Image.LANCZOS)
    bgr = cv2.cvtColor(np.asarray(pil_img), cv2.COLOR_RGB2BGR)

    results = []
    with _models() as (detector, recognizer):
        detector.setInputSize((bgr.shape[1], bgr.shape[0]))
        _, rows = detector.detect(bgr)
        for row in rows if rows is not None else []:
            w, h = row[2], row[3]
            if min(w, h) < MIN_FACE_PX:
                continue
            aligned = recognizer.alignCrop(bgr, row)
            vec = recognizer.feature(aligned).flatten().astype(np.float32)
            vec /= np.linalg.norm(vec) + 1e-9
            box = [int(round(v / scale)) for v in row[:4]]
            results.append((vec, box))
    return results


def selfie_embedding(pil_img):
    """Embedding of the most prominent face in a selfie."""
    # Selfies are close-ups, so a smaller working size is plenty and faster.
    faces = detect_faces(pil_img, max_side=1280)
    if not faces:
        raise NoFaceFound
    return max(faces, key=lambda f: f[1][2] * f[1][3])[0]


def make_thumbnail(pil_img, size=1024):
    """Preview used for the grid and the guest lightbox; originals are only fetched on download."""
    thumb = pil_img.copy()
    thumb.thumbnail((size, size), Image.LANCZOS)
    buf = io.BytesIO()
    thumb.save(buf, "JPEG", quality=82, optimize=True)
    return buf.getvalue()
