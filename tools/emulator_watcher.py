"""
emulator_watcher.py
───────────────────
Background daemon that periodically checks for new emulators via ADB and
automatically starts a thread for each one that is not yet running.

Configuration (.env)
────────────────────
EMULATOR_CHECK_INTERVAL   (int, seconds) — how often to poll ADB for new
                           emulators.  Default: 30 seconds.

Public API
──────────
start_watcher(threads, stop_events, drivers, pause_events, paused_ack_events,
              watcher_stop_event)
    → Starts the background watcher thread and returns it.
      Pass the *same* mutable dicts that des_cap.main_pro() uses so that any
      new emulators are merged into the live session automatically.

stop_watcher(watcher_thread, watcher_stop_event)
    → Signals the watcher to stop and waits for it to exit cleanly.

Usage example (in menu.py / main.py)
─────────────────────────────────────
    import threading
    import tools.emulator_watcher as emulator_watcher

    # After main_pro() returns the live dicts:
    watcher_stop = threading.Event()
    watcher_thread = emulator_watcher.start_watcher(
        threads, stop_events, drivers,
        pause_events, paused_ack_events,
        watcher_stop
    )

    # … later, when the session ends:
    emulator_watcher.stop_watcher(watcher_thread, watcher_stop)
"""

import os
import threading
import time

import logger
import tools.grabber as grabber


# ── Default poll interval (overridden by EMULATOR_CHECK_INTERVAL in .env) ───

_DEFAULT_INTERVAL: int = 30


# ── Internal helpers ─────────────────────────────────────────────────────────

def _get_interval() -> int:
    """Read EMULATOR_CHECK_INTERVAL from the environment (already loaded by dotenv)."""
    raw = os.getenv("EMULATOR_CHECK_INTERVAL", "").strip()
    if raw.isdigit():
        return int(raw)
    if raw:
        logger.log(
            f"[EmulatorWatcher] ⚠ EMULATOR_CHECK_INTERVAL='{raw}' is not a valid integer. "
            f"Using default {_DEFAULT_INTERVAL}s."
        )
    return _DEFAULT_INTERVAL


def _watcher_loop(
    threads: dict,
    stop_events: dict,
    drivers: dict,
    pause_events: dict,
    paused_ack_events: dict,
    watcher_stop_event: threading.Event,
) -> None:
    """
    Core loop — runs in its own daemon thread.

    Every EMULATOR_CHECK_INTERVAL seconds it:
      1. Queries ADB for the current emulator list.
      2. Compares against already-running threads.
      3. For any new emulator, delegates to des_cap.add_new_emulators() so it
         gets its own stop/pause events and a fully initialised Appium session.

    Importing des_cap here (instead of at module level) avoids a circular
    import since des_cap itself imports tools like watch, grabber, etc.
    """
    # Lazy import to avoid circular dependency at module load time.
    import des_cap  # noqa: PLC0415

    logger.log("[EmulatorWatcher] ✓ Watcher thread started.")
    interval = _get_interval()
    logger.log(f"[EmulatorWatcher] → Polling every {interval}s for new emulators.")

    while not watcher_stop_event.is_set():
        # ── honour stop signal promptly by sleeping in short slices ──────
        for _ in range(interval):
            if watcher_stop_event.is_set():
                break
            time.sleep(1)

        if watcher_stop_event.is_set():
            break

        # ── re-read interval each cycle so a runtime .env change is picked up ──
        interval = _get_interval()

        logger.log("[EmulatorWatcher] 🔍 Checking for new emulators...")

        # ── determine which UDIDs are currently running ───────────────────
        running_udids: set = {
            udid for udid, t in threads.items() if t.is_alive()
        }

        # ── get the full ADB emulator list ────────────────────────────────
        current_emulators = grabber.get_emulator_list()
        current_udids = {udid for udid, _ in current_emulators}

        new_udids = current_udids - running_udids

        if not new_udids:
            logger.log("[EmulatorWatcher] ✓ No new emulators found.")
            continue

        logger.log(
            f"[EmulatorWatcher] 🆕 New emulator(s) detected: {sorted(new_udids)}. "
            "Starting threads..."
        )

        # ── delegate to des_cap to create sessions + threads for new ones ──
        (
            new_threads,
            new_stop_events,
            new_drivers,
            new_pause_events,
            new_paused_ack_events,
        ) = des_cap.add_new_emulators(
            threads,
            stop_events,
            drivers,
            pause_events,
            paused_ack_events,
        )

        # ── merge results back into the shared live dicts ─────────────────
        threads.update(new_threads)
        stop_events.update(new_stop_events)
        drivers.update(new_drivers)
        pause_events.update(new_pause_events)
        paused_ack_events.update(new_paused_ack_events)

        if new_threads:
            logger.log(
                f"[EmulatorWatcher] ✓ Started {len(new_threads)} new thread(s): "
                f"{list(new_threads.keys())}"
            )
        else:
            logger.log(
                "[EmulatorWatcher] → add_new_emulators() returned no new threads "
                "(emulators may have already been registered)."
            )

    logger.log("[EmulatorWatcher] ✓ Watcher thread stopped.")


# ── Public API ────────────────────────────────────────────────────────────────

def start_watcher(
    threads: dict,
    stop_events: dict,
    drivers: dict,
    pause_events: dict,
    paused_ack_events: dict,
    watcher_stop_event: threading.Event,
) -> threading.Thread:
    """
    Spawn the background emulator-watcher daemon thread and return it.

    Parameters
    ----------
    threads, stop_events, drivers, pause_events, paused_ack_events
        The *same* mutable dicts returned by des_cap.main_pro().  The watcher
        merges any newly discovered emulators directly into these dicts.
    watcher_stop_event
        A threading.Event() controlled by the caller.  Set it to stop the loop.

    Returns
    -------
    threading.Thread
        The running watcher thread (daemon=True).
    """
    watcher_thread = threading.Thread(
        target=_watcher_loop,
        args=(
            threads,
            stop_events,
            drivers,
            pause_events,
            paused_ack_events,
            watcher_stop_event,
        ),
        daemon=True,
        name="EmulatorWatcher",
    )
    watcher_thread.start()
    return watcher_thread


def stop_watcher(
    watcher_thread: threading.Thread,
    watcher_stop_event: threading.Event,
    timeout: int = 10,
) -> None:
    """
    Signal the watcher to stop and wait for it to exit.

    Parameters
    ----------
    watcher_thread
        The thread returned by start_watcher().
    watcher_stop_event
        The same Event that was passed to start_watcher().
    timeout
        Seconds to wait for the thread to join before giving up.
    """
    logger.log("[EmulatorWatcher] → Stopping watcher...")
    watcher_stop_event.set()
    watcher_thread.join(timeout=timeout)
    if watcher_thread.is_alive():
        logger.log("[EmulatorWatcher] ⚠ Watcher thread did not stop within timeout.")
    else:
        logger.log("[EmulatorWatcher] ✓ Watcher stopped cleanly.")
