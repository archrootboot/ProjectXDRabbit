import os
import subprocess
import threading
import des_cap
import tools.campaign as campaign
import tools.campaign_status as campaign_status
import tools.extract_thumbs as extract_thumbs
import logger

current_threads = {}
current_stop_events = {}
current_drivers = {}
current_pause_events = {}
current_paused_ack_events = {}
appium_process = None


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
    global current_threads, current_stop_events, current_drivers, current_pause_events, current_paused_ack_events

    if current_threads:
        running = [udid for udid, t in current_threads.items() if t.is_alive()]
        if running:
            print(f"✗ Script already running on: {running}")
            print("Stop it first before starting again.")
            return

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
        print("\n 🤖  Appium CLI Controller")
        print("1.  Start Appium Core")
        print("2.  Run Script")
        print("3.  Check Status")
        print("4.  Add New Emulators")
        print("5.  Stop Specific Emulator")
        print("6.  Stop All Emulators")
        print("7.  Add Campaign During Script")
        print("8.  Add Campaign")
        print("9.  Campaign Status")
        print("10. Delete Complete Campaigns")
        print("11. Extract Thumbnails")
        print("12. Exit")

        choice = input("Enter your choice (1-12): ").strip()

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
            if current_threads:
                running = [udid for udid, t in current_threads.items() if t.is_alive()]
                if running:
                    print(f"⚠ These are still running: {running}")
                    confirm = input("Stop all and exit? (y/n): ").strip().lower()
                    if confirm == "y":
                        des_cap.stop_all(current_threads, current_stop_events, current_drivers)
                    else:
                        continue
            stop_appium()
            print("Exiting program. Goodbye!")
            break
        else:
            print("Invalid selection. Please try again (1-12).")


if __name__ == "__main__":
    show_menu()
