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


# ── Scrape One Campaign Item ──────────────────────────────────────────

def scrape_campaign_items(driver, udid):
    """
    Scrape all campaign rows visible in the My Campaign screen.
    Returns a list of dicts with keys: status, watch_seconds, views, views_total
    """
    wait = WebDriverWait(driver, 20)
    campaigns = []

    try:
        # Wait for at least one campaign row to appear
        wait.until(EC.presence_of_element_located(
            (AppiumBy.ID, "com.view.ytrabbit:id/textView_view_count")
        ))
    except Exception:
        logger.log(f"[{udid}] ⚠ No campaign rows found on screen.")
        return campaigns

    # ── Scroll and collect all items ─────────────────────────────────
    seen_texts = set()
    max_scrolls = 10
    scroll_attempts = 0

    while scroll_attempts < max_scrolls:
        try:
            # Find all view-count elements currently visible
            view_count_els = driver.find_elements(
                AppiumBy.ID, "com.view.ytrabbit:id/textView_view_count"
            )
            status_els = driver.find_elements(
                AppiumBy.ID, "com.view.ytrabbit:id/textView_status"
            )
            watch_sec_els = driver.find_elements(
                AppiumBy.ID, "com.view.ytrabbit:id/textView_watch_sec"
            )

            new_items_found = False

            for i in range(len(view_count_els)):
                try:
                    view_text  = view_count_els[i].text.strip()   # e.g. "21/20 View" or "0/10 View"
                    status_text = status_els[i].text.strip()       # e.g. "complete:2026-07-20 22:00:45 (UTC)" or "complete"
                    watch_text  = watch_sec_els[i].text.strip()    # e.g. "Watch Seconds:65"

                    # Use view_text + status as a unique key to avoid duplicates
                    item_key = f"{status_text}|{view_text}|{watch_text}"
                    if item_key in seen_texts:
                        continue

                    seen_texts.add(item_key)
                    new_items_found = True

                    # ── Parse view count ──────────────────────────
                    views_done  = 0
                    views_total = 0
                    try:
                        # "21/20 View" → split on space, take first token, split on /
                        count_part = view_text.split(" ")[0]  # "21/20"
                        parts = count_part.split("/")
                        views_done  = int(parts[0])
                        views_total = int(parts[1])
                    except Exception:
                        pass

                    # ── Parse watch seconds ───────────────────────
                    watch_seconds = 0
                    try:
                        # "Watch Seconds:65" → split on colon
                        watch_seconds = int(watch_text.split(":")[1].strip())
                    except Exception:
                        pass

                    # ── Parse completion status ───────────────────
                    is_complete   = "complete" in status_text.lower()
                    complete_time = ""
                    if is_complete and ":" in status_text:
                        # "complete:2026-07-20 22:00:45 (UTC)"
                        try:
                            complete_time = status_text.split("complete:")[1].strip()
                        except Exception:
                            complete_time = ""

                    campaigns.append({
                        "status":        "complete" if is_complete else "in-progress",
                        "complete_time": complete_time,
                        "watch_seconds": watch_seconds,
                        "views_done":    views_done,
                        "views_total":   views_total,
                        "raw_view":      view_text,
                    })

                except Exception as item_err:
                    logger.log(f"[{udid}] ⚠ Error parsing item {i}: {item_err}")
                    continue

            if not new_items_found:
                break  # No new rows after scroll → we're done

            # ── Scroll down to reveal more items ──────────────────
            screen_size = driver.get_window_size()
            start_y = int(screen_size["height"] * 0.75)
            end_y   = int(screen_size["height"] * 0.25)
            mid_x   = int(screen_size["width"]  * 0.5)

            driver.swipe(mid_x, start_y, mid_x, end_y, duration=600)
            time.sleep(1)
            scroll_attempts += 1

        except Exception as scroll_err:
            logger.log(f"[{udid}] ⚠ Scroll error: {scroll_err}")
            break

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
    divider     = "=" * 62
    thin_line   = "-" * 62

    print(f"\n{divider}")
    print("  📊  Campaign Status Report")
    print(divider)

    grand_total_campaigns  = 0
    grand_total_completed  = 0
    grand_total_views_done = 0
    grand_total_views_max  = 0

    for udid, campaigns in results.items():
        completed   = [c for c in campaigns if c["status"] == "complete"]
        in_progress = [c for c in campaigns if c["status"] == "in-progress"]
        total_views_done = sum(c["views_done"]  for c in campaigns)
        total_views_max  = sum(c["views_total"] for c in campaigns)

        print(f"\n  🤖  Emulator: {udid}")
        print(thin_line)

        if not campaigns:
            print("  ⚠  No campaigns found.")
        else:
            for i, c in enumerate(campaigns, 1):
                icon = "✓" if c["status"] == "complete" else "⏳"
                status_label = "Complete" if c["status"] == "complete" else "In Progress"
                print(f"  {icon} [{i}] {status_label}")
                if c["complete_time"]:
                    print(f"       Completed at : {c['complete_time']}")
                print(f"       Watch Seconds: {c['watch_seconds']}s")
                print(f"       Views        : {c['views_done']}/{c['views_total']}")

            print(thin_line)
            print(f"  Total Campaigns : {len(campaigns)}")
            print(f"  Completed       : {len(completed)}/{len(campaigns)}")
            print(f"  In Progress     : {len(in_progress)}")
            print(f"  Total Views     : {total_views_done}/{total_views_max}")

        grand_total_campaigns  += len(campaigns)
        grand_total_completed  += len(completed)
        grand_total_views_done += total_views_done
        grand_total_views_max  += total_views_max

    # ── Grand Summary ─────────────────────────────────────────────
    print(f"\n{divider}")
    print("  📋  Grand Summary (All Emulators)")
    print(thin_line)
    print(f"  Emulators Checked : {len(results)}")
    print(f"  Total Campaigns   : {grand_total_campaigns}")
    print(f"  Completed         : {grand_total_completed}/{grand_total_campaigns}")
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
