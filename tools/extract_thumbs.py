"""
tools/extract_thumbs.py

Extracts YouTube thumbnails from a list of video links in
skipvideo_link.txt and saves them to the skip_thumbs/ folder.

YouTube provides thumbnails at multiple qualities:
    maxresdefault  → 1280×720  (not always available)
    sddefault      → 640×480
    hqdefault      → 480×360
    mqdefault      → 320×180
    default        → 120×90

Every downloaded thumbnail is automatically converted to match the
captured-thumbnail format used by the app (540×460, black bars at
rows 0–56 top and rows 403–459 bottom, content at rows 57–402).
This ensures extracted thumbnails can be compared reliably against
app-captured ones without any extra processing step.

Image format (PNG or JPG) is controlled by THUMB_IMAGE_EXT in .env.
Image quality is controlled by THUMB_QUALITY in .env.
Images are named by video ID:  <VIDEO_ID>.<ext>
Duplicates (already saved) are skipped automatically.
"""

import os
import re
import urllib.request
import urllib.error
from dotenv import load_dotenv
from PIL import Image

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────

SKIP_LINKS_FILE = "skipvideo_link.txt"
SKIP_THUMBS_DIR = "skip_thumbs"

# ── image format from .env (png / jpg) ───────────────────────────────
_raw_ext  = os.getenv("THUMB_IMAGE_EXT", "jpg").strip().lower().lstrip(".")
THUMB_EXT = _raw_ext if _raw_ext in ("png", "jpg", "jpeg") else "jpg"

# ── thumbnail quality from .env ───────────────────────────────────────
# Valid values: maxresdefault | sddefault | hqdefault | mqdefault | default
# The chosen quality is tried first; remaining qualities are used as
# automatic fallbacks so a thumbnail is always saved even if the
# selected quality is unavailable for a particular video.
_VALID_QUALITIES = [
    "maxresdefault",
    "sddefault",
    "hqdefault",
    "mqdefault",
    "default",
]
_preferred = os.getenv("THUMB_QUALITY", "hqdefault").strip().lower()
if _preferred not in _VALID_QUALITIES:
    _preferred = "hqdefault"

# build fallback list: preferred first, then the rest in order
_YT_QUALITY_ORDER = [_preferred] + [q for q in _VALID_QUALITIES if q != _preferred]

# ── Captured-thumbnail format constants ───────────────────────────────
# These match the exact layout of thumbnails captured by the app,
# so extracted thumbnails can be compared against them reliably.
_CANVAS_W        = 540   # total canvas width
_CANVAS_H        = 460   # total canvas height
_CONTENT_Y_START = 57    # first row of content (black bar above)
_CONTENT_Y_END   = 402   # last row of content  (black bar below)
_CONTENT_H       = _CONTENT_Y_END - _CONTENT_Y_START + 1   # 346 px
_CONTENT_W       = _CANVAS_W                                # 540 px

# ── Play-button overlay constants ─────────────────────────────────────
# Matches the white circular play button burned into app-captured
# thumbnails: an opaque white circle centered on the canvas, with a
# triangle "cut out" of it so the underlying image shows through
# (the classic YouTube-style play icon). Ratios below were measured
# directly off a captured thumbnail (thumb_1785698915.png):
#   circle center ≈ canvas center, radius ≈ 63px on a 540×460 canvas
#   triangle: left edge  ≈ cx - 0.206*r,  apex ≈ cx + 0.381*r
#             top/bottom ≈ cy ∓ 0.286*r
_PLAY_BTN_RADIUS_RATIO   = 63 / 460   # radius as a fraction of canvas height
_PLAY_TRI_LEFT_RATIO     = 0.206      # left edge offset from center, ×radius
_PLAY_TRI_APEX_RATIO     = 0.381      # apex offset from center, ×radius
_PLAY_TRI_HALF_H_RATIO   = 0.286      # half-height offset from center, ×radius


# ── Helpers ───────────────────────────────────────────────────────────

def _extract_video_id(url):
    """
    Extract the 11-character video ID from any YouTube URL format.
    Returns the video ID string, or None if not found.

    Handles:
        https://www.youtube.com/watch?v=VIDEO_ID
        https://youtu.be/VIDEO_ID
        https://www.youtube.com/shorts/VIDEO_ID
        https://m.youtube.com/watch?v=VIDEO_ID
    """
    url = url.strip()
    match = re.search(r'(?:v=|youtu\.be/|shorts/)([\w\-]{11})', url)
    return match.group(1) if match else None


def _convert_to_captured_format(img):
    """
    Convert any downloaded thumbnail to match the captured-thumbnail
    format used by the app (540×460, black bars top/bottom).

    Steps:
      1. Strip the source image's own black bars to get pure content.
      2. Scale content to fill _CONTENT_H tall (preserving aspect ratio).
      3. Crop width to _CONTENT_W centered (removes extra width from
         wide 16:9 sources).
      4. Paste onto a _CANVAS_W × _CANVAS_H black canvas at y=_CONTENT_Y_START.

    Returns a new PIL.Image ready to save.
    """
    import numpy as np

    arr = np.array(img)

    # ── 1. Find and strip source black bars ───────────────────────────
    row_means = arr.mean(axis=(1, 2))
    col_means = arr.mean(axis=(0, 2))

    content_rows = [r for r, v in enumerate(row_means) if v > 10]
    content_cols = [c for c, v in enumerate(col_means) if v > 10]

    if content_rows and content_cols:
        src_y0, src_y1 = content_rows[0],  content_rows[-1]
        src_x0, src_x1 = content_cols[0],  content_cols[-1]
        content = img.crop((src_x0, src_y0, src_x1 + 1, src_y1 + 1))
    else:
        content = img   # no black bars detected — use full image

    src_w, src_h = content.size

    # ── 2. Scale to fill _CONTENT_H (keep aspect ratio) ──────────────
    scale   = _CONTENT_H / src_h
    new_w   = round(src_w * scale)
    scaled  = content.resize((new_w, _CONTENT_H), Image.LANCZOS)

    # ── 3. Crop width to _CONTENT_W centered ─────────────────────────
    if new_w > _CONTENT_W:
        x_off   = (new_w - _CONTENT_W) // 2
        scaled  = scaled.crop((x_off, 0, x_off + _CONTENT_W, _CONTENT_H))
    elif new_w < _CONTENT_W:
        # narrower than target — center with black side bars
        canvas_c = Image.new("RGB", (_CONTENT_W, _CONTENT_H), (0, 0, 0))
        x_off    = (_CONTENT_W - new_w) // 2
        canvas_c.paste(scaled, (x_off, 0))
        scaled   = canvas_c

    # ── 4. Place on full black canvas ────────────────────────────────
    canvas = Image.new("RGB", (_CANVAS_W, _CANVAS_H), (0, 0, 0))
    canvas.paste(scaled, (0, _CONTENT_Y_START))
    return canvas


def _add_play_button(img):
    """
    Draw the white play-button overlay onto a converted (540×460)
    thumbnail so it visually matches the app-captured format, which
    always has this icon burned into the center.

    The button is an opaque white circle with a triangular "window"
    cut out of it, so the image underneath shows through the triangle
    (this is what makes it read as a play icon rather than a plain
    white blob). Position/size are derived from the canvas size so
    this still lines up correctly even if _CANVAS_W/_CANVAS_H change.

    Returns a new PIL.Image (input is not modified).
    """
    from PIL import ImageDraw

    result = img.copy()
    draw   = ImageDraw.Draw(result)

    cx = _CANVAS_W / 2
    cy = _CANVAS_H / 2
    r  = _CANVAS_H * _PLAY_BTN_RADIUS_RATIO

    # ── opaque white circle ───────────────────────────────────────────
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 255, 255))

    # ── triangle cutout: paste original content back inside it ───────
    tri_left = cx - _PLAY_TRI_LEFT_RATIO * r
    tri_apex = cx + _PLAY_TRI_APEX_RATIO * r
    tri_top  = cy - _PLAY_TRI_HALF_H_RATIO * r
    tri_bot  = cy + _PLAY_TRI_HALF_H_RATIO * r

    mask = Image.new("L", (_CANVAS_W, _CANVAS_H), 0)
    ImageDraw.Draw(mask).polygon(
        [(tri_left, tri_top), (tri_left, tri_bot), (tri_apex, cy)],
        fill=255,
    )
    result.paste(img, (0, 0), mask)

    return result


def _fetch_thumbnail(video_id, save_path):
    """
    Try each thumbnail quality URL in order and save the first
    successful download to save_path.

    Returns True on success, False if all qualities failed.
    """
    for quality in _YT_QUALITY_ORDER:
        url = f"https://img.youtube.com/vi/{video_id}/{quality}.jpg"
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = resp.read()

            # YouTube returns a 120×90 placeholder for unavailable thumbs
            # — skip those and try next quality
            if len(data) < 2000:
                continue

            # Convert to captured-thumbnail format (540×460 with black bars)
            # so the script can match extracted thumbnails against app captures.
            try:
                from PIL import Image
                import io
                raw_img    = Image.open(io.BytesIO(data)).convert("RGB")
                converted  = _convert_to_captured_format(raw_img)
                converted  = _add_play_button(converted)
                fmt        = "PNG" if THUMB_EXT == "png" else "JPEG"
                converted.save(save_path, format=fmt)
            except ImportError:
                # Pillow not available — save raw bytes without conversion
                save_path = save_path.rsplit(".", 1)[0] + ".jpg"
                with open(save_path, "wb") as f:
                    f.write(data)

            return True

        except (urllib.error.URLError, urllib.error.HTTPError, OSError):
            continue

    return False


def _load_existing_ids(folder):
    """
    Scan skip_thumbs/ and return a set of video IDs already saved.
    Matches filenames like  dQw4w9WgXcQ.jpg  or  dQw4w9WgXcQ.png
    """
    existing = set()
    if not os.path.isdir(folder):
        return existing
    for fname in os.listdir(folder):
        name, _ = os.path.splitext(fname)
        if re.fullmatch(r'[\w\-]{11}', name):
            existing.add(name)
    return existing


# ── Main ──────────────────────────────────────────────────────────────

def run_extract_thumbs():
    """
    Read skipvideo_link.txt, extract thumbnails for each YouTube link,
    and save them to skip_thumbs/.

    Printed output matches the style used across the project.
    """
    print(f"\n→ Thumbnail Extractor")
    print(f"   Links file : {SKIP_LINKS_FILE}")
    print(f"   Output dir : {SKIP_THUMBS_DIR}/")
    print(f"   Format     : .{THUMB_EXT}  (THUMB_IMAGE_EXT in .env)")
    print(f"   Quality    : {_preferred}  (THUMB_QUALITY in .env)\n")

    # ── read links file ───────────────────────────────────────────────
    if not os.path.exists(SKIP_LINKS_FILE):
        print(f"✗ '{SKIP_LINKS_FILE}' not found.")
        print(f"  Create it and add one YouTube URL per line.")
        return

    with open(SKIP_LINKS_FILE, "r", encoding="utf-8") as f:
        raw_lines = [l.strip() for l in f if l.strip() and not l.strip().startswith("#")]

    if not raw_lines:
        print(f"⚠ '{SKIP_LINKS_FILE}' is empty. Add YouTube links and try again.")
        return

    print(f"   {len(raw_lines)} line(s) found in {SKIP_LINKS_FILE}\n")

    # ── prepare output folder ─────────────────────────────────────────
    os.makedirs(SKIP_THUMBS_DIR, exist_ok=True)
    existing_ids = _load_existing_ids(SKIP_THUMBS_DIR)

    if existing_ids:
        print(f"   {len(existing_ids)} existing thumbnail(s) found — duplicates will be skipped.\n")

    # ── process each line ─────────────────────────────────────────────
    saved    = 0
    skipped  = 0
    invalid  = 0
    failed   = 0

    for line in raw_lines:
        video_id = _extract_video_id(line)

        # ── invalid URL ───────────────────────────────────────────────
        if not video_id:
            print(f"  ⚠ Could not extract video ID from: {line}")
            invalid += 1
            continue

        # ── duplicate ─────────────────────────────────────────────────
        if video_id in existing_ids:
            print(f"  ↷ Skip (already exists): {video_id}.{THUMB_EXT}")
            skipped += 1
            continue

        # ── download ──────────────────────────────────────────────────
        save_path = os.path.join(SKIP_THUMBS_DIR, f"{video_id}.{THUMB_EXT}")
        ok = _fetch_thumbnail(video_id, save_path)

        if ok:
            print(f"  ✓ Saved: {video_id}.{THUMB_EXT}")
            existing_ids.add(video_id)   # prevent re-download within same run
            saved += 1
        else:
            print(f"  ✗ Failed to download thumbnail for: {video_id}  ({line})")
            failed += 1

    # ── summary ───────────────────────────────────────────────────────
    print(f"\n{'─' * 40}")
    print(f"  ✓ Saved    : {saved}")
    print(f"  ↷ Skipped  : {skipped}  (already existed)")
    if invalid:
        print(f"  ⚠ Invalid  : {invalid}  (bad URL / no video ID)")
    if failed:
        print(f"  ✗ Failed   : {failed}  (network error)")
    print(f"{'─' * 40}\n")
