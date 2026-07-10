import time
import os
from colorama import init, Fore, Style

# ── Initialize colorama for Windows CMD ──────────────────────────────
init(convert=True)

LOG_FILE = "logs.txt"

# ── Color tags map ────────────────────────────────────────────────────
COLOR_MAP = {
    "[GREEN]": Fore.GREEN,
    "[RED]":   Fore.RED,
    "[RESET]": Style.RESET_ALL,
}


def colorize(line):
    for tag, code in COLOR_MAP.items():
        line = line.replace(tag, code)
    return line


def show_logs():
    print("================================================")
    print("   📋  XDRabbit Log Window")
    print("================================================")
    print()

    # ── wait for log file to exist ──
    while not os.path.exists(LOG_FILE):
        time.sleep(0.5)

    with open(LOG_FILE, "r", encoding="utf-8") as f:
        content = f.read()
        if content:
            for line in content.splitlines():
                print(colorize(line), flush=True)

        # ── tail new lines in real time ──
        while True:
            line = f.readline()
            if line:
                print(colorize(line), end="", flush=True)
            else:
                time.sleep(0.3)


if __name__ == "__main__":
    show_logs()
