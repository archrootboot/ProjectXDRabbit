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


# ── Logcat Listener (starts BEFORE click) ────────────────────────────

class LogcatListener:
    """
    Starts a logcat process in the background immediately.
    Call .get_url(timeout) AFTER the click to collect the result.

    Correct order (eliminates the timing race):
        listener = LogcatListener(udid)
        listener.start()          ← listening begins here
        click_fn()                ← Intent fires here
        url = listener.get_url()  ← result collected here
        listener.stop()
    """

    _YT_PATTERN = re.compile(
        r'dat=(https?://(?:www\.)?(?:youtube\.com|youtu\.be)/[^\s}]+)'
    )

    def __init__(self, udid):
        self.udid         = udid
        self._result      = [None]
        self._stop_flag   = threading.Event()
        self._ready_flag  = threading.Event()  # set when proc is reading
        self._proc        = None
        self._thread      = None

    def start(self):
        """Spawn logcat process and wait until it is actively reading."""
        self._thread = threading.Thread(target=self._read, daemon=True)
        self._thread.start()
        # wait up to 3s for the process to be ready before returning
        self._ready_flag.wait(timeout=3)

    def _read(self):
        try:
            self._proc = subprocess.Popen(
                ["adb", "-s", self.udid, "logcat",
                 "-s", "ActivityManager:I", "IntentResolver:I"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="ignore"
            )
            self._ready_flag.set()   # signal: process is live and reading

            for line in self._proc.stdout:
                if self._stop_flag.is_set():
                    break
                m = self._YT_PATTERN.search(line)
                if m:
                    url = normalize_url(m.group(1))
                    if url:
                        self._result[0] = url
                        self._stop_flag.set()
                        break

        except Exception as e:
            logger.log(f"[{self.udid}][YT] ⚠ logcat listener error: {e}")
            self._ready_flag.set()   # unblock start() even on error

    def get_url(self, timeout=8):
        """
        Block until a YouTube URL is found or timeout expires.
        Returns normalized URL string or None.
        """
        self._thread.join(timeout=timeout)
        return self._result[0]

    def stop(self):
        """Terminate the background logcat process."""
        self._stop_flag.set()
        if self._proc:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=2)
            except Exception:
                pass


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
    Full skip-or-play flow. Call this instead of clicking play directly.

    Flow:
        1. Try page source strategies first (no click, no side effects).
           → URL found + in skip list  : return "skip" immediately.
           → URL found + not in list   : click and return "play".

        2. URL not in page (common for this app):
           → Start LogcatListener FIRST (eliminates timing race).
           → Click play button         → Intent fires → YouTube opens.
           → Collect URL from listener (up to 8s).
           → URL in skip list          : driver.back() → return "skip".
           → URL not in skip list      : return "play".
           → URL not captured          : return "unknown" (fail-open).

    Returns:
        "skip"    → video skipped, back already pressed by this function
        "play"    → video is playing, caller waits normally
        "unknown" → URL not captured, video is playing (fail-open)
    """

    # ── Step 1: try page source (no side effects) ─────────────────────
    url = _get_url_from_page(driver, udid)

    if url:
        if url in skip_list:
            logger.log(f"[{udid}][YT] ⏭ SKIP (pre-click) — in skip list: {url}")
            return "skip"
        logger.log(f"[{udid}][YT] ▶ PLAY (pre-click) — not in skip list: {url}")
        click_fn()
        return "play"

    # ── Step 2: start listener THEN click (fixes the timing race) ─────
    logger.log(f"[{udid}][YT] → Starting logcat listener before click...")

    listener = LogcatListener(udid)
    listener.start()              # ← listening NOW, before any click
    logger.log(f"[{udid}][YT] → Logcat listener ready. Clicking play...")

    click_fn()                    # ← Intent fires here

    url = listener.get_url(timeout=8)   # ← wait up to 8s for the URL
    listener.stop()

    if url is None:
        logger.log(f"[{udid}][YT] ⚠ URL not captured from logcat — letting video play.")
        return "unknown"

    logger.log(f"[{udid}][YT] ✓ Captured URL: {url}")

    if url in skip_list:
        logger.log(f"[{udid}][YT] ⏭ SKIP (post-click) — pressing back.")
        time.sleep(1)       # brief pause so YouTube has launched
        driver.back()       # return to the app
        time.sleep(1)
        return "skip"

    logger.log(f"[{udid}][YT] ▶ PLAY — not in skip list.")
    return "play"
