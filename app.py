import os
from flask import Flask, jsonify, request
import scraper

app = Flask(__name__)
# Strip whitespace: pasted env vars often carry a stray trailing newline/space.
SCRAPE_TOKEN = os.environ.get("SCRAPE_TOKEN", "").strip()


@app.route("/")
def home():
    return "PMWATCH is running."


@app.route("/debug-env")
def debug_env():
    """Safe diagnostic: reports whether SCRAPE_TOKEN is loaded and its
    shape WITHOUT revealing the value. Lists which required env vars
    are present. Remove after Step 1 verification."""
    tok = os.environ.get("SCRAPE_TOKEN", "")
    probe = request.args.get("probe", None)
    return jsonify({
        "code_version": "v3-strip",
        "probe_matches_raw": (probe == tok) if probe is not None else None,
        "probe_matches_stripped": (probe.strip() == tok.strip()) if probe is not None else None,
        "scrape_token_set": bool(tok),
        "scrape_token_length": len(tok),
        "scrape_token_first": tok[:1] if tok else None,
        "scrape_token_last": tok[-1:] if tok else None,
        "scrape_token_stripped_matches": tok.strip() == "pmwatch-8842-verify",
        "has_mc_username": bool(os.environ.get("MC_USERNAME")),
        "has_mc_password": bool(os.environ.get("MC_PASSWORD")),
        "has_database_url": bool(os.environ.get("DATABASE_URL")),
    })


@app.route("/test-login")
def test_login():
    token = request.args.get("token", "").strip()
    if not SCRAPE_TOKEN or token != SCRAPE_TOKEN:
        return jsonify({"error": "bad or missing token"}), 403
    return jsonify(scraper.test_login())
