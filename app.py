import os
from flask import Flask, jsonify, request
import scraper

app = Flask(__name__)
SCRAPE_TOKEN = os.environ.get("SCRAPE_TOKEN", "")


@app.route("/")
def home():
    return "PMWATCH is running."


@app.route("/test-login")
def test_login():
    token = request.args.get("token", "")
    if not SCRAPE_TOKEN or token != SCRAPE_TOKEN:
        return jsonify({"error": "bad or missing token"}), 403
    return jsonify(scraper.test_login())
