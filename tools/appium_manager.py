"""
appium_manager.py
─────────────────
Utility to ensure the Appium server is alive on the configured port.

Public API
----------
ensure_appium_running(port=4723, max_wait=30)
    → Checks if Appium is reachable.  If not:
        1. Kills any process that is already bound to the port (EADDRINUSE).
        2. Starts a fresh Appium process in the background.
        3. Waits up to `max_wait` seconds for it to become reachable.
    Returns True if Appium is ready, False if it could not be started.

is_appium_connection_error(exc)
    → Returns True if the exception is the "WinError 10061 / connection refused"
      error so callers can detect it without string-matching themselves.

is_system_port_busy_error(exc)
    → Returns True if the exception is the UiAutomator2 "local port #XXXX is busy"
      error, meaning the systemPort used by the driver is already occupied.

ensure_system_port_free(system_port=8200)
    → Kills any process holding `system_port` (the UiAutomator2 systemPort).
      Call this before (re-)creating an Appium session when you catch a
      is_system_port_busy_error, or use it proactively before every session.
      Returns True if the port is now free, False if it could not be released.
"""

import os
import subprocess
import time
import socket
import logger

# ── constants ─────────────────────────────────────────────────────────────────

# Default Appium server port
DEFAULT_APPIUM_PORT: int = 4723

# UiAutomator2 driver systemPort — must match the 'systemPort' capability
# you pass to Appium.  Change here if you use a different value.
DEFAULT_SYSTEM_PORT: int = 8200

# ── helpers ──────────────────────────────────────────────────────────────────

def _is_port_open(host: str, port: int) -> bool:
    """Return True if something is accepting TCP connections on host:port."""
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


def _kill_process_on_port(port: int) -> None:
    """
    Find and kill every PID that is listening on `port` (Windows).
    Uses `netstat -ano` to locate PIDs, then `taskkill /F /PID`.
    """
    try:
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True, text=True, timeout=10
        )
        pids_killed = set()
        for line in result.stdout.splitlines():
            # Match lines like:  TCP  0.0.0.0:4723  ...  LISTENING  1234
            if f":{port}" in line and ("LISTENING" in line or "ESTABLISHED" in line):
                parts = line.split()
                pid = parts[-1]
                if pid.isdigit() and pid not in pids_killed:
                    logger.log(f"[AppiumManager] → Killing PID {pid} blocking port {port}...")
                    subprocess.run(
                        ["taskkill", "/F", "/PID", pid],
                        capture_output=True, timeout=10
                    )
                    pids_killed.add(pid)
                    logger.log(f"[AppiumManager] ✓ PID {pid} killed.")
        if not pids_killed:
            logger.log(f"[AppiumManager] → No process found blocking port {port}.")
    except Exception as e:
        logger.log(f"[AppiumManager] ⚠ Could not kill process on port {port}: {e}")


def _start_appium(port: int) -> subprocess.Popen:
    """
    Launch Appium in the background and return the Popen handle.
    stdout/stderr are discarded so they do not pollute the console.
    """
    logger.log(f"[AppiumManager] → Starting Appium on port {port}...")
    proc = subprocess.Popen(
        ["appium", "--port", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    logger.log(f"[AppiumManager] ✓ Appium process started (PID: {proc.pid}).")
    return proc


# ── module-level handle so we don't spawn duplicates ─────────────────────────

_appium_proc = None
_appium_start_lock = None  # initialised lazily to avoid import-time threading dep


# ── public API ────────────────────────────────────────────────────────────────

def is_appium_connection_error(exc: Exception) -> bool:
    """
    Returns True when `exc` is the typical "Appium not running" error:
      HTTPConnectionPool … WinError 10061 … actively refused
    Works without importing requests / urllib3 directly.
    """
    msg = str(exc)
    return (
        "WinError 10061" in msg
        or "connection refused" in msg.lower()
        or ("Max retries exceeded" in msg and "NewConnectionError" in msg)
    )


def is_system_port_busy_error(exc: Exception) -> bool:
    """
    Returns True when `exc` is the UiAutomator2 "systemPort is busy" error::

        UiAutomator2 Server cannot start because the local port #8200 is busy.
        Make sure the port you provide via 'systemPort' capability is not occupied.

    This typically means a previous Appium session was not properly closed and
    the UiAutomator2 server is still holding the port.
    """
    msg = str(exc)
    return (
        "is busy" in msg.lower()
        and ("systemport" in msg.lower() or "local port" in msg.lower() or "uiautomator2" in msg.lower())
    ) or (
        "UiAutomator2 Server cannot start" in msg
    )


def ensure_system_port_free(system_port: int = DEFAULT_SYSTEM_PORT) -> bool:
    """
    Kill every process that is currently occupying `system_port` (the
    UiAutomator2 systemPort capability value, default 8200).

    Call this:
      • Proactively, before each new Appium/UiAutomator2 session.
      • Reactively, inside an except block when is_system_port_busy_error(exc)
        returns True, then retry creating the session.

    Returns True if the port appears free afterward, False on unexpected error.

    Example — reactive use::

        try:
            driver = webdriver.Remote(url, options)
        except Exception as exc:
            if is_system_port_busy_error(exc):
                logger.log("[AppiumManager] systemPort busy — clearing and retrying...")
                ensure_system_port_free(8200)
                driver = webdriver.Remote(url, options)  # retry once
            else:
                raise
    """
    logger.log(f"[AppiumManager] → Ensuring system port {system_port} is free...")
    try:
        _kill_process_on_port(system_port)
        time.sleep(0.5)  # brief pause to let the OS reclaim the port
        # Verify the port is actually free now
        if not _is_port_open("127.0.0.1", system_port):
            logger.log(f"[AppiumManager] ✓ System port {system_port} is now free.")
            return True
        else:
            logger.log(f"[AppiumManager] ⚠ System port {system_port} still appears occupied after kill attempt.")
            return False
    except Exception as e:
        logger.log(f"[AppiumManager] ⚠ Error while freeing system port {system_port}: {e}")
        return False


def ensure_appium_running(port: int = 4723, max_wait: int = 30) -> bool:
    """
    Guarantee Appium is reachable on `port`.

    Steps:
      1. Quick check — if already up, return True immediately.
      2. Kill any process hogging the port (handles EADDRINUSE).
      3. Start a fresh Appium process.
      4. Poll every second up to `max_wait` seconds.
      5. Return True if reachable, False otherwise.
    """
    global _appium_proc, _appium_start_lock

    # Lazy-init thread lock (avoids circular import of threading at module load)
    if _appium_start_lock is None:
        import threading
        _appium_start_lock = threading.Lock()

    with _appium_start_lock:
        host = "127.0.0.1"

        # ── 1. Already running? ───────────────────────────────────────────
        if _is_port_open(host, port):
            logger.log(f"[AppiumManager] ✓ Appium already reachable on port {port}.")
            return True

        logger.log(f"[AppiumManager] ✗ Appium not reachable on port {port}. Restarting...")

        # ── 2. Kill anything blocking the port ───────────────────────────
        _kill_process_on_port(port)
        time.sleep(1)  # brief pause after kill

        # ── 3. Start fresh Appium ─────────────────────────────────────────
        try:
            _appium_proc = _start_appium(port)
        except FileNotFoundError:
            logger.log("[AppiumManager] ✗ 'appium' command not found. "
                       "Is Appium installed and on PATH?")
            return False

        # ── 4. Poll until reachable ───────────────────────────────────────
        logger.log(f"[AppiumManager] ⏳ Waiting up to {max_wait}s for Appium to become ready...")
        for elapsed in range(max_wait):
            time.sleep(1)
            if _is_port_open(host, port):
                logger.log(f"[AppiumManager] ✓ Appium is ready after {elapsed + 1}s.")
                return True

        logger.log(f"[AppiumManager] ✗ Appium did not become ready within {max_wait}s.")
        return False
