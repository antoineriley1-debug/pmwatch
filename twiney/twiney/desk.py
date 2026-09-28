"""The recording desk: REC on / off, markers, screenshots, session journal, replay launcher.

Everything a prop desk does with a session after the fact starts here:
  - start / stop a recording at any moment (space bar); a recording started
    mid-session first dumps the current state so it replays cleanly
  - drop a marker (M) with the symbol and what the story said at that second
  - take a screenshot (P) of the whole screen into recordings/shots/
  - on stop, write a one-page journal next to the recording
  - list recordings with their markers, and open one in the replay desk
"""

import json
import os
import subprocess
import sys
import time

from .book import ASK, BID, INSERT
from .recorder import Recorder, read_events


class Desk:
    def __init__(self, engine, cfg, plays, version, prefix="twiney", base_dir=None):
        self.engine = engine
        self.cfg = cfg
        self.plays = plays
        self.version = version
        self.prefix = prefix
        self.dir = cfg["recording"]["dir"]
        self.base_dir = base_dir or os.getcwd()
        self.started = None
        self.marks = []
        self.shots = []
        self.notes = []   # free-text journal notes typed during the session
        self.journal_path = None
        self.replay_proc = None
        engine.desk = self

    # ---- recording ------------------------------------------------------------

    @property
    def recording(self):
        return self.engine.recorder is not None

    def start(self, t=None):
        if self.recording:
            return self.engine.recorder.path
        t = t or time.time()
        from .replay import session_header
        rec = Recorder(self.dir, time.strftime(f"{self.prefix}-%Y%m%d-%H%M%S.jsonl", time.localtime(t)))
        rec.write(session_header(self.plays, self.cfg, self.version))
        self.engine.dump_state(rec, t)   # so a recording started mid-session replays from a full book
        self.engine.recorder = rec
        self.started = t
        self.marks, self.shots, self.notes, self.journal_path = [], [], [], None
        self.engine._message("info", f"REC — recording to {os.path.basename(rec.path)}", t)
        return rec.path

    def stop(self, t=None):
        rec = self.engine.recorder
        if rec is None:
            return None
        t = t or time.time()
        path = rec.path
        self.engine.recorder = None
        rec.close()
        self.journal_path = self.write_journal(path, t)
        self.engine._message("info", f"STOPPED recording {os.path.basename(path)} — journal: {os.path.basename(self.journal_path)}", t)
        return path

    def toggle(self, t=None):
        return {"recording": False, "path": self.stop(t)} if self.recording else {"recording": True, "path": self.start(t)}

    # ---- markers + screenshots ------------------------------------------------

    def mark(self, t, symbol=None, note="", shot=None):
        st = self.engine.syms.get(symbol) if symbol else None
        price = st.price() if st else None
        headline = ""
        try:
            snap = self.engine.snapshot(t)
            pane = next((p for p in snap["panes"] if p and p["symbol"] == symbol), None)
            if pane:
                headline = pane["headline"]
        except Exception:
            pass
        m = {"t": t, "symbol": symbol, "price": price, "note": note or "", "headline": headline, "shot": shot,
             "n": len(self.marks) + 1}
        self.marks.append(m)
        self.engine._rec(dict(m, ev="mark"))
        if self.recording:
            with open(self.engine.recorder.path[:-6] + ".marks.jsonl", "a", encoding="utf-8") as fh:
                fh.write(json.dumps(m) + "\n")
        return m

    def add_note(self, t, text, symbol=None):
        text = text.strip()
        if text:
            n = {"t": t, "symbol": symbol, "text": text}
            self.notes.append(n)
            self.engine._rec(dict(n, ev="note"))
        return self.notes[-30:]

    def set_note(self, n, note):
        for m in self.marks:
            if m["n"] == n:
                m["note"] = note
                self.engine._rec({"ev": "mark_note", "t": time.time(), "n": n, "note": note})
                return True
        return False

    def screenshot(self, t, symbol=None, note=""):
        try:
            from PIL import ImageGrab
        except ImportError:
            return {"ok": False, "reason": "screenshots need the Pillow package: run  python -m pip install pillow  (install_ibapi.bat does it)"}
        shots = os.path.join(self.dir, "shots")
        os.makedirs(shots, exist_ok=True)
        stem = os.path.basename(self.engine.recorder.path)[:-6] if self.recording else time.strftime("%Y%m%d")
        name = f"{stem}-{time.strftime('%H%M%S', time.localtime(t))}{'-' + symbol if symbol else ''}.png"
        path = os.path.join(shots, name)
        try:
            ImageGrab.grab(all_screens=True).save(path)
        except Exception as exc:
            return {"ok": False, "reason": f"screenshot failed: {exc}"}
        self.shots.append(path)
        m = self.mark(t, symbol, note or "screenshot", shot="shots/" + name)
        return {"ok": True, "path": path, "mark": m}

    # ---- journal ------------------------------------------------------------------

    def write_journal(self, rec_path, t):
        eng = self.engine
        calls, grades = [], {}
        for ev in read_events(rec_path):
            if ev.get("ev") == "alert":
                calls.append(ev)
            elif ev.get("ev") == "grade":
                if ev.get("verdict"):
                    grades[ev["key"]] = ev["verdict"]
                else:
                    grades.pop(ev["key"], None)
        fills = sorted(eng.fills.values(), key=lambda f: f["t"])
        pnl = eng.day_pnl()
        started = self.started or t
        lines = [f"# TWINEY session journal — {os.path.basename(rec_path)}", "",
                 f"- Started: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(started))}",
                 f"- Stopped: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(t))}  ({(t - started) / 60:.0f} min)",
                 f"- Plays: {', '.join(p['symbol'] for p in self.plays)}",
                 f"- Day P&L: realized {pnl['realized']:+,.0f} · open {pnl['open']:+,.0f} · total {pnl['total']:+,.0f}",
                 "", "## Notes", ""]
        if not self.notes:
            lines.append("_none_")
        for n in self.notes:
            lines.append(f"- **{time.strftime('%H:%M:%S', time.localtime(n['t']))}** {n['symbol'] or ''} {n['text']}")
        lines += ["", "## Markers", ""]
        if not self.marks:
            lines.append("_none_")
        for m in self.marks:
            when = time.strftime("%H:%M:%S", time.localtime(m["t"]))
            lines.append(f"- **{when}** {m['symbol'] or ''} {m['price'] or ''} — {m['note']}"
                         + (f" — _{m['headline']}_" if m["headline"] else "")
                         + (f" — ![shot]({m['shot']})" if m.get("shot") else ""))
        lines += ["", "## Calls", ""]
        if not calls:
            lines.append("_none_")
        for a in calls:
            when = time.strftime("%H:%M:%S", time.localtime(a["t"]))
            g = grades.get(a.get("key"))
            lines.append(f"- {when} {a['symbol']} **{a['label']}** @ {a['price']}" + (f" — graded {g.upper()}" if g else "")
                         + f"\n  {a.get('text', '')}")
        lines += ["", "## Fills", ""]
        if not fills:
            lines.append("_none_")
        for f in fills:
            lines.append(f"- {f['time']} {f['symbol']} {f['side']} {int(f['shares'])} @ {f['price']}")
        lines += ["", "## Screenshots", ""] + ([f"- {os.path.basename(s)}" for s in self.shots] or ["_none_"]) + [""]
        path = rec_path[:-6] + ".journal.md"
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
        return path

    # ---- recordings on disk ------------------------------------------------------

    def list_recordings(self):
        out = []
        if not os.path.isdir(self.dir):
            return out
        for name in sorted(os.listdir(self.dir), reverse=True):
            if not name.endswith(".jsonl") or name.endswith(".marks.jsonl") or name == "grades.jsonl":
                continue
            path = os.path.join(self.dir, name)
            marks = []
            mpath = path[:-6] + ".marks.jsonl"
            if os.path.exists(mpath):
                marks = list(read_events(mpath))
            out.append({"name": name, "size_mb": round(os.path.getsize(path) / 1e6, 1),
                        "modified": os.path.getmtime(path), "marks": marks,
                        "journal": os.path.exists(path[:-6] + ".journal.md"),
                        "current": self.recording and os.path.abspath(self.engine.recorder.path) == os.path.abspath(path)})
        return out[:40]

    def open_replay(self, name, port, speed=1.0):
        """Start the replay desk for a recording in a second TWINEY on another port."""
        path = os.path.join(self.dir, os.path.basename(name))
        if not os.path.exists(path) or not name.endswith(".jsonl"):
            return {"ok": False, "reason": "no such recording"}
        if self.replay_proc is not None and self.replay_proc.poll() is None:
            self.replay_proc.terminate()
        script = os.path.join(self.base_dir, "run_twiney.py")
        cmd = [sys.executable, script, "--replay", path, "--speed", str(speed), "--port", str(port), "--no-browser"]
        for flag in ("--config", "--plays"):
            pass
        self.replay_proc = subprocess.Popen(cmd, cwd=self.base_dir)
        return {"ok": True, "url": f"http://127.0.0.1:{port}", "pid": self.replay_proc.pid}


def dump_state(engine, rec, t):
    """Write the engine's current state as ordinary events so a recording started
    mid-session replays with full books, charts and plays."""
    with engine.lock:
        for sym, st in engine.syms.items():
            for f, v in st.l1.items():
                if v is not None:
                    rec.write({"ev": "l1", "t": t, "sym": sym, "f": f, "v": v})
            for k in sorted(st.daily):
                o, h, l, c = st.daily[k]
                rec.write({"ev": "dbar", "t": t, "sym": sym, "t0": k, "o": o, "h": h, "l": l, "c": c})
            for b in st.bar_list():
                rec.write({"ev": "hbar", "t": t, "sym": sym, "t0": b[0], "o": b[1], "h": b[2], "l": b[3], "c": b[4], "v": b[5]})
            if st.retired:
                rec.write({"ev": "retire", "t": t, "sym": sym, "reason": st.retired["reason"]})
        for sym in engine.slots:
            rec.write({"ev": "slot", "t": t, "sym": sym, "on": True, "reason": "dump"})
            st = engine.syms[sym]
            if st.book is not None:
                for side in (BID, ASK):
                    for i, (price, size, _n) in enumerate(st.book.levels(side)):
                        rec.write({"ev": "depth", "t": t, "sym": sym, "pos": i, "op": INSERT, "side": side,
                                   "px": price, "sz": size, "mm": ""})
        for key, verdict in engine.grades.items():
            rec.write({"ev": "grade", "t": t, "key": key, "verdict": verdict})
