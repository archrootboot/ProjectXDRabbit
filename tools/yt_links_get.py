"""
tools/yt_links_get.py

Thumbnail-based video skip detection using perceptual hashing (pHash).

How it works:
    1. Capture a screenshot of the current screen via Appium.
    2. Capture directly from imageView_img element (element.screenshot_as_png).
    3. Compute a 64-bit pHash fingerprint — near-zero CPU cost.
    4. Compare against hashes pre-built from your skip_thumbs/ folder.
    5. If Hamming distance <= threshold → same video → skip.
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
    - Screenshot capture : ~200-500ms (Appium, unavoidable)
"""

import os
import io
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

SKIP_THUMBS_DIR  = "skip_thumbs"  # folder with reference thumbnails

# Dual-hash matching (aHash + wHash must both agree)
# aHash catches overall brightness/color structure  → robust to overlays
# wHash catches wavelet frequency patterns          → robust to resizing
# Both must be within threshold to count as a match (reduces false positives)
AHASH_THRESHOLD  = 6              # aHash Hamming distance ≤ this = match
WHASH_THRESHOLD  = 10             # wHash Hamming distance ≤ this = match


# ── Build Skip Hashes ─────────────────────────────────────────────────

def build_skip_hashes():
    """
    Read every image in skip_thumbs/ and compute its pHash.
    Returns a dict: { filename: pHash } for use in check_and_play().

    Call this ONCE at startup — result stays in memory for the session.
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
            # store both hash types per image
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


# ── Capture Thumbnail Directly from Element ───────────────────────────

THUMB_ELEMENT_ID = "com.view.ytrabbit:id/imageView_img"

def _capture_thumbnail(driver, udid):
    """
    Capture the thumbnail image directly from the imageView_img element
    using element.screenshot_as_png — no full-screen capture needed.

    This is faster and more precise than a full screenshot + crop:
      - Only the exact element pixels are transferred
      - No coordinate math required
      - Unaffected by screen resolution or density differences

    Returns a PIL Image (RGB), or None on failure.
    """
    if not _DEPS_OK:
        return None

    try:
        from appium.webdriver.common.appiumby import AppiumBy

        el        = driver.find_element(AppiumBy.ID, THUMB_ELEMENT_ID)
        png_bytes = el.screenshot_as_png          # element-level screenshot
        img       = Image.open(io.BytesIO(png_bytes)).convert("RGB")

        logger.log(f"[{udid}][YT] ✓ Thumbnail captured from element "
                   f"({img.width}×{img.height}px)")
        return img

    except Exception as e:
        logger.log(f"[{udid}][YT] ✗ Element screenshot failed: {e}")
        return None

def _is_skip_thumbnail(thumb_img, skip_hashes, udid):
    """
    Dual-hash comparison: aHash + wHash must BOTH be within threshold.

    Why dual hash?
      - Captured thumbnail has a play button overlay in the centre
      - Reference thumbnail (from YouTube) has black bars and different crop
      - pHash (DCT-based) is too sensitive to these structural differences
      - aHash (average brightness) + wHash (wavelet) are both robust to
        overlays, slight crops, and resolution differences — together they
        give high accuracy with very low false-positive rate.

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

    for fname, ref in skip_hashes.items():
        a_dist = cur_ahash - ref["ahash"]
        w_dist = cur_whash - ref["whash"]

        # both must match — dual vote reduces false positives
        if a_dist <= AHASH_THRESHOLD and w_dist <= WHASH_THRESHOLD:
            # pick closest overall match if multiple qualify
            score = a_dist + w_dist
            if best_name is None or score < (best_a + best_w):
                best_a    = a_dist
                best_w    = w_dist
                best_name = fname

    if best_name:
        logger.log(f"[{udid}][YT] ⏭ MATCH '{best_name}' "
                   f"(aHash={best_a} wHash={best_w}) → skip.")
        return True, best_name

    logger.log(f"[{udid}][YT] ▶ No match → play.")
    return False, None


# ── Save Current Thumbnail (helper for building skip list) ────────────

def save_current_thumbnail(driver, udid, filename=None):
    """
    Convenience helper: capture the current thumbnail and save it to
    skip_thumbs/ so you can build your reference set without manually
    cropping screenshots.

    Usage (call from a one-off script or REPL):
        import tools.yt_links_get as yt
        hashes = yt.build_skip_hashes()
        yt.save_current_thumbnail(driver, "emulator-5556", "video_name.png")
    """
    os.makedirs(SKIP_THUMBS_DIR, exist_ok=True)
    img = _capture_thumbnail(driver, udid)
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

def check_and_play(driver, udid, skip_hashes, click_fn):
    """
    Thumbnail-based skip-or-play gate. Call instead of clicking play.

    Flow:
        1. Capture screenshot → crop to thumbnail region.
        2. Compute pHash → compare against skip_hashes.
        3. Match found  → return "skip"  (no click performed).
        4. No match     → call click_fn() → return "play".
        5. Capture fail → call click_fn() → return "unknown" (fail-open).

    Args:
        driver      : Appium WebDriver instance
        udid        : device/emulator ID string
        skip_hashes : dict returned by build_skip_hashes()
        click_fn    : zero-arg callable that clicks the play button

    Returns:
        "skip"    → video matched skip list, no click made
        "play"    → video did not match, click_fn() called
        "unknown" → thumbnail capture failed, click_fn() called (fail-open)
    """
    if not _DEPS_OK:
        logger.log(f"[{udid}][YT] ⚠ Dependencies missing — playing video.")
        click_fn()
        return "unknown"

    # ── capture & hash current thumbnail ─────────────────────────────
    thumb = _capture_thumbnail(driver, udid)

    if thumb is None:
        logger.log(f"[{udid}][YT] ⚠ Capture failed — playing video (fail-open).")
        click_fn()
        return "unknown"

    # ── compare against skip references ──────────────────────────────
    matched, fname = _is_skip_thumbnail(thumb, skip_hashes, udid)

    if matched:
        return "skip"

    # ── not a skip video — click play ────────────────────────────────
    click_fn()
    return "play"
