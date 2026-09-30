"""Replay a TWINEY JSONL recording through a fresh engine (audit / tuning)."""

import time

from .flow import FLOW_LABELS
from .engine import ALERT_LABELS, PS60_LABELS, Engine
from .recorder import read_events

TICK_STEP = 0.25  # the live session evaluates time-based rules every 0.25s


def session_header(plays, cfg, version):
    from .settings import redacted
    return {"ev": "session", "t": time.time(), "version": version, "plays": plays, "config": redacted(cfg),
            "ticks": True}   # this recording carries the live tick times


def replay(path, plays=None, cfg=None, speed=0.0, on_alert=None, engine_ready=None, control=None):
    """Feed every recorded event into a new engine.

    Uses the plays/config stored in the recording header unless overridden, so a
    recording can be re-run with different reload settings to tune them.
    Returns (engine, recorded_alerts).
    """
    engine = None
    recorded = []
    prev_t = None
    next_tick = None
    ticks_recorded = False
    replayed = []           # every replayed alert (the engine itself keeps only the last 300)

    def new_engine(p, c):
        eng = Engine(p, c)
        eng.listeners.append(replayed.append)
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
                engine.replayed_alerts = replayed
                ticks_recorded = bool(ev.get("ticks"))
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
        if kind == "tick":
            if ticks_recorded:
                engine.tick(t, allocate_slots=False)   # exactly when the live session ran it
            prev_t = t if prev_t is None else max(prev_t, t)
            continue
        if ticks_recorded:
            pass                   # ticks come from the recording itself
        elif next_tick is None:
            next_tick = t + TICK_STEP
        # reproduce the live session's periodic evaluation (every TICK_STEP seconds)
        if not ticks_recorded:     # an older recording: rebuild the ticks on the live grid
            if t - next_tick > 120.0:
                engine.tick(next_tick, allocate_slots=False)
                next_tick = t  # long gap (e.g. overnight): jump ahead
            # live, the tick at time T runs after every event stamped T: so tick strictly before this event's time
            while next_tick < t or (kind == "slot" and next_tick <= t):   # a slot change is made by the tick at its own time
                engine.tick(next_tick, allocate_slots=False)
                next_tick += TICK_STEP
        if control is not None:
            control["position"] = t
            seek = control.get("seek")
            if seek is not None and t >= seek:
                control["seek"] = None
                seek = None
            while control.get("paused") and not control.get("stop") and seek is None:
                time.sleep(0.1)
            if control.get("stop"):
                break
            spd = control.get("speed") or speed
            if seek is None and spd and spd > 0 and prev_t is not None and t > prev_t:
                time.sleep(min((t - prev_t) / spd, 5.0))
        elif speed and speed > 0 and prev_t is not None and t > prev_t:
            time.sleep(min((t - prev_t) / speed, 5.0))
        prev_t = t if prev_t is None else max(prev_t, t)
        engine.ingest(ev)
    if engine is not None and prev_t is not None and not ticks_recorded:
        engine.tick(prev_t, allocate_slots=False)
    return engine, recorded


def compare(engine, recorded):
    """Summarise replayed vs recorded alert labels."""
    def counts(alerts):
        out = {}
        for a in alerts:
            if a["label"] in ALERT_LABELS + PS60_LABELS + FLOW_LABELS:
                key = (a["symbol"], a["label"], a["price"])
                out[key] = out.get(key, 0) + 1
        return out
    return counts(list(getattr(engine, "replayed_alerts", None) or engine.alerts)), counts(recorded)
