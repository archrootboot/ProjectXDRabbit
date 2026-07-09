import subprocess
import logger
import menu


def main():
    # ── clear old logs ──
    logger.clear_log()

    # ── open log window in separate CMD ──
    subprocess.Popen(
        'start "XDRabbit Logs" cmd /k python log_window.py',
        shell=True
    )

    # ── start menu in this window ──
    menu.show_menu()


if __name__ == "__main__":
    main()
