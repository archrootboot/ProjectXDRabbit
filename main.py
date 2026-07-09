import threading
import subprocess
import logger
import log_window
import menu


def main():
    # ── start log window in separate CMD ──
    log_thread = threading.Thread(
        target=log_window.show_logs,
        daemon=True
    )

    # ── open new CMD window for logs ──
    subprocess.Popen(
        'start "XDRabbit Logs" cmd /k python log_window.py',
        shell=True
    )

    # ── start menu in this window ──
    menu.show_menu()


if __name__ == "__main__":
    main()
