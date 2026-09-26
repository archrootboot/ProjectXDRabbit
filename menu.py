import os
import subprocess
import threading
import des_cap
import tools.campaign as campaign
import tools.campaign_status as campaign_status
import tools.extract_thumbs as extract_thumbs
import tools.emulator_watcher as emulator_watcher
import logger

current_threads = {}
current_stop_events = {}
current_drivers = {}
current_pause_events = {}
current_paused_ack_events = {}
appium_process = None

# ── Emulator Watcher state ────────────────────────────────────────────
_watcher_thread: threading.Thread | None = None
_watcher_stop_event: threading.Event | None = None

# ── Script pause state ────────────────────────────────────────────────
_script_paused = False


# ── Options ───────────────────────────────────────────────────────────

def option_one():
    global appium_process

    if appium_process and appium_process.poll() is None:
        print("⚠ Appium is already running.")
        return

    print("\nStarting Appium Core...")
    result = start_appium_windows()
    if result is None:
        print("✗ Appium failed to start.")
        return
    appium_process = result


def option_two():
    global current_threads, current_stop_events, current_drivers, current_pause_events, current_paused_ack_events, _script_paused

    # ── if script is running, toggle pause / resume ───────────────────
    if current_threads:
        running = [udid for udid, t in current_threads.items() if t.is_alive()]
        if running:
            if not _script_paused:
                # ── PAUSE: set pause_event on every running emulator ──
                print("\n⏸ Pausing script on all emulators...")
                for udid in running:
                    pe = current_pause_events.get(udid)
                    if pe is not None:
                        pe.set()
                        logger.log(f"[{udid}] ⏸ Pause requested via menu.")
                _script_paused = True
                print("✓ Script paused. Press 2 again to resume.")
            else:
                # ── RESUME: clear pause_event on every emulator ───────
                print("\n▶ Resuming script on all emulators...")
                for udid in running:
                    pe = current_pause_events.get(udid)
                    if pe is not None:
                        pe.clear()
                        logger.log(f"[{udid}] ▶ Resumed via menu.")
                _script_paused = False
                print("✓ Script resumed.")
            return

    # ── script not started yet — start it ────────────────────────────
    _script_paused = False
    print("\nExecuting The Script...")
    current_threads, current_stop_events, current_drivers, current_pause_events, current_paused_ack_events = des_cap.main_pro()


def option_three():
    if not current_threads:
        print("✗ No script is running.")
        return

    status = des_cap.get_status(current_threads)
    print("\nEmulator Status:")
    for udid, state in status.items():
        icon = "✓" if state == "running" else "✗"
        print(f"  {icon} {udid} → {state}")


def option_four():
    global current_threads, current_stop_events, current_drivers, current_pause_events, current_paused_ack_events

    if not current_threads:
        print("⚠ No script running yet. Use option 2 to start.")
        return

    print("\n→ Scanning for new emulators...")
    new_threads, new_stop_events, new_drivers, new_pause_events, new_paused_ack_events = des_cap.add_new_emulators(
        current_threads,
        current_stop_events,
        current_drivers,
        current_pause_events,
        current_paused_ack_events
    )

    if not new_threads:
        print("⚠ No new emulators found.")
        return

    current_threads.update(new_threads)
    current_stop_events.update(new_stop_events)
    current_drivers.update(new_drivers)
    current_pause_events.update(new_pause_events)
    current_paused_ack_events.update(new_paused_ack_events)

    print(f"✓ Added {len(new_threads)} new emulator(s): {list(new_threads.keys())}")


def option_five():
    if not current_stop_events:
        print("✗ No script is running.")
        return

    option_three()  # show status first

    target = input("\nEnter emulator ID to stop: ").strip()
    des_cap.stop_one(target, current_threads, current_stop_events, current_drivers)


def option_six():
    if not current_stop_events:
        print("✗ No script is running.")
        return

    print("\nStopping all emulators...")
    des_cap.stop_all(current_threads, current_stop_events, current_drivers)


def option_seven():
    """Add Campaign During Script — uses existing drivers, no new connections."""
    if not current_threads:
        print("✗ No script is running. Start the script first (option 2).")
        return

    running = [udid for udid, t in current_threads.items() if t.is_alive()]
    if not running:
        print("✗ No emulators are currently running.")
        return

    print(f"\n→ Add Campaign During Script")
    print(f"  Running emulators ({len(running)}): {sorted(running)}")
    print("  Campaigns will be added one by one in order.")
    print("  All other emulators keep running the main job uninterrupted.\n")

    view_quantity  = input("Enter View Quantity: ").strip()
    watch_seconds  = input("Enter Watch Seconds: ").strip()
    random_input   = input("Enable Random Behavior? (y/n): ").strip().lower()
    random_behavior = random_input in ("y", "yes")

    if random_behavior:
        print("\n→ Go with Random Behavior.")
        min_startime  = input("Enter Min Start Time: ").strip()
        max_startime  = input("Enter Max Start Time: ").strip()
        min_watchtime = input("Enter Min Watch Time: ").strip()
        max_watchtime = input("Enter Max Watch Time: ").strip()
    else:
        min_startime  = None
        max_startime  = None
        min_watchtime = None
        max_watchtime = None

    print("\n→ Running campaign setup in background — main script continues...\n")

    def _run():
        success, message = campaign.run_add_campaign_during_script(
            current_threads=current_threads,
            current_drivers=current_drivers,
            current_pause_events=current_pause_events,
            current_paused_ack_events=current_paused_ack_events,
            view_quantity=view_quantity,
            watch_seconds=watch_seconds,
            random_behavior=random_behavior,
            min_startime=min_startime,
            max_startime=max_startime,
            min_watchtime=min_watchtime,
            max_watchtime=max_watchtime,
        )
        print(f"\n{message}")

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    print("✓ Campaign setup started in background. Check logs for progress.")


def option_eight():
    print("\n→ Add Campaign Setup")

    view_quantity  = input("Enter View Quantity: ").strip()
    watch_seconds  = input("Enter Watch Seconds: ").strip()
    random_input   = input("Enable Random Behavior? (y/n): ").strip().lower()
    random_behavior = random_input in ("y", "yes")

    if random_behavior:
        print("\n→ Go with Random Behavior.")
        min_startime  = input("Enter Min Start Time: ").strip()
        max_startime  = input("Enter Max Start Time: ").strip()
        min_watchtime = input("Enter Min Watch Time: ").strip()
        max_watchtime = input("Enter Max Watch Time: ").strip()
    else:
        min_startime  = None
        max_startime  = None
        min_watchtime = None
        max_watchtime = None

    success, message = campaign.run_add_campaign(
        view_quantity=view_quantity,
        watch_seconds=watch_seconds,
        random_behavior=random_behavior,
        min_startime=min_startime,
        max_startime=max_startime,
        min_watchtime=min_watchtime,
        max_watchtime=max_watchtime
    )
    print(f"\n{message}")


def option_nine():
    print("\n→ Fetching campaign status from all emulators...")
    campaign_status.run_campaign_status()


def option_ten():
    print("→ Scanning for completed campaigns to delete...")
    campaign_status.run_delete_completed()


def option_eleven():
    extract_thumbs.run_extract_thumbs()


def option_twelve():
    """Toggle the background emulator-watcher on or off."""
    global _watcher_thread, _watcher_stop_event

    # ── if watcher is already running, stop it ────────────────────────
    if _watcher_thread is not None and _watcher_thread.is_alive():
        print("\n→ Stopping Emulator Monitor...")
        emulator_watcher.stop_watcher(_watcher_thread, _watcher_stop_event)
        _watcher_thread = None
        _watcher_stop_event = None
        print("✓ Emulator Monitor stopped.")
        return

    # ── require the main script to be running first ───────────────────
    if not current_threads:
        print("✗ No script is running. Start the script first (option 2).")
        return

    import os
    interval = os.getenv("EMULATOR_CHECK_INTERVAL", "30").strip()
    print(f"\n→ Starting Emulator Monitor (polling every {interval}s)...")

    _watcher_stop_event = threading.Event()
    _watcher_thread = emulator_watcher.start_watcher(
        current_threads,
        current_stop_events,
        current_drivers,
        current_pause_events,
        current_paused_ack_events,
        _watcher_stop_event,
    )
    print(f"✓ Emulator Monitor started — will auto-detect and launch new emulators every {interval}s.")


def stop_appium():
    global appium_process
    if appium_process and appium_process.poll() is None:
        try:
            print("→ Stopping Appium Core...")
            appium_process.kill()
            appium_process.wait()
            print("✓ Appium Core stopped.")
        except Exception as e:
            print(f"⚠ Error stopping Appium: {e}")
        finally:
            appium_process = None
    else:
        print("⚠ Appium is not running.")


def start_appium_windows(port=4723):
    try:
        print(f"Launching Appium on port {port}...")
        process = subprocess.Popen(
            f"appium -p {port}",
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        print(f"✓ Appium started on port {port} (PID: {process.pid})")
        return process
    except FileNotFoundError:
        print("✗ Appium not found. Run: npm install -g appium")
        return None
    except Exception as e:
        print(f"✗ Failed to start Appium: {e}")
        return None


# ── Menu ──────────────────────────────────────────────────────────────

def show_menu():
    while True:
        # ── build the dynamic monitor label ──────────────────────────────
        monitor_active = _watcher_thread is not None and _watcher_thread.is_alive()
        monitor_label  = "[ACTIVE ✓]" if monitor_active else "[inactive]"

        # ── build the dynamic script label ───────────────────────────────
        _any_running = current_threads and any(t.is_alive() for t in current_threads.values())
        if _any_running and _script_paused:
            script_label = "[PAUSED ⏸]"
        elif _any_running:
            script_label = "[RUNNING ▶]"
        else:
            script_label = "[inactive]"

        print("\n 🤖  Appium CLI Controller")
        print("1.  Start Appium Core")
        print(f"2.  Run Script            {script_label}")
        print("3.  Check Status")
        print("4.  Add New Emulators")
        print("5.  Stop Specific Emulator")
        print("6.  Stop All Emulators")
        print("7.  Add Campaign During Script")
        print("8.  Add Campaign")
        print("9.  Campaign Status")
        print("10. Delete Complete Campaigns")
        print("11. Extract Thumbnails")
        print(f"12. Emulator Monitor  {monitor_label}")
        print("13. Exit")

        choice = input("Enter your choice (1-13): ").strip()

        if choice == "1":
            option_one()
        elif choice == "2":
            option_two()
        elif choice == "3":
            option_three()
        elif choice == "4":
            option_four()
        elif choice == "5":
            option_five()
        elif choice == "6":
            option_six()
        elif choice == "7":
            option_seven()
        elif choice == "8":
            option_eight()
        elif choice == "9":
            option_nine()
        elif choice == "10":
            option_ten()
        elif choice == "11":
            option_eleven()
        elif choice == "12":
            option_twelve()
        elif choice == "13":
            if current_threads:
                running = [udid for udid, t in current_threads.items() if t.is_alive()]
                if running:
                    print(f"⚠ These are still running: {running}")
                    confirm = input("Stop all and exit? (y/n): ").strip().lower()
                    if confirm == "y":
                        if _watcher_thread and _watcher_thread.is_alive():
                            emulator_watcher.stop_watcher(_watcher_thread, _watcher_stop_event)
                        des_cap.stop_all(current_threads, current_stop_events, current_drivers)
                    else:
                        continue
            else:
                if _watcher_thread and _watcher_thread.is_alive():
                    emulator_watcher.stop_watcher(_watcher_thread, _watcher_stop_event)
            stop_appium()
            print("Exiting program. Goodbye!")
            break
        else:
            print("Invalid selection. Please try again (1-13).")


if __name__ == "__main__":
    show_menu()
