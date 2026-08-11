import os
from flask import Flask, jsonify, request
import scraper
import db

app = Flask(__name__)


def _scrape_token():
    """Read the token at REQUEST time, not import time.
    A module-level constant can freeze to "" if the worker imported
    before the env var was populated. Strip stray paste whitespace.
    """
    return os.environ.get("SCRAPE_TOKEN", "").strip()


def _check_token():
    token = request.args.get("token", "").strip()
    expected = _scrape_token()
    return bool(expected) and token == expected


@app.route("/")
def home():
    return "PMWATCH is running."


@app.route("/health")
def health():
    """Liveness + DB connectivity check."""
    out = {"app": "ok"}
    try:
        out["stored_pms"] = db.count_pms()
        out["db"] = "ok"
    except Exception as e:
        out["db"] = "error"
        out["db_error"] = str(e)
    return jsonify(out)


@app.route("/test-login")
def test_login():
    if not _check_token():
        return jsonify({"error": "bad or missing token"}), 403
    return jsonify(scraper.test_login())


@app.route("/discover")
def discover():
    """Step 2 discovery: dump MC's real list/nav structure for one hospital."""
    if not _check_token():
        return jsonify({"error": "bad or missing token"}), 403
    rc = request.args.get("repaircenter", "52626")
    return jsonify(scraper.discover(repaircenter=rc))


@app.route("/pms")
def pms():
    """Inspect stored closed PMs."""
    if not _check_token():
        return jsonify({"error": "bad or missing token"}), 403
    hospital = request.args.get("hospital")
    return jsonify({
        "count": db.count_pms(hospital),
        "recent": db.recent_pms(limit=50, hospital_code=hospital),
    })
