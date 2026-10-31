"""
tools/adb_controller.py
───────────────────────
Pure-ADB UI controller — full replacement for the Appium WebDriver.

Strategy
────────
  • Find elements  : adb shell uiautomator dump → pull XML → parse with ElementTree
  • Click          : adb shell input tap x y   (center of element bounds)
  • Type text      : adb shell input text <url-encoded>  (short strings)
                     clipboard broadcast for strings with special chars
  • Back / key     : adb shell input keyevent <code>
  • Screenshot     : adb exec-out screencap -p  → bytes in memory
  • Crop element   : PIL.Image crop from bounds parsed out of XML
  • App control    : adb shell am start / am force-stop

All functions accept `udid` as the first argument so multi-device
sessions work correctly in parallel threads.

Public helpers
──────────────
  run(udid, *args, **kw)          → CompletedProcess
  dump_ui(udid)                   → ElementTree root (None on fail)
  find_element(root, resource_id=None, text=None, class_name=None)
      → element or None
  find_elements(root, resource_id=None, text=None, class_name=None)
      → list
  get_bounds(element)             → (x, y, x2, y2) or None
  get_center(element)             → (cx, cy)        or None
  tap(udid, x, y)                 → bool
  tap_element(udid, element)      → bool
  wait_for_element(udid, timeout, resource_id=None, text=None, class_name=None,
                   contains_text=None)
      → element or None
  click_by_id(udid, resource_id, timeout=30)    → bool
  click_by_text(udid, text, timeout=30)         → bool
  get_text_by_id(udid, resource_id, timeout=10) → str or None
  get_all_texts(udid, resource_id, timeout=10)  → list[str]
  input_text(udid, text)                        → bool
  clear_and_type(udid, resource_id, text, timeout=30) → bool
  keyevent(udid, code)                          → bool
  start_app(udid, package, activity)            → bool
  stop_app(udid, package)                       → bool
  screenshot_bytes(udid)                        → bytes or None
  element_screenshot(udid, element)             → PIL.Image or None
  scroll_to_text(udid, target_text, timeout=15) → bool
  current_activity(udid)                        → str or None
"""

import io
import os
import re
import subprocess
import time
import xml.etree.ElementTree as ET

import logger

# ── ADB executable ────────────────────────────────────────────────────────────

_ADB = "adb"   # assumes adb is on PATH; override if needed


# ── Low-level runner ──────────────────────────────────────────────────────────

def run(udid: str, *args, timeout: int = 30, **kwargs) -> subprocess.CompletedProcess:
    """Run an adb command for a specific device. Returns CompletedProcess."""
    cmd = [_ADB, "-s", udid] + list(args)
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            **kwargs
        )
    except subprocess.TimeoutExpired:
        logger.log(f"[{udid}][ADB] ⚠ Timeout ({timeout}s): {' '.join(args)}")
        return subprocess.CompletedProcess(cmd, -1, stdout="", stderr="timeout")
    except Exception as e:
        logger.log(f"[{udid}][ADB] ✗ Error running {' '.join(args)}: {e}")
        return subprocess.CompletedProcess(cmd, -1, stdout="", stderr=str(e))


def run_bytes(udid: str, *args, timeout: int = 30) -> bytes:
    """Run an adb command and return raw bytes (for screencap)."""
    cmd = [_ADB, "-s", udid] + list(args)
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=timeout)
        return result.stdout
    except Exception as e:
        logger.log(f"[{udid}][ADB] ✗ Error (bytes): {e}")
        return b""


# ── UI dump & parse ───────────────────────────────────────────────────────────

def dump_ui(udid: str):
    """
    Dump the current UI hierarchy and return the parsed XML root.
    Dumps to /sdcard/ui_dump.xml on device, then reads via exec-out cat.
    Returns None on failure.
    """
    r = run(udid, "shell", "uiautomator", "dump", "/sdcard/ui_dump.xml", timeout=15)
    if r.returncode != 0:
        logger.log(f"[{udid}][ADB] ✗ uiautomator dump failed: {r.stderr.strip()}")
        return None

    r2 = run(udid, "exec-out", "cat", "/sdcard/ui_dump.xml", timeout=10)
    xml_text = r2.stdout.strip()
    if not xml_text:
        logger.log(f"[{udid}][ADB] ✗ UI dump returned empty content.")
        return None

    try:
        root = ET.fromstring(xml_text)
        return root
    except ET.ParseError as e:
        logger.log(f"[{udid}][ADB] ✗ XML parse error: {e}")
        return None


def find_element(root, resource_id=None, text=None, class_name=None, contains_text=None):
    """
    Find the first element matching all given criteria (AND logic).
    Returns the element or None.
    """
    if root is None:
        return None
    for node in root.iter():
        if resource_id and node.attrib.get("resource-id") != resource_id:
            continue
        if text and node.attrib.get("text") != text:
            continue
        if contains_text and contains_text not in node.attrib.get("text", ""):
            continue
        if class_name and node.attrib.get("class") != class_name:
            continue
        return node
    return None


def find_elements(root, resource_id=None, text=None, class_name=None, contains_text=None):
    """Find all elements matching all given criteria. Returns a list."""
    results = []
    if root is None:
        return results
    for node in root.iter():
        if resource_id and node.attrib.get("resource-id") != resource_id:
            continue
        if text and node.attrib.get("text") != text:
            continue
        if contains_text and contains_text not in node.attrib.get("text", ""):
            continue
        if class_name and node.attrib.get("class") != class_name:
            continue
        results.append(node)
    return results


def find_nth_element(root, resource_id: str, index: int):
    """Find the nth (1-based) element matching resource_id."""
    elements = find_elements(root, resource_id=resource_id)
    if index < 1 or index > len(elements):
        return None
    return elements[index - 1]


def get_bounds(element):
    """
    Parse bounds attribute '[x1,y1][x2,y2]' into (x1, y1, x2, y2).
    Returns None if missing or malformed.
    """
    if element is None:
        return None
    bounds_str = element.attrib.get("bounds", "")
    m = re.findall(r"\d+", bounds_str)
    if len(m) == 4:
        return tuple(int(v) for v in m)
    return None


def get_center(element):
    """Return center (cx, cy) of an element's bounds. None on failure."""
    b = get_bounds(element)
    if b is None:
        return None
    x1, y1, x2, y2 = b
    return ((x1 + x2) // 2, (y1 + y2) // 2)


# ── Touch / input ─────────────────────────────────────────────────────────────

def tap(udid: str, x: int, y: int) -> bool:
    """Tap at screen coordinate (x, y). Returns True on success."""
    r = run(udid, "shell", "input", "tap", str(x), str(y))
    return r.returncode == 0


def tap_element(udid: str, element) -> bool:
    """Tap the center of a UI element. Returns True on success."""
    center = get_center(element)
    if center is None:
        logger.log(f"[{udid}][ADB] ✗ tap_element: could not get bounds.")
        return False
    return tap(udid, *center)


def keyevent(udid: str, code) -> bool:
    """Send a key event. Accepts integer codes or KEYCODE_* strings."""
    r = run(udid, "shell", "input", "keyevent", str(code))
    return r.returncode == 0


def back(udid: str) -> bool:
    """Press the Android Back key (keyevent 4)."""
    return keyevent(udid, 4)


def home(udid: str) -> bool:
    """Press the Home key (keyevent 3)."""
    return keyevent(udid, 3)


def input_text(udid: str, text: str) -> bool:
    """
    Type text into the focused field using adb shell input text.
    Special characters (://.?=&% space) are percent-encoded so the
    shell does not interpret them.
    """
    safe = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._~")
    encoded = ""
    for ch in text:
        if ch in safe:
            encoded += ch
        else:
            encoded += f"%{ord(ch):02X}"

    r = run(udid, "shell", "input", "text", encoded, timeout=15)
    return r.returncode == 0


def clear_field(udid: str) -> bool:
    """Select all text in the focused field and delete it."""
    keyevent(udid, 277)   # KEYCODE_CTRL_A
    keyevent(udid, 67)    # KEYCODE_DEL
    return True


# ── Wait helpers ──────────────────────────────────────────────────────────────

def wait_for_element(udid: str, timeout: int = 30, resource_id=None, text=None,
                     class_name=None, contains_text=None, poll_interval: float = 1.0):
    """
    Poll the UI hierarchy until the target element appears or timeout expires.
    Returns the element, or None on timeout.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        root = dump_ui(udid)
        el = find_element(root, resource_id=resource_id, text=text,
                          class_name=class_name, contains_text=contains_text)
        if el is not None:
            return el
        time.sleep(poll_interval)
    logger.log(
        f"[{udid}][ADB] ✗ wait_for_element timed out after {timeout}s "
        f"(id={resource_id} text={text})"
    )
    return None


def click_by_id(udid: str, resource_id: str, timeout: int = 30) -> bool:
    """Wait for element by resource-id then tap it. Returns True on success."""
    el = wait_for_element(udid, timeout=timeout, resource_id=resource_id)
    if el is None:
        return False
    return tap_element(udid, el)


def click_by_text(udid: str, text: str, timeout: int = 30) -> bool:
    """Wait for element by exact text then tap it. Returns True on success."""
    el = wait_for_element(udid, timeout=timeout, text=text)
    if el is None:
        return False
    return tap_element(udid, el)


def get_text_by_id(udid: str, resource_id: str, timeout: int = 10):
    """
    Return the text attribute of the first matching element.
    Returns None if not found within timeout.
    """
    el = wait_for_element(udid, timeout=timeout, resource_id=resource_id)
    if el is None:
        return None
    return el.attrib.get("text", "").strip()


def get_all_texts(udid: str, resource_id: str, timeout: int = 10) -> list:
    """Return the text of every element matching resource_id."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        root = dump_ui(udid)
        els = find_elements(root, resource_id=resource_id)
        if els:
            return [e.attrib.get("text", "").strip() for e in els]
        time.sleep(1.0)
    return []


def clear_and_type(udid: str, resource_id: str, text: str, timeout: int = 30) -> bool:
    """Click input field, clear it, then type text. Returns True on success."""
    if not click_by_id(udid, resource_id, timeout=timeout):
        logger.log(f"[{udid}][ADB] ✗ clear_and_type: element {resource_id} not found.")
        return False
    time.sleep(0.5)
    keyevent(udid, 277)   # KEYCODE_CTRL_A
    keyevent(udid, 67)    # KEYCODE_DEL
    time.sleep(0.3)
    return input_text(udid, text)


# ── App control ───────────────────────────────────────────────────────────────

def start_app(udid: str, package: str, activity: str) -> bool:
    """Launch an app via `am start`. Returns True on success."""
    r = run(udid, "shell", "am", "start", "-n", f"{package}/{activity}", timeout=20)
    ok = r.returncode == 0 and "Error" not in r.stdout
    if not ok:
        logger.log(f"[{udid}][ADB] ✗ start_app failed: {r.stdout.strip() or r.stderr.strip()}")
    return ok


def stop_app(udid: str, package: str) -> bool:
    """Force-stop an app. Returns True on success."""
    r = run(udid, "shell", "am", "force-stop", package, timeout=15)
    return r.returncode == 0


def current_activity(udid: str):
    """Return the currently focused activity name, or None on failure."""
    r = run(udid, "shell", "dumpsys", "activity", "activities", timeout=10)
    for line in r.stdout.splitlines():
        if "mCurrentFocus" in line or "ResumedActivity" in line:
            m = re.search(r"([a-zA-Z0-9_.]+/[a-zA-Z0-9_.]+)", line)
            if m:
                return m.group(1)
    return None


# ── Screenshot ────────────────────────────────────────────────────────────────

def screenshot_bytes(udid: str):
    """
    Capture a full-screen screenshot via `adb exec-out screencap -p`.
    Returns raw PNG bytes, or None on failure.
    """
    data = run_bytes(udid, "exec-out", "screencap", "-p", timeout=20)
    if data and data[:4] == b"\x89PNG":
        return data
    cleaned = data.replace(b"\r\n", b"\n")
    if cleaned and cleaned[:4] == b"\x89PNG":
        return cleaned
    logger.log(f"[{udid}][ADB] ✗ screenshot returned invalid PNG ({len(data)} bytes).")
    return None


def element_screenshot(udid: str, element):
    """
    Return a PIL.Image cropped to the element's bounding box.
    Uses a full-screen ADB screenshot + crop.
    Returns None on failure.
    """
    try:
        from PIL import Image
    except ImportError:
        logger.log(f"[{udid}][ADB] ✗ Pillow not installed.")
        return None

    bounds = get_bounds(element)
    if bounds is None:
        logger.log(f"[{udid}][ADB] ✗ element_screenshot: no bounds on element.")
        return None

    data = screenshot_bytes(udid)
    if not data:
        return None

    try:
        img = Image.open(io.BytesIO(data)).convert("RGB")
        x1, y1, x2, y2 = bounds
        return img.crop((x1, y1, x2, y2))
    except Exception as e:
        logger.log(f"[{udid}][ADB] ✗ element_screenshot crop failed: {e}")
        return None


# ── Scroll to text ────────────────────────────────────────────────────────────

def scroll_to_text(udid: str, target_text: str, timeout: int = 15) -> bool:
    """
    Scroll until an element with the given text becomes visible.
    Uses repeated swipe-up gestures.  Returns True if found.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        root = dump_ui(udid)
        el = find_element(root, text=target_text)
        if el is not None:
            return True
        run(udid, "shell", "input", "swipe", "540", "800", "540", "400", "300")
        time.sleep(0.5)
    logger.log(f"[{udid}][ADB] ✗ scroll_to_text: '{target_text}' not found within {timeout}s.")
    return False


# ── Spinner helper ────────────────────────────────────────────────────────────

def select_spinner_value(udid: str, value: str, timeout: int = 10) -> bool:
    """
    Click a Spinner then select an item by text. Scrolls if needed.
    Returns True on success.
    """
    spinner = wait_for_element(udid, timeout=timeout, class_name="android.widget.Spinner")
    if spinner is None:
        logger.log(f"[{udid}][ADB] ✗ select_spinner_value: Spinner not found.")
        return False
    tap_element(udid, spinner)
    time.sleep(1.5)

    if scroll_to_text(udid, value, timeout=10):
        el = wait_for_element(udid, timeout=5, text=value)
        if el:
            tap_element(udid, el)
            return True

    logger.log(f"[{udid}][ADB] ✗ select_spinner_value: '{value}' not found in dropdown.")
    return False
