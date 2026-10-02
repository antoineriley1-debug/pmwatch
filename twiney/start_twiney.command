#!/bin/bash
# TWINEY launcher for macOS. Double-click to run (first time: right-click > Open).
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 was not found. Install Python 3.10+ from python.org."; read -r -p "Press Enter to close"; exit 1
fi
# your settings, key, plays and layout live in ~/TWINEY - a new build never touches them
python3 run_twiney.py "$@"
read -r -p "Press Enter to close"
