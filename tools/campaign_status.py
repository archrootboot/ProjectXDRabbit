"""
tools/campaign_status.py
────────────────────────
Campaign status checker and completed-campaign deleter — pure ADB version.
No Appium, no WebDriver.
"""

import os
import threading
import time

import tools.adb_controller as adb
import tools.grabber as grabber
import logger
from dotenv import load_dotenv

# ── Constants ─────────────────────────────────────────────────────────

MAX_CAMPAIGNS = 3

# Resource IDs
_RES_BTN_BACKS    = "com.view.ytrabbit:id/btn_backs"
_RES_MY_CAMPAIGN  = "com.view.ytrabbit:id/textView7"
_RES_TIME         = "com.view.ytrabbit:id/textView_time"
_RES_DONE         = "com.view.ytrabbit:id/textView_done"
_RES_MIN          = "com.view.ytrabbit:id/textView_min"
_RES_MAX          = "com.view.ytrabbit:id/textView_max"
_RES_BTN_BACKSE   = "com.view.ytrabbit:id/btn_backse"
_RES_OK_BTN       = "android:id/button1"


# ── Scrape Campaign Items ─────────────────────────────────────────────

def scrape_campaign_items(udid):
    """
    Probe campaign slots [1]→[MAX_CAMPAIGNS] from the current UI dump.

    A slot is considered empty when textView_time returns nothing.
    Returns a list of campaign dicts.
    """
    root = adb.dump_ui(udid)
    if root is None:
        logger.log(f"[{udid}] ⚠ Could not dump UI for campaign scrape.")
        return []

    campaigns = []

    for index in range(1, MAX_CAMPAIGNS + 1):
        time_el = adb.find_nth_element(root, _RES_TIME, index)
        if time_el is None:
            logger.log(f"[{udid}] → Slot [{index}] empty — stopping.")
            break

        watch_text = time_el.attrib.get("text", "").strip()
        if not watch_text:
            logger.log(f"[{udid}] → Slot [{index}] empty — stopping.")
            break

        # Watch seconds
        watch_seconds = 0
        try:
            watch_seconds = int(watch_text)
        except ValueError:
            pass

        # Views done / total
        views_done  = 0
        views_total = 0
        try:
            min_el = adb.find_nth_element(root, _RES_MIN, index)
            if min_el is not None:
                views_done = int(min_el.attrib.get("text", "0").strip())
        except ValueError:
            pass
        try:
            max_el = adb.find_nth_element(root, _RES_MAX, index)
            if max_el is not None:
                views_total = int(max_el.attrib.get("text", "0").strip())
        except ValueError:
            pass

        # Status / completion time
        done_el     = adb.find_nth_element(root, _RES_DONE, index)
        status_text = done_el.attrib.get("text", "").strip() if done_el is not None else ""
        complete_time = ""
        if "complete:" in status_text:
            complete_time = status_text.split("complete:", 1)[1].strip()

        is_complete = bool(complete_time)

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


# ── Navigate to My Campaign ───────────────────────────────────────────

def _navigate_to_my_campaign(udid, timeout=30):
    """Navigate from any screen to the My Campaign list."""
    pkg      = os.getenv("APP_PACKAGE")
    activity = os.getenv("APP_MAIN_ACTIVITY")
    adb.start_app(udid, pkg, activity)
    time.sleep(5)

    logger.log(f"[{udid}] → Opening My Campaign screen...")
    adb.click_by_id(udid, _RES_MY_CAMPAIGN, timeout=timeout)
    time.sleep(2)


# ── Check Campaigns For One Emulator ─────────────────────────────────

def check_campaigns_for_emulator(udid, results, results_lock):
    try:
        logger.log(f"[{udid}] → Starting campaign status check...")
        _navigate_to_my_campaign(udid)

        campaigns = scrape_campaign_items(udid)
        logger.log(f"[{udid}] ✓ Found {len(campaigns)} campaign(s)")

        with results_lock:
            results[udid] = campaigns

        # Navigate back to main screen
        adb.click_by_id(udid, _RES_BTN_BACKSE, timeout=20)
        logger.log(f"[{udid}] ✓ Navigated back to main screen.")

    except Exception as e:
        logger.log(f"[{udid}] ✗ Status check error: {e}")
        with results_lock:
            results[udid] = []


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


# ── Main Entry for Status ─────────────────────────────────────────────

def run_campaign_status():
    load_dotenv()

    emulators = grabber.get_emulator_list()
    if not emulators:
        print("✗ No emulators found. Aborting.")
        return

    print(f"\n→ Checking campaigns on {len(emulators)} emulator(s)...")

    results      = {}
    results_lock = threading.Lock()
    threads      = []

    for i, (udid, _) in enumerate(emulators):
        t = threading.Thread(
            target=check_campaigns_for_emulator,
            args=(udid, results, results_lock)
        )
        threads.append(t)
        t.start()

        if i < len(emulators) - 1:
            time.sleep(5)

    for t in threads:
        t.join()

    print_report(results)


# ── Delete Completed Campaigns (standalone) ───────────────────────────

def delete_completed_for_emulator(udid):
    """
    Connect to a device, navigate to My Campaign, delete all completed slots.
    Returns the number deleted.
    """
    try:
        logger.log(f"[{udid}] → Connecting to delete completed campaigns...")
        _navigate_to_my_campaign(udid)
        deleted = _delete_completed_slots(udid)

        # Navigate back
        try:
            adb.click_by_id(udid, _RES_BTN_BACKSE, timeout=20)
            logger.log(f"[{udid}] ✓ Navigated back to main screen.")
        except Exception as back_err:
            logger.log(f"[{udid}] ⚠ Could not click back button: {back_err}")

        return deleted

    except Exception as e:
        logger.log(f"[{udid}] ✗ Delete error: {e}")
        return 0


# ── Delete Completed Slots (shared core logic) ────────────────────────

def _delete_completed_slots(udid):
    """
    Probe all slots, re-checking after each delete (list shifts after deletion).
    Stays on My Campaign screen when done.
    Returns the number of deleted slots.
    """
    deleted = 0

    for _pass in range(MAX_CAMPAIGNS):
        found_completed = False

        # Re-dump after each delete since the list shifts
        root = adb.dump_ui(udid)
        if root is None:
            break

        for index in range(1, MAX_CAMPAIGNS + 1):
            done_el = adb.find_nth_element(root, _RES_DONE, index)
            if done_el is None:
                break  # slot doesn't exist

            done_text     = done_el.attrib.get("text", "").strip()
            complete_time = ""
            if "complete:" in done_text:
                complete_time = done_text.split("complete:", 1)[1].strip()

            if not complete_time:
                logger.log(f"[{udid}] → Slot [{index}] in-progress — skipping.")
                continue

            # Completed → click textView_time to trigger delete dialog
            try:
                time_el = adb.find_nth_element(root, _RES_TIME, index)
                if time_el is None:
                    continue
                adb.tap_element(udid, time_el)

                # Confirm deletion
                adb.click_by_id(udid, _RES_OK_BTN, timeout=15)
                logger.log(f"[{udid}] ✓ Slot [{index}] deleted "
                           f"(completed at {complete_time}).")

                deleted += 1
                found_completed = True
                time.sleep(1)
                break  # restart pass from slot [1] after list shifts

            except Exception as click_err:
                logger.log(f"[{udid}] ⚠ Could not delete slot [{index}]: {click_err}")

        if not found_completed:
            break

    if deleted == 0:
        logger.log(f"[{udid}] → No completed campaigns to delete.")
    else:
        logger.log(f"[{udid}] ✓ Deleted {deleted} completed campaign(s).")

    return deleted


# ── Delete Completed On Running Device (during-script) ────────────────

def delete_completed_on_device(udid):
    """
    Delete all completed campaign slots on a device that is currently idle
    (paused by the campaign flow).  Navigates: btn_backs → textView7.

    Returns the number of deleted slots.
    Stays on My Campaign screen after deletion.
    """
    # Go to main screen first
    logger.log(f"[{udid}] → Clicking Back to main screen...")
    try:
        adb.click_by_id(udid, _RES_BTN_BACKS, timeout=20)
        logger.log(f"[{udid}] ✓ Main screen reached.")
        time.sleep(2)
    except Exception as e:
        logger.log(f"[{udid}] ⚠ Could not click btn_backs: {e}")

    # Navigate to My Campaign
    logger.log(f"[{udid}] → Opening My Campaign for delete check...")
    adb.click_by_id(udid, _RES_MY_CAMPAIGN, timeout=20)
    time.sleep(2)

    return _delete_completed_slots(udid)
    # stays on My Campaign screen — caller proceeds to slot check


# ── Main Entry for Delete ─────────────────────────────────────────────

def run_delete_completed():
    load_dotenv()

    emulators = grabber.get_emulator_list()
    if not emulators:
        print("✗ No emulators found. Aborting.")
        return

    print(f"\n→ Deleting completed campaigns on {len(emulators)} emulator(s)...")

    grand_total = 0

    for udid, _ in emulators:
        deleted = delete_completed_for_emulator(udid)
        grand_total += deleted
        print(f"  {'✓' if deleted > 0 else '→'} {udid}: {deleted} deleted")

    print(f"\n  Total deleted across all emulators: {grand_total}")
