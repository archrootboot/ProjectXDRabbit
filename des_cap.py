from appium import webdriver
from appium.options.android import UiAutomator2Options
from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import threading
import time
import tools.grabber as grabber
import tools.watch as watch
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


def run_emulator(udid, system_port, stop_event, drivers):
    driver = None
    try:
        driver = webdriver.Remote(webdriver_url, options=build_options(udid, system_port))
        drivers[udid] = driver
        print(f"✓ {udid} connected (systemPort: {system_port})")

        # ── open app with retry ──
        print(f"→ Opening app on {udid}...")
        for attempt in range(3):
            try:
                driver.activate_app(os.getenv("APP_PACKAGE"))
                print(f"✓ App opened on {udid}")
                break
            except Exception as e:
                print(f"⚠ [{udid}] Attempt {attempt + 1}/3 failed to open app: {e}")
                time.sleep(3)
        else:
            raise Exception(f"[{udid}] Failed to open app after 3 attempts")

        # ── click element after app opens with retry ──
        wait = WebDriverWait(driver, 15)
        for attempt in range(3):
            try:
                element = wait.until(EC.element_to_be_clickable(
                    (AppiumBy.ID, "com.view.ytrabbit:id/textView4df")
                ))
                element.click()
                print(f"✓ Element clicked on {udid}")
                break
            except Exception as e:
                print(f"⚠ [{udid}] Attempt {attempt + 1}/3 failed to click element: {e}")
                time.sleep(3)
        else:
            raise Exception(f"[{udid}] Failed to click element after 3 attempts")

        watch.watch_video(driver, udid, stop_event)

    except Exception as e:
        print(f"✗ Error with {udid}: {e}")
    finally:
        # ── always try to quit driver cleanly ──
        if driver is not None:
            try:
                driver.quit()
                print(f"✓ {udid} disconnected")
            except Exception:
                pass   # ← ignore quit errors


# ── Thread control functions ──────────────────────────────────────────

def stop_one(udid, threads, stop_events, drivers):
    if udid in stop_events:
        # ── only close app if thread is still alive ──
        if udid in drivers:
            if threads[udid].is_alive():
                try:
                    print(f"→ Closing app on {udid}...")
                    drivers[udid].terminate_app(os.getenv("APP_PACKAGE"))
                except Exception as e:
                    print(f"⚠ Could not close app on {udid}: {e}")
            else:
                print(f"→ {udid} already stopped, skipping app close.")

        # ── signal thread to stop ──
        stop_events[udid].set()

        # ── wait for thread with timeout ──
        print(f"→ Waiting for {udid} thread to stop...")
        threads[udid].join(timeout=15)

        if threads[udid].is_alive():
            print(f"⚠ {udid} thread did not stop cleanly within timeout.")
        else:
            print(f"✓ {udid} stopped cleanly.")
    else:
        print(f"✗ {udid} not found.")


def stop_all(threads, stop_events, drivers):
    # ── only close app if thread is still alive ──
    for udid in stop_events:
        if udid in drivers:
            if udid in threads and threads[udid].is_alive():
                try:
                    print(f"→ Closing app on {udid}...")
                    drivers[udid].terminate_app(os.getenv("APP_PACKAGE"))
                except Exception as e:
                    print(f"⚠ Could not close app on {udid}: {e}")
            else:
                print(f"→ {udid} already stopped, skipping app close.")

    # ── signal all threads to stop ──
    for event in stop_events.values():
        event.set()

    # ── wait for all threads with timeout ──
    for udid, thread in threads.items():
        thread.join(timeout=15)
        if thread.is_alive():
            print(f"⚠ {udid} thread did not stop cleanly within timeout.")
        else:
            print(f"✓ {udid} stopped cleanly.")

    print("All emulators stopped.")


def get_status(threads):
    status = {}
    for udid, thread in threads.items():
        status[udid] = "running" if thread.is_alive() else "stopped"
    return status


# ── Add New Emulators ─────────────────────────────────────────────────

def add_new_emulators(existing_threads, existing_stop_events, existing_drivers):
    emulators = grabber.get_emulator_list()

    if not emulators:
        print("✗ No emulators found via ADB.")
        return {}, {}, {}

    new_stop_events = {}
    new_threads = {}
    new_drivers = {}

    for i, (udid, sys_port) in enumerate(emulators):
        # ── skip already running emulators ──
        if udid in existing_threads and existing_threads[udid].is_alive():
            print(f"→ {udid} already running, skipping.")
            continue

        print(f"→ New emulator detected: {udid}")
        stop_event = threading.Event()
        new_stop_events[udid] = stop_event

        thread = threading.Thread(
            target=run_emulator,
            args=(udid, sys_port, stop_event, existing_drivers)
        )
        new_threads[udid] = thread
        thread.start()
        print(f"→ Thread started for {udid}")

        # ── 5s interval between thread starts ──
        if i < len(emulators) - 1:
            print(f"→ Waiting 5s before next thread...")
            time.sleep(5)

    return new_threads, new_stop_events, new_drivers


# ── Main ──────────────────────────────────────────────────────────────

def main_pro():
    load_dotenv()
    global webdriver_url
    webdriver_url = os.getenv("WEBDRIVER_URL")

    if not webdriver_url:
        print("✗ WEBDRIVER_URL not set in .env file.")
        return {}, {}, {}

    emulators = grabber.get_emulator_list()

    if not emulators:
        print("✗ No emulators found. Aborting.")
        return {}, {}, {}

    stop_events = {}   # { "emulator-5554": Event, ... }
    threads = {}       # { "emulator-5554": Thread, ... }
    drivers = {}       # { "emulator-5554": driver, ... }

    for i, (udid, sys_port) in enumerate(emulators):
        stop_event = threading.Event()
        stop_events[udid] = stop_event

        thread = threading.Thread(
            target=run_emulator,
            args=(udid, sys_port, stop_event, drivers)
        )
        threads[udid] = thread
        thread.start()
        print(f"→ Thread started for {udid}")

        # ── 5s interval between thread starts ──
        if i < len(emulators) - 1:
            print(f"→ Waiting 5s before next thread...")
            time.sleep(5)

    return threads, stop_events, drivers


if __name__ == "__main__":
    main_pro()
