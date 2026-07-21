from appium import webdriver
from appium.options.android import UiAutomator2Options
from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import threading
import time
import os
import tools.grabber as grabber
import logger
from dotenv import load_dotenv


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
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


# ── Constants ─────────────────────────────────────────────────────────

MAX_CAMPAIGNS = 3
RECYCLER_ID   = "com.view.ytrabbit:id/recyclerView_list"


# ── Scrape Campaign Items ─────────────────────────────────────────────

def _get_indexed_text(driver, resource_id, index):
    """
    Read text from the nth element (1-based) matching a resource-id.
    Uses XPath index so each slot maps to the correct row.
    Returns empty string on any failure.
    """
    xpath = f'(//android.widget.TextView[@resource-id="{resource_id}"])[{index}]'
    try:
        el = driver.find_element(AppiumBy.XPATH, xpath)
        return el.text.strip()
    except Exception:
        return ""


def scrape_campaign_items(driver, udid):
    """
    Probe slots [1]→[3] using exact resource-IDs found via Appium Inspector:

      textView_done  → status / completion timestamp
      textView_time  → watch seconds value  (e.g. "65")
      textView_min   → views done           (e.g. "20")
      textView_max   → views total          (e.g. "20")

    A slot is considered empty when textView_time returns nothing for that index.
    Availability = MAX_CAMPAIGNS − filled slots.
    """
    wait = WebDriverWait(driver, 20)
    campaigns = []

    # ── Wait for the recycler to appear ──────────────────────────
    try:
        wait.until(EC.presence_of_element_located(
            (AppiumBy.ID, RECYCLER_ID)
        ))
    except Exception:
        logger.log(f"[{udid}] ⚠ recyclerView_list not found — no campaigns.")
        return campaigns

    # ── Probe each slot ───────────────────────────────────────────
    for index in range(1, MAX_CAMPAIGNS + 1):

        # textView_time is always present when a slot is occupied;
        # use it as the existence check
        watch_text = _get_indexed_text(driver, "com.view.ytrabbit:id/textView_time", index)
        if not watch_text:
            logger.log(f"[{udid}] → Slot [{index}] empty — stopping.")
            break

        # ── Watch seconds ─────────────────────────────────────────
        watch_seconds = 0
        try:
            watch_seconds = int(watch_text)
        except ValueError:
            pass

        # ── Views done / total ────────────────────────────────────
        views_done  = 0
        views_total = 0
        try:
            views_done  = int(_get_indexed_text(driver, "com.view.ytrabbit:id/textView_min", index))
        except ValueError:
            pass
        try:
            views_total = int(_get_indexed_text(driver, "com.view.ytrabbit:id/textView_max", index))
        except ValueError:
            pass

        # ── Status / completion time ──────────────────────────────
        # textView_done holds e.g. "complete:2026-07-20 22:00:45 (UTC)"
        # or just "complete" for in-progress items
        status_text   = _get_indexed_text(driver, "com.view.ytrabbit:id/textView_done", index)
        is_complete   = "complete" in status_text.lower()
        complete_time = ""
        if is_complete and "complete:" in status_text:
            try:
                complete_time = status_text.split("complete:")[1].strip()
            except Exception:
                pass

        campaigns.append({
            "slot":          index,
            "status":        "complete" if is_complete else "in-progress",
            "complete_time": complete_time,
            "watch_seconds": watch_seconds,
            "views_done":    views_done,
            "views_total":   views_total,
        })
        logger.log(
            f"[{udid}] ✓ Slot [{index}] — "
            f"views: {views_done}/{views_total}, "
            f"watch: {watch_seconds}s, "
            f"status: {status_text[:40]}"
        )

    return campaigns


# ── Scrape One Emulator ───────────────────────────────────────────────

def check_campaigns_for_emulator(udid, system_port, webdriver_url, results, results_lock):
    driver = None
    try:
        logger.log(f"[{udid}] → Connecting for campaign status check...")
        driver = webdriver.Remote(webdriver_url, options=build_options(udid, system_port))

        pkg = os.getenv("APP_PACKAGE")
        driver.activate_app(pkg)
        wait_for_app_foreground(driver, udid, timeout=30)

        wait = WebDriverWait(driver, 30)

        # ── Navigate to My Campaign ───────────────────────────────
        logger.log(f"[{udid}] → Opening My Campaign screen...")
        my_campaign = wait.until(EC.element_to_be_clickable(
            (AppiumBy.ID, "com.view.ytrabbit:id/textView7")
        ))
        my_campaign.click()
        time.sleep(2)

        # ── Scrape campaign list ──────────────────────────────────
        campaigns = scrape_campaign_items(driver, udid)
        logger.log(f"[{udid}] ✓ Found {len(campaigns)} campaign(s)")

        with results_lock:
            results[udid] = campaigns

    except Exception as e:
        logger.log(f"[{udid}] ✗ Status check error: {e}")
        with results_lock:
            results[udid] = []
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass


# ── Print Report ──────────────────────────────────────────────────────

def print_report(results):
    divider   = "=" * 62
    thin_line = "-" * 62

    print(f"\n{divider}")
    print("  📊  Campaign Status Report")
    print(divider)

    grand_total_campaigns  = 0
    grand_total_completed  = 0
    grand_total_views_done = 0
    grand_total_views_max  = 0
    grand_total_available  = 0

    for udid, campaigns in results.items():
        completed        = [c for c in campaigns if c["status"] == "complete"]
        in_progress      = [c for c in campaigns if c["status"] == "in-progress"]
        slots_used       = len(campaigns)
        slots_avail      = MAX_CAMPAIGNS - slots_used
        total_views_done = sum(c["views_done"]  for c in campaigns)
        total_views_max  = sum(c["views_total"] for c in campaigns)

        avail_label = f"✓ {slots_avail} available" if slots_avail > 0 else "✗ FULL"
        print(f"\n  🤖  Emulator : {udid}")
        print(f"  Slots       : {slots_used}/{MAX_CAMPAIGNS} used  ({avail_label})")
        print(thin_line)

        if not campaigns:
            print("  ⚠  No campaigns found — all slots free.")
        else:
            for c in campaigns:
                icon         = "✓" if c["status"] == "complete" else "⏳"
                status_label = "Complete" if c["status"] == "complete" else "In Progress"
                print(f"  {icon} [Slot {c['slot']}] {status_label}")
                if c["complete_time"]:
                    print(f"          Completed at : {c['complete_time']}")
                print(f"          Watch Seconds: {c['watch_seconds']}s")
                print(f"          Views        : {c['views_done']}/{c['views_total']}")

            print(thin_line)
            print(f"  Campaigns   : {slots_used}  |  Done: {len(completed)}  |  Running: {len(in_progress)}")
            print(f"  Total Views : {total_views_done}/{total_views_max}")

        grand_total_campaigns  += slots_used
        grand_total_completed  += len(completed)
        grand_total_views_done += total_views_done
        grand_total_views_max  += total_views_max
        grand_total_available  += slots_avail

    # ── Grand Summary ─────────────────────────────────────────────
    total_emulators = len(results)
    total_slots     = total_emulators * MAX_CAMPAIGNS

    print(f"\n{divider}")
    print("  📋  Grand Summary (All Emulators)")
    print(thin_line)
    print(f"  Emulators         : {total_emulators}")
    print(f"  Total Slots       : {total_slots}  ({grand_total_campaigns} used, {grand_total_available} available)")
    print(f"  Campaigns Done    : {grand_total_completed}/{grand_total_campaigns}")
    print(f"  In Progress       : {grand_total_campaigns - grand_total_completed}")
    print(f"  Total Views       : {grand_total_views_done}/{grand_total_views_max}")
    print(divider)


# ── Main Entry ────────────────────────────────────────────────────────

def run_campaign_status():
    load_dotenv()
    webdriver_url = os.getenv("WEBDRIVER_URL")

    if not webdriver_url:
        print("✗ WEBDRIVER_URL not set in .env file.")
        return

    emulators = grabber.get_emulator_list()
    if not emulators:
        print("✗ No emulators found. Aborting.")
        return

    print(f"\n→ Checking campaigns on {len(emulators)} emulator(s)...")

    results      = {}
    results_lock = threading.Lock()
    threads      = []

    for i, (udid, sys_port) in enumerate(emulators):
        t = threading.Thread(
            target=check_campaigns_for_emulator,
            args=(udid, sys_port, webdriver_url, results, results_lock)
        )
        threads.append(t)
        t.start()

        if i < len(emulators) - 1:
            time.sleep(5)  # stagger connections

    for t in threads:
        t.join()

    print_report(results)
