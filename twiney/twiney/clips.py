"""Clips: a stretch of a recording saved to the journal (recordings/clips.jsonl), to watch again later."""

import json
import os
import threading
import time

_lock = threading.Lock()


def _path(rec_dir):
    return os.path.join(rec_dir, "clips.jsonl")


def load(rec_dir):
    out = []
    try:
        with open(_path(rec_dir), encoding="utf-8") as fh:
            for line in fh:
                try:
                    c = json.loads(line)
                except ValueError:
                    continue            # a damaged line costs that line only
                if isinstance(c, dict) and c.get("id"):
                    out.append(c)
    except OSError:
        pass
    return out


def _write(rec_dir, clips):
    os.makedirs(rec_dir, exist_ok=True)
    tmp = _path(rec_dir) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        for c in clips:
            fh.write(json.dumps(c) + "\n")
    os.replace(tmp, _path(rec_dir))


def add(rec_dir, rec, t0, t1, symbol=None, note=""):
    rec = os.path.basename(str(rec or ""))
    if not rec.endswith(".jsonl") or not os.path.exists(os.path.join(rec_dir, rec)):
        raise ValueError("no such recording")
    t0, t1 = float(t0), float(t1)
    if t1 < t0:
        t0, t1 = t1, t0
    if t1 - t0 < 1:
        raise ValueError("a clip needs at least a second")
    with _lock:
        clips = load(rec_dir)
        clip = {"id": f"c{int(time.time() * 1000)}", "rec": rec, "t0": round(t0, 3), "t1": round(t1, 3),
                "symbol": (str(symbol).upper() if symbol else None), "note": str(note or "")[:300],
                "created": time.time()}
        clips.append(clip)
        _write(rec_dir, clips)
    return clip


def delete(rec_dir, clip_id):
    with _lock:
        clips = load(rec_dir)
        keep = [c for c in clips if c["id"] != clip_id]
        if len(keep) == len(clips):
            return False
        _write(rec_dir, keep)
    return True


def note(rec_dir, clip_id, text):
    with _lock:
        clips = load(rec_dir)
        for c in clips:
            if c["id"] == clip_id:
                c["note"] = str(text or "")[:300]
                _write(rec_dir, clips)
                return True
    return False
