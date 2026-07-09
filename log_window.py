import logger


def show_logs():
    print("================================================")
    print("   📋  XDRabbit Log Window")
    print("================================================")
    print()

    while True:
        # ── block until a new log message arrives ──
        message = logger.log_queue.get()
        print(message, flush=True)


if __name__ == "__main__":
    show_logs()
