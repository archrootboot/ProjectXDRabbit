"""
tools/yt_links_get.py

Thumbnail-based video skip detection using perceptual hashing (pHash).

How it works:
    1. Capture a screenshot of the current element via ADB (screencap + crop).
    2. Compute dual-hash fingerprint (aHash + wHash) — near-zero CPU cost.
    3. Compare against hashes pre-built from your skip_thumbs/ folder.
    4. If Hamming distance <= threshold → same video → skip.
       Otherwise → click play normally.

Setup:
    1. pip install Pillow imagehash
    2. Create a folder:  skip_thumbs/
       Place cropped thumbnail screenshots (.png/.jpg) of videos to skip.
    3. Call build_skip_hashes() once at startup.
    4. Call check_and_play() instead of clicking play directly.

CPU cost:
    - pHash computation  : ~1-3ms per image
    - Hash comparison    : microseconds (integer XOR)
    - Screenshot capture : ~300-600ms (ADB screencap, unavoidable)
"""

import os
import logger

# ── lazy imports (only loaded if this module is used) ─────────────────
try:
    from PIL import Image
    import imagehash
    _DEPS_OK = True
except ImportError:
    _DEPS_OK = False
    logger.log("[YT] ⚠ Pillow / imagehash not installed. "
               "Run: pip install Pillow imagehash")


# ── Config ────────────────────────────────────────────────────────────

SKIP_THUMBS_DIR  = "skip_thumbs"

# Dual-hash matching (aHash + wHash must both agree)
AHASH_THRESHOLD  = int(os.getenv("AHASH_THRESHOLD", 8))
WHASH_THRESHOLD  = int(os.getenv("WHASH_THRESHOLD", 12))


# ── Build Skip Hashes ─────────────────────────────────────────────────

def build_skip_hashes():
    """
    Read every image in skip_thumbs/ and compute its pHash.
    Returns a dict: { filename: {"ahash": ..., "whash": ...} }.
    Call this ONCE at startup.
    """
    if not _DEPS_OK:
        logger.log("[YT] ✗ Cannot build hashes — missing dependencies.")
        return {}

    if not os.path.isdir(SKIP_THUMBS_DIR):
        logger.log(f"[YT] ⚠ '{SKIP_THUMBS_DIR}/' folder not found — "
                   "creating it. Add thumbnail images to enable skip.")
        os.makedirs(SKIP_THUMBS_DIR, exist_ok=True)
        return {}

    hashes = {}
    exts   = (".png", ".jpg", ".jpeg", ".bmp", ".webp")

    for fname in os.listdir(SKIP_THUMBS_DIR):
        if not fname.lower().endswith(exts):
            continue
        fpath = os.path.join(SKIP_THUMBS_DIR, fname)
        try:
            img  = Image.open(fpath).convert("RGB")
            hashes[fname] = {
                "ahash": imagehash.average_hash(img),
                "whash": imagehash.whash(img),
            }
            logger.log(f"[YT] ✓ Loaded hash for: {fname}")
        except Exception as e:
            logger.log(f"[YT] ⚠ Could not hash {fname}: {e}")

    if hashes:
        logger.log(f"[YT] ✓ {len(hashes)} skip thumbnail(s) loaded.")
    else:
        logger.log(f"[YT] ⚠ No images found in '{SKIP_THUMBS_DIR}/'.")

    return hashes


# ── Capture Thumbnail Via ADB ─────────────────────────────────────────

THUMB_ELEMENT_ID = "com.view.ytrabbit:id/imageView_img"

def _capture_thumbnail(udid, thumb_el=None):
    """
    Capture the thumbnail using ADB:
      • If thumb_el (parsed XML element) is provided → full screenshot + crop
        to the element's bounding box (most accurate).
      • Fallback: find the element via a fresh uiautomator dump, then crop.
      • If cropping fails → return None (fail-safe; play will proceed).

    Returns a PIL Image (RGB), or None on failure.
    """
    if not _DEPS_OK:
        return None

    import tools.adb_controller as adb

    try:
        # If we weren't given a pre-fetched element, look it up now
        if thumb_el is None:
            root   = adb.dump_ui(udid)
            thumb_el = adb.find_element(root, resource_id=THUMB_ELEMENT_ID)

        if thumb_el is None:
            logger.log(f"[{udid}][YT] ✗ Thumbnail element not found in UI dump.")
            return None

        img = adb.element_screenshot(udid, thumb_el)
        if img is None:
            return None

        logger.log(f"[{udid}][YT] ✓ Thumbnail captured ({img.width}×{img.height}px).")
        return img

    except Exception as e:
        logger.log(f"[{udid}][YT] ✗ Thumbnail capture failed: {e}")
        return None


def _is_skip_thumbnail(thumb_img, skip_hashes, udid):
    """
    Dual-hash comparison: aHash + wHash must BOTH be within threshold.
    Returns (True, matched_filename) or (False, None).
    """
    if not skip_hashes or not _DEPS_OK:
        return False, None

    try:
        cur_ahash = imagehash.average_hash(thumb_img)
        cur_whash = imagehash.whash(thumb_img)
    except Exception as e:
        logger.log(f"[{udid}][YT] ✗ Hash computation failed: {e}")
        return False, None

    best_a    = None
    best_w    = None
    best_name = None
    close_a   = None
    close_w   = None
    close_name = None

    for fname, ref in skip_hashes.items():
        a_dist = cur_ahash - ref["ahash"]
        w_dist = cur_whash - ref["whash"]

        if a_dist <= AHASH_THRESHOLD and w_dist <= WHASH_THRESHOLD:
            score = a_dist + w_dist
            if best_name is None or score < (best_a + best_w):
                best_a    = a_dist
                best_w    = w_dist
                best_name = fname
        else:
            score = a_dist + w_dist
            if close_name is None or score < (close_a + close_w):
                close_a    = a_dist
                close_w    = w_dist
                close_name = fname

    if best_name:
        logger.log(f"[{udid}][YT] ⏭ MATCH '{best_name}' "
                   f"(aHash={best_a} wHash={best_w}) → skip.")
        return True, best_name

    if close_name:
        logger.log(f"[{udid}][YT] ▶ No match → play. "
                   f"Closest: '{close_name}' "
                   f"(aHash={close_a} wHash={close_w} | "
                   f"thresholds: aHash≤{AHASH_THRESHOLD} wHash≤{WHASH_THRESHOLD})")
    else:
        logger.log(f"[{udid}][YT] ▶ No match → play. (skip_thumbs/ is empty)")
    return False, None


# ── Save Current Thumbnail (helper for building skip list) ────────────

def save_current_thumbnail(udid, filename=None):
    """
    Capture the current thumbnail and save it to skip_thumbs/.
    Usage (call from a one-off script or REPL):
        import tools.yt_links_get as yt
        hashes = yt.build_skip_hashes()
        yt.save_current_thumbnail("emulator-5556", "video_name.png")
    """
    os.makedirs(SKIP_THUMBS_DIR, exist_ok=True)
    img = _capture_thumbnail(udid)
    if img is None:
        logger.log(f"[{udid}][YT] ✗ Could not capture thumbnail to save.")
        return None

    if filename is None:
        import time
        filename = f"thumb_{int(time.time())}.png"

    fpath = os.path.join(SKIP_THUMBS_DIR, filename)
    img.save(fpath)
    logger.log(f"[{udid}][YT] ✓ Thumbnail saved → {fpath}")
    return fpath


# ── Main Entry Point ──────────────────────────────────────────────────

def check_and_play(udid, skip_hashes, click_fn, thumb_el=None):
    """
    Thumbnail-based skip-or-play gate. Call instead of clicking play.

    Flow:
        1. Capture screenshot → crop to thumbnail element.
        2. Compute pHash → compare against skip_hashes.
        3. Match found  → return "skip"  (no click performed).
        4. No match     → call click_fn() → return "play".
        5. Capture fail → call click_fn() → return "unknown" (fail-open).

    Args:
        udid        : device serial string
        skip_hashes : dict returned by build_skip_hashes()
        click_fn    : zero-arg callable that clicks the play button
        thumb_el    : optional pre-fetched XML element for the thumbnail

    Returns:
        "skip"    → video matched skip list, no click made
        "play"    → video did not match, click_fn() called
        "unknown" → thumbnail capture failed, click_fn() called (fail-open)
    """
    if not _DEPS_OK:
        logger.log(f"[{udid}][YT] ⚠ Dependencies missing — playing video.")
        click_fn()
        return "unknown"

    thumb = _capture_thumbnail(udid, thumb_el=thumb_el)

    if thumb is None:
        logger.log(f"[{udid}][YT] ⚠ Capture failed — playing video (fail-open).")
        click_fn()
        return "unknown"

    matched, fname = _is_skip_thumbnail(thumb, skip_hashes, udid)

    if matched:
        return "skip"

    click_fn()
    return "play"
