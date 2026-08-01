import os
import re
import subprocess
import time
import threading
import logger

SKIP_FILE = "skipytlink.txt"


# ── Load Skip List ────────────────────────────────────────────────────

def load_skip_list():
    """
    Load YouTube URLs from skipytlink.txt into a set.
    Creates the file automatically if it does not exist.
    Ignores blank lines and lines starting with #.
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
    Extract the video ID and return a clean consistent URL.
    Handles youtube.com/watch?v= and youtu.be/ formats.
    Returns None if no valid 11-char video ID is found.
    """
    if not url:
        return None
    match = re.search(r'(?:v=|youtu\.be/)([\w\-]{11})', url)
    if match:
        return f"https://www.youtube.com/watch?v={match.group(1)}"
    return None


# ── Clear Logcat Buffer ───────────────────────────────────────────────

def clear_logcat(udid):
    """
    Flush the logcat buffer on the target device so the next read
    only contains events that happen AFTER this call.
    """
    try:
        subprocess.run(
            ["adb", "-s", udid, "logcat", "-c"],
            capture_output=True,
            timeout=5
        )
    except Exception as e:
        logger.log(f"[{udid}][YT] ⚠ clear_logcat failed: {e}")


# ── Capture URL from Logcat After Click ──────────────────────────────

def capture_yt_url_from_logcat(udid, timeout=6):
    """
    Read logcat for up to `timeout` seconds after the play button is
    clicked and return the first YouTube URL fired via Intent.

    The app fires:
        ActivityManager: START u0 {act=android.intent.action.VIEW
                         dat=https://www.youtube.com/watch?v=XXXXX ...}

    Returns a normalized URL string, or None if nothing is found in time.
    """
    pattern = re.compile(
        r'dat=(https?://(?:www\.)?(?:youtube\.com|youtu\.be)/[^\s}]+)'
    )

    result_holder = [None]
    stop_flag     = threading.Event()

    def _read():
        try:
            proc = subprocess.Popen(
                ["adb", "-s", udid, "logcat", "-v", "brief",
                 "-s", "ActivityManager:I"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="ignore"
            )
            while not stop_flag.is_set():
                line = proc.stdout.readline()
                if not line:
                    break
                m = pattern.search(line)
                if m:
                    url = normalize_url(m.group(1))
                    if url:
                        result_holder[0] = url
                        stop_flag.set()
                        break
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except Exception:
                pass
        except Exception as e:
            logger.log(f"[{udid}][YT] ⚠ logcat thread error: {e}")

    t = threading.Thread(target=_read, daemon=True)
    t.start()
    t.join(timeout=timeout)
    stop_flag.set()   # make sure thread exits even if URL not found

    return result_holder[0]


# ── Page Source Strategies (pre-click, best effort) ───────────────────

def _get_url_from_page(driver, udid):
    """
    Try to extract URL without clicking.
    Returns a normalized URL or None.
    These rarely work for native apps but are worth trying first.
    """
    from appium.webdriver.common.appiumby import AppiumBy

    # Strategy A: content-desc attribute
    try:
        el = driver.find_element(
            AppiumBy.XPATH,
            '//*[contains(@content-desc, "youtube.com") '
            'or contains(@content-desc, "youtu.be")]'
        )
        url = normalize_url(el.get_attribute("content-desc"))
        if url:
            logger.log(f"[{udid}][YT] ✓ URL via content-desc: {url}")
            return url
    except Exception:
        pass

    # Strategy B: text attribute
    try:
        el = driver.find_element(
            AppiumBy.XPATH,
            '//*[contains(@text, "youtube.com") '
            'or contains(@text, "youtu.be")]'
        )
        url = normalize_url(el.get_attribute("text"))
        if url:
            logger.log(f"[{udid}][YT] ✓ URL via text attr: {url}")
            return url
    except Exception:
        pass

    # Strategy C: full page source XML scan
    try:
        matches = re.findall(
            r'https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)[\w\-]{11}[^\s"\'<>]*',
            driver.page_source
        )
        if matches:
            url = normalize_url(matches[0])
            if url:
                logger.log(f"[{udid}][YT] ✓ URL via page source: {url}")
                return url
    except Exception:
        pass

    # Strategy D: WebView context
    try:
        for ctx in driver.contexts:
            if "WEBVIEW" not in ctx:
                continue
            try:
                driver.switch_to.context(ctx)
                url = normalize_url(driver.current_url)
                if url:
                    logger.log(f"[{udid}][YT] ✓ URL via WebView: {url}")
                    driver.switch_to.context("NATIVE_APP")
                    return url
                matches = re.findall(
                    r'https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)[\w\-]{11}[^\s"\'<>]*',
                    driver.page_source
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

    return None


# ── Main Entry Point ──────────────────────────────────────────────────

def check_and_play(driver, udid, skip_list, click_fn):
    """
    Full skip-or-play flow. Call this instead of clicking the play
    button directly.

    Flow:
        1. Try to get URL from page source (no click needed).
           → If found and in skip list: skip immediately, no click.
           → If found and NOT in skip list: click and play normally.

        2. If page source gives nothing (the common case for this app):
           → Clear logcat buffer.
           → Click the play button.
           → Listen to logcat for up to 6s for the Intent URL.
           → If URL appears and is in skip list: press back immediately.
           → If URL not in skip list or not found: let it play normally.

    Args:
        driver    : Appium WebDriver instance
        udid      : device/emulator ID string
        skip_list : set of normalized URLs loaded by load_skip_list()
        click_fn  : zero-argument callable that clicks the play button
                    e.g. lambda: image_element.click()

    Returns:
        "skip"    → video was skipped (back already pressed)
        "play"    → video is playing, caller should wait normally
        "unknown" → URL could not be determined, video is playing
    """

    # ── Step 1: try page source first (no side effects) ───────────────
    url = _get_url_from_page(driver, udid)

    if url:
        if url in skip_list:
            logger.log(f"[{udid}][YT] ⏭ SKIP (pre-click) — in skip list: {url}")
            return "skip"
        else:
            logger.log(f"[{udid}][YT] ▶ PLAY (pre-click) — not in skip list: {url}")
            click_fn()
            return "play"

    # ── Step 2: URL not in page — click and capture from logcat ───────
    logger.log(f"[{udid}][YT] → URL not in page source, using logcat capture...")

    clear_logcat(udid)   # flush stale log entries
    click_fn()           # click play — this fires the Intent

    url = capture_yt_url_from_logcat(udid, timeout=6)

    if url is None:
        logger.log(f"[{udid}][YT] ⚠ URL not captured from logcat — letting video play.")
        return "unknown"

    logger.log(f"[{udid}][YT] ✓ Captured URL from logcat: {url}")

    if url in skip_list:
        logger.log(f"[{udid}][YT] ⏭ SKIP (post-click) — pressing back.")
        time.sleep(1)          # brief pause so YouTube has started
        driver.back()          # return to the app
        time.sleep(1)
        return "skip"

    logger.log(f"[{udid}][YT] ▶ PLAY — not in skip list.")
    return "play"
