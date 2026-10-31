"""
tools/campaign.py
─────────────────
Campaign management — pure ADB version (no Appium).

All UI interactions use adb_controller (XML dump → tap by coordinate).
"""

import os
import threading
import time

import tools.adb_controller as adb
import tools.grabber as grabber
import tools.campaign_status as campaign_status
import logger
from dotenv import load_dotenv

CAMPAIGN_FILE            = "campaign_link.txt"
MAX_CAMPAIGNS_PER_EMULATOR = 3

# ── File-level lock — prevents concurrent read-modify-write ──────────
_campaign_file_lock = threading.Lock()

# ── Resource IDs ──────────────────────────────────────────────────────
_RES_BTN_BACKS    = "com.view.ytrabbit:id/btn_backs"
_RES_MY_CAMPAIGN  = "com.view.ytrabbit:id/textView7"
_RES_EDIT_TEXT    = "com.view.ytrabbit:id/editText"
_RES_ADD_BTN      = "com.view.ytrabbit:id/button"
_RES_VIEW_QTY     = "com.view.ytrabbit:id/textView_view"
_RES_WATCH_SEC    = "com.view.ytrabbit:id/textView_sec"
_RES_RANDOM_SW    = "com.view.ytrabbit:id/switch_random"
_RES_MIN_START    = "com.view.ytrabbit:id/textView_min_start"
_RES_MAX_START    = "com.view.ytrabbit:id/textView_max_start"
_RES_MIN_WATCH    = "com.view.ytrabbit:id/textView_min_watch"
_RES_MAX_WATCH    = "com.view.ytrabbit:id/textView_max_watch"
_RES_OK_BTN       = "android:id/button1"
_RES_TIME         = "com.view.ytrabbit:id/textView_time"
_RES_BTN_BACKSE   = "com.view.ytrabbit:id/btn_backse"
_RES_WATCH_SCREEN = "com.view.ytrabbit:id/textView4df"


# ── Read Links ────────────────────────────────────────────────────────

def read_campaign_links():
    """
    Returns a list of (link, line_index) tuples for lines not yet marked done.
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
            continue
        if stripped.lower().endswith(" done") or stripped.lower() == "done":
            skipped += 1
            continue
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
    """Append ' done' to the line at line_index in campaign_link.txt. Thread-safe."""
    with _campaign_file_lock:
        try:
            with open(CAMPAIGN_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()

            original = lines[line_index].rstrip("\n").rstrip("\r")
            if not original.lower().endswith(" done"):
                lines[line_index] = original + " done\n"

            with open(CAMPAIGN_FILE, "w", encoding="utf-8") as f:
                f.writelines(lines)

            logger.log(f"→ Marked as done in {CAMPAIGN_FILE}: {original.strip()}")
        except Exception as e:
            logger.log(f"⚠ Could not mark link done (line {line_index}): {e}")


# ── Count Occupied Slots ──────────────────────────────────────────────

def count_occupied_slots(udid):
    """
    Count occupied campaign slots by reading textView_time[1..MAX] from the
    current UI dump.  Returns an integer 0–MAX_CAMPAIGNS_PER_EMULATOR.
    """
    root = adb.dump_ui(udid)
    if root is None:
        return 0

    occupied = 0
    for index in range(1, MAX_CAMPAIGNS_PER_EMULATOR + 1):
        el = adb.find_nth_element(root, _RES_TIME, index)
        if el is None:
            break
        text = el.attrib.get("text", "").strip()
        if text:
            occupied += 1
        else:
            break

    logger.log(f"[{udid}] → Occupied slots: {occupied}/{MAX_CAMPAIGNS_PER_EMULATOR}")
    return occupied


# ── Distribute Links ──────────────────────────────────────────────────

def distribute_links(pending, available_slots_map):
    """Distribute pending links across emulators based on available slot counts."""
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


# ── Option Helpers (spinner-based settings) ───────────────────────────

def _spinner_option(udid, trigger_res_id, value):
    """Click a trigger → open spinner → select value → confirm."""
    if not adb.click_by_id(udid, trigger_res_id, timeout=30):
        logger.log(f"[{udid}] ✗ Could not click {trigger_res_id}")
        return False
    time.sleep(3)

    if not adb.select_spinner_value(udid, str(value), timeout=10):
        logger.log(f"[{udid}] ✗ Could not select '{value}' in spinner.")
        return False

    if not adb.click_by_id(udid, _RES_OK_BTN, timeout=10):
        logger.log(f"[{udid}] ✗ Could not click OK button.")
        return False
    return True


def view_quantity_option(udid, value):
    return _spinner_option(udid, _RES_VIEW_QTY, value)


def watch_seconds_option(udid, value):
    return _spinner_option(udid, _RES_WATCH_SEC, value)


def random_behavior_option(udid):
    ok = adb.click_by_id(udid, _RES_RANDOM_SW, timeout=30)
    if ok:
        logger.log(f"[{udid}] ✓ random behavior option clicked...")
    return ok


def min_startime_option(udid, value):
    return _spinner_option(udid, _RES_MIN_START, value)


def max_startime_option(udid, value):
    return _spinner_option(udid, _RES_MAX_START, value)


def min_watchtime_option(udid, value):
    return _spinner_option(udid, _RES_MIN_WATCH, value)


def max_watchtime_option(udid, value):
    return _spinner_option(udid, _RES_MAX_WATCH, value)


# ── Core Campaign UI Work ─────────────────────────────────────────────

def _do_add_campaign(udid, pending_links, view_quantity, watch_seconds,
                     random_behavior, min_startime, max_startime,
                     min_watchtime, max_watchtime,
                     already_on_campaign_screen=False):
    """
    Perform the actual campaign UI steps on a device.
    Used by both standalone and during-script flows.
    """
    pkg = os.getenv("APP_PACKAGE")

    if not already_on_campaign_screen:
        # Open app
        adb.start_app(udid, pkg, os.getenv("APP_MAIN_ACTIVITY"))
        time.sleep(5)

        # Navigate to main screen
        logger.log(f"[{udid}] → Clicking Back to main screen...")
        adb.click_by_id(udid, _RES_BTN_BACKS, timeout=30)
        logger.log(f"[{udid}] ✓ Main screen reached.")
        time.sleep(2)

        # Click My Campaign
        logger.log(f"[{udid}] → Clicking My Campaign...")
        adb.click_by_id(udid, _RES_MY_CAMPAIGN, timeout=30)
        logger.log(f"[{udid}] ✓ My Campaign opened")
        time.sleep(2)

    # Add each link
    for i, (link, line_index) in enumerate(pending_links):
        logger.log(f"[{udid}] → Adding link {i + 1}/{len(pending_links)}: {link}")

        # Clear + type in the input field
        adb.clear_and_type(udid, _RES_EDIT_TEXT, link, timeout=30)
        logger.log(f"[{udid}] ✓ Link entered")

        # Click ADD
        adb.click_by_id(udid, _RES_ADD_BTN, timeout=30)
        logger.log(f"[{udid}] ✓ ADD clicked — waiting for video settings screen...")

        view_quantity_option(udid, str(view_quantity))
        logger.log(f"[{udid}] ✓ view quantity option done...")

        watch_seconds_option(udid, str(watch_seconds))
        logger.log(f"[{udid}] ✓ watch seconds option done...")

        if random_behavior:
            random_behavior_option(udid)
            logger.log(f"[{udid}] ✓ random behavior option done...")

            min_startime_option(udid, str(min_startime))
            logger.log(f"[{udid}] ✓ min start time option done...")

            max_startime_option(udid, str(max_startime))
            logger.log(f"[{udid}] ✓ max start time option done...")

            min_watchtime_option(udid, str(min_watchtime))
            logger.log(f"[{udid}] ✓ min watch time option done...")

            max_watchtime_option(udid, str(max_watchtime))
            logger.log(f"[{udid}] ✓ max watch time option done...")

        # Scroll to and click "Done"
        adb.scroll_to_text(udid, "Done", timeout=15)
        adb.click_by_text(udid, "Done", timeout=10)
        logger.log(f"[{udid}] ✓ All options Done ...")

        time.sleep(3)

        mark_link_done(line_index)
        logger.log(f"[{udid}] ✓ Link {i + 1} added and marked done")

        if i < len(pending_links) - 1:
            time.sleep(2)

    logger.log(f"[{udid}] ✓ All {len(pending_links)} campaign(s) added.")

    # Navigate back to main screen
    adb.click_by_id(udid, _RES_BTN_BACKSE, timeout=30)
    logger.log(f"[{udid}] ✓ Navigated back to main screen.")

    # Re-enter watch screen
    logger.log(f"[{udid}] → Re-entering watch screen...")
    adb.click_by_id(udid, _RES_WATCH_SCREEN, timeout=30)
    logger.log(f"[{udid}] ✓ Watch screen re-entered. Main job can resume.")


# ── Standalone Campaign For One Emulator ─────────────────────────────

def add_campaign_for_emulator(udid, pending_links, view_quantity, watch_seconds,
                               random_behavior, min_startime, max_startime,
                               min_watchtime, max_watchtime):
    """
    Add campaigns for a single emulator (standalone — no existing session).
    Opens the app via ADB directly.
    """
    try:
        logger.log(f"[{udid}] → Starting campaign setup via ADB...")
        _do_add_campaign(
            udid, pending_links,
            view_quantity, watch_seconds, random_behavior,
            min_startime, max_startime, min_watchtime, max_watchtime
        )
    except Exception as e:
        logger.log(f"[{udid}] ✗ Campaign error: {e}")


# ── Campaign On Running Emulator (during-script) ──────────────────────

def add_campaign_on_running_emulator(udid, pause_event, paused_ack,
                                     pending_links, view_quantity, watch_seconds,
                                     random_behavior, min_startime, max_startime,
                                     min_watchtime, max_watchtime):
    """
    Add campaigns to a device that is currently running the watch loop.
    Pauses the watch loop, does campaign work, then resumes.
    """
    logger.log(f"[{udid}] ⏸ Signalling pause — waiting for current video to finish...")
    if paused_ack:
        paused_ack.clear()
    pause_event.set()

    max_wait = int(os.getenv("CAMPAIGN_PAUSE_TIMEOUT", "300"))
    logger.log(f"[{udid}] ⏳ Waiting for watch loop to confirm idle (max {max_wait}s)...")

    if paused_ack:
        confirmed = paused_ack.wait(timeout=max_wait)
        if confirmed:
            logger.log(f"[{udid}] ✓ Watch loop confirmed idle.")
        else:
            logger.log(f"[{udid}] ⚠ Idle confirmation timed out after {max_wait}s. Proceeding anyway.")
    else:
        logger.log(f"[{udid}] ⚠ No paused_ack event — waiting 5s as fallback...")
        time.sleep(5)

    try:
        pkg      = os.getenv("APP_PACKAGE")
        activity = os.getenv("APP_MAIN_ACTIVITY")

        logger.log(f"[{udid}] → Activating app...")
        adb.start_app(udid, pkg, activity)
        time.sleep(3)

        # Delete completed campaigns first to free slots
        logger.log(f"[{udid}] → Checking and deleting completed campaigns...")
        deleted = campaign_status.delete_completed_on_device(udid)
        if deleted > 0:
            logger.log(f"[{udid}] ✓ Freed {deleted} slot(s) by deleting completed campaigns.")
        else:
            logger.log(f"[{udid}] → No completed campaigns found to delete.")

        # Live slot check (already on My Campaign screen after delete)
        occupied  = count_occupied_slots(udid)
        available = MAX_CAMPAIGNS_PER_EMULATOR - occupied

        if available == 0:
            logger.log(f"[{udid}] ✗ All {MAX_CAMPAIGNS_PER_EMULATOR} slots full — skipping.")
            try:
                adb.click_by_id(udid, _RES_BTN_BACKSE, timeout=20)
            except Exception:
                pass
            try:
                adb.click_by_id(udid, _RES_WATCH_SCREEN, timeout=20)
                logger.log(f"[{udid}] ✓ Watch screen re-entered.")
            except Exception as re_err:
                logger.log(f"[{udid}] ⚠ Could not re-enter watch screen: {re_err}")
            return

        links_to_add = pending_links[:available]
        if len(pending_links) > available:
            skipped = len(pending_links) - available
            logger.log(f"[{udid}] ⚠ {available} slot(s) free, "
                       f"{len(pending_links)} link(s) assigned — trimming {skipped} extra.")
        logger.log(f"[{udid}] ✓ {available} slot(s) free — adding {len(links_to_add)} link(s).")

        _do_add_campaign(
            udid, links_to_add,
            view_quantity, watch_seconds, random_behavior,
            min_startime, max_startime, min_watchtime, max_watchtime,
            already_on_campaign_screen=True
        )
        logger.log(f"[{udid}] ✓ Campaign setup complete.")

    except Exception as e:
        logger.log(f"[{udid}] ✗ Campaign-during-script error: {e}")
        try:
            adb.click_by_id(udid, _RES_WATCH_SCREEN, timeout=15)
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
    Add campaigns to all running emulators one by one while the main
    script keeps running on the others.
    """
    load_dotenv()

    running_udids = sorted([
        udid for udid, t in current_threads.items() if t.is_alive()
    ])

    if not running_udids:
        logger.log("✗ No running emulators found.")
        return False, "✗ No running emulators found."

    logger.log(f"→ Campaign-during-script: processing {len(running_udids)} emulator(s) "
               f"in order: {running_udids}")

    pending = read_campaign_links()
    if not pending:
        return False, "✗ No pending links found in campaign_link.txt."

    logger.log(f"→ {len(pending)} pending link(s) will be offered to each emulator.")

    for i, udid in enumerate(running_udids):
        pause_event = current_pause_events.get(udid)
        paused_ack  = current_paused_ack_events.get(udid)

        logger.log(f"→ [{i + 1}/{len(running_udids)}] Processing {udid} "
                   f"| others keep running...")

        add_campaign_on_running_emulator(
            udid, pause_event, paused_ack, pending,
            view_quantity, watch_seconds, random_behavior,
            min_startime, max_startime, min_watchtime, max_watchtime
        )

        pending = read_campaign_links()
        if not pending:
            logger.log("→ No more pending links — stopping early.")
            break

        logger.log(f"✓ [{i + 1}/{len(running_udids)}] Done with {udid}. "
                   f"{len(pending)} pending link(s) remaining.")

    logger.log("✓ Campaign-during-script completed for all emulators.")
    return True, "✓ Campaign-during-script completed for all emulators."


# ── Main Campaign Runner (standalone) ────────────────────────────────

def run_add_campaign(view_quantity, watch_seconds, random_behavior,
                     min_startime, max_startime, min_watchtime, max_watchtime):
    load_dotenv()

    pending = read_campaign_links()
    if not pending:
        return False, "✗ No pending links found in campaign_link.txt."

    emulators = grabber.get_emulator_list()
    if not emulators:
        logger.log("✗ No emulators found. Aborting.")
        return False, "✗ No emulators found."

    # Check occupied slots per emulator
    logger.log("→ Checking occupied campaign slots on each emulator...")
    available_slots_map = {}

    for udid, _ in emulators:
        try:
            pkg      = os.getenv("APP_PACKAGE")
            activity = os.getenv("APP_MAIN_ACTIVITY")

            adb.start_app(udid, pkg, activity)
            time.sleep(5)

            adb.click_by_id(udid, _RES_MY_CAMPAIGN, timeout=20)
            time.sleep(2)

            occupied  = count_occupied_slots(udid)
            available = MAX_CAMPAIGNS_PER_EMULATOR - occupied
            available_slots_map[udid] = available

            if available == 0:
                logger.log(f"[{udid}] ✗ All slots full — will be skipped.")
            else:
                logger.log(f"[{udid}] ✓ {available} slot(s) available.")

            # Navigate back
            try:
                adb.click_by_id(udid, _RES_BTN_BACKSE, timeout=20)
                logger.log(f"[{udid}] ✓ Navigated back to main screen.")
            except Exception as back_err:
                logger.log(f"[{udid}] ⚠ Could not click back button: {back_err}")

        except Exception as e:
            logger.log(f"[{udid}] ⚠ Could not check slots: {e} — skipping.")
            available_slots_map[udid] = 0

    total_available = sum(available_slots_map.values())
    if total_available == 0:
        logger.log("✗ All emulators are full. No slots available.")
        return False, "✗ All emulators are full. No slots available."

    logger.log(f"→ Total available slots across all emulators: {total_available}")
    if len(pending) > total_available:
        logger.log(f"⚠ {len(pending)} pending links but only {total_available} free slot(s). "
                   f"Extra links will be ignored.")

    distribution = distribute_links(pending, available_slots_map)

    if not distribution:
        logger.log("✗ No links to distribute.")
        return False, "✗ No links to distribute."

    for i, (udid, assigned_links) in enumerate(distribution.items()):
        logger.log(f"→ [{i + 1}/{len(distribution)}] Running campaign for {udid}...")
        add_campaign_for_emulator(
            udid, assigned_links,
            view_quantity, watch_seconds, random_behavior,
            min_startime, max_startime, min_watchtime, max_watchtime
        )
        logger.log(f"✓ [{i + 1}/{len(distribution)}] Done with {udid}.")

    logger.log("✓ Add Campaign completed for all emulators.")
    return True, "✓ Add Campaign completed for all emulators."
