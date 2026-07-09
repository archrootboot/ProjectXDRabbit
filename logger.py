import queue

# ── Shared log queue ──────────────────────────────────────────────────
log_queue = queue.Queue()


def log(message):
    log_queue.put(message)
