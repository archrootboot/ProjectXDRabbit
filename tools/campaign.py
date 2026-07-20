from appium import webdriver
from appium.options.android import UiAutomator2Options
from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import threading
import time
import tools.grabber as grabber
import logger
import os
from dotenv import load_dotenv

CAMPAIGN_FILE = "campaign_link.txt"
MAX_CAMPAIGNS_PER_EMULATOR = 3


# ── Read Links ────────────────────────────────────────────────────────

def read_campaign_links():
    if not os.path.exists(CAMPAIGN_FILE):
        logger.log(f"✗ {CAMPAIGN_FILE} not found.")
        return []

    with open(CAMPAIGN_FILE, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f.readlines()]

    links = [l for l in lines if l]  # remove empty lines

    if not links:
        logger.log(f"✗ {CAMPAIGN_FILE} is empty.")
        return []

    logger.log(f"✓ Found {len(links)} link(s) in {CAMPAIGN_FILE}")
    return links


# ── Distribute Links Across Emulators ────────────────────────────────

def distribute_links(links, emulators):
    """
    Distribute links across emulators sequentially.
    Each emulator gets up to MAX_CAMPAIGNS_PER_EMULATOR links.

    Example: 6 links, 3 emulators → emulator1: [1,2,3], emulator2: [4,5,6]
    Example: 4 links, 3 emulators → emulator1: [1,2,3], emulator2: [4]
    """
    distribution = {}
    link_index = 0

    for udid, _ in emulators:
        if link_index >= len(links):
            break
        assigned = links[link_index: link_index + MAX_CAMPAIGNS_PER_EMULATOR]
        distribution[udid] = assigned
        link_index += MAX_CAMPAIGNS_PER_EMULATOR
        logger.log(f"→ {udid} assigned {len(assigned)} link(s): {assigned}")

    return distribution


# ── Build Options ─────────────────────────────────────────────────────

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


# ── Wait For App Foreground ───────────────────────────────────────────

def wait_for_app_foreground(driver, udid, timeout=30):
    pkg = os.getenv("APP_PACKAGE")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if driver.current_package == pkg:
                logger.log(f"[{udid}] ✓ App is in foreground ({driver.current_activity})")
                return True
        except Exception:
            pass
        time.sleep(1)
    logger.log(f"[{udid}] ⚠ App did not reach foreground within {timeout}s — proceeding anyway")
    return False

#options
def view_quantity_option(driver, udid, value: str):
    wait = WebDriverWait(driver, 30)
    view_quantity_click = wait.until(EC.element_to_be_clickable(
    (AppiumBy.ID, "com.view.ytrabbit:id/textView_view")
    ))
    view_quantity_click.click()
    
    # Step 1: open the spinner
    spinner = driver.find_element(AppiumBy.CLASS_NAME, "android.widget.Spinner")
    spinner.click()
    logger.log(f"[{udid}] ✓  view quantity spinner clicked...")

    # Step 2: wait for list to appear
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((
            AppiumBy.ANDROID_UIAUTOMATOR,
            'new UiSelector().resourceId("android:id/text1")'
        ))
    )

    # Step 3: scroll into view and click
    driver.find_element(
        AppiumBy.ANDROID_UIAUTOMATOR,
        f'new UiScrollable(new UiSelector().scrollable(true))'
        f'.scrollIntoView(new UiSelector().text("{value}"))'
    ).click()

# ── Add Campaign For One Emulator ─────────────────────────────────────

def add_campaign_for_emulator(udid, system_port, links, webdriver_url, done_event, view_quantity, watch_seconds, random_behavior):
    driver = None
    try:
        logger.log(f"[{udid}] → Connecting...")
        driver = webdriver.Remote(webdriver_url, options=build_options(udid, system_port))
        logger.log(f"[{udid}] ✓ Connected")

        # ── open app ──
        pkg = os.getenv("APP_PACKAGE")
        driver.activate_app(pkg)
        wait_for_app_foreground(driver, udid, timeout=30)

        wait = WebDriverWait(driver, 30)

        # ── click My Campaign ──
        logger.log(f"[{udid}] → Clicking My Campaign...")
        my_campaign = wait.until(EC.element_to_be_clickable(
            (AppiumBy.ID, "com.view.ytrabbit:id/textView7")
        ))
        my_campaign.click()
        logger.log(f"[{udid}] ✓ My Campaign opened")
        time.sleep(2)

        # ── add each link ──
        for i, link in enumerate(links):
            logger.log(f"[{udid}] → Adding link {i + 1}/{len(links)}: {link}")

            # ── input field ──
            input_field = wait.until(EC.element_to_be_clickable(
                (AppiumBy.ID, "com.view.ytrabbit:id/editText")
            ))
            input_field.clear()
            input_field.send_keys(link)
            logger.log(f"[{udid}] ✓ Link entered")

            # ── click ADD ──
            add_button = wait.until(EC.element_to_be_clickable(
                (AppiumBy.ID, "com.view.ytrabbit:id/button")
            ))
            add_button.click()
            logger.log(f"[{udid}] ✓ ADD clicked — waiting for video settings screen...")



            # ── wait for video settings screen (Screen 3) ──
            # ── YOUR CODE GOES HERE ───────────────────────
            view_quantity_option(driver, udid, str(view_quantity))
            logger.log(f"[{udid}] ✓ view quantity option done...")
            # ─────────────────────────────────────────────



            time.sleep(3)  # placeholder until your code fills this section

            logger.log(f"[{udid}] ✓ Link {i + 1} added successfully")

            if i < len(links) - 1:
                time.sleep(2)  # small gap between links

        logger.log(f"[{udid}] ✓ All {len(links)} campaign(s) added.")

    except Exception as e:
        logger.log(f"[{udid}] ✗ Campaign error: {e}")
    finally:
        if driver is not None:
            try:
                driver.quit()
                logger.log(f"[{udid}] ✓ Disconnected")
            except Exception:
                pass
        done_event.set()


# ── Main Campaign Runner ──────────────────────────────────────────────

def run_add_campaign(view_quantity, watch_seconds, random_behavior):
    load_dotenv()
    webdriver_url = os.getenv("WEBDRIVER_URL")

    if not webdriver_url:
        logger.log("✗ WEBDRIVER_URL not set in .env file.")
        return

    # ── read links ──
    links = read_campaign_links()
    if not links:
        return

    # ── get emulators ──
    emulators = grabber.get_emulator_list()
    if not emulators:
        logger.log("✗ No emulators found. Aborting.")
        return

    # ── check total capacity ──
    total_capacity = len(emulators) * MAX_CAMPAIGNS_PER_EMULATOR
    if len(links) > total_capacity:
        logger.log(f"⚠ {len(links)} links but only {total_capacity} slots "
                   f"({len(emulators)} emulators × {MAX_CAMPAIGNS_PER_EMULATOR}). "
                   f"Extra links will be ignored.")

    # ── distribute links ──
    distribution = distribute_links(links, emulators)

    if not distribution:
        logger.log("✗ No links to distribute.")
        return

    # ── launch threads ──
    threads = []
    done_events = []

    emulator_map = {udid: sys_port for udid, sys_port in emulators}

    for i, (udid, assigned_links) in enumerate(distribution.items()):
        sys_port = emulator_map[udid]
        done_event = threading.Event()
        done_events.append(done_event)

        t = threading.Thread(
            target=add_campaign_for_emulator,
            args=(udid, sys_port, assigned_links, webdriver_url, done_event, view_quantity, watch_seconds, random_behavior)
        )
        threads.append(t)
        t.start()
        logger.log(f"→ Campaign thread started for {udid}")

        if i < len(distribution) - 1:
            logger.log(f"→ Waiting 5s before next emulator...")
            time.sleep(5)

    # ── wait for all threads to finish ──
    for done_event in done_events:
        done_event.wait()

    logger.log("✓ Add Campaign completed for all emulators.")
