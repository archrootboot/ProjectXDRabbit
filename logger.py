import os

LOG_FILE = "logs.txt"


def clear_log():
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        f.write("")


def log(message):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(message + "\n")
        f.flush()


# ── Color helpers ─────────────────────────────────────────────────────
def green(message):
    log(f"[GREEN]{message}[RESET]")


def red(message):
    log(f"[RED]{message}[RESET]")
