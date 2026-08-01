import os
import re
import subprocess
import logger

SKIP_FILE = "skipytlink.txt"


# ── Load Skip List ────────────────────────────────────────────────────

def load_skip_list():
    """
    Load YouTube URLs from skipytlink.txt into a set.
    Creates the file automatically if it does not exist.
    Returns a set of normalized URLs for fast lookup.
    """
    if not os.path.exists(SKIP_FILE):
        logger.log(f"[YT] ⚠ {SKIP_FILE} not found — creating empty file.")
        open(SKIP_FILE, "w", encoding="utf-8").close()
        return set()

    with open(SKIP_FILE, "r", encoding="utf-8") as f:
        links = set(
            line.strip()
            for line in f
            if line.strip() and not line.strip().startswith("#")
        )

    logger.log(f"[YT] ✓ Loaded {len(links)} skip link(s) from {SKIP_FILE}")
    return links


# ── Normalize URL ─────────────────────────────────────────────────────

def normalize_url(url):
    """
    Extract the video ID and return a clean, consistent URL.
    Handles both youtube.com/watch?v= and youtu.be/ formats.
    Returns None if no valid video ID is found.
    """
    if not url:
        return None

    match = re.search(r'(?:v=|youtu\.be/)([\w\-]{11})', url)
    if match:
        return f"https://www.youtube.com/watch?v={match.group(1)}"

    return None


# ── Extract YouTube URL from Page Source ──────────────────────────────

def get_yt_url_from_page(driver, udid):
    """
    Extract the YouTube URL from the current screen WITHOUT clicking.

    Strategy A — content-desc attribute contains a YouTube URL
    Strategy B — text attribute contains a YouTube URL
    Strategy C — scan full page source XML for YouTube URLs
    Strategy D — switch to WebView context and read current URL / source

    Returns a normalized URL string, or None if not found.
    """

    # ── Strategy A: content-desc ──────────────────────────────────────
    try:
        from appium.webdriver.common.appiumby import AppiumBy
        el = driver.find_element(
            AppiumBy.XPATH,
            '//*[contains(@content-desc, "youtube.com") '
            'or contains(@content-desc, "youtu.be")]'
        )
        raw = el.get_attribute("content-desc")
        url = normalize_url(raw)
        if url:
            logger.log(f"[{udid}][YT] ✓ URL via content-desc: {url}")
            return url
    except Exception:
        pass

    # ── Strategy B: text attribute ────────────────────────────────────
    try:
        from appium.webdriver.common.appiumby import AppiumBy
        el = driver.find_element(
            AppiumBy.XPATH,
            '//*[contains(@text, "youtube.com") '
            'or contains(@text, "youtu.be")]'
        )
        raw = el.get_attribute("text")
        url = normalize_url(raw)
        if url:
            logger.log(f"[{udid}][YT] ✓ URL via text attr: {url}")
            return url
    except Exception:
        pass

    # ── Strategy C: scan page source XML ─────────────────────────────
    try:
        source = driver.page_source
        matches = re.findall(
            r'https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)[\w\-]{11}[^\s"\'<>]*',
            source
        )
        if matches:
            url = normalize_url(matches[0])
            if url:
                logger.log(f"[{udid}][YT] ✓ URL via page source: {url}")
                return url
    except Exception:
        pass

    # ── Strategy D: WebView context ───────────────────────────────────
    try:
        contexts = driver.contexts
        for ctx in contexts:
            if "WEBVIEW" not in ctx:
                continue
            try:
                driver.switch_to.context(ctx)

                # try current URL first
                current = driver.current_url
                url = normalize_url(current)
                if url:
                    logger.log(f"[{udid}][YT] ✓ URL via WebView current_url: {url}")
                    driver.switch_to.context("NATIVE_APP")
                    return url

                # scan WebView page source
                wv_source = driver.page_source
                matches = re.findall(
                    r'https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)[\w\-]{11}[^\s"\'<>]*',
                    wv_source
                )
                if matches:
                    url = normalize_url(matches[0])
                    if url:
                        logger.log(f"[{udid}][YT] ✓ URL via WebView source: {url}")
                        driver.switch_to.context("NATIVE_APP")
                        return url

            except Exception:
                pass
            finally:
                try:
                    driver.switch_to.context("NATIVE_APP")
                except Exception:
                    pass
    except Exception:
        pass

    logger.log(f"[{udid}][YT] ⚠ Could not extract YouTube URL from screen.")
    return None


# ── Get YouTube URL via ADB Logcat (Post-Click Capture) ──────────────

def get_yt_url_from_logcat(udid):
    """
    Capture YouTube URL from ADB logcat by reading recent ActivityManager logs.
    Used as a fallback after a click has been made.
    Returns a normalized URL string, or None if not found.
    """
    try:
        result = subprocess.run(
            ["adb", "-s", udid, "logcat", "-d", "-s", "ActivityManager:I"],
            capture_output=True,
            text=True,
            timeout=10
        )
        matches = re.findall(
            r'dat=(https?://(?:www\.)?(?:youtube\.com|youtu\.be)/[^\s}]+)',
            result.stdout
        )
        if matches:
            url = normalize_url(matches[-1])   # use most recent match
            if url:
                logger.log(f"[{udid}][YT] ✓ URL via logcat: {url}")
                return url
    except Exception as e:
        logger.log(f"[{udid}][YT] ⚠ logcat fallback failed: {e}")

    return None


# ── Main Check ────────────────────────────────────────────────────────

def should_skip_video(driver, udid, skip_list):
    """
    Check whether the current video should be skipped.

    1. Extract the YouTube URL from the screen (no click needed).
    2. Normalize it.
    3. Check against the skip_list set.

    Returns:
        (should_skip: bool, url: str | None)
        should_skip = True  → video is in skipytlink.txt, do NOT click play
        should_skip = False → video is new, safe to click play
    """
    url = get_yt_url_from_page(driver, udid)

    if url is None:
        logger.log(f"[{udid}][YT] ⚠ No URL found — allowing play (fail-open).")
        return False, None

    if url in skip_list:
        logger.log(f"[{udid}][YT] ⏭ SKIP — URL in skip list: {url}")
        return True, url

    logger.log(f"[{udid}][YT] ▶ PLAY — URL not in skip list: {url}")
    return False, url
