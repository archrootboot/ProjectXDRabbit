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
    """
    Returns a list of (link, line_index) tuples for lines that are not
    already marked as done.  line_index is the 0-based position in the
    file so mark_link_done() can rewrite exactly the right line.
    Lines that end with 'done' (case-insensitive, with or without a
    trailing space) are silently skipped.
    """
    if not os.path.exists(CAMPAIGN_FILE):
        logger.log(f"✗ {CAMPAIGN_FILE} not found.")
        return []

    with open(CAMPAIGN_FILE, "r", encoding="utf-8") as f:
        raw_lines = f.readlines()

    pending = []
    skipped = 0
    for i, raw in enumerate(raw_lines):
        stripped = raw.strip()
        if not stripped:
            continue  # blank line
        if stripped.lower().endswith(" done") or stripped.lower() == "done":
            skipped += 1
            continue  # already used
        pending.append((stripped, i))

    if skipped:
        logger.log(f"→ Skipped {skipped} already-done link(s) in {CAMPAIGN_FILE}")

    if not pending:
        logger.log(f"✗ No pending links in {CAMPAIGN_FILE}.")
        return []

    logger.log(f"✓ Found {len(pending)} pending link(s) in {CAMPAIGN_FILE}")
    return pending


# ── Mark Link Done ────────────────────────────────────────────────────

def mark_link_done(line_index):
    """
    Rewrite line at line_index (0-based) in campaign_link.txt by
    appending ' done' to it.  Thread-safe via a per-call file read+write.
    """
    try:
        with open(CAMPAIGN_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()

        original = lines[line_index].rstrip("\n").rstrip("\r")
        # Guard against double-marking
        if not original.lower().endswith(" done"):
            lines[line_index] = original + " done\n"

        with open(CAMPAIGN_FILE, "w", encoding="utf-8") as f:
            f.writelines(lines)

        logger.log(f"→ Marked as done in {CAMPAIGN_FILE}: {original.strip()}")
    except Exception as e:
        logger.log(f"⚠ Could not mark link done (line {line_index}): {e}")


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

def distribute_links(pending, available_slots_map):
    """
    Distribute pending (link, line_index) tuples across emulators using
    per-emulator available slot counts.

    available_slots_map: { udid: available_slot_count }

    Example: 4 pending links, emulator1 has 2 free, emulator2 has 3 free
             → emulator1: [(link1, idx1), (link2, idx2)],
               emulator2: [(link3, idx3), (link4, idx4)]
    """
    distribution = {}
    cursor = 0

    for udid, available in available_slots_map.items():
        if cursor >= len(pending):
            break
        if available == 0:
            logger.log(f"→ {udid} is FULL — skipping.")
            continue

        assigned = pending[cursor: cursor + available]
        distribution[udid] = assigned
        cursor += available
        logger.log(f"→ {udid} assigned {len(assigned)} link(s) "
                   f"({available} slot(s) free): {[l for l, _ in assigned]}")

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

def add_campaign_for_emulator(udid, system_port, pending_links, webdriver_url, done_event, view_quantity, watch_seconds, random_behavior, min_startime, max_startime, min_watchtime, max_watchtime):
    """
    pending_links: list of (link_url, line_index) tuples.
    Each link is marked 'done' in campaign_link.txt immediately after it is
    successfully submitted to the app.
    """
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
        for i, (link, line_index) in enumerate(pending_links):
            logger.log(f"[{udid}] → Adding link {i + 1}/{len(pending_links)}: {link}")

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



            time.sleep(3)

            # ── mark this link as done in campaign_link.txt ──
            mark_link_done(line_index)
            logger.log(f"[{udid}] ✓ Link {i + 1} added and marked done")

            if i < len(pending_links) - 1:
                time.sleep(2)  # small gap between links

        logger.log(f"[{udid}] ✓ All {len(pending_links)} campaign(s) added.")

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


# ── Semaphore-Aware Thread Wrapper ───────────────────────────────────

def run_with_semaphore(semaphore, udid, system_port, pending_links, webdriver_url,
                       done_event, view_quantity, watch_seconds, random_behavior,
                       min_startime, max_startime, min_watchtime, max_watchtime):
    """
    Acquire the semaphore before running add_campaign_for_emulator and
    release it when done.  This keeps concurrent threads ≤ MAX_THREADS.
    """
    with semaphore:
        logger.log(f"[{udid}] → Semaphore acquired. Starting campaign thread...")
        add_campaign_for_emulator(
            udid, system_port, pending_links, webdriver_url, done_event,
            view_quantity, watch_seconds, random_behavior,
            min_startime, max_startime, min_watchtime, max_watchtime
        )
    logger.log(f"[{udid}] → Semaphore released.")


# ── Main Campaign Runner ──────────────────────────────────────────────

def run_add_campaign(view_quantity, watch_seconds, random_behavior, min_startime, max_startime, min_watchtime, max_watchtime):
    load_dotenv()
    webdriver_url = os.getenv("WEBDRIVER_URL")

    if not webdriver_url:
        logger.log("✗ WEBDRIVER_URL not set in .env file.")
        return False, "✗ WEBDRIVER_URL not set in .env file."

    # ── read MAX_THREADS from .env (default 5) ──
    max_threads = int(os.getenv("MAX_THREADS", "5").strip())
    logger.log(f"→ Max concurrent campaign threads: {max_threads}")

    # ── read pending (unfinished) links ──
    pending = read_campaign_links()
    if not pending:
        return False, "✗ No pending links found in campaign_link.txt."

    # ── get emulators ──
    emulators = grabber.get_emulator_list()
    if not emulators:
        logger.log("✗ No emulators found. Aborting.")
        return False, "✗ No emulators found."

    # ── check occupied slots per emulator before distributing ──
    # Cap this phase to max_threads concurrent checks too, so we don't
    # open more driver sessions than the machine can handle.
    logger.log(f"→ Checking occupied campaign slots (up to {max_threads} at a time)...")
    available_slots_map = {}
    emulator_map        = {udid: sys_port for udid, sys_port in emulators}
    check_semaphore     = threading.Semaphore(max_threads)
    slot_results        = {}   # udid → available_count
    slot_lock           = threading.Lock()

    def check_slots_for(udid, sys_port):
        tmp_driver = None
        with check_semaphore:
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

                if available == 0:
                    logger.log(f"[{udid}] ✗ All slots full — will be skipped.")
                else:
                    logger.log(f"[{udid}] ✓ {available} slot(s) available.")

                try:
                    wait_tmp.until(EC.element_to_be_clickable(
                        (AppiumBy.ID, "com.view.ytrabbit:id/btn_backse")
                    )).click()
                    logger.log(f"[{udid}] ✓ Navigated back to main screen.")
                except Exception as back_err:
                    logger.log(f"[{udid}] ⚠ Could not click back button: {back_err}")

            except Exception as e:
                logger.log(f"[{udid}] ⚠ Could not check slots: {e} — skipping.")
                available = 0
            finally:
                if tmp_driver is not None:
                    try:
                        tmp_driver.quit()
                    except Exception:
                        pass

        with slot_lock:
            slot_results[udid] = available

    check_threads = []
    for udid, sys_port in emulators:
        ct = threading.Thread(target=check_slots_for, args=(udid, sys_port))
        check_threads.append(ct)
        ct.start()

    for ct in check_threads:
        ct.join()

    available_slots_map = slot_results

    total_available = sum(available_slots_map.values())
    if total_available == 0:
        logger.log("✗ All emulators are full. No slots available.")
        return False, "✗ All emulators are full. No slots available."

    logger.log(f"→ Total available slots across all emulators: {total_available}")
    if len(pending) > total_available:
        logger.log(f"⚠ {len(pending)} pending links but only {total_available} free slot(s). "
                   f"Extra links will be ignored.")

    # ── distribute pending links based on actual available slots ──
    distribution = distribute_links(pending, available_slots_map)

    if not distribution:
        logger.log("✗ No links to distribute.")
        return False, "✗ No links to distribute."

    # ── launch threads, capped at MAX_THREADS concurrently ──
    semaphore   = threading.Semaphore(max_threads)
    threads     = []
    done_events = []

    logger.log(f"→ Launching {len(distribution)} campaign thread(s) "
               f"(max {max_threads} concurrent)...")

    for udid, assigned_links in distribution.items():
        sys_port   = emulator_map[udid]
        done_event = threading.Event()
        done_events.append(done_event)

        t = threading.Thread(
            target=run_with_semaphore,
            args=(semaphore, udid, sys_port, assigned_links, webdriver_url,
                  done_event, view_quantity, watch_seconds, random_behavior,
                  min_startime, max_startime, min_watchtime, max_watchtime)
        )
        threads.append(t)
        t.start()
        logger.log(f"→ Campaign thread queued for {udid}")

    # ── wait for all threads to finish ──
    for done_event in done_events:
        done_event.wait()

    logger.log("✓ Add Campaign completed for all emulators.")
    return True, "✓ Add Campaign completed for all emulators."
