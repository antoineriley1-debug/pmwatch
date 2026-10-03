"""Where YOUR files live: settings (config.json with the Quant Data key), plays, layout, alerts and recordings.

They sit in a folder of their own, outside the program folder, so unzipping a new build never touches them:
    Windows   C:\\Users\\<you>\\TWINEY
    Mac       /Users/<you>/TWINEY
(or wherever TWINEY_HOME points). The first start copies an existing config.json / plays.json from the program
folder in, so nothing you already set up is lost. Secrets never leave this folder: not into zips, git or recordings."""

import os
import shutil

USER_FILES = ("config.json", "plays.json", "layout.json", "layouts.json", "alerts.json")


def data_dir():
    """The folder for your files, created if missing."""
    d = os.environ.get("TWINEY_HOME") or os.path.join(os.path.expanduser("~"), "TWINEY")
    os.makedirs(d, exist_ok=True)
    return d


def user_file(name, program_dir=None):
    """The path of one of your files in the data folder. The first time, a copy that was sitting in the program
    folder (an older build kept them there) moves in, so your port and key come along."""
    d = data_dir()
    path = os.path.join(d, name)
    if not os.path.exists(path) and program_dir:
        old = os.path.join(program_dir, name)
        if os.path.isfile(old):
            shutil.copy2(old, path)
    return path


def ensure_config(program_dir):
    """config.json in the data folder, made from config.example.json when there is none yet."""
    path = user_file("config.json", program_dir)
    if not os.path.exists(path):
        example = os.path.join(program_dir, "config.example.json")
        if os.path.isfile(example):
            shutil.copy2(example, path)
    return path


def ensure_plays(program_dir, symbols=("SPY", "QQQ", "AAPL", "NVDA", "TSLA", "AMD")):
    """plays.json in the data folder: a blank watch-only list when there is none yet (you draw your own levels)."""
    import json
    path = user_file("plays.json", program_dir)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"plays": [{"symbol": s, "watch": True} for s in symbols]}, fh, indent=2)
    return path


def recordings_dir(cfg_dir_value):
    """Recordings go in the data folder too unless config.json names an absolute path."""
    v = cfg_dir_value or "recordings"
    return v if os.path.isabs(v) else os.path.join(data_dir(), v)
