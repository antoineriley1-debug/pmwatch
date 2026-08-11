import os
from datetime import datetime
from flask import Flask, jsonify, request, render_template
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
    """Mobile-first dashboard: hospital cards + closed-PM table."""
    selected = request.args.get("hospital")
    try:
        db.init_db()
        hospitals = db.hospital_stats()
        raw_rows = db.list_pms(hospital_code=selected, limit=500)
        total = db.count_pms()
    except Exception as e:
        return f"PMWATCH is running. (DB not ready: {e})", 200

    # Flatten the raw JSON so the template can read reason/location/target.
    rows = []
    for r in raw_rows:
        raw = r.get("raw") or {}
        rows.append({
            "wo_number": r.get("wo_number"),
            "asset_name": r.get("asset_name"),
            "close_date": r.get("close_date"),
            "closed_by": r.get("closed_by"),
            "reason": raw.get("reason"),
            "location": raw.get("location"),
            "target_date": raw.get("target_date"),
            "raw": raw,
        })

    return render_template(
        "dashboard.html",
        hospitals=hospitals,
        rows=rows,
        total=total,
        selected=selected,
        updated=datetime.now().strftime("%b %d, %I:%M %p"),
    )


@app.route("/ping")
def ping():
    return "PMWATCH is running."


@app.route("/health")
def health():
    """Liveness + DB connectivity check."""
    out = {"app": "ok"}
    try:
        db.init_db()  # idempotent: creates closed_pms + indexes if missing
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


@app.route("/scrape")
def scrape():
    """Step 2: scrape closed PMs for one hospital into Neon.
    Default hospital 52626. ?store=0 to dry-run without writing."""
    if not _check_token():
        return jsonify({"error": "bad or missing token"}), 403
    hospital = request.args.get("hospital", "52626")
    store = request.args.get("store", "1") != "0"
    return jsonify(scraper.scrape_hospital(hospital_code=hospital, store=store))


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
