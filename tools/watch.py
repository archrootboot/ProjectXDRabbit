import os
from dotenv import load_dotenv
from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time


def watch_video(driver, udid, stop_event):
    wait = WebDriverWait(driver, 15)
    consecutive_skips = 0
    consecutive_errors = 0      # ← track main loop errors
    max_skips = 10
    max_errors = 3              # ← max errors before restart
    check_interval = 5          # ← check stop_event every 5 seconds
    buffer_time = 20            # ← extra wait after video duration
    time_value_skip = int(os.getenv("SKIP_TIME_VALUE", "0").strip())


    # ── Point Check ───────────────────────────────────────────────────

    def point_check(old_point_value):
        try:
            point_element = wait.until(EC.presence_of_element_located(
                (AppiumBy.ID, "com.view.ytrabbit:id/textView_points")
            ))
            point_value = point_element.text
            if point_value != old_point_value:
                print(f"[{udid}] Points updated: {point_value}")
                return point_value
            else:
                print(f"[{udid}] Points not updated yet.")
                return None
        except Exception as e:
            print(f"[{udid}] ⚠ point_check failed: {e}")
            return None   # ← safe fallback


    # ── Restart App ───────────────────────────────────────────────────

    def restart_app():
        pkg = os.getenv("APP_PACKAGE")
        print(f"[{udid}] ⚠ Bug detected! Restarting app...")

        try:
            driver.terminate_app(pkg)
        except Exception as e:
            print(f"[{udid}] ⚠ terminate_app failed: {e}")

        time.sleep(3)

        try:
            driver.activate_app(pkg)
        except Exception as e:
            print(f"[{udid}] ⚠ activate_app failed: {e}")
            return False   # ← signal restart failed

        time.sleep(10)  # ← wait for app to stabilize

        # ── click element after app reopens ──
        try:
            element = wait.until(EC.element_to_be_clickable(
                (AppiumBy.ID, "com.view.ytrabbit:id/textView4df")
            ))
            element.click()
            print(f"[{udid}] ✓ App restarted successfully.")
            return True    # ← signal restart succeeded
        except Exception as e:
            print(f"[{udid}] ⚠ Element click after restart failed: {e}")
            return False


    # ── Validate Duration ─────────────────────────────────────────────

    def is_valid_duration(value):
        try:
            return int(value.strip()) > time_value_skip
        except ValueError:
            return False


    # ── Wait For Video ────────────────────────────────────────────────

    def wait_for_video(duration):
        total_wait = duration + buffer_time
        elapsed = 0
        print(f"[{udid}] ▶ Video started. Waiting {total_wait}s ({duration}s + {buffer_time}s buffer)...")

        while not stop_event.is_set() and elapsed < total_wait:
            time.sleep(check_interval)
            elapsed += check_interval
            print(f"[{udid}] ⏱ Waiting... ({elapsed}s/{total_wait}s)")

            # ── keepalive to prevent session timeout ──
            try:
                driver.current_activity
            except Exception as e:
                print(f"[{udid}] ⚠ Session lost during video wait: {e}")
                return "session_lost"

        if stop_event.is_set():
            return "stopped"

        print(f"[{udid}] ✓ Video finished.")
        return "done"


    # ── Main Loop ─────────────────────────────────────────────────────

    while not stop_event.is_set():
        try:
            time_element = wait.until(EC.presence_of_element_located(
                (AppiumBy.ID, "com.view.ytrabbit:id/textView_time")
            ))
            time_value = time_element.text.strip()

            if is_valid_duration(time_value):
                # ── only fetch points when watching a video ──
                point_element = wait.until(EC.presence_of_element_located(
                    (AppiumBy.ID, "com.view.ytrabbit:id/textView_points")
                ))
                old_point_value = point_element.text

                duration = int(time_value)
                consecutive_skips = 0   # ← reset on valid video

                image_id = "com.view.ytrabbit:id/imageView_img2"
                image_element = wait.until(EC.element_to_be_clickable(
                    (AppiumBy.ID, image_id)
                ))
                image_element.click()

                result = wait_for_video(duration)

                if result == "done":
                    driver.tap([(42, 918)], 100)
                    print(f"[{udid}] ✓ Tapped back.")
                    point_check(old_point_value)
                    consecutive_errors = 0   # ← reset on success

                elif result == "stopped":
                    break

                elif result == "session_lost":
                    print(f"[{udid}] ⚠ Session lost. Stopping thread.")
                    break

            else:
                consecutive_skips += 1
                print(f"[{udid}] Skipping ({consecutive_skips}/{max_skips}). Value: '{time_value}'")

                if consecutive_skips >= max_skips:
                    consecutive_skips = 0
                    success = restart_app()
                    if not success:
                        print(f"[{udid}] ⚠ Restart failed. Retrying in 10s...")
                        time.sleep(10)
                    continue

                skip_button = wait.until(EC.element_to_be_clickable(
                    (AppiumBy.ID, "com.view.ytrabbit:id/textView_chage")
                ))
                skip_button.click()

        except Exception as e:
            consecutive_errors += 1
            print(f"[{udid}] Error ({consecutive_errors}/{max_errors}): {e}, retrying in 5s...")
            time.sleep(5)

            if consecutive_errors >= max_errors:
                print(f"[{udid}] ⚠ Too many errors. Restarting app...")
                consecutive_errors = 0   # ← reset counter
                success = restart_app()
                if not success:
                    print(f"[{udid}] ⚠ Restart failed. Stopping thread.")
                    break   # ← stop thread if restart also failed
            continue

    print(f"[{udid}] Stop signal received. Exiting cleanly.")
