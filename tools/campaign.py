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


# ── Count Occupied Slots On One Emulator ─────────────────────────────

def count_occupied_slots(driver, udid):
    """
    Count how many campaign slots are already occupied by probing
    textView_time[1..MAX] — same proven XPath used in campaign_status.
    Returns an integer 0–MAX_CAMPAIGNS_PER_EMULATOR.
    """
    occupied = 0
    for index in range(1, MAX_CAMPAIGNS_PER_EMULATOR + 1):
        xpath = (
            f'(//android.widget.TextView'
            f'[@resource-id="com.view.ytrabbit:id/textView_time"])[{index}]'
        )
        try:
            el = driver.find_element(AppiumBy.XPATH, xpath)
            if el.text.strip():
                occupied += 1
            else:
                break
        except Exception:
            break  # element not found → slot empty → stop counting

    logger.log(f"[{udid}] → Occupied slots: {occupied}/{MAX_CAMPAIGNS_PER_EMULATOR}")
    return occupied


# ── Distribute Links Across Emulators ────────────────────────────────

def distribute_links(links, available_slots_map):
    """
    Distribute links across emulators using per-emulator available slot counts.

    available_slots_map: { udid: available_slot_count }

    Example: 4 links, emulator1 has 2 free, emulator2 has 3 free
             → emulator1: [link1, link2], emulator2: [link3, link4]
    """
    distribution = {}
    link_index = 0

    for udid, available in available_slots_map.items():
        if link_index >= len(links):
            break
        if available == 0:
            logger.log(f"→ {udid} is FULL — skipping.")
            continue

        assigned = links[link_index: link_index + available]
        distribution[udid] = assigned
        link_index += available
        logger.log(f"→ {udid} assigned {len(assigned)} link(s) "
                   f"({available} slot(s) free): {assigned}")

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
    
    time.sleep(3)
    spinner = driver.find_element(AppiumBy.CLASS_NAME, "android.widget.Spinner")
    spinner.click()
    logger.log(f"[{udid}] ✓  view quantity spinner clicked...")

    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((
            AppiumBy.ANDROID_UIAUTOMATOR,
            'new UiSelector().resourceId("android:id/text1")'
        ))
    )

    driver.find_element(
        AppiumBy.ANDROID_UIAUTOMATOR,
        f'new UiScrollable(new UiSelector().scrollable(true))'
        f'.scrollIntoView(new UiSelector().text("{value}"))'
    ).click()

    view_quantity_choose = wait.until(EC.element_to_be_clickable(
    (AppiumBy.ID, "android:id/button1")
    ))
    view_quantity_choose.click()


def watch_seconds_option(driver, udid, value: str):
    wait = WebDriverWait(driver, 30)
    watch_seconds_click = wait.until(EC.element_to_be_clickable(
    (AppiumBy.ID, "com.view.ytrabbit:id/textView_sec")
    ))
    watch_seconds_click.click()
    
    time.sleep(3)
    spinner = driver.find_element(AppiumBy.CLASS_NAME, "android.widget.Spinner")
    spinner.click()
    logger.log(f"[{udid}] ✓  watch seconds spinner clicked...")

    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((
            AppiumBy.ANDROID_UIAUTOMATOR,
            'new UiSelector().resourceId("android:id/text1")'
        ))
    )

    driver.find_element(
        AppiumBy.ANDROID_UIAUTOMATOR,
        f'new UiScrollable(new UiSelector().scrollable(true))'
        f'.scrollIntoView(new UiSelector().text("{value}"))'
    ).click()

    watch_seconds_choose = wait.until(EC.element_to_be_clickable(
    (AppiumBy.ID, "android:id/button1")
    ))
    watch_seconds_choose.click()

def random_behavior_option(driver, udid,):
    wait = WebDriverWait(driver, 30)
    random_behavior_button = wait.until(EC.element_to_be_clickable(
    (AppiumBy.ID, "com.view.ytrabbit:id/switch_random")
    ))
    random_behavior_button.click()
    logger.log(f"[{udid}] ✓ random behavior option clicked...")

def min_startime_option(driver, udid, value: str):
    wait = WebDriverWait(driver, 30)
    min_startime_click = wait.until(EC.element_to_be_clickable(
    (AppiumBy.ID, "com.view.ytrabbit:id/textView_min_start")
    ))
    min_startime_click.click()

    time.sleep(3)
    spinner = driver.find_element(AppiumBy.CLASS_NAME, "android.widget.Spinner")
    spinner.click()
    logger.log(f"[{udid}] ✓  min start time spinner clicked...")

    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((
            AppiumBy.ANDROID_UIAUTOMATOR,
            'new UiSelector().resourceId("android:id/text1")'
        ))
    )

    driver.find_element(
        AppiumBy.ANDROID_UIAUTOMATOR,
        f'new UiScrollable(new UiSelector().scrollable(true))'
        f'.scrollIntoView(new UiSelector().text("{value}"))'
    ).click()

    min_startime_choose = wait.until(EC.element_to_be_clickable(
    (AppiumBy.ID, "android:id/button1")
    ))
    min_startime_choose.click()

def max_startime_option(driver, udid, value: str):
    wait = WebDriverWait(driver, 30)
    max_startime_click = wait.until(EC.element_to_be_clickable(
    (AppiumBy.ID, "com.view.ytrabbit:id/textView_max_start")
    ))
    max_startime_click.click()

    time.sleep(3)
    spinner = driver.find_element(AppiumBy.CLASS_NAME, "android.widget.Spinner")
    spinner.click()
    logger.log(f"[{udid}] ✓  max start time spinner clicked...")

    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((
            AppiumBy.ANDROID_UIAUTOMATOR,
            'new UiSelector().resourceId("android:id/text1")'
        ))
    )

    driver.find_element(
        AppiumBy.ANDROID_UIAUTOMATOR,
        f'new UiScrollable(new UiSelector().scrollable(true))'
        f'.scrollIntoView(new UiSelector().text("{value}"))'
    ).click()

    max_startime_choose = wait.until(EC.element_to_be_clickable(
    (AppiumBy.ID, "android:id/button1")
    ))
    max_startime_choose.click()

def min_watchtime_option(driver, udid, value: str):
    wait = WebDriverWait(driver, 30)
    min_watchtime_click = wait.until(EC.element_to_be_clickable(
    (AppiumBy.ID, "com.view.ytrabbit:id/textView_min_watch")
    ))
    min_watchtime_click.click()

    time.sleep(3)  
    spinner = driver.find_element(AppiumBy.CLASS_NAME, "android.widget.Spinner")
    spinner.click()
    logger.log(f"[{udid}] ✓  min watch time spinner clicked...")

    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((
            AppiumBy.ANDROID_UIAUTOMATOR,
            'new UiSelector().resourceId("android:id/text1")'
        ))
    )

    driver.find_element(
        AppiumBy.ANDROID_UIAUTOMATOR,
        f'new UiScrollable(new UiSelector().scrollable(true))'
        f'.scrollIntoView(new UiSelector().text("{value}"))'
    ).click()

    min_watchtime_choose = wait.until(EC.element_to_be_clickable(
    (AppiumBy.ID, "android:id/button1")
    ))
    min_watchtime_choose.click()

def max_watchtime_option(driver, udid, value: str):
    wait = WebDriverWait(driver, 30)
    max_watchtime_click = wait.until(EC.element_to_be_clickable(
    (AppiumBy.ID, "com.view.ytrabbit:id/textView_max_watch")
    ))
    max_watchtime_click.click()

    time.sleep(3)
    spinner = driver.find_element(AppiumBy.CLASS_NAME, "android.widget.Spinner")
    spinner.click()
    logger.log(f"[{udid}] ✓  max watch time spinner clicked...")

    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((
            AppiumBy.ANDROID_UIAUTOMATOR,
            'new UiSelector().resourceId("android:id/text1")'
        ))
    )

    driver.find_element(
        AppiumBy.ANDROID_UIAUTOMATOR,
        f'new UiScrollable(new UiSelector().scrollable(true))'
        f'.scrollIntoView(new UiSelector().text("{value}"))'
    ).click()

    max_watchtime_choose = wait.until(EC.element_to_be_clickable(
    (AppiumBy.ID, "android:id/button1")
    ))
    max_watchtime_choose.click()


# ── Add Campaign For One Emulator ─────────────────────────────────────

def add_campaign_for_emulator(udid, system_port, links, webdriver_url, done_event, view_quantity, watch_seconds, random_behavior, min_startime, max_startime, min_watchtime, max_watchtime):
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

            watch_seconds_option(driver, udid, str(watch_seconds))
            logger.log(f"[{udid}] ✓ watch seconds option done...")

            if random_behavior:
                random_behavior_option(driver, udid)
                logger.log(f"[{udid}] ✓ random behavior option done...")

                min_startime_option(driver, udid, str(min_startime))
                logger.log(f"[{udid}] ✓ min start time option done...")

                max_startime_option(driver, udid, str(max_startime))
                logger.log(f"[{udid}] ✓ max start time option done...")

                min_watchtime_option(driver, udid, str(min_watchtime))
                logger.log(f"[{udid}] ✓ min watch time option done...")

                max_watchtime_option(driver, udid, str(max_watchtime))
                logger.log(f"[{udid}] ✓ max watch time option done...")

            driver.find_element(
            AppiumBy.ANDROID_UIAUTOMATOR,
            'new UiScrollable(new UiSelector().scrollable(true))'
            '.scrollIntoView(new UiSelector().text("Done"))'
            ).click()
            logger.log(f"[{udid}] ✓ All options Done ...")

            
            # ─────────────────────────────────────────────



            time.sleep(3)  # placeholder until your code fills this section

            logger.log(f"[{udid}] ✓ Link {i + 1} added successfully")

            if i < len(links) - 1:
                time.sleep(2)  # small gap between links

        logger.log(f"[{udid}] ✓ All {len(links)} campaign(s) added.")

        # ── navigate back to main screen ──
        wait.until(EC.element_to_be_clickable(
            (AppiumBy.ID, "com.view.ytrabbit:id/btn_backse")
        )).click()
        logger.log(f"[{udid}] ✓ Navigated back to main screen.")

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

def run_add_campaign(view_quantity, watch_seconds, random_behavior, min_startime, max_startime, min_watchtime, max_watchtime):
    load_dotenv()
    webdriver_url = os.getenv("WEBDRIVER_URL")

    if not webdriver_url:
        logger.log("✗ WEBDRIVER_URL not set in .env file.")
        return False, "✗ WEBDRIVER_URL not set in .env file."

    # ── read links ──
    links = read_campaign_links()
    if not links:
        return False, "✗ No links found in campaign_link.txt."

    # ── get emulators ──
    emulators = grabber.get_emulator_list()
    if not emulators:
        logger.log("✗ No emulators found. Aborting.")
        return False, "✗ No emulators found."

    # ── check occupied slots per emulator before distributing ──
    logger.log("→ Checking occupied campaign slots on each emulator...")
    available_slots_map = {}
    emulator_map = {udid: sys_port for udid, sys_port in emulators}

    for udid, sys_port in emulators:
        tmp_driver = None
        try:
            tmp_driver = webdriver.Remote(webdriver_url, options=build_options(udid, sys_port))
            pkg = os.getenv("APP_PACKAGE")
            tmp_driver.activate_app(pkg)
            wait_for_app_foreground(tmp_driver, udid, timeout=30)

            wait_tmp = WebDriverWait(tmp_driver, 20)
            my_campaign = wait_tmp.until(EC.element_to_be_clickable(
                (AppiumBy.ID, "com.view.ytrabbit:id/textView7")
            ))
            my_campaign.click()
            time.sleep(2)

            occupied  = count_occupied_slots(tmp_driver, udid)
            available = MAX_CAMPAIGNS_PER_EMULATOR - occupied
            available_slots_map[udid] = available

            if available == 0:
                logger.log(f"[{udid}] ✗ All slots full — will be skipped.")
            else:
                logger.log(f"[{udid}] ✓ {available} slot(s) available.")

        except Exception as e:
            logger.log(f"[{udid}] ⚠ Could not check slots: {e} — skipping.")
            available_slots_map[udid] = 0
        finally:
            if tmp_driver is not None:
                try:
                    tmp_driver.quit()
                except Exception:
                    pass

    total_available = sum(available_slots_map.values())
    if total_available == 0:
        logger.log("✗ All emulators are full. No slots available.")
        return False, "✗ All emulators are full. No slots available."

    logger.log(f"→ Total available slots across all emulators: {total_available}")
    if len(links) > total_available:
        logger.log(f"⚠ {len(links)} links but only {total_available} free slot(s). "
                   f"Extra links will be ignored.")

    # ── distribute links based on actual available slots ──
    distribution = distribute_links(links, available_slots_map)

    if not distribution:
        logger.log("✗ No links to distribute.")
        return False, "✗ No links to distribute."

    # ── launch threads ──
    threads = []
    done_events = []

    for i, (udid, assigned_links) in enumerate(distribution.items()):
        sys_port = emulator_map[udid]
        done_event = threading.Event()
        done_events.append(done_event)

        t = threading.Thread(
            target=add_campaign_for_emulator,
            args=(udid, sys_port, assigned_links, webdriver_url, done_event, view_quantity, watch_seconds, random_behavior, min_startime, max_startime, min_watchtime, max_watchtime)
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
    return True, "✓ Add Campaign completed for all emulators."
