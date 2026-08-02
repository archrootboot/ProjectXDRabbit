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

            # convert to PNG if needed (jpg bytes → PIL → save as png)
            if THUMB_EXT in ("png",):
                try:
                    from PIL import Image
                    import io
                    img = Image.open(io.BytesIO(data)).convert("RGB")
                    img.save(save_path, format="PNG")
                except ImportError:
                    # Pillow not available — save raw jpg bytes anyway
                    save_path = save_path.rsplit(".", 1)[0] + ".jpg"
                    with open(save_path, "wb") as f:
                        f.write(data)
            else:
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
