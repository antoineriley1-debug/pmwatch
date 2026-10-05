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


def _hm(t):
    """New York wall clock, HH:MM, for a log line."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    try:
        return datetime.fromtimestamp(float(t), ZoneInfo("America/New_York")).strftime("%H:%M")
    except (TypeError, ValueError, OSError):
        return "--:--"


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
        self.voice_notes = {}   # voice notes taken without a recording: n (negative) -> {t, symbol, audio}
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

    def _new_trade(self, sym, signed, t, fill=None):
        fill = fill or {}
        under = sym.split(" ")[0]                     # an option trade is filed under its stock
        st = getattr(self.engine, "syms", {}).get(under)
        play = (st.play if st is not None else None) or next((p for p in self.plays if p["symbol"] == under), None) or {}
        self._seq += 1
        opt = bool(fill.get("opt"))
        # the PLAN at the moment you got in: the lines on the chart for the direction you took (a put / short rides the
        # short side). Kept with the trade, so the result is judged against what you planned
        bull = (signed > 0) if not opt else ((sym.split(" ")[2].endswith("C")) == (signed > 0))
        own_long = play.get("side", "long") == "long"
        lines = play if bull == own_long else (play.get("alt") or {})
        plan = {k: lines.get(k) for k in ("trigger", "second_entry", "stop", "target") if lines.get(k)}
        side = "long" if signed > 0 else "short"
        from datetime import datetime
        from zoneinfo import ZoneInfo
        when = datetime.fromtimestamp(t, ZoneInfo("America/New_York")).strftime("%m/%d %H:%M")
        what = (" ".join(sym.split(" ")[2:]) if opt else side.upper())
        return {"id": f"{sym.replace(' ', '_')}-{int(t)}-{self._seq}", "symbol": sym, "underlying": under, "side": side,
                "opt": opt, "mult": float(fill.get("mult") or (100 if opt else 1)),
                "name": f"{under} {what} {('· ' + play.get('setup')) if play.get('setup') else ''} {when}".replace("  ", " ").strip(),
                "opened": t, "closed": None, "qty": 0.0, "entry_qty": 0.0, "entry_cost": 0.0,
                "exit_qty": 0.0, "exit_cost": 0.0, "setup": play.get("setup") or "",
                "grade": "", "note": "", "pnl": None, "pnl_pct": None, "execs": [], "plan": plan,
                "rec": self.current_recording(),
                "flow": self.engine.flow.context_text(under, t) if getattr(self.engine, "flow", None) else ""}

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
        if not fill.get("opt"):            # the fill in the trade's log (an option fill is logged by the engine)
            self.add_note(t, f"FILL {'BOUGHT' if signed > 0 else 'SOLD'} {qty:g} {sym} @ {fill['price']}", sym, kind="fill")
        while abs(signed) > 1e-9:
            tr = self._open.get(sym)
            if tr is None:
                tr = self._open[sym] = self._new_trade(sym, signed, t, fill)
            long_ = tr["side"] == "long"
            if ex and ex not in tr["execs"]:
                tr["execs"].append(ex)
            tr["t_last"] = t
            if (signed > 0) == long_:                       # adding
                tr["entry_qty"] += abs(signed); tr["entry_cost"] += abs(signed) * fill["price"]
                tr["qty"] += signed
                tr.setdefault("legs", []).append([ex, signed, fill["price"], "entry"])
                signed = 0.0
            else:                                            # reducing: never past flat inside one trade
                take = min(abs(signed), abs(tr["qty"]))
                tr["exit_qty"] += take; tr["exit_cost"] += take * fill["price"]
                part = take if signed > 0 else -take
                tr["qty"] += part
                tr.setdefault("legs", []).append([ex, part, fill["price"], "exit"])
                signed -= part
            if abs(tr["qty"]) < 1e-9 and tr["entry_qty"] > 0:
                self._close(sym, tr, t)
        self._write_open()

    def correct_fill(self, old, new, t):
        """IBKR corrected an execution: take the old one out of the open trade and put the corrected one in."""
        ex = old.get("exec_id")
        tr = self._open.get(old["symbol"])
        if tr is None or not any(l[0] == ex for l in tr.get("legs", [])):
            self.engine._message("warn", f"{old['symbol']}: a corrected execution belongs to a trade already closed "
                                         f"in the journal — check that trade's numbers", t, old["symbol"])
            return
        keep = []
        for leg in tr["legs"]:
            if leg[0] != ex:
                keep.append(leg)
                continue
            _e, part, px, kind = leg
            if kind == "entry":
                tr["entry_qty"] -= abs(part); tr["entry_cost"] -= abs(part) * px
            else:
                tr["exit_qty"] -= abs(part); tr["exit_cost"] -= abs(part) * px
            tr["qty"] -= part
        tr["legs"] = keep
        if ex in tr.get("execs", []):
            tr["execs"].remove(ex)
        self._seen.discard(ex)
        if abs(tr["qty"]) < 1e-9 and not keep:
            del self._open[old["symbol"]]
        self.on_fill(new, t)

    def _close(self, sym, tr, t):
        long_ = tr["side"] == "long"
        mult = float(tr.get("mult") or 1)
        entry = tr["entry_cost"] / tr["entry_qty"]; exit_ = tr["exit_cost"] / max(tr["exit_qty"], 1e-9)
        tr["entry"], tr["exit"] = round(entry, 4), round(exit_, 4)
        tr["pnl"] = round((exit_ - entry) * tr["entry_qty"] * mult * (1 if long_ else -1), 2)
        tr["pnl_pct"] = round((exit_ - entry) / entry * 100 * (1 if long_ else -1), 3) if entry else None
        tr["closed"] = t
        tr["shares"] = tr["entry_qty"]
        tr["minutes"] = round((t - (tr.get("opened") or t)) / 60.0, 1)
        # the RESULT: win / loss (a scratch is within a tenth of a percent), and R against the stop you planned
        tr["result"] = "SCRATCH" if tr["pnl_pct"] is not None and abs(tr["pnl_pct"]) < 0.1 else ("WIN" if tr["pnl"] > 0 else "LOSS")
        stop = (tr.get("plan") or {}).get("stop")
        if stop and not tr.get("opt") and abs(entry - stop) > 1e-9:
            tr["r"] = round((exit_ - entry) * (1 if long_ else -1) / abs(entry - stop), 2)
        self._fill_story(tr, t)
        self.trades.append({k: v for k, v in tr.items() if k not in ("qty", "entry_cost", "exit_cost", "exit_qty", "entry_qty", "legs")})
        self.engine._rec({"ev": "trade", "t": t, "trade": self.trades[-1]})
        self._write_trades()
        del self._open[sym]
        try:
            self.save_trade(self.trades[-1]["id"])
        except Exception:
            pass
        self.engine._message("info", f"JOURNAL: {self.trades[-1]['name']} — {tr['result']} {tr['pnl']:+,.2f}"
                                     + (f" ({tr['r']:+.2f}R)" if tr.get("r") is not None else "") + " · saved", t, tr.get("underlying"))

    def _fill_story(self, tr, t):
        """The trade log (everything set, sent, filled, said and marked on the stock from a little before the entry to the
        exit), the spoken TRANSCRIPT on its own, and the MARKS with what the screen showed."""
        under = tr.get("underlying") or tr["symbol"].split(" ")[0]
        since, until = (tr.get("opened") or t) - 600, t + 1
        notes = [n for n in self.notes if n.get("symbol") in (under, tr["symbol"]) and since <= n["t"] <= until]
        tr["log"] = " | ".join(f"{_hm(n['t'])} {n['text']}" for n in notes)[:6000]
        tr["transcript"] = [{"t": n["t"], "text": n["text"].lstrip("🎙 ").strip()} for n in notes if n.get("kind") == "voice"][-40:]
        tr["marks"] = [{"t": m["t"], "price": m.get("price"), "note": m.get("note"), "context": m.get("context"), "shot": m.get("shot")}
                       for m in self.marks if m.get("symbol") in (under, tr["symbol"]) and since <= m["t"] <= until][-40:]

    def reconcile(self, t):
        """An open journal trade must be a real position. One the broker shows FLAT (closed while TED was off, or a
        practice session that ended) is dropped, said once, so the next trade on that ticker starts fresh. Never in the
        10 s after a fill (the position report trails it); live, only once positions have had 20 s to arrive."""
        eng = self.engine
        first = self.__dict__.setdefault("_recon_first", t)
        state = (getattr(eng, "connection", {}) or {}).get("state")
        if state not in ("DEMO", "CONNECTED"):
            return
        if state == "CONNECTED" and (t - first < 20 or not getattr(eng, "account_seen", False)):
            return
        changed = False
        for sym, tr in list(self._open.items()):
            if t - float(tr.get("t_last") or tr.get("opened") or 0) < 10:
                continue
            if tr.get("opt"):
                held = float((getattr(eng, "opt_positions", {}).get(sym) or {}).get("qty") or 0)
            else:
                held = sum(float(p.get("qty") or 0) for (a, s_), p in list(eng.positions.items()) if s_ == sym)
            if held == 0 and abs(float(tr.get("qty") or 0)) > 1e-9:
                del self._open[sym]
                changed = True
                eng._message("warn", f"JOURNAL: the open {sym} trade from {_hm(tr.get('opened') or t)} was dropped — the position is "
                                     f"flat (it was closed while TED was not watching, so its exit price is not known)", t, sym.split(" ")[0])
        if changed:
            self._write_open()

    def open_view(self):
        """The trades you are IN right now, for the JOURNAL: live P&L, the plan, the log and the words so far."""
        out = []
        for sym, tr in list(self._open.items()):
            if not tr.get("entry_qty"):
                continue
            avg = tr["entry_cost"] / tr["entry_qty"]
            under = tr.get("underlying") or sym.split(" ")[0]
            if tr.get("opt"):
                q = (getattr(self.engine, "opt_quotes", {}) or {}).get(sym) or {}
                now = (q["bid"] + q["ask"]) / 2 if q.get("bid") and q.get("ask") else q.get("last")
            else:
                st = self.engine.syms.get(sym)
                now = st.price() if st else None
            pnl = round((now - avg) * tr["qty"] * float(tr.get("mult") or 1), 2) if now else None
            view = dict({k: v for k, v in tr.items() if k not in ("legs", "execs")}, entry=round(avg, 4), now=now, pnl=pnl, open=True)
            self._fill_story(view, time.time())
            out.append(view)
        return out

    def journal_dir(self):
        return os.path.join(self.dir, "journal")

    def save_trade(self, trade_id):
        """One page per trade, next to the recordings: journal/<date>-<name>.md — the plan, the fills, the result, what
        you said and what you marked. Re-written when you rename or grade it."""
        tr = next((x for x in self.trades if x["id"] == trade_id), None)
        if tr is None:
            return None
        from datetime import datetime
        from zoneinfo import ZoneInfo
        ny = ZoneInfo("America/New_York")
        when = lambda x: datetime.fromtimestamp(x, ny).strftime("%Y-%m-%d %H:%M:%S") if x else "—"
        os.makedirs(self.journal_dir(), exist_ok=True)
        safe = "".join(ch if ch.isalnum() or ch in "-_ " else "-" for ch in (tr.get("name") or tr["id"]))[:60].strip().replace(" ", "_")
        old = tr.get("file")
        name = f"{datetime.fromtimestamp(tr.get('opened') or time.time(), ny).strftime('%Y-%m-%d-%H%M')}-{safe}.md"
        mult = float(tr.get("mult") or 1)
        unit = "contracts" if tr.get("opt") else "shares"
        plan = tr.get("plan") or {}
        L = [f"# {tr.get('name') or tr['id']}", "",
             f"**{tr.get('result', '—')}  {tr['pnl']:+,.2f} $**  ({tr.get('pnl_pct') or 0:+.2f}%" + (f", {tr['r']:+.2f}R" if tr.get("r") is not None else "") + ")" if tr.get("pnl") is not None else "", "",
             f"- {tr['symbol']} · {tr['side'].upper()} {tr.get('shares', 0):g} {unit}" + (f" (× {mult:g})" if tr.get("opt") else ""),
             f"- In {when(tr.get('opened'))} @ {tr.get('entry')} · out {when(tr.get('closed'))} @ {tr.get('exit')} · {tr.get('minutes', '—')} min",
             f"- Setup: {tr.get('setup') or '—'} · grade: {tr.get('grade') or '—'}",
             f"- Plan: " + (" · ".join(f"{k.replace('_', ' ').replace('trigger', 'pivot')} {v}" for k, v in plan.items()) or "—"),
             f"- Option flow at entry: {tr.get('flow') or '—'}",
             f"- Recording: {tr.get('rec') or '—'}", "",
             "## Note", "", tr.get("note") or "_—_", "",
             "## What you said (transcript)", ""]
        L += [f"- **{_hm(x['t'])}** {x['text']}" for x in (tr.get("transcript") or [])] or ["_nothing recorded_"]
        L += ["", "## Marks", ""]
        L += [f"- **{_hm(m['t'])}** {m.get('price') or ''} {m.get('note') or ''}" + (f" — {m['context']}" if m.get("context") else "")
              + (f" — ![shot](../{m['shot']})" if m.get("shot") else "") for m in (tr.get("marks") or [])] or ["_none_"]
        L += ["", "## Everything that happened", ""]
        L += [f"- {line}" for line in (tr.get("log") or "").split(" | ") if line] or ["_—_"]
        path = os.path.join(self.journal_dir(), name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(L) + "\n")
        if old and old != name:
            try:
                os.remove(os.path.join(self.journal_dir(), old))
            except OSError:
                pass
        tr["file"] = name
        self._write_trades()
        return name

    def trades_csv(self):
        """The whole trade journal as a spreadsheet (opens in Excel / Google Sheets). Times in New York time."""
        import csv, io
        from datetime import datetime
        from zoneinfo import ZoneInfo
        ny = ZoneInfo("America/New_York")
        when = lambda x: datetime.fromtimestamp(x, ny).strftime("%Y-%m-%d %H:%M:%S") if x else ""
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["date / time opened (ET)", "closed (ET)", "symbol", "side", "shares", "entry", "exit",
                    "P&L $", "P&L %", "setup", "grade", "note", "option flow at entry", "trade log", "trade id"])
        for tr in self.trades:
            w.writerow([when(tr.get("opened")), when(tr.get("closed")), tr.get("symbol"), tr.get("side"),
                        tr.get("shares"), tr.get("entry"), tr.get("exit"), tr.get("pnl"), tr.get("pnl_pct"),
                        tr.get("setup"), tr.get("grade"), tr.get("note"), tr.get("flow"), tr.get("log", ""), tr.get("id")])
        return out.getvalue()

    def tag_trade(self, trade_id, setup=None, grade=None, note=None, name=None):
        """Name, setup, grade and note: on a closed trade (its page is saved again) or on the one you are in now."""
        for tr in self.trades:
            if tr["id"] == trade_id:
                if setup is not None: tr["setup"] = str(setup)[:40]
                if grade is not None: tr["grade"] = str(grade)[:4]
                if note is not None: tr["note"] = str(note)[:2000]
                if name is not None and str(name).strip(): tr["name"] = str(name).strip()[:80]
                self.engine._rec({"ev": "trade_tag", "t": time.time(), "id": trade_id, "setup": tr["setup"], "grade": tr["grade"],
                                  "note": tr["note"], "name": tr.get("name")})
                self._write_trades()
                self.save_trade(trade_id)
                return True
        for tr in self._open.values():
            if tr["id"] == trade_id:
                if setup is not None: tr["setup"] = str(setup)[:40]
                if grade is not None: tr["grade"] = str(grade)[:4]
                if note is not None: tr["note"] = str(note)[:2000]
                if name is not None and str(name).strip(): tr["name"] = str(name).strip()[:80]
                self._write_open()
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
        self.voice_notes = {}   # voice notes taken without a recording: n (negative) -> {t, symbol, audio}
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

    def current_recording(self):
        return os.path.basename(self.engine.recorder.path) if self.recording and self.engine.recorder else None

    # ---- the mic: spoken journal entries during a recording -----------------------------------------
    def mic_start(self, t, symbol=None):
        """The mic went on. Recording: a marker right now, so the moment is on the recording before anything is
        said. Not recording: a voice note on its own, stamped now, going straight into the symbol's trade log."""
        if self.recording:
            return self.mark(t, symbol, "🎙 voice note")
        n = -(len(self.voice_notes) + 1)
        self.voice_notes[n] = {"n": n, "t": t, "symbol": symbol, "voice": True}
        return self.voice_notes[n]

    def mic_text(self, n, text, t1):
        """What was said becomes the journal entry, stamped at the moment the mic went on (and the marker's note
        when there is a recording)."""
        n = int(n)
        text = " ".join(str(text or "").split())[:4000]
        if n < 0:
            v = self.voice_notes.get(n)
            if v is None:
                raise ValueError("no such voice note")
            if not text:
                text = "(voice note — no words picked up; the audio is saved)"
            self.add_note(v["t"], "🎙 " + text, v.get("symbol"), kind="voice", voice=n)
            return v
        m = next((m for m in self.marks if m.get("n") == n), None)
        if m is None:
            raise ValueError("no such marker")
        if not text:
            text = "(voice note — no words picked up; the audio is saved with the marker)"
        m["note"] = "🎙 " + text[:280]
        m["voice"] = True
        self.engine._rec({"ev": "mark_note", "t": t1, "n": n, "note": m["note"]})
        self.add_note(m["t"], "🎙 " + text, m.get("symbol"), mark=n, rec=self.current_recording(), kind="voice")
        self._rewrite_marks()
        return m

    def mic_audio(self, n, data, ext, t1):
        """The voice note's audio, saved next to the recording and hung on its marker (to hear it again); a
        voice note taken without a recording is saved under its own name."""
        n = int(n)
        folder = os.path.join(self.dir, "voice")
        os.makedirs(folder, exist_ok=True)
        if n < 0:
            v = self.voice_notes.get(n)
            if v is None:
                raise ValueError("no such voice note")
            name = f"note-{int(v['t'])}-{abs(n)}.{ext}"
            with open(os.path.join(folder, name), "wb") as fh:
                fh.write(data)
            v["audio"] = name
            self.engine._rec({"ev": "note_audio", "t": t1, "n": n, "audio": name})
            return v
        m = next((m for m in self.marks if m.get("n") == n), None)
        if m is None:
            raise ValueError("no such marker")
        rec = self.current_recording() or "session.jsonl"
        name = f"{rec[:-6]}-{n}.{ext}"
        with open(os.path.join(folder, name), "wb") as fh:
            fh.write(data)
        m["audio"] = name
        m["audio_s"] = round(max(0.0, t1 - m["t"]), 1)
        self.engine._rec({"ev": "mark_audio", "t": t1, "n": int(n), "audio": name, "audio_s": m["audio_s"]})
        self._rewrite_marks()
        return m

    def _rewrite_marks(self):
        if not self.recording:
            return
        path = self.engine.recorder.path[:-6] + ".marks.jsonl"
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            for x in self.marks:
                fh.write(json.dumps(x) + "\n")
        os.replace(tmp, path)

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
        context = self._screen_context(symbol, t)
        m = {"t": t, "symbol": symbol, "price": price, "note": note or "", "headline": headline, "shot": shot,
             "n": len(self.marks) + 1, "context": context}
        self.marks.append(m)
        self.engine._rec(dict(m, ev="mark"))
        if symbol and not (note or "").startswith("🎙"):   # a voice note's words land on their own when you stop talking
            self.add_note(t, f"⚑ MARK {price if price is not None else ''} {('— ' + note) if note else ''} — {context}".replace("  ", " "),
                          symbol, kind="mark", mark=m["n"])
        if self.recording:
            with open(self.engine.recorder.path[:-6] + ".marks.jsonl", "a", encoding="utf-8") as fh:
                fh.write(json.dumps(m) + "\n")
        return m

    def _screen_context(self, symbol, t):
        """What the screen showed at that second, in one line: price, quote, your position and its P&L, your lines, the
        PS60 read, the reload buyer / seller, the option you hold and the flow."""
        eng = self.engine
        st = eng.syms.get(symbol) if symbol else None
        if st is None:
            return ""
        parts = []
        try:
            bid, ask = st.bbo()
            parts.append(f"{symbol} {st.price()}" + (f" ({bid} × {ask})" if bid and ask else ""))
            pos = sum(p["qty"] for (a, s_), p in eng.positions.items() if s_ == symbol)
            if pos:
                parts.append(f"{'LONG' if pos > 0 else 'SHORT'} {abs(pos):g}")
            for k, p in list(getattr(eng, "opt_positions", {}).items()):
                if k.split(" ")[0] == symbol and p.get("qty"):
                    parts.append(f"holding {p['qty']:g} {k}")
            pl = st.play
            lv = [f"{n} {pl[k]}" for k, n in (("trigger", "pivot"), ("second_entry", "2nd"), ("stop", "stop"), ("target", "target")) if pl.get(k)]
            if lv:
                parts.append(" · ".join(lv))
            for tr in st.trackers.values():
                if tr.proven and tr.displayed > 0:
                    parts.append(f"RELOAD {'BUYER' if tr.side == BID else 'SELLER'} {tr.price} ↻{tr.proven_refills}")
            try:
                tp = st.tape.stats(t) or {}
                if tp.get("read"):
                    parts.append(f"tape {tp['read']}")
            except Exception:
                pass
            if getattr(eng, "flow", None):
                fl = eng.flow.context_text(symbol, t)
                if fl:
                    parts.append("flow: " + fl[:120])
        except Exception:
            pass
        return " · ".join(x for x in parts if x)[:600]

    def add_note(self, t, text, symbol=None, **extra):
        text = text.strip()
        if text:
            n = dict({"t": t, "symbol": symbol, "text": text}, **extra)
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

    # ---- ★ good sessions: flagged so they are easy to find among the recordings ----------------------
    @property
    def flags_path(self):
        return os.path.join(self.dir, "flags.json")

    def _flags(self):
        try:
            with open(self.flags_path, encoding="utf-8") as fh:
                f = json.load(fh)
            return f if isinstance(f, dict) else {}
        except (OSError, ValueError):
            return {}

    def flag(self, name, on=True):
        name = os.path.basename(str(name))
        if not name.endswith(".jsonl") or not os.path.exists(os.path.join(self.dir, name)):
            return False
        f = self._flags()
        if on:
            f[name] = True
        else:
            f.pop(name, None)
        os.makedirs(self.dir, exist_ok=True)
        tmp = self.flags_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(f, fh)
        os.replace(tmp, self.flags_path)
        return True

    def list_recordings(self):
        out = []
        if not os.path.isdir(self.dir):
            return out
        flags = self._flags()
        for name in sorted(os.listdir(self.dir), reverse=True):
            if not name.endswith(".jsonl") or name.endswith(".marks.jsonl") or name in NOT_SESSIONS:
                continue
            path = os.path.join(self.dir, name)
            marks = []
            mpath = path[:-6] + ".marks.jsonl"
            if os.path.exists(mpath):
                marks = list(read_events(mpath))
            out.append({"name": name, "size_mb": round(os.path.getsize(path) / 1e6, 1), "flag": flags.get(name, False),
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

    def open_replay(self, name, port, speed=1.0, start=None, end=None):
        """Start the replay desk for a recording in a second TWINEY on another port."""
        path = os.path.join(self.dir, os.path.basename(name))
        if not os.path.exists(path) or not name.endswith(".jsonl"):
            return {"ok": False, "reason": "no such recording"}
        if self.replay_proc is not None and self.replay_proc.poll() is None:
            self.replay_proc.terminate()
        script = os.path.join(self.base_dir, "run_twiney.py")
        cmd = [sys.executable, script, "--replay", path, "--speed", str(speed), "--port", str(port), "--no-browser"]
        if start is not None:
            cmd += ["--start", str(float(start))]
        if end is not None:
            cmd += ["--end", str(float(end))]
        for flag in ("--config", "--plays"):
            pass
        self.replay_proc = subprocess.Popen(cmd, cwd=self.base_dir)
        return {"ok": True, "url": f"http://127.0.0.1:{port}", "pid": self.replay_proc.pid}


NOT_SESSIONS = {"grades.jsonl", "trades.jsonl", "clips.jsonl"}   # journal files that live next to the recordings


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
            for kind in ("m30", "m5x", "m5"):
                for k in sorted(getattr(st, kind, {}) or {}):
                    o, h, l, c, v = st.__dict__[kind][k]
                    rec.write({"ev": "sbar", "t": t, "sym": sym, "k": kind, "t0": k, "o": o, "h": h, "l": l, "c": c, "v": v})
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
