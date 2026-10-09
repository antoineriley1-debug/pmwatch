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


def span(path):
    """First and last market time in a recording (for the replay scrubber)."""
    import json as _json
    first = last = None
    with open(path, "rb") as fh:
        for i, line in enumerate(fh):
            try:
                ev = _json.loads(line)
            except ValueError:
                continue
            if ev.get("ev") not in ("session", None) and ev.get("t"):
                first = ev["t"]
                break
            if i > 5000:
                break
        fh.seek(0, 2)
        size = fh.tell()
        fh.seek(max(0, size - 262144))
        for line in fh.read().splitlines()[1:] or []:
            try:
                ev = _json.loads(line)
            except ValueError:
                continue
            if ev.get("t") and ev.get("ev") != "session":
                last = ev["t"] if last is None else max(last, ev["t"])
    return first, last


def replay(path, plays=None, cfg=None, speed=0.0, on_alert=None, engine_ready=None, control=None, trainer=None):
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
    trained_t = [None]

    def train_hook(alert):
        """TRAINING: a spoken call with a direction in it pauses the replay and asks you."""
        try:
            st = engine.syms.get(alert.get("symbol")) if engine is not None else None
            if st is None:
                return
            atr = (st.__dict__.get("_story_atr") or {}).get("v") or st.play.get("atr")
            if trainer.ask(alert, alert.get("t") or engine.last_t, st.price(), atr) and control is not None:
                control["paused"] = True
        except Exception:
            pass

    def pace(t):
        """Real-time pacing, pause, seek and stop: for every event, ticks included. False = stop."""
        if trainer is not None and engine is not None and (trained_t[0] is None or t - trained_t[0] >= 1.0):
            trained_t[0] = t
            trainer.tick(t, {sym: st.price() for sym, st in engine.syms.items() if st.price()})
        if control is not None:
            control["position"] = t
            end = control.get("pause_at")
            if (end is not None and t >= end and control.get("seek") is None and not control.get("stop")
                    and control.get("restart_at") is None):   # never on a pass that is about to rewind
                control["pause_at"] = None          # the end of a clip: stop there, paused
                control["paused"] = True
                control["clip_done"] = True
            seek = control.get("seek")
            if seek is not None and t >= seek:
                control["seek"] = None
                seek = None
            while control.get("paused") and not control.get("stop") and seek is None:
                if control.get("step"):
                    control["step"] = False      # one event through, then paused again
                    break
                time.sleep(0.1)
            if control.get("stop"):
                return False
            spd = control.get("speed") or speed
            if seek is None and spd and spd > 0 and prev_t is not None and t > prev_t:
                time.sleep(min((t - prev_t) / spd, 5.0))
        elif speed and speed > 0 and prev_t is not None and t > prev_t:
            time.sleep(min((t - prev_t) / speed, 5.0))
        return True

    def new_engine(p, c):
        eng = Engine(p, c)
        eng.listeners.append(replayed.append)
        if on_alert:
            eng.listeners.append(on_alert)
        if trainer is not None:
            eng.listeners.append(train_hook)
            eng.trainer = trainer
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
                if not pace(t):
                    break
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
        if not pace(t):
            break
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
