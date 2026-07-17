from appium import webdriver
from appium.options.android import UiAutomator2Options
from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import threading
import time
import tools.grabber as grabber
import tools.watch as watch
import logger
import os
from dotenv import load_dotenv


def build_options(udid, system_port):
    options = UiAutomator2Options()
    options.platform_name = "Android"
    options.udid = udid
    options.app_package = os.getenv("APP_PACKAGE")
    options.app_activity = os.getenv("APP_MAIN_ACTIVITY")
    options.no_reset = True
    options.full_reset = False
    options.new_command_timeout = int(os.getenv("NEW_COMMAND_TIMEOUT"))
    options.set_capability("systemPort", system_port)
    return options


def wait_for_app_foreground(driver, udid, timeout=30):
    """Poll until the target app activity is in the foreground."""
    pkg            = os.getenv("APP_PACKAGE")        # com.view.ytrabbit
    activity       = os.getenv("APP_MAIN_ACTIVITY")  # com.view.ytrabbit.MainActivity
    short_activity = activity.split(".")[-1]          # MainActivity

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            current_activity = driver.current_activity  # ".MainActivity" or "MainActivity"
            current_package  = driver.current_package   # "com.view.ytrabbit"

            if current_package == pkg and short_activity in current_activity:
                logger.log(f"[{udid}] ✓ App is in foreground ({current_activity})")
                return True
        except Exception:
            pass
        time.sleep(1)

    logger.log(f"[{udid}] ⚠ App did not reach foreground within {timeout}s — proceeding anyway")
    return False


def get_click_timeout(num_emulators):
    """Scale the WebDriverWait timeout based on how many emulators are running."""
    base = 30
    per_extra = 3
    return base + max(0, num_emulators - 1) * per_extra


def run_emulator(udid, system_port, stop_event, drivers):
    driver = None
    try:
        driver = webdriver.Remote(webdriver_url, options=build_options(udid, system_port))
        drivers[udid] = driver
        logger.log(f"✓ {udid} connected (systemPort: {system_port})")

        # ── open app with retry ──
        logger.log(f"→ Opening app on {udid}...")
        for attempt in range(3):
            try:
                driver.activate_app(os.getenv("APP_PACKAGE"))
                logger.log(f"✓ App opened on {udid}")
                break
            except Exception as e:
                logger.log(f"⚠ [{udid}] Attempt {attempt + 1}/3 failed to open app: {e}")
                time.sleep(3)
        else:
            raise Exception(f"[{udid}] Failed to open app after 3 attempts")

        # ── wait for app to be in foreground before clicking ──
        wait_for_app_foreground(driver, udid, timeout=30)

        # ── scale timeout based on number of active emulators ──
        click_timeout = get_click_timeout(len(drivers))
        logger.log(f"[{udid}] → Using click timeout: {click_timeout}s (emulators: {len(drivers)})")
        wait = WebDriverWait(driver, click_timeout)

        # ── click element after app opens with retry ──
        for attempt in range(5):
            try:
                element = wait.until(EC.element_to_be_clickable(
                    (AppiumBy.ID, "com.view.ytrabbit:id/textView4df")
                ))
                element.click()
                logger.log(f"✓ Element clicked on {udid}")
                break
            except Exception as e:
                logger.log(f"⚠ [{udid}] Attempt {attempt + 1}/5 failed to click element: {e}")
                time.sleep(5)
        else:
            raise Exception(f"[{udid}] Failed to click element after 5 attempts")

        watch.watch_video(driver, udid, stop_event)

    except Exception as e:
        logger.log(f"✗ Error with {udid}: {e}")
    finally:
        if driver is not None:
            try:
                driver.quit()
                logger.log(f"✓ {udid} disconnected")
            except Exception:
                pass


# ── Thread control functions ──────────────────────────────────────────

def stop_one(udid, threads, stop_events, drivers):
    if udid in stop_events:
        if udid in drivers:
            if threads[udid].is_alive():
                try:
                    logger.log(f"→ Closing app on {udid}...")
                    drivers[udid].terminate_app(os.getenv("APP_PACKAGE"))
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
    else:
        logger.log(f"✗ {udid} not found.")


def stop_all(threads, stop_events, drivers):
    for udid in stop_events:
        if udid in drivers:
            if udid in threads and threads[udid].is_alive():
                try:
                    logger.log(f"→ Closing app on {udid}...")
                    drivers[udid].terminate_app(os.getenv("APP_PACKAGE"))
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

def add_new_emulators(existing_threads, existing_stop_events, existing_drivers):
    emulators = grabber.get_emulator_list()

    if not emulators:
        logger.log("✗ No emulators found via ADB.")
        return {}, {}, {}

    new_stop_events = {}
    new_threads = {}
    new_drivers = {}

    for i, (udid, sys_port) in enumerate(emulators):
        if udid in existing_threads and existing_threads[udid].is_alive():
            logger.log(f"→ {udid} already running, skipping.")
            continue

        logger.log(f"→ New emulator detected: {udid}")
        stop_event = threading.Event()
        new_stop_events[udid] = stop_event

        thread = threading.Thread(
            target=run_emulator,
            args=(udid, sys_port, stop_event, existing_drivers)
        )
        new_threads[udid] = thread
        thread.start()
        logger.log(f"→ Thread started for {udid}")

        if i < len(emulators) - 1:
            logger.log(f"→ Waiting 5s before next thread...")
            time.sleep(5)

    return new_threads, new_stop_events, new_drivers


# ── Main ──────────────────────────────────────────────────────────────

def main_pro():
    load_dotenv()
    global webdriver_url
    webdriver_url = os.getenv("WEBDRIVER_URL")

    if not webdriver_url:
        logger.log("✗ WEBDRIVER_URL not set in .env file.")
        return {}, {}, {}

    emulators = grabber.get_emulator_list()

    if not emulators:
        logger.log("✗ No emulators found. Aborting.")
        return {}, {}, {}

    stop_events = {}
    threads = {}
    drivers = {}

    for i, (udid, sys_port) in enumerate(emulators):
        stop_event = threading.Event()
        stop_events[udid] = stop_event

        thread = threading.Thread(
            target=run_emulator,
            args=(udid, sys_port, stop_event, drivers)
        )
        threads[udid] = thread
        thread.start()
        logger.log(f"→ Thread started for {udid}")

        if i < len(emulators) - 1:
            logger.log(f"→ Waiting 5s before next thread...")
            time.sleep(5)

    return threads, stop_events, drivers


if __name__ == "__main__":
    main_pro()
