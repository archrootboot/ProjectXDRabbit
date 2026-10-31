"""
des_cap.py
──────────
Main emulator orchestrator — pure ADB version.

No Appium, no WebDriver.  Each emulator thread:
  1. Starts the app via ADB.
  2. Navigates to the watch screen.
  3. Runs the watch_video loop (tools/watch.py).
"""

import os
import threading
import time

import tools.adb_controller as adb
import tools.grabber as grabber
import tools.watch as watch
import logger
from dotenv import load_dotenv

# Shared across all emulator threads — ensures only one emulator at a time
# goes through the find-video → click-play window.
play_lock = None


def run_emulator(udid, stop_event, drivers, pause_events, paused_ack_events, play_lock=None):
    """
    Thread target for one emulator.

    Parameters
    ----------
    udid              : device serial (e.g. 'emulator-5554')
    stop_event        : threading.Event — set to stop this thread
    drivers           : shared dict {udid: None}  (kept for API compat with menu.py)
    pause_events      : shared dict {udid: threading.Event}
    paused_ack_events : shared dict {udid: threading.Event}
    play_lock         : shared threading.Lock
    """
    pkg      = os.getenv("APP_PACKAGE")
    activity = os.getenv("APP_MAIN_ACTIVITY")

    try:
        logger.log(f"→ Opening app on {udid}...")

        # Start / bring app to foreground with retry
        for attempt in range(3):
            ok = adb.start_app(udid, pkg, activity)
            if ok:
                logger.log(f"✓ App opened on {udid}")
                break
            logger.log(f"⚠ [{udid}] Attempt {attempt + 1}/3 failed to open app.")
            time.sleep(3)
        else:
            raise Exception(f"[{udid}] Failed to open app after 3 attempts")

        # Mark as "connected" in the shared drivers dict
        drivers[udid] = udid   # use udid as a sentinel (no driver object needed)
        logger.log(f"✓ {udid} registered")

        # Wait for app to fully load
        time.sleep(5)

        # Scale click timeout based on number of active emulators
        click_timeout = 30 + max(0, len(drivers) - 1) * 3
        logger.log(f"[{udid}] → Using click timeout: {click_timeout}s (emulators: {len(drivers)})")

        # Wait then click the watch button
        logger.log(f"→ wait 10s before click element on {udid}...")
        time.sleep(10)

        _RES_WATCH = "com.view.ytrabbit:id/textView4df"
        for attempt in range(5):
            el = adb.wait_for_element(udid, timeout=click_timeout, resource_id=_RES_WATCH)
            if el is not None:
                adb.tap_element(udid, el)
                logger.log(f"✓ Element clicked on {udid}")
                break
            logger.log(f"⚠ [{udid}] Attempt {attempt + 1}/5 failed to click element.")
            time.sleep(10)
        else:
            raise Exception(f"[{udid}] Failed to click element after 5 attempts")

        watch.watch_video(
            udid,
            stop_event,
            pause_events.get(udid),
            paused_ack_events.get(udid),
            play_lock,
        )

    except Exception as e:
        logger.log(f"✗ Error with {udid}: {e}")
    finally:
        # Remove from drivers dict on exit
        drivers.pop(udid, None)
        logger.log(f"✓ {udid} thread exiting")


# ── Thread control functions ──────────────────────────────────────────

def stop_one(udid, threads, stop_events, drivers):
    if udid not in stop_events:
        logger.log(f"✗ {udid} not found.")
        return

    if udid in drivers and threads.get(udid) and threads[udid].is_alive():
        try:
            logger.log(f"→ Closing app on {udid}...")
            adb.stop_app(udid, os.getenv("APP_PACKAGE"))
        except Exception as e:
            logger.log(f"⚠ Could not close app on {udid}: {e}")
    else:
        logger.log(f"→ {udid} already stopped, skipping app close.")

    stop_events[udid].set()

    logger.log(f"→ Waiting for {udid} thread to stop...")
    threads[udid].join(timeout=15)

    if threads[udid].is_alive():
        logger.log(f"⚠ {udid} thread did not stop cleanly within timeout.")
    else:
        logger.log(f"✓ {udid} stopped cleanly.")


def stop_all(threads, stop_events, drivers):
    for udid in stop_events:
        if udid in drivers and udid in threads and threads[udid].is_alive():
            try:
                logger.log(f"→ Closing app on {udid}...")
                adb.stop_app(udid, os.getenv("APP_PACKAGE"))
            except Exception as e:
                logger.log(f"⚠ Could not close app on {udid}: {e}")
        else:
            logger.log(f"→ {udid} already stopped, skipping app close.")

    for event in stop_events.values():
        event.set()

    for udid, thread in threads.items():
        thread.join(timeout=15)
        if thread.is_alive():
            logger.log(f"⚠ {udid} thread did not stop cleanly within timeout.")
        else:
            logger.log(f"✓ {udid} stopped cleanly.")

    logger.log("All emulators stopped.")


def get_status(threads):
    status = {}
    for udid, thread in threads.items():
        status[udid] = "running" if thread.is_alive() else "stopped"
    return status


# ── Add New Emulators ─────────────────────────────────────────────────

def add_new_emulators(existing_threads, existing_stop_events, existing_drivers,
                      existing_pause_events, existing_paused_ack_events):
    emulators = grabber.get_emulator_list()

    if not emulators:
        logger.log("✗ No emulators found via ADB.")
        return {}, {}, {}, {}, {}

    new_stop_events       = {}
    new_threads           = {}
    new_drivers           = {}
    new_pause_events      = {}
    new_paused_ack_events = {}

    for i, (udid, _) in enumerate(emulators):
        if udid in existing_threads and existing_threads[udid].is_alive():
            logger.log(f"→ {udid} already running, skipping.")
            continue

        logger.log(f"→ New emulator detected: {udid}")
        stop_event       = threading.Event()
        pause_event      = threading.Event()
        paused_ack_event = threading.Event()
        new_stop_events[udid]       = stop_event
        new_pause_events[udid]      = pause_event
        new_paused_ack_events[udid] = paused_ack_event

        merged_pause_events      = {**existing_pause_events,      **new_pause_events}
        merged_paused_ack_events = {**existing_paused_ack_events, **new_paused_ack_events}

        thread = threading.Thread(
            target=run_emulator,
            args=(udid, stop_event, existing_drivers,
                  merged_pause_events, merged_paused_ack_events, play_lock)
        )
        new_threads[udid] = thread
        thread.start()
        logger.log(f"→ Thread started for {udid}")

        if i < len(emulators) - 1:
            logger.log(f"→ Waiting 10s before next thread...")
            time.sleep(10)

    return new_threads, new_stop_events, new_drivers, new_pause_events, new_paused_ack_events


# ── Main ──────────────────────────────────────────────────────────────

def main_pro():
    load_dotenv()
    global play_lock
    play_lock = threading.Lock()
    logger.log("✓ play_lock created — emulators will take turns clicking play.")

    emulators = grabber.get_emulator_list()

    if not emulators:
        logger.log("✗ No emulators found. Aborting.")
        return {}, {}, {}, {}, {}

    stop_events       = {}
    threads           = {}
    drivers           = {}
    pause_events      = {}
    paused_ack_events = {}

    for udid, _ in emulators:
        stop_events[udid]       = threading.Event()
        pause_events[udid]      = threading.Event()
        paused_ack_events[udid] = threading.Event()

    for i, (udid, _) in enumerate(emulators):
        thread = threading.Thread(
            target=run_emulator,
            args=(udid, stop_events[udid], drivers,
                  pause_events, paused_ack_events, play_lock)
        )
        threads[udid] = thread
        thread.start()
        logger.log(f"→ Thread started for {udid}")

        if i < len(emulators) - 1:
            logger.log(f"→ Waiting 10s before next thread...")
            time.sleep(10)

    return threads, stop_events, drivers, pause_events, paused_ack_events


if __name__ == "__main__":
    main_pro()
