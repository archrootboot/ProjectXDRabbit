"""
debug_logcat.py  —  Run this STANDALONE on your Windows machine.

1. Make sure the emulator is running and visible.
2. Run:  python debug_logcat.py
3. When prompted, click the play button in the app.
4. Wait ~10 seconds.
5. Paste the full output here so we can see what logcat actually says.
"""

import subprocess
import time

UDID = "emulator-5556"   # change if needed
DURATION = 12            # seconds to capture after you press Enter


def run():
    print(f"\n[1] Clearing logcat buffer on {UDID}...")
    subprocess.run(["adb", "-s", UDID, "logcat", "-c"], capture_output=True)
    print("    Done.\n")

    input("[2] Press ENTER, then immediately click the play button in the app...")

    print(f"\n[3] Capturing ALL logcat output for {DURATION}s — do not touch anything...\n")
    print("=" * 70)

    start = time.time()
    proc = subprocess.Popen(
        ["adb", "-s", UDID, "logcat", "-v", "brief"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="ignore"
    )

    lines = []
    while time.time() - start < DURATION:
        line = proc.stdout.readline()
        if not line:
            break
        print(line, end="")
        lines.append(line)

    proc.terminate()
    print("=" * 70)

    # ── filter for anything YouTube / intent related ──
    print("\n[4] Filtered lines (youtube / intent / START / VIEW / dat=):\n")
    keywords = ["youtube", "youtu.be", "intent", "START", "VIEW", "dat=",
                "ActivityManager", "com.view", "rabbit"]
    found = [l for l in lines if any(k.lower() in l.lower() for k in keywords)]

    if found:
        for l in found:
            print(l, end="")
    else:
        print("  ⚠  Nothing matched — see full output above for clues.")

    print("\n[5] Done. Copy this entire output and share it.\n")


if __name__ == "__main__":
    run()
