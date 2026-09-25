"""Replay a TWINEY JSONL recording through a fresh engine (audit / tuning)."""

import time

from .engine import ALERT_LABELS, Engine
from .recorder import read_events

TICK_STEP = 0.25  # the live session evaluates time-based rules every 0.25s


def session_header(plays, cfg, version):
    return {"ev": "session", "t": time.time(), "version": version, "plays": plays, "config": cfg}


def replay(path, plays=None, cfg=None, speed=0.0, on_alert=None, engine_ready=None):
    """Feed every recorded event into a new engine.

    Uses the plays/config stored in the recording header unless overridden, so a
    recording can be re-run with different reload settings to tune them.
    Returns (engine, recorded_alerts).
    """
    engine = None
    recorded = []
    prev_t = None
    next_tick = None

    def new_engine(p, c):
        eng = Engine(p, c)
        if on_alert:
            eng.listeners.append(on_alert)
        if engine_ready is not None:
            engine_ready(eng)
        return eng

    for ev in read_events(path):
        kind = ev.get("ev")
        if kind == "session":
            if engine is None:
                engine = new_engine(plays or ev["plays"], cfg or ev["config"])
            continue
        if engine is None:
            if plays is None or cfg is None:
                raise ValueError("recording has no session header; pass plays and config")
            engine = new_engine(plays, cfg)
        if kind == "alert":
            recorded.append(ev)
            continue
        t = ev.get("t")
        if t is None:
            continue
        if next_tick is None:
            next_tick = t + TICK_STEP
        # reproduce the live session's periodic evaluation (every TICK_STEP seconds)
        if t - next_tick > 120.0:
            engine.tick(next_tick, allocate_slots=False)
            next_tick = t  # long gap (e.g. overnight): jump ahead
        while next_tick <= t:
            engine.tick(next_tick, allocate_slots=False)
            next_tick += TICK_STEP
        if speed and speed > 0 and prev_t is not None and t > prev_t:
            time.sleep(min((t - prev_t) / speed, 5.0))
        prev_t = t if prev_t is None else max(prev_t, t)
        engine.ingest(ev)
    if engine is not None and prev_t is not None:
        engine.tick(prev_t, allocate_slots=False)
    return engine, recorded


def compare(engine, recorded):
    """Summarise replayed vs recorded alert labels."""
    def counts(alerts):
        out = {}
        for a in alerts:
            if a["label"] in ALERT_LABELS:
                key = (a["symbol"], a["label"], a["price"])
                out[key] = out.get(key, 0) + 1
        return out
    return counts(list(engine.alerts)), counts(recorded)
