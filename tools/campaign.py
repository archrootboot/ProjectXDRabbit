from appium import webdriver
from appium.options.android import UiAutomator2Options
from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import threading
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


# ── Option Helpers ────────────────────────────────────────────────────

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

def random_behavior_option(driver, udid):
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


# ── Add Campaign For One Emulator (standalone — own driver) ───────────

def add_campaign_for_emulator(udid, system_port, pending_links, webdriver_url, view_quantity, watch_seconds, random_behavior, min_startime, max_startime, min_watchtime, max_watchtime):
    """
    pending_links: list of (link_url, line_index) tuples.
    Each link is marked 'done' in campaign_link.txt immediately after it is
    successfully submitted to the app.
    Opens its own driver connection (used by the original Add Campaign flow).
    """
    driver = None
    try:
        logger.log(f"[{udid}] → Connecting...")
        driver = webdriver.Remote(webdriver_url, options=build_options(udid, system_port))
        logger.log(f"[{udid}] ✓ Connected")

        _do_add_campaign_on_driver(
            driver, udid, pending_links,
            view_quantity, watch_seconds, random_behavior,
            min_startime, max_startime, min_watchtime, max_watchtime
        )

    except Exception as e:
        logger.log(f"[{udid}] ✗ Campaign error: {e}")
    finally:
        if driver is not None:
            try:
                driver.quit()
                logger.log(f"[{udid}] ✓ Disconnected")
            except Exception:
                pass


# ── Core Campaign UI Work (shared by both flows) ──────────────────────

def _do_add_campaign_on_driver(driver, udid, pending_links, view_quantity, watch_seconds,
                               random_behavior, min_startime, max_startime, min_watchtime,
                               max_watchtime, already_on_campaign_screen=False):
    """
    Perform the actual campaign UI steps on an already-open driver.
    Used by both the standalone flow (add_campaign_for_emulator) and the
    live-script flow (add_campaign_on_running_emulator).

    already_on_campaign_screen: if True, skip activate_app + textView7 click
    because the caller already navigated there (e.g. after a live slot check).
    """
    pkg  = os.getenv("APP_PACKAGE")
    wait = WebDriverWait(driver, 30)

    if not already_on_campaign_screen:
        # ── open app ──
        driver.activate_app(pkg)
        time.sleep(5)

        #Back to main screen
        logger.log(f"[{udid}] → Back to main screen...")
        wait.until(EC.element_to_be_clickable(
            (AppiumBy.ID, "com.view.ytrabbit:id/btn_backs")
        )).click()
        time.sleep(2)

        # ── click My Campaign ──
        logger.log(f"[{udid}] → Clicking My Campaign...")
        wait.until(EC.element_to_be_clickable(
            (AppiumBy.ID, "com.view.ytrabbit:id/textView7")
        )).click()
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

    # ── re-enter watch job screen so watch_video resumes correctly ──
    logger.log(f"[{udid}] → Re-entering watch screen...")
    re_enter_wait = WebDriverWait(driver, 30)
    watch_btn = re_enter_wait.until(EC.element_to_be_clickable(
        (AppiumBy.ID, "com.view.ytrabbit:id/textView4df")
    ))
    watch_btn.click()
    logger.log(f"[{udid}] ✓ Watch screen re-entered. Main job can resume.")


# ── Add Campaign On A Running Emulator (reuses existing driver) ────────

def add_campaign_on_running_emulator(udid, driver, pause_event, paused_ack,
                                     pending_links, view_quantity, watch_seconds,
                                     random_behavior, min_startime, max_startime,
                                     min_watchtime, max_watchtime):
    """
    Called from the campaign-during-script thread for ONE emulator.

    Steps:
      1. Set pause_event  → watch_video's pause_gate() catches it at the next
         safe idle point (after point_check or after a skip). Never mid-video.
      2. Wait on paused_ack — watch.py's pause_gate() sets this the instant it
         enters its idle loop. Driver is confirmed free at this point.
      3. Navigate to My Campaign and check actual occupied slots live.
         Trim pending_links to only what fits. Skip if already full.
      4. Add links, then navigate back and re-enter watch screen.
      5. Clear pause_event → pause_gate() unblocks, watch_video resumes.
    """
    logger.log(f"[{udid}] ⏸ Signalling pause — waiting for current video to finish...")
    if paused_ack:
        paused_ack.clear()  # ensure clean state before we start
    pause_event.set()

    # ── Wait for confirmed idle signal from pause_gate ────────────────
    max_wait = 300
    logger.log(f"[{udid}] ⏳ Waiting for watch loop to confirm idle (max {max_wait}s)...")

    if paused_ack:
        confirmed = paused_ack.wait(timeout=max_wait)
        if confirmed:
            logger.log(f"[{udid}] ✓ Watch loop confirmed idle. Driver is free.")
        else:
            logger.log(f"[{udid}] ⚠ Idle confirmation timed out after {max_wait}s. Proceeding anyway.")
    else:
        logger.log(f"[{udid}] ⚠ No paused_ack event — waiting 5s as fallback...")
        time.sleep(5)

    try:
        pkg  = os.getenv("APP_PACKAGE")
        wait = WebDriverWait(driver, 30)

        # ── navigate to My Campaign to check actual available slots ──
        logger.log(f"[{udid}] → Navigating to My Campaign for slot check...")
        driver.activate_app(pkg)
        time.sleep(3)

        wait.until(EC.element_to_be_clickable(
            (AppiumBy.ID, "com.view.ytrabbit:id/textView7")
        )).click()
        logger.log(f"[{udid}] ✓ My Campaign opened.")
        time.sleep(2)

        # ── live slot check ──
        occupied  = count_occupied_slots(driver, udid)
        available = MAX_CAMPAIGNS_PER_EMULATOR - occupied

        if available == 0:
            logger.log(f"[{udid}] ✗ All {MAX_CAMPAIGNS_PER_EMULATOR} slots full — skipping.")
            # navigate back and re-enter watch screen before returning
            try:
                wait.until(EC.element_to_be_clickable(
                    (AppiumBy.ID, "com.view.ytrabbit:id/btn_backse")
                )).click()
            except Exception:
                pass
            try:
                WebDriverWait(driver, 20).until(EC.element_to_be_clickable(
                    (AppiumBy.ID, "com.view.ytrabbit:id/textView4df")
                )).click()
                logger.log(f"[{udid}] ✓ Watch screen re-entered.")
            except Exception as re_err:
                logger.log(f"[{udid}] ⚠ Could not re-enter watch screen: {re_err}")
            return

        # ── trim links to what actually fits ──
        links_to_add = pending_links[:available]
        if len(pending_links) > available:
            skipped = len(pending_links) - available
            logger.log(f"[{udid}] ⚠ {available} slot(s) free, "
                       f"{len(pending_links)} link(s) assigned — trimming {skipped} extra.")
        logger.log(f"[{udid}] ✓ {available} slot(s) free — adding {len(links_to_add)} link(s).")

        # ── add the links (already on My Campaign screen) ──
        _do_add_campaign_on_driver(
            driver, udid, links_to_add,
            view_quantity, watch_seconds, random_behavior,
            min_startime, max_startime, min_watchtime, max_watchtime,
            already_on_campaign_screen=True
        )
        logger.log(f"[{udid}] ✓ Campaign setup complete.")

    except Exception as e:
        logger.log(f"[{udid}] ✗ Campaign-during-script error: {e}")
        # best-effort: try to get back to watch screen so resume works
        try:
            WebDriverWait(driver, 15).until(EC.element_to_be_clickable(
                (AppiumBy.ID, "com.view.ytrabbit:id/textView4df")
            )).click()
            logger.log(f"[{udid}] ✓ Watch screen re-entered after error.")
        except Exception:
            pass
    finally:
        pause_event.clear()
        logger.log(f"[{udid}] ▶ Pause cleared — main job resuming on {udid}.")


# ── During-Script Campaign Runner ─────────────────────────────────────

def run_add_campaign_during_script(
    current_threads, current_drivers, current_pause_events, current_paused_ack_events,
    view_quantity, watch_seconds, random_behavior,
    min_startime, max_startime, min_watchtime, max_watchtime
):
    """
    Add campaigns to all running emulators one by one, in emulator-ID order,
    while the main script keeps running uninterrupted on the others.

    Flow per emulator:
      - pause watch_video on that emulator
      - add all available campaign slots (up to MAX_CAMPAIGNS_PER_EMULATOR)
        using the already-connected driver
      - resume watch_video
      - move to next emulator
    """
    load_dotenv()

    # ── get running emulators in sorted order ──
    running_udids = sorted([
        udid for udid, t in current_threads.items() if t.is_alive()
    ])

    if not running_udids:
        logger.log("✗ No running emulators found.")
        return False, "✗ No running emulators found."

    logger.log(f"→ Campaign-during-script: processing {len(running_udids)} emulator(s) "
               f"in order: {running_udids}")

    # ── read pending links once up front ──
    pending = read_campaign_links()
    if not pending:
        return False, "✗ No pending links found in campaign_link.txt."

    # ── assume worst case: every emulator could have up to MAX slots free.
    #    The real slot count is checked live inside add_campaign_on_running_emulator
    #    AFTER the pause is confirmed and the driver is safely idle — that is
    #    the only correct time to navigate the app for a slot count.
    #    Here we just assign MAX_CAMPAIGNS_PER_EMULATOR links per emulator so
    #    distribute_links() hands out candidates; the live check will trim extras.
    available_slots_map = {}
    for udid in running_udids:
        driver = current_drivers.get(udid)
        if driver is None:
            logger.log(f"[{udid}] ⚠ No driver found — will be skipped.")
            available_slots_map[udid] = 0
        else:
            available_slots_map[udid] = MAX_CAMPAIGNS_PER_EMULATOR

    total_available = sum(available_slots_map.values())
    if total_available == 0:
        logger.log("✗ No drivers available.")
        return False, "✗ No drivers available."

    logger.log(f"→ Distributing up to {MAX_CAMPAIGNS_PER_EMULATOR} link(s) per emulator "
               f"across {len(running_udids)} emulator(s). Actual slot count checked live per emulator.")

    # ── distribute pending links across emulators ──
    distribution = distribute_links(pending, available_slots_map)

    if not distribution:
        logger.log("✗ No links to distribute.")
        return False, "✗ No links to distribute."

    # ── process each emulator one by one ──
    for i, (udid, assigned_links) in enumerate(distribution.items()):
        driver      = current_drivers.get(udid)
        pause_event = current_pause_events.get(udid)

        if driver is None:
            logger.log(f"[{udid}] ⚠ Driver not available — skipping.")
            continue

        logger.log(f"→ [{i + 1}/{len(distribution)}] Adding campaign to {udid} "
                   f"(up to {len(assigned_links)} link(s)) | others keep running...")

        paused_ack = current_paused_ack_events.get(udid)
        add_campaign_on_running_emulator(
            udid, driver, pause_event, paused_ack, assigned_links,
            view_quantity, watch_seconds, random_behavior,
            min_startime, max_startime, min_watchtime, max_watchtime
        )

        logger.log(f"✓ [{i + 1}/{len(distribution)}] Done with {udid}.")

    logger.log("✓ Campaign-during-script completed for all emulators.")
    return True, "✓ Campaign-during-script completed for all emulators."


# ── Main Campaign Runner (original standalone flow) ───────────────────

def run_add_campaign(view_quantity, watch_seconds, random_behavior, min_startime, max_startime, min_watchtime, max_watchtime):
    load_dotenv()
    webdriver_url = os.getenv("WEBDRIVER_URL")

    if not webdriver_url:
        logger.log("✗ WEBDRIVER_URL not set in .env file.")
        return False, "✗ WEBDRIVER_URL not set in .env file."

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
    logger.log("→ Checking occupied campaign slots on each emulator...")
    available_slots_map = {}
    emulator_map = {udid: sys_port for udid, sys_port in emulators}

    for udid, sys_port in emulators:
        tmp_driver = None
        try:
            tmp_driver = webdriver.Remote(webdriver_url, options=build_options(udid, sys_port))
            pkg = os.getenv("APP_PACKAGE")
            tmp_driver.activate_app(pkg)
            time.sleep(5)

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

            # ── always navigate back to main screen after checking ──
            try:
                wait_tmp.until(EC.element_to_be_clickable(
                    (AppiumBy.ID, "com.view.ytrabbit:id/btn_backse")
                )).click()
                logger.log(f"[{udid}] ✓ Navigated back to main screen.")
            except Exception as back_err:
                logger.log(f"[{udid}] ⚠ Could not click back button: {back_err}")

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
    if len(pending) > total_available:
        logger.log(f"⚠ {len(pending)} pending links but only {total_available} free slot(s). "
                   f"Extra links will be ignored.")

    # ── distribute pending links based on actual available slots ──
    distribution = distribute_links(pending, available_slots_map)

    if not distribution:
        logger.log("✗ No links to distribute.")
        return False, "✗ No links to distribute."

    # ── run emulators one by one (sequential) ──
    for i, (udid, assigned_links) in enumerate(distribution.items()):
        sys_port = emulator_map[udid]
        logger.log(f"→ [{i + 1}/{len(distribution)}] Running campaign for {udid}...")
        add_campaign_for_emulator(
            udid, sys_port, assigned_links, webdriver_url,
            view_quantity, watch_seconds, random_behavior,
            min_startime, max_startime, min_watchtime, max_watchtime
        )
        logger.log(f"✓ [{i + 1}/{len(distribution)}] Done with {udid}.")

    logger.log("✓ Add Campaign completed for all emulators.")
    return True, "✓ Add Campaign completed for all emulators."
