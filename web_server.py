"""
XDRabbit Web Server
-------------------
Run:  python web_server.py
Then open http://localhost:5000
"""

import os
import sys
import time
import threading
import webbrowser
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from flask import Flask, Response, jsonify, request, send_from_directory

# ── Import project modules ────────────────────────────────────────────
import logger
import des_cap
import tools.grabber as grabber
import tools.campaign as campaign
import tools.campaign_status as campaign_status

# ── App ───────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
WEB_DIR  = BASE_DIR / "web"

app = Flask(__name__, static_folder=str(WEB_DIR), static_url_path="")

# ── Shared State ──────────────────────────────────────────────────────
state = {
    "threads":           {},
    "stop_events":       {},
    "drivers":           {},
    "pause_events":      {},
    "paused_ack_events": {},
    "appium_process":    None,
}
state_lock = threading.Lock()

LOG_FILE = "logs.txt"


# ── Helpers ───────────────────────────────────────────────────────────

def appium_running():
    p = state["appium_process"]
    return p is not None and p.poll() is None


def emulator_status():
    with state_lock:
        return {udid: "running" if t.is_alive() else "stopped"
                for udid, t in state["threads"].items()}


# ── SSE log stream ────────────────────────────────────────────────────

def _sse_generator():
    """Tail logs.txt and yield SSE events in real time."""
    while not os.path.exists(LOG_FILE):
        yield ": wait\n\n"
        time.sleep(0.3)

    with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
        # Flush existing content first
        content = f.read()
        for line in content.splitlines():
            if line.strip():
                yield f"data: {line.replace(chr(10), ' ')}\n\n"

        # Tail new lines
        while True:
            line = f.readline()
            if line:
                data = line.rstrip("\n")
                if data.strip():
                    yield f"data: {data}\n\n"
            else:
                time.sleep(0.15)
                yield ": ping\n\n"


@app.route("/stream")
def stream():
    return Response(
        _sse_generator(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control":     "no-cache",
            "X-Accel-Buffering": "no",
            "Connection":        "keep-alive",
        },
    )


# ── REST API ──────────────────────────────────────────────────────────

@app.route("/api/status")
def api_status():
    return jsonify({
        "appium":    appium_running(),
        "emulators": emulator_status(),
    })


@app.route("/api/appium/start", methods=["POST"])
def api_appium_start():
    if appium_running():
        return jsonify({"ok": False, "msg": "Appium already running"})
    import subprocess
    port = 4723
    try:
        logger.log(f"→ Starting Appium on port {port}...")
        process = subprocess.Popen(
            f"appium -p {port}",
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        with state_lock:
            state["appium_process"] = process
        logger.log(f"✓ Appium started (PID: {process.pid})")
        return jsonify({"ok": True, "msg": f"Appium started (PID {process.pid})"})
    except Exception as e:
        logger.log(f"✗ Failed to start Appium: {e}")
        return jsonify({"ok": False, "msg": str(e)})


@app.route("/api/appium/stop", methods=["POST"])
def api_appium_stop():
    p = state["appium_process"]
    if not p or p.poll() is not None:
        return jsonify({"ok": False, "msg": "Appium not running"})
    try:
        logger.log("→ Stopping Appium...")
        p.kill(); p.wait()
        with state_lock:
            state["appium_process"] = None
        logger.log("✓ Appium stopped")
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)})


@app.route("/api/start", methods=["POST"])
def api_start():
    with state_lock:
        running = [u for u, t in state["threads"].items() if t.is_alive()]
    if running:
        return jsonify({"ok": False, "msg": f"Already running: {running}"})

    def _run():
        t, se, d, pe, pae = des_cap.main_pro()
        with state_lock:
            state["threads"].update(t)
            state["stop_events"].update(se)
            state["drivers"].update(d)
            state["pause_events"].update(pe)
            state["paused_ack_events"].update(pae)

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"ok": True, "msg": "Script starting..."})


@app.route("/api/stop_all", methods=["POST"])
def api_stop_all():
    with state_lock:
        if not state["threads"]:
            return jsonify({"ok": False, "msg": "No script running"})
        t  = dict(state["threads"])
        se = dict(state["stop_events"])
        d  = dict(state["drivers"])

    def _run():
        des_cap.stop_all(t, se, d)
        with state_lock:
            state["threads"].clear()
            state["stop_events"].clear()
            state["drivers"].clear()
            state["pause_events"].clear()
            state["paused_ack_events"].clear()

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"ok": True, "msg": "Stopping all emulators..."})


@app.route("/api/stop_one", methods=["POST"])
def api_stop_one():
    udid = (request.json or {}).get("udid", "").strip()
    if not udid:
        return jsonify({"ok": False, "msg": "udid required"})
    with state_lock:
        if udid not in state["threads"]:
            return jsonify({"ok": False, "msg": f"{udid} not found"})
        t  = dict(state["threads"])
        se = dict(state["stop_events"])
        d  = dict(state["drivers"])

    threading.Thread(target=des_cap.stop_one,
                     args=(udid, t, se, d), daemon=True).start()
    return jsonify({"ok": True, "msg": f"Stopping {udid}..."})


@app.route("/api/add_emulators", methods=["POST"])
def api_add_emulators():
    with state_lock:
        if not state["threads"]:
            return jsonify({"ok": False, "msg": "Start the script first"})
        t   = dict(state["threads"])
        se  = dict(state["stop_events"])
        d   = dict(state["drivers"])
        pe  = dict(state["pause_events"])
        pae = dict(state["paused_ack_events"])

    def _run():
        nt, nse, nd, npe, npae = des_cap.add_new_emulators(t, se, d, pe, pae)
        with state_lock:
            state["threads"].update(nt)
            state["stop_events"].update(nse)
            state["drivers"].update(nd)
            state["pause_events"].update(npe)
            state["paused_ack_events"].update(npae)

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"ok": True, "msg": "Scanning for new emulators..."})


@app.route("/api/campaign", methods=["POST"])
def api_campaign():
    body            = request.json or {}
    mode            = body.get("mode", "standalone")
    view_quantity   = str(body.get("view_quantity", "")).strip()
    watch_seconds   = str(body.get("watch_seconds", "")).strip()
    random_behavior = bool(body.get("random_behavior", False))
    min_startime    = str(body.get("min_startime",  "")).strip() or None
    max_startime    = str(body.get("max_startime",  "")).strip() or None
    min_watchtime   = str(body.get("min_watchtime", "")).strip() or None
    max_watchtime   = str(body.get("max_watchtime", "")).strip() or None

    if not view_quantity or not watch_seconds:
        return jsonify({"ok": False, "msg": "view_quantity and watch_seconds required"})

    def _run():
        if mode == "during":
            with state_lock:
                ct  = dict(state["threads"])
                cd  = dict(state["drivers"])
                cpe = dict(state["pause_events"])
                cpa = dict(state["paused_ack_events"])
            ok, msg = campaign.run_add_campaign_during_script(
                current_threads=ct, current_drivers=cd,
                current_pause_events=cpe, current_paused_ack_events=cpa,
                view_quantity=view_quantity, watch_seconds=watch_seconds,
                random_behavior=random_behavior,
                min_startime=min_startime, max_startime=max_startime,
                min_watchtime=min_watchtime, max_watchtime=max_watchtime,
            )
        else:
            ok, msg = campaign.run_add_campaign(
                view_quantity=view_quantity, watch_seconds=watch_seconds,
                random_behavior=random_behavior,
                min_startime=min_startime, max_startime=max_startime,
                min_watchtime=min_watchtime, max_watchtime=max_watchtime,
            )
        logger.log(f"[Campaign] {'✓' if ok else '✗'} {msg}")

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"ok": True, "msg": "Campaign started — check logs."})


@app.route("/api/campaign_status")
def api_campaign_status():
    threading.Thread(target=campaign_status.run_campaign_status,
                     daemon=True).start()
    return jsonify({"ok": True, "msg": "Fetching campaign status — check logs."})


@app.route("/api/clear_log", methods=["POST"])
def api_clear_log():
    logger.clear_log()
    return jsonify({"ok": True})


# ── Serve frontend ────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(str(WEB_DIR), "index.html")


# ── Entry ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logger.clear_log()
    logger.log("✓ XDRabbit Web Dashboard ready at http://localhost:5000")

    def _open():
        time.sleep(1.2)
        webbrowser.open("http://localhost:5000")

    threading.Thread(target=_open, daemon=True).start()
    app.run(host="0.0.0.0", port=5000, threaded=True, debug=False)
