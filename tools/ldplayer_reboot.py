"""
ldplayer_reboot.py
──────────────────
Handles scheduled, ordered rebooting of LDPlayer emulator instances via
ldconsole.exe, with ADB device name ↔ LDPlayer title mapping.

Configuration (.env)
────────────────────
LDPLAYER_PATH          Path to ldconsole.exe
                       e.g. C:\\LDPlayer\\ldconsole.exe

REBOOT_INTERVAL_SECONDS  How many seconds between each reboot cycle.
                         e.g. 14400  → reboot cycle runs every 4 hours

REBOOT_INSTANCE_COUNT  How many LDPlayer instances to reboot per cycle,
                       taken in order (index 0, 1, 2 …).
                       e.g. 2  → reboot LDPlayer-0 then LDPlayer-1 each cycle

Public API
──────────
start_reboot_scheduler(threads, stop_events, drivers,
                       pause_events, paused_ack_events, scheduler_stop_event)
    → Starts the background scheduler thread and returns it.

stop_reboot_scheduler(scheduler_thread, scheduler_stop_event)
    → Signals the scheduler to stop and waits for it to exit cleanly.
"""

import os
import re
import subprocess
import threading
import time

import logger


# ── Defaults (overridden by .env) ─────────────────────────────────────────────

_DEFAULT_INTERVAL_SECONDS = 14400  # 4 hours
_DEFAULT_INSTANCE_COUNT = 1


# ── ldconsole helpers ─────────────────────────────────────────────────────────

def _get_ldconsole_path() -> str:
    """Return the ldconsole.exe path from LDPLAYER_PATH env var."""
    path = os.getenv("LDPLAYER_PATH", "").strip()
    if not path:
        raise EnvironmentError(
            "LDPLAYER_PATH is not set in .env — cannot locate ldconsole.exe"
        )
    return path


def _get_interval_seconds() -> int:
    """Return REBOOT_INTERVAL_SECONDS from the environment."""
    raw = os.getenv("REBOOT_INTERVAL_SECONDS", "").strip()
    try:
        seconds = int(raw) if raw else _DEFAULT_INTERVAL_SECONDS
    except ValueError:
        logger.log(
            f"[LDReboot] ⚠ REBOOT_INTERVAL_SECONDS='{raw}' is not a valid integer. "
            f"Using default {_DEFAULT_INTERVAL_SECONDS}s."
        )
        seconds = _DEFAULT_INTERVAL_SECONDS
    return max(1, seconds)


def _get_instance_count() -> int:
    """Return REBOOT_INSTANCE_COUNT from .env."""
    raw = os.getenv("REBOOT_INSTANCE_COUNT", "").strip()
    if raw.isdigit():
        return max(1, int(raw))
    if raw:
        logger.log(
            f"[LDReboot] ⚠ REBOOT_INSTANCE_COUNT='{raw}' is not a valid integer. "
            f"Using default {_DEFAULT_INSTANCE_COUNT}."
        )
    return _DEFAULT_INSTANCE_COUNT


# ── ADB ↔ LDPlayer name mapping ───────────────────────────────────────────────

def _get_ldplayer_list(ldconsole: str) -> list[dict]:
    """
    Run `ldconsole list2` and return a list of dicts:
        { 'index': int, 'name': str, 'adb_port': int }

    ldconsole list2 output columns (comma-separated):
        index, name, top-window-handle, bind-window-handle,
        android-started-int, pid, pid2, adb-port
    """
    try:
        result = subprocess.run(
            [ldconsole, "list2"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        entries = []
        for line in result.stdout.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 8:
                continue
            try:
                index    = int(parts[0])
                name     = parts[1]
                adb_port = int(parts[7]) if parts[7].isdigit() else -1
                entries.append({"index": index, "name": name, "adb_port": adb_port})
            except (ValueError, IndexError):
                continue
        return entries
    except FileNotFoundError:
        logger.log(f"[LDReboot] ✗ ldconsole.exe not found at: {ldconsole}")
        return []
    except subprocess.TimeoutExpired:
        logger.log("[LDReboot] ✗ ldconsole list2 timed out.")
        return []
    except Exception as e:
        logger.log(f"[LDReboot] ✗ Error running ldconsole list2: {e}")
        return []


def _build_adb_to_ld_map(ldconsole: str) -> dict[str, dict]:
    """
    Build a mapping of ADB device name → LDPlayer info.

    ADB reports emulators as 'emulator-<port>' where port == adb_port from
    ldconsole list2.  For TCP/IP style devices (e.g. '127.0.0.1:5556') the
    port number is extracted directly.

    Returns:
        {
            'emulator-5556': { 'index': 0, 'name': 'LDPlayer-0', 'adb_port': 5556 },
            ...
        }
    """
    ld_list = _get_ldplayer_list(ldconsole)
    mapping = {}
    for entry in ld_list:
        port = entry["adb_port"]
        if port <= 0:
            continue
        # Standard ADB emulator device name  → emulator-<adb_port>
        adb_key = f"emulator-{port}"
        mapping[adb_key] = entry
        # Also cover TCP/IP style (127.0.0.1:<port>)
        tcp_key = f"127.0.0.1:{port}"
        mapping[tcp_key] = entry
    return mapping


# ── Reboot logic ──────────────────────────────────────────────────────────────

def _reboot_instance(ldconsole: str, ld_index: int, ld_name: str) -> bool:
    """
    Reboot a single LDPlayer instance by its index via ldconsole.

    Returns True on success, False on failure.
    """
    try:
        logger.log(f"[LDReboot] → Rebooting {ld_name} (index {ld_index})...")
        result = subprocess.run(
            [ldconsole, "reboot", "--index", str(ld_index)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            logger.log(f"[LDReboot] ✓ {ld_name} reboot command sent successfully.")
            return True
        else:
            logger.log(
                f"[LDReboot] ✗ ldconsole reboot failed for {ld_name}: "
                f"rc={result.returncode} {result.stderr.strip()}"
            )
            return False
    except FileNotFoundError:
        logger.log(f"[LDReboot] ✗ ldconsole.exe not found at: {ldconsole}")
        return False
    except subprocess.TimeoutExpired:
        logger.log(f"[LDReboot] ✗ Reboot command timed out for {ld_name}.")
        return False
    except Exception as e:
        logger.log(f"[LDReboot] ✗ Unexpected error rebooting {ld_name}: {e}")
        return False


def run_reboot_cycle(
    threads: dict,
    stop_events: dict,
    drivers: dict,
    pause_events: dict,
    paused_ack_events: dict,
) -> None:
    """
    Execute one reboot cycle:
      1. Build ADB ↔ LDPlayer map.
      2. Pick REBOOT_INSTANCE_COUNT instances in ascending index order.
      3. For each: stop the Appium thread → reboot via ldconsole.
         (The emulator watcher will auto-reconnect once the emulator is back.)
    """
    try:
        ldconsole = _get_ldconsole_path()
    except EnvironmentError as e:
        logger.log(f"[LDReboot] ✗ {e}")
        return

    count = _get_instance_count()
    logger.log(f"[LDReboot] 🔄 Starting reboot cycle — rebooting {count} instance(s)...")

    # ── Debug: show currently tracked ADB UDIDs ───────────────────────
    tracked = list(threads.keys())
    logger.log(f"[LDReboot] 🔍 Tracked ADB devices: {tracked}")

    # ── Debug: show raw ldconsole list2 output ────────────────────────
    try:
        raw = subprocess.run(
            [ldconsole, "list2"],
            capture_output=True, text=True, timeout=15,
        )
        logger.log(f"[LDReboot] 🔍 ldconsole list2 raw:\n{raw.stdout.strip()}")
    except Exception as dbg_e:
        logger.log(f"[LDReboot] ✗ Debug ldconsole call failed: {dbg_e}")

    adb_map = _build_adb_to_ld_map(ldconsole)
    logger.log(f"[LDReboot] 🔍 ADB→LD map keys: {list(adb_map.keys())}")

    if not adb_map:
        logger.log("[LDReboot] ✗ Could not retrieve LDPlayer instance list. Skipping cycle.")
        return

    # Build ordered list: only ADB devices that are currently tracked, sorted by LD index
    candidates = []
    for udid in list(threads.keys()):
        if udid in adb_map:
            ld_info = adb_map[udid]
            candidates.append((udid, ld_info))
    # Sort by LDPlayer index (ascending) so reboot order matches instance numbering
    candidates.sort(key=lambda x: x[1]["index"])

    if not candidates:
        logger.log("[LDReboot] ⚠ No running emulators could be mapped to LDPlayer instances.")
        return

    targets = candidates[:count]
    logger.log(
        f"[LDReboot] → Reboot targets: "
        + ", ".join(f"{udid} → {info['name']}" for udid, info in targets)
    )

    for udid, ld_info in targets:
        ld_name  = ld_info["name"]
        ld_index = ld_info["index"]

        # ── 1. Stop the Appium thread for this emulator ───────────────────
        logger.log(f"[LDReboot] → Stopping Appium thread for {udid} ({ld_name})...")
        import des_cap  # noqa: PLC0415 — lazy import to avoid circular dependency
        des_cap.stop_one(udid, threads, stop_events, drivers)

        # ── 2. Remove from tracking dicts so watcher treats it as "new" ──
        for d in (threads, stop_events, drivers, pause_events, paused_ack_events):
            d.pop(udid, None)

        # ── 3. Reboot via ldconsole ───────────────────────────────────────
        _reboot_instance(ldconsole, ld_index, ld_name)

        logger.log(
            f"[LDReboot] ✓ {ld_name} rebooted — "
            "emulator watcher will reconnect once it comes back online."
        )

        # Brief pause between instances to avoid overloading the host
        time.sleep(5)

    logger.log("[LDReboot] ✅ Reboot cycle complete.")


# ── Background scheduler ──────────────────────────────────────────────────────

def _scheduler_loop(
    threads: dict,
    stop_events: dict,
    drivers: dict,
    pause_events: dict,
    paused_ack_events: dict,
    scheduler_stop_event: threading.Event,
) -> None:
    """
    Background loop that fires run_reboot_cycle() every REBOOT_INTERVAL_SECONDS.
    Sleeps in 1-second ticks to honour the stop signal promptly.
    """
    interval = _get_interval_seconds()
    logger.log(
        f"[LDReboot] ✓ Scheduler started — reboot cycle every "
        f"{interval}s."
    )

    elapsed = 0
    while not scheduler_stop_event.is_set():
        time.sleep(1)
        elapsed += 1
        if scheduler_stop_event.is_set():
            break
        if elapsed >= interval:
            elapsed = 0
            # Re-read interval in case .env was updated
            interval = _get_interval_seconds()
            run_reboot_cycle(threads, stop_events, drivers, pause_events, paused_ack_events)

    logger.log("[LDReboot] ✓ Scheduler thread stopped.")


# ── Public API ────────────────────────────────────────────────────────────────

def start_reboot_scheduler(
    threads: dict,
    stop_events: dict,
    drivers: dict,
    pause_events: dict,
    paused_ack_events: dict,
    scheduler_stop_event: threading.Event,
) -> threading.Thread:
    """
    Spawn the background reboot-scheduler daemon thread and return it.

    Parameters
    ----------
    threads, stop_events, drivers, pause_events, paused_ack_events
        The *same* mutable dicts used by des_cap.main_pro().
    scheduler_stop_event
        A threading.Event() controlled by the caller — set it to stop.

    Returns
    -------
    threading.Thread
        The running scheduler thread (daemon=True).
    """
    t = threading.Thread(
        target=_scheduler_loop,
        args=(
            threads,
            stop_events,
            drivers,
            pause_events,
            paused_ack_events,
            scheduler_stop_event,
        ),
        daemon=True,
        name="LDRebootScheduler",
    )
    t.start()
    return t


def stop_reboot_scheduler(
    scheduler_thread: threading.Thread,
    scheduler_stop_event: threading.Event,
    timeout: int = 10,
) -> None:
    """
    Signal the scheduler to stop and wait for it to exit.

    Parameters
    ----------
    scheduler_thread
        The thread returned by start_reboot_scheduler().
    scheduler_stop_event
        The same Event passed to start_reboot_scheduler().
    timeout
        Seconds to wait before giving up.
    """
    logger.log("[LDReboot] → Stopping scheduler...")
    scheduler_stop_event.set()
    scheduler_thread.join(timeout=timeout)
    if scheduler_thread.is_alive():
        logger.log("[LDReboot] ⚠ Scheduler thread did not stop within timeout.")
    else:
        logger.log("[LDReboot] ✓ Scheduler stopped cleanly.")

