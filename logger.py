import os

LOG_FILE = "logs.txt"


def clear_log():
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        f.write("")


def log(message):
    print(message)   # ← still print to main window
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(message + "\n")
        f.flush()
