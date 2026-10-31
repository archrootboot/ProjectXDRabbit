import os
import time
import logger
import tools.yt_links_get as yt_links_get
import tools.adb_controller as adb

# Resource IDs used by the ytrabbit app
_RES_TIME   = "com.view.ytrabbit:id/textView_time"
_RES_POINTS = "com.view.ytrabbit:id/textView_points"
_RES_IMG    = "com.view.ytrabbit:id/imageView_img2"
_RES_SKIP   = "com.view.ytrabbit:id/textView_chage"
_RES_WATCH  = "com.view.ytrabbit:id/textView4df"


def watch_video(udid, stop_event, pause_event=None, paused_ack=None, play_lock=None):
    """
    Main watch loop — pure ADB version.

    Replaces the Appium-based watch_video().  No driver/WebDriver argument;
    all interaction goes through adb_controller using the device udid.

    Parameters
    ----------
    udid          : device serial (e.g. 'emulator-5554' or '127.0.0.1:21503')
    stop_event    : threading.Event — set to stop the loop
    pause_event   : threading.Event — set by campaign code to pause between videos
    paused_ack    : threading.Event — this function sets it when truly idle
    play_lock     : threading.Lock  — shared across threads; held during play-click
    """
    consecutive_skips  = 0
    consecutive_errors = 0
    max_skips          = int(os.getenv("MAX_SKIPS", "10").strip())
    max_errors         = 3
    check_interval     = 5
    buffer_time        = 20

    # ── build skip hashes once per session ───────────────────────────
    skip_hashes = yt_links_get.build_skip_hashes()

    # ── load watch time filter from .env ──────────────────────────────
    watch_time_raw = os.getenv("WATCH_TIME_VALUES", "").strip()

    # ── point not updated error tracking ─────────────────────────────
    max_point_errors      = int(os.getenv("MAX_POINT_ERRORS", "10").strip())
    max_point_error_time  = int(os.getenv("MAX_POINT_ERROR_TIME", "1800").strip())
    point_not_updated_count = 0
    point_error_start_time  = None

    # ── thread-lock state ─────────────────────────────────────────────
    lock_held = False


    # ── Point Check ───────────────────────────────────────────────────

    def point_check(old_point_value):
        nonlocal point_not_updated_count, point_error_start_time

        try:
            point_value = adb.get_text_by_id(udid, _RES_POINTS, timeout=15)
            if point_value is None:
                logger.red(f"[{udid}] ⚠ point_check: could not read points element.")
                return None

            if point_value != old_point_value:
                logger.green(f"[{udid}] Points updated: {point_value}")
                return point_value

            else:
                point_not_updated_count += 1

                if point_error_start_time is None:
                    point_error_start_time = time.time()

                elapsed_time = int(time.time() - point_error_start_time)

                logger.red(
                    f"[{udid}] Points not updated. "
                    f"(count: {point_not_updated_count}/{max_point_errors} | "
                    f"time: {elapsed_time}s/{max_point_error_time}s)"
                )

                if point_not_updated_count >= max_point_errors and elapsed_time <= max_point_error_time:
                    logger.red(
                        f"[{udid}] ⚠ {point_not_updated_count} point errors in "
                        f"{elapsed_time}s → restarting app..."
                    )
                    point_not_updated_count = 0
                    point_error_start_time  = None
                    restart_app()

                elif elapsed_time > max_point_error_time:
                    logger.log(f"[{udid}] → Time window expired. Resetting point error counter.")
                    point_not_updated_count = 0
                    point_error_start_time  = None

                return None

        except Exception as e:
            logger.red(f"[{udid}] ⚠ point_check failed: {e}")
            return None


    # ── Restart App ───────────────────────────────────────────────────

    def restart_app():
        pkg      = os.getenv("APP_PACKAGE")
        activity = os.getenv("APP_MAIN_ACTIVITY")
        logger.log(f"[{udid}] ⚠ Bug detected! Restarting app...")

        try:
            adb.stop_app(udid, pkg)
        except Exception as e:
            logger.log(f"[{udid}] ⚠ stop_app failed: {e}")

        time.sleep(3)

        try:
            adb.start_app(udid, pkg, activity)
        except Exception as e:
            logger.log(f"[{udid}] ⚠ start_app failed: {e}")
            return False

        time.sleep(5)

        # Click the watch button to re-enter the watch screen
        for attempt in range(5):
            el = adb.wait_for_element(udid, timeout=45, resource_id=_RES_WATCH)
            if el is not None:
                adb.tap_element(udid, el)
                logger.log(f"[{udid}] ✓ App restarted successfully (attempt {attempt + 1}).")
                return True
            logger.log(f"[{udid}] ⚠ Element click after restart attempt {attempt + 1}/5 failed.")
            time.sleep(5)

        logger.log(f"[{udid}] ✗ Failed to click element after restart — all 5 attempts exhausted.")
        return False


    # ── Validate Duration ─────────────────────────────────────────────

    def is_valid_duration(value):
        try:
            duration = int(value.strip())

            if not watch_time_raw:
                return duration > 0

            if watch_time_raw.startswith("<="):
                return duration <= int(watch_time_raw[2:].strip())
            elif watch_time_raw.startswith(">="):
                return duration >= int(watch_time_raw[2:].strip())
            elif watch_time_raw.startswith("<"):
                return duration < int(watch_time_raw[1:].strip())
            elif watch_time_raw.startswith(">"):
                return duration > int(watch_time_raw[1:].strip())
            else:
                targets = set(
                    int(v.strip()) for v in watch_time_raw.split(",") if v.strip().isdigit()
                )
                return duration in targets

        except ValueError:
            return False


    # ── Wait For Video ────────────────────────────────────────────────

    def wait_for_video(duration):
        nonlocal lock_held
        total_wait = duration + buffer_time
        elapsed    = 0

        # Release play lock now that the video is about to start
        if play_lock is not None and lock_held:
            play_lock.release()
            lock_held = False
            logger.log(f"[{udid}] 🔓 Play lock released — video is playing.")

        logger.log(f"[{udid}] ▶ Video started. Waiting {total_wait}s ({duration}s + {buffer_time}s buffer)...")

        while not stop_event.is_set() and elapsed < total_wait:
            # Honour a pause request mid-video
            if pause_event and pause_event.is_set():
                logger.log(f"[{udid}] ⏸ Pause requested via menu.")
                if paused_ack:
                    paused_ack.set()
                while pause_event.is_set() and not stop_event.is_set():
                    time.sleep(1)
                if paused_ack:
                    paused_ack.clear()
                if stop_event.is_set():
                    return "stopped"
                logger.log(f"[{udid}] ▶ Resumed — continuing video wait.")

            time.sleep(check_interval)
            elapsed += check_interval
            logger.log(f"[{udid}] ⏱ Waiting... ({elapsed}s/{total_wait}s)")

            # Liveness check via ADB
            act = adb.current_activity(udid)
            if act is None:
                logger.log(f"[{udid}] ⚠ Session lost during video wait.")
                return "session_lost"

        if stop_event.is_set():
            return "stopped"

        logger.log(f"[{udid}] ✓ Video finished.")
        return "done"


    # ── Pause Gate ────────────────────────────────────────────────────

    def pause_gate():
        """Block at a safe idle point while campaign setup runs."""
        if pause_event and pause_event.is_set():
            logger.log(f"[{udid}] ⏸ Paused for campaign setup — waiting...")
            if paused_ack:
                paused_ack.set()
            while pause_event.is_set() and not stop_event.is_set():
                time.sleep(1)
            if paused_ack:
                paused_ack.clear()
            if not stop_event.is_set():
                logger.log(f"[{udid}] ▶ Resumed main script after campaign setup.")


    # ── Main Loop ─────────────────────────────────────────────────────

    while not stop_event.is_set():
        try:
            # Read the current video duration from the UI
            time_value = adb.get_text_by_id(udid, _RES_TIME, timeout=15)
            if time_value is None:
                consecutive_errors += 1
                logger.log(f"[{udid}] ⚠ Could not read time element. Error {consecutive_errors}/{max_errors}.")
                time.sleep(5)
                if consecutive_errors >= max_errors:
                    consecutive_errors = 0
                    if not restart_app():
                        break
                continue

            if is_valid_duration(time_value):
                old_point_value = adb.get_text_by_id(udid, _RES_POINTS, timeout=10) or ""
                duration = int(time_value)
                consecutive_skips = 0

                # Locate play button element for bounds
                img_el = adb.wait_for_element(udid, timeout=30, resource_id=_RES_IMG)
                time.sleep(1)

                # Acquire play lock before thumbnail check + play click
                if play_lock is not None and not lock_held:
                    logger.log(f"[{udid}] 🔒 Waiting for play lock...")
                    play_lock.acquire()
                    lock_held = True
                    logger.log(f"[{udid}] 🔒 Play lock acquired.")

                # Check thumbnail then click (or skip)
                def _click_play():
                    if img_el is not None:
                        adb.tap_element(udid, img_el)
                    else:
                        # Fallback: find it fresh
                        adb.click_by_id(udid, _RES_IMG, timeout=10)

                yt_result = yt_links_get.check_and_play(
                    udid        = udid,
                    skip_hashes = skip_hashes,
                    click_fn    = _click_play,
                    # pass the element for cropped screenshot
                    thumb_el    = img_el,
                )

                if yt_result == "skip":
                    logger.log(f"[{udid}] ⏭ Video skipped. Loading next...")
                    adb.click_by_id(udid, _RES_SKIP, timeout=15)
                    time.sleep(2)
                    pause_gate()
                    continue

                # yt_result == "play" or "unknown" → wait for video end
                result = wait_for_video(duration)

                if result == "done":
                    # Tap back (same coordinate as original code)
                    adb.tap(udid, 12, 1010)
                    logger.log(f"[{udid}] ✓ Tapped back.")
                    point_check(old_point_value)
                    consecutive_errors = 0
                    pause_gate()

                elif result == "stopped":
                    break

                elif result == "session_lost":
                    logger.log(f"[{udid}] ⚠ Session lost. Stopping thread.")
                    break

            else:
                consecutive_skips += 1
                logger.log(f"[{udid}] Skipping ({consecutive_skips}/{max_skips}). Value: '{time_value}'")

                if consecutive_skips >= max_skips:
                    consecutive_skips = 0
                    success = restart_app()
                    if not success:
                        logger.log(f"[{udid}] ⚠ Restart failed. Retrying in 10s...")
                        time.sleep(10)
                    continue

                adb.click_by_id(udid, _RES_SKIP, timeout=15)
                time.sleep(2)
                pause_gate()

        except Exception as e:
            # Safety: release lock if held when exception occurred
            if play_lock is not None and lock_held:
                play_lock.release()
                lock_held = False
                logger.log(f"[{udid}] 🔓 Play lock released (exception path).")

            consecutive_errors += 1
            logger.log(f"[{udid}] Error ({consecutive_errors}/{max_errors}): {e}, retrying in 5s...")
            time.sleep(5)

            if consecutive_errors >= max_errors:
                logger.log(f"[{udid}] ⚠ Too many errors. Restarting app...")
                consecutive_errors = 0
                success = restart_app()
                if not success:
                    logger.log(f"[{udid}] ⚠ Restart failed. Stopping thread.")
                    break
            continue

    logger.log(f"[{udid}] Stop signal received. Exiting cleanly.")
