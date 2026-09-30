"""The recording desk: REC on / off, markers, screenshots, session journal, replay launcher.

Everything a prop desk does with a session after the fact starts here:
  - start / stop a recording at any moment (space bar); a recording started
    mid-session first dumps the current state so it replays cleanly
  - drop a marker (M) with the symbol and what the story said at that second
  - take a screenshot (P) of the whole screen into recordings/shots/
  - on stop, write a one-page journal next to the recording
  - list recordings with their markers, and open one in the replay desk
"""

import csv
import io
import json
import os
import subprocess
import sys
import time
import zipfile

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
        self.trades = []          # closed round trips, each with its PS60 setup / grade / note
        self._open = {}           # symbol -> the trade being built from fills (saved, so a restart keeps it)
        self._load_trades()
        engine.desk = self

    # ---- trade journal: every round trip, categorised by the PS60 setup you were trading -------------

    SETUPS = ["Macro break (60m supply)", "Macro breakdown (60m demand)", "Large MP", "Second entry", "Remount",
              "Sneaky pivot", "50-day breakout", "50-day breakdown", "200-day break", "MA bounce", "MA rejection",
              "Gap and go", "Gap fill", "Squeeze", "Capitulation bounce", "Range break", "Scalp", "Other"]

    @property
    def trades_path(self):
        return os.path.join(self.dir, "trades.jsonl")

    @property
    def open_path(self):
        return os.path.join(self.dir, "open_trades.json")

    def _load_trades(self):
        """Line by line: a damaged line (a crash mid-write) is skipped, never the whole journal."""
        self.trades, self._seen = [], set()
        try:
            with open(self.trades_path, encoding="utf-8") as fh:
                for line in fh:
                    try:
                        tr = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(tr, dict):
                        self.trades.append(tr)
        except OSError:
            pass
        self.trades = self.trades[-500:]
        try:   # a position open when the desk closed carries on after the restart
            with open(self.open_path, encoding="utf-8") as fh:
                self._open = {k: v for k, v in json.load(fh).items() if isinstance(v, dict)}
        except (OSError, ValueError, AttributeError):
            self._open = {}
        for tr in self.trades + list(self._open.values()):
            self._seen.update(tr.get("execs") or [])
        self._seq = len(self.trades) + len(self._open)

    def _write_trades(self):
        os.makedirs(self.dir, exist_ok=True)
        tmp = self.trades_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            for tr in self.trades[-500:]:
                fh.write(json.dumps(tr) + "\n")
        os.replace(tmp, self.trades_path)          # all or nothing: never a half-written journal

    def _write_open(self):
        os.makedirs(self.dir, exist_ok=True)
        tmp = self.open_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self._open, fh)
        os.replace(tmp, self.open_path)

    def _new_trade(self, sym, signed, t):
        play = next((p for p in self.plays if p["symbol"] == sym), None) or getattr(self.engine, "syms", {}).get(sym)
        play = getattr(play, "play", play) or {}
        self._seq += 1
        return {"id": f"{sym}-{int(t)}-{self._seq}", "symbol": sym, "side": "long" if signed > 0 else "short",
                "opened": t, "closed": None, "qty": 0.0, "entry_qty": 0.0, "entry_cost": 0.0,
                "exit_qty": 0.0, "exit_cost": 0.0, "setup": play.get("setup") or "",
                "grade": "", "note": "", "pnl": None, "pnl_pct": None, "execs": [],
                "flow": self.engine.flow.context_text(sym, t) if getattr(self.engine, "flow", None) else ""}

    def on_fill(self, fill, t):
        """Build round trips from fills: open on the first fill, close when the position is back to flat.
        Each execution counts once (IBKR re-sends the day's executions); a fill that goes through zero
        closes this trade and opens the next one in the other direction with what is left."""
        sym, qty = fill["symbol"], float(fill["shares"])
        ex = fill.get("exec_id")
        if ex:
            if ex in self._seen:
                return
            self._seen.add(ex)
        signed = qty if fill["side"] == "BOT" else -qty
        while abs(signed) > 1e-9:
            tr = self._open.get(sym)
            if tr is None:
                tr = self._open[sym] = self._new_trade(sym, signed, t)
            long_ = tr["side"] == "long"
            if ex and ex not in tr["execs"]:
                tr["execs"].append(ex)
            if (signed > 0) == long_:                       # adding
                tr["entry_qty"] += abs(signed); tr["entry_cost"] += abs(signed) * fill["price"]
                tr["qty"] += signed
                signed = 0.0
            else:                                            # reducing: never past flat inside one trade
                take = min(abs(signed), abs(tr["qty"]))
                tr["exit_qty"] += take; tr["exit_cost"] += take * fill["price"]
                tr["qty"] += take if signed > 0 else -take
                signed += -take if signed > 0 else take
            if abs(tr["qty"]) < 1e-9 and tr["entry_qty"] > 0:
                self._close(sym, tr, t)
        self._write_open()

    def _close(self, sym, tr, t):
        long_ = tr["side"] == "long"
        entry = tr["entry_cost"] / tr["entry_qty"]; exit_ = tr["exit_cost"] / max(tr["exit_qty"], 1e-9)
        tr["entry"], tr["exit"] = round(entry, 4), round(exit_, 4)
        tr["pnl"] = round((exit_ - entry) * tr["entry_qty"] * (1 if long_ else -1), 2)
        tr["pnl_pct"] = round((exit_ - entry) / entry * 100 * (1 if long_ else -1), 3) if entry else None
        tr["closed"] = t
        tr["shares"] = tr["entry_qty"]
        self.trades.append({k: v for k, v in tr.items() if k not in ("qty", "entry_cost", "exit_cost", "exit_qty", "entry_qty")})
        self.engine._rec({"ev": "trade", "t": t, "trade": self.trades[-1]})
        self._write_trades()
        del self._open[sym]

    def tag_trade(self, trade_id, setup=None, grade=None, note=None):
        for tr in self.trades:
            if tr["id"] == trade_id:
                if setup is not None: tr["setup"] = str(setup)[:40]
                if grade is not None: tr["grade"] = str(grade)[:4]
                if note is not None: tr["note"] = str(note)[:300]
                self.engine._rec({"ev": "trade_tag", "t": time.time(), "id": trade_id, "setup": tr["setup"], "grade": tr["grade"], "note": tr["note"]})
                self._write_trades()
                return True
        return False

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

    def export_bundle(self, name, t=None):
        """One zip with everything about a session, made for handing to a person or an AI:
        the raw recording, markers, journal, screenshots, and a compact SUMMARY.md + calls.csv."""
        name = os.path.basename(name)
        path = os.path.join(self.dir, name)
        if not name.endswith(".jsonl") or not os.path.exists(path):
            return None
        stem = name[:-6]
        current = self.recording and os.path.abspath(self.engine.recorder.path) == os.path.abspath(path)
        journal = path[:-6] + ".journal.md"
        if current:
            # export while still recording: write the journal so far, keep recording
            journal = self.write_journal(path, t or time.time())
            os.replace(journal, path[:-6] + ".journal.md")
            journal = path[:-6] + ".journal.md"
        header, calls, grades, marks, notes, fills, orders = None, [], {}, [], [], [], []
        first_t = last_t = None
        n_events = 0
        for ev in read_events(path):
            n_events += 1
            k = ev.get("ev")
            if k == "session":
                header = ev
            elif k == "alert":
                calls.append(ev)
            elif k == "grade":
                if ev.get("verdict"):
                    grades[ev["key"]] = ev["verdict"]
                else:
                    grades.pop(ev["key"], None)
            elif k == "mark":
                marks.append(ev)
            elif k == "note":
                notes.append(ev)
            elif k == "order":
                orders.append(ev)
            if ev.get("t") is not None and k not in ("session",):
                first_t = ev["t"] if first_t is None else min(first_t, ev["t"])
                last_t = ev["t"] if last_t is None else max(last_t, ev["t"])
        if current:
            fills = sorted(self.engine.fills.values(), key=lambda f: f["t"])
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(path, f"{stem}/{name}")
            for extra in (path[:-6] + ".marks.jsonl", journal):
                if os.path.exists(extra):
                    z.write(extra, f"{stem}/{os.path.basename(extra)}")
            shots = os.path.join(self.dir, "shots")
            if os.path.isdir(shots):
                for f in sorted(os.listdir(shots)):
                    if f.startswith(stem + "-"):
                        z.write(os.path.join(shots, f), f"{stem}/shots/{f}")
            # calls.csv
            cs = io.StringIO()
            w = csv.writer(cs)
            w.writerow(["time", "symbol", "call", "price", "side", "role", "absorbed_shares", "refills", "grade", "text"])
            for a in calls:
                w.writerow([time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(a["t"])), a["symbol"], a["label"], a["price"],
                            a.get("side"), a.get("role"), a.get("absorbed"), a.get("refreshes"), grades.get(a.get("key"), ""),
                            a.get("text", "")])
            z.writestr(f"{stem}/calls.csv", cs.getvalue())
            # SUMMARY.md — what an AI needs first
            fmt = lambda x: time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(x)) if x else "—"
            s = [f"# TWINEY session {stem}", "",
                 "This bundle is a TWINEY (PS60 order-flow workstation) session. Files:",
                 f"- `{name}`: every raw event as JSON lines (l1 quotes, depth book ops, prints, calls, orders, marks, notes).",
                 "- `calls.csv`: the calls TWINEY made (reload buyer/seller, cleaned up, pulled, remount, rejection) with the trader's grades.",
                 "- `*.journal.md`: the trader's session journal. `*.marks.jsonl`: markers. `shots/`: screenshots.", "",
                 f"- Session: {fmt(first_t)} → {fmt(last_t)}  ({((last_t or 0) - (first_t or 0)) / 60:.0f} min), {n_events:,} events",
                 f"- TWINEY version: {header.get('version') if header else '?'}", ""]
            if header:
                s += ["## Plays (the trader's PS60 levels)", "", "| symbol | side | pivot | 2nd entry | target | stop | mp | atr | notes |", "|---|---|---|---|---|---|---|---|---|"]
                for p in header.get("plays", []):
                    s.append(f"| {p['symbol']} | {p['side']} | {p.get('trigger')} | {p.get('second_entry') or ''} | {p.get('target') or ''} | {p.get('stop') or ''} | {p.get('mp') or ''} | {p.get('atr') or ''} | {p.get('notes', '')} |")
                s += ["", "## Settings that shaped the calls", "", "```json", json.dumps({k: header.get("config", {}).get(k) for k in ("reload", "tape", "trap", "ps60", "voice")}, indent=1), "```", ""]
            s += ["## Calls", ""] + ([f"- {fmt(a['t'])} **{a['symbol']} {a['label']}** @ {a['price']}" + (f" — graded {grades[a['key']].upper()}" if a.get("key") in grades else "") + f"\n  {a.get('text', '')}" for a in calls] or ["_none_"])
            s += ["", "## Notes", ""] + ([f"- {fmt(n['t'])} {n.get('symbol') or ''}: {n['text']}" for n in notes] or ["_none_"])
            s += ["", "## Markers", ""] + ([f"- {fmt(m['t'])} {m.get('symbol') or ''} {m.get('price') or ''} — {m.get('note') or ''} {('— ' + m['headline']) if m.get('headline') else ''}" for m in marks] or ["_none_"])
            s += ["", "## Orders sent", ""] + ([f"- {fmt(o['t'])} {o['action']} {o['qty']} {o['sym']} @ {o['px']}" + (f" + {', '.join(l['role'] + ' ' + str(l.get('aux') or l['price']) for l in o.get('legs', []))}" if o.get("legs") else "") for o in orders] or ["_none_"])
            if fills:
                s += ["", "## Fills (this session)", ""] + [f"- {f['time']} {f['symbol']} {f['side']} {int(f['shares'])} @ {f['price']}" for f in fills]
            s += ["", "## Vocabulary", "",
                  "- RELOAD BUYER / SELLER: resting size at a price kept coming back after being hit (refills) while shares traded into it (absorbed).",
                  "- CLEANED UP: that reload got eaten and price went through the level. PULLED: it vanished without getting hit.",
                  "- REMOUNT: price went through a level and reclaimed it. REJECTION: went through and lost it again.",
                  "- Pivot, second entry, measured potential (MP), ATR, cash flow, runner, max pain: PS60 terms (Dan Shapiro).", ""]
            z.writestr(f"{stem}/SUMMARY.md", "\n".join(s))
        return buf.getvalue()

    def delete_recording(self, name):
        """Delete a recording and everything that belongs to it (markers, journal, screenshots)."""
        name = os.path.basename(name)
        path = os.path.join(self.dir, name)
        if not name.endswith(".jsonl") or not os.path.exists(path):
            return {"ok": False, "reason": "no such recording"}
        if self.recording and os.path.abspath(self.engine.recorder.path) == os.path.abspath(path):
            return {"ok": False, "reason": "that one is recording right now — stop it first (space bar)"}
        stem = name[:-6]
        removed = []
        for f in (path, path[:-6] + ".marks.jsonl", path[:-6] + ".journal.md"):
            if os.path.exists(f):
                os.remove(f)
                removed.append(os.path.basename(f))
        shots = os.path.join(self.dir, "shots")
        if os.path.isdir(shots):
            for f in os.listdir(shots):
                if f.startswith(stem + "-"):
                    os.remove(os.path.join(shots, f))
                    removed.append("shots/" + f)
        return {"ok": True, "removed": removed}

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
                rec.write({"ev": "dbar", "t": t, "sym": sym, "t0": k, "o": o, "h": h, "l": l, "c": c, "v": st.daily_vol.get(k)})
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
