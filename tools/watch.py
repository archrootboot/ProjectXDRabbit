import os
import time
from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import logger
import tools.yt_links_get as yt_links_get


def watch_video(driver, udid, stop_event, pause_event=None, paused_ack=None, play_lock=None):
    wait = WebDriverWait(driver, 15)
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

    # ── point not updated error tracking (per emulator) ───────────────
    max_point_errors     = int(os.getenv("MAX_POINT_ERRORS", "10").strip())
    max_point_error_time = int(os.getenv("MAX_POINT_ERROR_TIME", "1800").strip())
    point_not_updated_count = 0
    point_error_start_time  = None

    # ── thread-lock state (acquired before play, released at video start) ──
    lock_held = False


    # ── Point Check ───────────────────────────────────────────────────

    def point_check(old_point_value):
        nonlocal point_not_updated_count, point_error_start_time

        try:
            point_element = wait.until(EC.presence_of_element_located(
                (AppiumBy.ID, "com.view.ytrabbit:id/textView_points")
            ))
            point_value = point_element.text

            if point_value != old_point_value:
                logger.green(f"[{udid}] Points updated: {point_value}")
                return point_value

            else:
                point_not_updated_count += 1

                if point_error_start_time is None:
                    point_error_start_time = time.time()

                elapsed_time = int(time.time() - point_error_start_time)

                logger.red(f"[{udid}] Points not updated. "
                           f"(count: {point_not_updated_count}/{max_point_errors} | "
                           f"time: {elapsed_time}s/{max_point_error_time}s)")

                if point_not_updated_count >= max_point_errors and elapsed_time <= max_point_error_time:
                    logger.red(f"[{udid}] ⚠ {point_not_updated_count} point errors in "
                               f"{elapsed_time}s → restarting app...")
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
        pkg = os.getenv("APP_PACKAGE")
        logger.log(f"[{udid}] ⚠ Bug detected! Restarting app...")

        try:
            driver.terminate_app(pkg)
        except Exception as e:
            logger.log(f"[{udid}] ⚠ terminate_app failed: {e}")

        time.sleep(3)

        try:
            driver.activate_app(pkg)
        except Exception as e:
            logger.log(f"[{udid}] ⚠ activate_app failed: {e}")
            return False

        time.sleep(5)

        # ── use a longer timeout for the post-restart click ──
        # 10+ emulators means the machine is under load — 45s gives enough headroom
        restart_wait = WebDriverWait(driver, 45)

        for attempt in range(5):
            try:
                element = restart_wait.until(EC.element_to_be_clickable(
                    (AppiumBy.ID, "com.view.ytrabbit:id/textView4df")
                ))
                element.click()
                logger.log(f"[{udid}] ✓ App restarted successfully (attempt {attempt + 1}).")
                return True
            except Exception as e:
                logger.log(f"[{udid}] ⚠ Element click after restart attempt {attempt + 1}/5 failed: {e}")
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
                threshold = int(watch_time_raw[2:].strip())
                return duration <= threshold

            elif watch_time_raw.startswith(">="):
                threshold = int(watch_time_raw[2:].strip())
                return duration >= threshold

            elif watch_time_raw.startswith("<"):
                threshold = int(watch_time_raw[1:].strip())
                return duration < threshold

            elif watch_time_raw.startswith(">"):
                threshold = int(watch_time_raw[1:].strip())
                return duration > threshold

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

        # ── release play lock now that the video is about to start ──────
        if play_lock is not None and lock_held:
            play_lock.release()
            lock_held = False
            logger.log(f"[{udid}] 🔓 Play lock released — video is playing.")

        logger.log(f"[{udid}] ▶ Video started. Waiting {total_wait}s ({duration}s + {buffer_time}s buffer)...")

        while not stop_event.is_set() and elapsed < total_wait:
            time.sleep(check_interval)
            elapsed += check_interval
            logger.log(f"[{udid}] ⏱ Waiting... ({elapsed}s/{total_wait}s)")

            try:
                driver.current_activity
            except Exception as e:
                logger.log(f"[{udid}] ⚠ Session lost during video wait: {e}")
                return "session_lost"

        if stop_event.is_set():
            return "stopped"

        logger.log(f"[{udid}] ✓ Video finished.")
        return "done"


    # ── Pause Gate ────────────────────────────────────────────────────
    # Called only at safe idle points (after point_check, after a skip).
    # Never interrupts a video in progress.

    def pause_gate():
        """Block here if a campaign setup is waiting. Safe to call only
        between videos — never while a video is counting down.
        Sets paused_ack so the campaign thread knows the driver is free."""
        if pause_event and pause_event.is_set():
            logger.log(f"[{udid}] ⏸ Paused for campaign setup — waiting for it to finish...")
            if paused_ack:
                paused_ack.set()    # tell campaign side: driver is idle now
            while pause_event.is_set() and not stop_event.is_set():
                time.sleep(1)
            if paused_ack:
                paused_ack.clear()  # reset for next use
            if not stop_event.is_set():
                logger.log(f"[{udid}] ▶ Resumed main script after campaign setup.")


    # ── Main Loop ─────────────────────────────────────────────────────

    while not stop_event.is_set():
        try:
            time_element = wait.until(EC.presence_of_element_located(
                (AppiumBy.ID, "com.view.ytrabbit:id/textView_time")
            ))
            time_value = time_element.text.strip()

            if is_valid_duration(time_value):
                point_element = wait.until(EC.presence_of_element_located(
                    (AppiumBy.ID, "com.view.ytrabbit:id/textView_points")
                ))
                old_point_value = point_element.text

                duration = int(time_value)
                consecutive_skips = 0

                # ── locate play button (needed for click_fn lambda) ───
                image_element = wait.until(EC.element_to_be_clickable(
                    (AppiumBy.ID, "com.view.ytrabbit:id/imageView_img2")
                ))
                time.sleep(1)

                # ── acquire play lock before thumbnail check + play click ──
                if play_lock is not None and not lock_held:
                    logger.log(f"[{udid}] 🔒 Waiting for play lock...")
                    play_lock.acquire()
                    lock_held = True
                    logger.log(f"[{udid}] 🔒 Play lock acquired.")

                # ── check thumbnail and click (or skip) ──────────────
                yt_result = yt_links_get.check_and_play(
                    driver      = driver,
                    udid        = udid,
                    skip_hashes = skip_hashes,
                    click_fn    = lambda: image_element.click()
                )

                if yt_result == "skip":
                    # thumbnail matched skip list — use app's skip button
                    logger.log(f"[{udid}] ⏭ Video skipped. Loading next...")
                    skip_button = wait.until(EC.element_to_be_clickable(
                        (AppiumBy.ID, "com.view.ytrabbit:id/textView_chage")
                    ))
                    skip_button.click()
                    time.sleep(2)
                    # ── safe idle point: between videos ──
                    pause_gate()
                    continue
                # ─────────────────────────────────────────────────────
                # yt_result == "play" or "unknown" → wait for video end

                result = wait_for_video(duration)

                if result == "done":
                    driver.tap([(13, 943)], 100)
                    logger.log(f"[{udid}] ✓ Tapped back.")
                    point_check(old_point_value)
                    consecutive_errors = 0
                    # ── safe idle point: video done, points recorded ──
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

                skip_button = wait.until(EC.element_to_be_clickable(
                    (AppiumBy.ID, "com.view.ytrabbit:id/textView_chage")
                ))
                skip_button.click()
                time.sleep(2)
                # ── safe idle point: duration skipped, between videos ──
                pause_gate()

        except Exception as e:
            # ── safety: release lock if it was held when exception occurred ──
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
