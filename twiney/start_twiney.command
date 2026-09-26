#!/bin/bash
# TWINEY launcher for macOS. Double-click to run (first time: right-click > Open).
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 was not found. Install Python 3.10+ from python.org."; read -r -p "Press Enter to close"; exit 1
fi
if [ ! -f config.json ]; then
  cp config.example.json config.json
  echo "Created config.json - check the \"port\" matches TWS: 7497 paper, 7496 live."
fi
if [ ! -f plays.json ]; then
  cp plays.example.json plays.json
  echo "Created plays.json with PLACEHOLDER plays - edit it with your real PS60 levels."
fi
python3 run_twiney.py "$@"
read -r -p "Press Enter to close"
