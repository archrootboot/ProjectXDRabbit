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

def _extract_port_from_udid(udid: str) -> int:
    """
    Extract the numeric port from an ADB device UDID.
      'emulator-5554'    → 5554
      '127.0.0.1:5555'   → 5555
      anything else      → -1
    """
    import re as _re
    m = _re.search(r':(\d+)$', udid) or _re.search(r'-(\d+)$', udid)
    return int(m.group(1)) if m else -1


def _get_ldplayer_list(ldconsole: str) -> list[dict]:
    """
    Run `ldconsole list2` and return a list of dicts:
        { 'index': int, 'name': str }

    ldconsole list2 columns (comma-separated):
        index, name, hwnd1, hwnd2, android-started, pid, pid2, width, height, dpi
        (ADB port is NOT in list2 output — derived via formula instead)
    """
    try:
        result = subprocess.run(
            [ldconsole, "list2"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        raw = result.stdout.strip()
        if raw:
            logger.log(f"[LDReboot] 🔍 ldconsole list2:\n{raw}")
        else:
            logger.log("[LDReboot] ⚠ ldconsole list2 returned empty output.")

        entries = []
        for line in raw.splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 2:
                continue
            try:
                index = int(parts[0])
                name  = parts[1]
                entries.append({"index": index, "name": name})
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


def _ld_index_to_adb_udid(index: int) -> tuple[str, str]:
    """
    Convert a LDPlayer instance index to its ADB device names.

    LDPlayer assigns ADB ports by formula:  port = 5554 + (index × 2)
      index 0 → port 5554 → 'emulator-5554'
      index 1 → port 5556 → 'emulator-5556'
      index 2 → port 5558 → 'emulator-5558'

    Returns both the standard emulator style and TCP/IP style:
        ('emulator-5554', '127.0.0.1:5554')
    """
    port = 5554 + index * 2
    return f"emulator-{port}", f"127.0.0.1:{port}"


def _build_adb_to_ld_map(ldconsole: str) -> dict[str, dict]:
    """
    Build a mapping of ADB device name → LDPlayer info.

    Uses the standard LDPlayer ADB port formula (5554 + index×2) since
    ldconsole list2 does not expose the ADB port directly.

    Returns:
        {
            'emulator-5554': { 'index': 0, 'name': 'LDPlayer-0' },
            '127.0.0.1:5554': { 'index': 0, 'name': 'LDPlayer-0' },
            'emulator-5556': { 'index': 1, 'name': 'LDPlayer-1' },
            ...
        }
    """
    ld_list = _get_ldplayer_list(ldconsole)
    mapping: dict[str, dict] = {}
    for entry in ld_list:
        emu_key, tcp_key = _ld_index_to_adb_udid(entry["index"])
        mapping[emu_key] = entry
        mapping[tcp_key] = entry
    logger.log(f"[LDReboot] 🔍 ADB→LD map: { {k: v['name'] for k, v in mapping.items()} }")
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

    adb_map = _build_adb_to_ld_map(ldconsole)

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

