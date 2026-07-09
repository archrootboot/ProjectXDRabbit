import time
import os

LOG_FILE = "logs.txt"


def show_logs():
    print("================================================")
    print("   📋  XDRabbit Log Window")
    print("================================================")
    print()

    # ── wait for log file to exist ──
    while not os.path.exists(LOG_FILE):
        time.sleep(0.5)

    with open(LOG_FILE, "r", encoding="utf-8") as f:
        # ── read any existing content first ──
        content = f.read()
        if content:
            print(content, end="")

        # ── tail new lines in real time ──
        while True:
            line = f.readline()
            if line:
                print(line, end="", flush=True)
            else:
                time.sleep(0.3)   # ← check every 0.3s


if __name__ == "__main__":
    show_logs()
