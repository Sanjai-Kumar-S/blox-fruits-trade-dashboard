import os
from collections import deque
from datetime import datetime, timezone
from threading import Lock
from flask import Flask, jsonify, render_template, request, send_from_directory

try:
    from flask_cors import CORS
except ImportError:
    CORS = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = (
    os.path.join(BASE_DIR, "templates")
    if os.path.isdir(os.path.join(BASE_DIR, "templates"))
    else BASE_DIR
)

app = Flask(__name__, template_folder=TEMPLATE_DIR)
# Enable CORS across all endpoints so Roblox HttpService or external bots can poll/post freely
if CORS is not None:
    CORS(app, resources={r"/*": {"origins": "*"}})


@app.after_request
def apply_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response

state_lock = Lock()
command_queue = deque()
activity_logs = deque(maxlen=150)
stats = {
    "total_dispatched": 0,
    "total_polled": 0,
    "last_poll_at": None,
    "last_command_sent": None,
}


def add_log(event_type: str, message: str, payload: dict | None = None) -> dict:
    entry = {
        "id": int(datetime.now(timezone.utc).timestamp() * 1000000),
        "timestamp": datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3],
        "type": event_type,  # DISPATCH, POLL_HIT, POLL_EMPTY, SYSTEM, ERROR
        "message": message,
        "payload": payload,
    }
    activity_logs.append(entry)
    return entry


def normalize_command(raw_cmd: str, normalize_prefix: bool = True) -> str:
    """
    Normalizes commands like '!add Phoenix-Phoenix' -> 'addphoenix-phoenix'
    when normalize_prefix is True, or preserves custom formatting if already normalized.
    """
    cleaned = raw_cmd.strip()
    if not cleaned:
        return ""
    if normalize_prefix and cleaned.lower().startswith("!add "):
        item_part = cleaned[5:].strip().lower().replace(" ", "")
        return f"add{item_part}"
    return cleaned


add_log("SYSTEM", "Cloud Trade Automation Backend initialized and awaiting commands.")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/static/css/style.css")
def serve_css():
    css_dir = os.path.join(BASE_DIR, "static", "css")
    if os.path.isfile(os.path.join(css_dir, "style.css")):
        return send_from_directory(css_dir, "style.css")
    return send_from_directory(BASE_DIR, "style.css")


@app.route("/static/js/main.js")
def serve_js():
    js_dir = os.path.join(BASE_DIR, "static", "js")
    if os.path.isfile(os.path.join(js_dir, "main.js")):
        return send_from_directory(js_dir, "main.js")
    return send_from_directory(BASE_DIR, "main.js")


@app.route("/get_commands", methods=["GET"])
def get_commands():
    """
    Polled by the Roblox client (e.g., via HttpService:GetAsync).
    Returns the next queued command in JSON format (e.g., {"command": "addphoenix-phoenix"})
    and clears it from the queue after fetching.
    """
    with state_lock:
        now_iso = datetime.now(timezone.utc).isoformat()
        stats["total_polled"] += 1
        stats["last_poll_at"] = now_iso

        if command_queue:
            next_cmd = command_queue.popleft()
            stats["last_command_sent"] = next_cmd
            response_payload = {"command": next_cmd}
            add_log(
                "POLL_HIT",
                f"Roblox client fetched queued command: '{next_cmd}'",
                response_payload,
            )
        else:
            response_payload = {"command": None}
            # Log empty polls only if explicitly requested via ?verbose=1 or keep lightweight
            if request.args.get("log_empty", "true").lower() != "false":
                add_log(
                    "POLL_EMPTY",
                    "GET /get_commands polled by client (queue empty)",
                    response_payload,
                )

    return jsonify(response_payload), 200


@app.route("/api/command", methods=["POST"])
def post_command():
    """
    Receives command updates from the web dashboard UI buttons, item bar, or Discord bot.
    Expected JSON body: {"command": "...", "normalize": true}
    """
    data = request.get_json(silent=True) or {}
    raw_command = str(data.get("command", "")).strip()
    should_normalize = bool(data.get("normalize", True))
    source = str(data.get("source", "Dashboard UI")).strip()

    if not raw_command:
        return jsonify({"status": "error", "error": "Command cannot be empty"}), 400

    final_command = normalize_command(raw_command, normalize_prefix=should_normalize)

    with state_lock:
        command_queue.append(final_command)
        stats["total_dispatched"] += 1
        queue_size = len(command_queue)
        log_entry = add_log(
            "DISPATCH",
            f"[{source}] Queued command: '{final_command}'"
            + (f" (from '{raw_command}')" if final_command != raw_command else ""),
            {"command": final_command, "queue_size": queue_size},
        )

    return (
        jsonify(
            {
                "status": "queued",
                "command": final_command,
                "raw_command": raw_command,
                "queue_size": queue_size,
                "log": log_entry,
            }
        ),
        200,
    )


@app.route("/api/status", methods=["GET"])
def get_status():
    """Returns current queue, stats, and recent activity logs for the live terminal."""
    with state_lock:
        return jsonify(
            {
                "queue": list(command_queue),
                "stats": dict(stats),
                "logs": list(activity_logs),
            }
        )


@app.route("/api/queue/clear", methods=["POST"])
def clear_queue():
    """Clears any pending commands in the queue."""
    with state_lock:
        cleared_count = len(command_queue)
        command_queue.clear()
        add_log("SYSTEM", f"Cleared {cleared_count} pending command(s) from queue.")
    return jsonify({"status": "cleared", "cleared_count": cleared_count}), 200


@app.route("/api/logs/clear", methods=["POST"])
def clear_logs():
    """Clears the live terminal log history."""
    with state_lock:
        activity_logs.clear()
        add_log("SYSTEM", "Terminal logs cleared by operator.")
    return jsonify({"status": "cleared"}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
