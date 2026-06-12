"""
Tables API — shranjuje stanje miz za Restavracija POS.
Teče kot ločen proces na Railway (port 5001).
Podatki se shranjujejo v /data/tables.json (Railway Volume).
"""

import os
import json
from flask import Flask, request, jsonify
from functools import wraps

app = Flask(__name__)

DATA_FILE = os.environ.get("TABLES_DATA_FILE", "/data/tables.json")
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")
NUM_TABLES = 10


def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not APP_PASSWORD:
            return f(*args, **kwargs)
        auth = request.headers.get("X-API-Password", "")
        if auth != APP_PASSWORD:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated


def load_tables():
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r", encoding="utf-8") as fh:
                return json.load(fh)
    except Exception:
        pass
    return {str(i): {"items": [], "sent": False} for i in range(1, NUM_TABLES + 1)}


def save_tables(data):
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-API-Password"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response


@app.route("/tables", methods=["OPTIONS"])
def tables_options():
    return "", 204


@app.route("/tables", methods=["GET"])
@require_auth
def get_tables():
    return jsonify(load_tables())


@app.route("/tables", methods=["POST"])
@require_auth
def post_tables():
    data = request.get_json(force=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Invalid data"}), 400
    save_tables(data)
    return jsonify({"ok": True})


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("TABLES_PORT", 5001))
    app.run(host="0.0.0.0", port=port)
