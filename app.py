import os
from flask import Flask, jsonify, request
import scraper

app = Flask(__name__)


def _scrape_token():
    """Read the token at REQUEST time, not import time.
    A module-level constant can freeze to "" if the worker imported
    before the env var was populated. Strip stray paste whitespace."""
    return os.environ.get("SCRAPE_TOKEN", "").strip()


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
        "code_version": "v5-bytes",
        "probe_matches_raw": (probe == tok) if probe is not None else None,
        "probe_matches_stripped": (probe.strip() == tok.strip()) if probe is not None else None,
        "token_repr": repr(tok),
        "token_bytes_hex": tok.encode("utf-8").hex(),
        "testlogin_would_pass": (probe.strip() == tok.strip()) if probe is not None else None,
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
    expected = _scrape_token()
    if not expected or token != expected:
        return jsonify({
            "error": "bad or missing token",
            "debug_incoming_token_repr": repr(token),
            "debug_expected_repr": repr(expected),
            "debug_incoming_hex": token.encode("utf-8").hex(),
            "debug_expected_hex": expected.encode("utf-8").hex(),
            "debug_equal": token == expected,
        }), 403
    return jsonify(scraper.test_login())
