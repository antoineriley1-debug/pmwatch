"""DESK AI: a local Ollama model, taught PS60, reading the desk's own records.

It is never in the live read path. The desk's rules make every call on the tape; the model reads what the desk
recorded (the story, the calls, THE DESK SCORE, the levels, the 60-minute candles, the option flow, your notes and
fills) and writes it up: the day's recap and tomorrow's plan, an explanation of one call, your voice notes cleaned
up, the cross-day study. Nothing it writes becomes an alert, a voice call or a trade.

Everything it was given is kept next to its answer (recordings/ai/), so the words can always be checked against the
numbers. Ollama runs on this computer: no key, nothing leaves the machine.
"""

import json
import os
import re
import threading
import time
import urllib.error
import urllib.request

KNOWLEDGE = os.path.join(os.path.dirname(__file__), "knowledge", "ps60.md")

JOBS = ("recap", "explain", "notes", "study", "ask")

# the language lock, applied to the model's words too (it slips even when taught)
LANGUAGE = [(re.compile(r"\bresistance\b", re.I), "supply"), (re.compile(r"\bsupport levels?\b", re.I), "demand"),
            (re.compile(r"\bsupport\b(?! the)", re.I), "demand"), (re.compile(r"\bdark[ -]pool\b", re.I), "large orders"),
            (re.compile(r"\biceberg\b", re.I), "large size"), (re.compile(r"\btrigger(?:ed|s)?\b", re.I), "pivot")]


def language(text):
    out = str(text or "")
    for rx, word in LANGUAGE:
        out = rx.sub(lambda m, w=word: w.upper() if m.group(0).isupper() else w, out)
    out = re.sub(r"\ban (large|pivot|supply|demand)\b", r"a \1", out)       # "an iceberg" became "a large size"
    out = re.sub(r"\bAn (large|pivot|supply|demand)\b", r"A \1", out)
    return out


def knowledge():
    try:
        with open(KNOWLEDGE, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return "You read the market the PS60 way: supply to supply, demand to demand, pivot, confirmation, second entry, measured potential."


class Ollama:
    """The local model server. ``generate`` blocks (the caller runs it off the desk's threads)."""

    def __init__(self, url="http://127.0.0.1:11434", model="llama3.1:8b", timeout=240.0, num_ctx=8192, temperature=0.3):
        self.url = str(url or "").rstrip("/")
        self.model = str(model or "")
        self.timeout = float(timeout or 240)
        self.num_ctx = int(num_ctx or 8192)
        self.temperature = float(temperature if temperature is not None else 0.3)

    def _call(self, path, body=None, timeout=None):
        req = urllib.request.Request(self.url + path, data=None if body is None else json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"}, method="POST" if body is not None else "GET")
        with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:      # noqa: S310 (local address from SETTINGS)
            return json.loads(r.read().decode("utf-8") or "{}")

    def models(self, timeout=3.0):
        """The models Ollama has pulled, or raises (not running / wrong address)."""
        out = self._call("/api/tags", timeout=timeout)
        return [str(m.get("name") or m.get("model") or "") for m in out.get("models") or []]

    def generate(self, system, prompt):
        body = {"model": self.model, "system": system, "prompt": prompt, "stream": False,
                "options": {"temperature": self.temperature, "num_ctx": self.num_ctx}}
        out = self._call("/api/generate", body)
        if out.get("error"):
            raise RuntimeError(str(out["error"]))
        return str(out.get("response") or "").strip()


class DeskAI:
    """One job at a time, off the desk's threads; the answer and what it was given are kept on disk."""

    def __init__(self, engine, cfg, rec_dir, client=None):
        self.engine = engine
        self.cfg = cfg
        self.rec_dir = rec_dir
        self.dir = os.path.join(rec_dir, "ai") if rec_dir else None
        self.client = client
        self.lock = threading.Lock()
        self.busy = None                 # the job running now
        self.started = None
        self.last = {}                   # job -> {"t", "text", "given", "file", "ms", "error"}
        self.reach = {"t": 0.0, "ok": None, "models": [], "error": None}
        self.recap_day = None            # the day the close recap ran (or was started) for
        self.live_day = None             # the last day the desk was CONNECTED (the close recap needs a real day)
        self.error = None

    # ---- settings ---------------------------------------------------------------------------------------------
    def ac(self):
        return self.cfg.get("ai") or {}

    def enabled(self):
        return bool(self.ac().get("enabled"))

    def _client(self):
        if self.client is not None:
            return self.client
        a = self.ac()
        return Ollama(a.get("url") or "http://127.0.0.1:11434", a.get("model") or "llama3.1:8b", a.get("timeout_s") or 240,
                      a.get("num_ctx") or 8192, a.get("temperature") if a.get("temperature") is not None else 0.3)

    # ---- status (cheap: no network) ---------------------------------------------------------------------------
    def status(self):
        a = self.ac()
        with self.lock:
            last = {k: {kk: v[kk] for kk in ("t", "file", "ms", "error", "title") if kk in v} for k, v in self.last.items()}
            return {"enabled": self.enabled(), "url": a.get("url"), "model": a.get("model"), "busy": self.busy,
                    "since": self.started, "reachable": self.reach["ok"], "models": list(self.reach["models"])[:12],
                    "reach_error": self.reach["error"], "model_ok": (a.get("model") in self.reach["models"]) if self.reach["ok"] else None,
                    "last": last, "error": self.error, "dir": self.dir}

    def check(self, force=False):
        """Is Ollama answering, and does it have the model? Remembered for 30 s."""
        if not force and time.time() - self.reach["t"] < 30:
            return self.reach["ok"]
        try:
            models = self._client().models()
            with self.lock:
                self.reach.update(t=time.time(), ok=True, models=models, error=None)
            return True
        except Exception as exc:           # not running, wrong address, refused
            with self.lock:
                self.reach.update(t=time.time(), ok=False, models=[], error=self._why(exc))
            return False

    @staticmethod
    def _why(exc):
        s = str(exc)
        if isinstance(exc, urllib.error.URLError) or "refused" in s.lower() or "connect" in s.lower():
            return "Ollama is not answering at this address: start Ollama (it runs in the background) or fix the address in SETTINGS > AI"
        if isinstance(exc, urllib.error.HTTPError):
            return f"Ollama answered {exc.code}: {s[:120]}"
        return s[:200]

    # ---- jobs -------------------------------------------------------------------------------------------------
    def run(self, job, t=None, **kw):
        """Start a job in the background. Returns {ok, reason}."""
        if job not in JOBS:
            return {"ok": False, "reason": f"unknown job {job}"}
        if not self.enabled():
            return {"ok": False, "reason": "DESK AI is off: SETTINGS > AI > enabled"}
        if not self.check(force=True):
            return {"ok": False, "reason": self.reach["error"] or "Ollama is not answering"}
        model = self.ac().get("model")
        if self.reach["models"] and model not in self.reach["models"] and not any(m.split(":")[0] == str(model).split(":")[0] for m in self.reach["models"]):
            return {"ok": False, "reason": f"Ollama does not have the model '{model}': in a terminal run  ollama pull {model}  (or pick one it has in SETTINGS > AI: {', '.join(self.reach['models'][:6])})"}
        with self.lock:
            if self.busy:
                return {"ok": False, "reason": f"the AI is still writing the {self.busy}; one job at a time"}
            self.busy = job
            self.started = t or time.time()
            self.error = None
        threading.Thread(target=self._work, args=(job, t or time.time(), kw), name="twiney-ai", daemon=True).start()
        return {"ok": True}

    def _work(self, job, t, kw):
        t0 = time.time()
        title, given, ask = "", "", ""
        try:
            title, given, ask = self.prepare(job, t, **kw)
            text = language(self._client().generate(knowledge(), given + "\n\n" + ask))
            if not text:
                raise RuntimeError("the model answered with nothing")
            rec = {"t": t, "title": title, "text": text, "given": given + "\n\n" + ask, "ms": int((time.time() - t0) * 1000), "error": None}
            rec["file"] = self._save(job, t, rec)
            with self.lock:
                self.last[job] = rec
            self._say("info", f"DESK AI: {title} is ready ({rec['ms'] // 1000}s)", t)
        except Exception as exc:
            why = self._why(exc) if isinstance(exc, (urllib.error.URLError, urllib.error.HTTPError)) else str(exc)[:300]
            with self.lock:
                self.last[job] = {"t": t, "title": title or job, "text": "", "given": given, "ms": int((time.time() - t0) * 1000), "error": why, "file": None}
                self.error = why
            self._say("error", f"DESK AI: the {title or job} failed: {why}", t)
        finally:
            with self.lock:
                self.busy = None
                self.started = None

    def _say(self, level, text, t):
        try:
            self.engine._message(level, text, t, category="DESK AI")
        except Exception:
            pass

    def _save(self, job, t, rec):
        if not self.dir:
            return None
        try:
            os.makedirs(self.dir, exist_ok=True)
            from . import studies
            name = f"{job}-{studies.day_key(t)}-{studies.ny(t).strftime('%H%M%S')}.md"      # New York time, like the desk
            path = os.path.join(self.dir, name)
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"# {rec['title']}\n\n{rec['text']}\n\n---\n\n## What the AI was given\n\n```\n{rec['given']}\n```\n")
            return name
        except OSError:
            return None

    def result(self, job):
        with self.lock:
            r = self.last.get(job)
            return dict(r) if r else None

    def files(self):
        if not self.dir or not os.path.isdir(self.dir):
            return []
        out = []
        for n in sorted(os.listdir(self.dir), reverse=True)[:60]:
            if n.endswith(".md"):
                out.append({"name": n, "job": n.split("-")[0], "day": n.split("-")[1] if n.count("-") >= 2 else ""})
        return out

    def read(self, name):
        if not self.dir or not re.fullmatch(r"[a-z]+-\d{8}-\d{6}\.md", str(name or "")):
            return None
        try:
            with open(os.path.join(self.dir, name), encoding="utf-8") as f:
                return f.read()
        except OSError:
            return None

    # ---- the close recap on its own ----------------------------------------------------------------------------
    def tick(self, t):
        """Once a minute from the desk: remembers a live day; after the close, writes the recap + tomorrow's plan
        on its own when SETTINGS says so."""
        from . import studies
        day = studies.day_key(t)
        if (self.engine.connection or {}).get("state") == "CONNECTED":
            self.live_day = day
        a = self.ac()
        if not (self.enabled() and a.get("recap_at_close", True)) or self.recap_day == day or self.live_day != day:
            return False
        if studies.ny_secs(t) < 16 * 3600 + 60 * int(a.get("recap_minutes_after_close", 5) or 5):
            return False
        self.recap_day = day
        return self.run("recap", t=t).get("ok", False)

    # ---- the packets: what the model is given -----------------------------------------------------------------
    def prepare(self, job, t, **kw):
        """(title, the data packet, the ask)."""
        if job == "recap":
            return ("Day recap + tomorrow's plan", self.packet_day(t), ASK_RECAP)
        if job == "explain":
            sym = str(kw.get("symbol") or self.engine.focus or "").upper()
            return (f"{sym}: why the desk said it", self.packet_explain(t, sym, kw.get("text") or "", kw.get("key")), ASK_EXPLAIN)
        if job == "notes":
            return ("Your notes, cleaned up", self.packet_notes(t), ASK_NOTES)
        if job == "study":
            days = int(kw.get("days") or self.ac().get("days_back") or 20)
            return (f"Cross-day study ({days} days)", self.packet_study(t, days), ASK_STUDY)
        q = str(kw.get("text") or "").strip()[:2000]
        return ("Your question", self.packet_day(t, brief=True), ASK_QUESTION + "\n\nTWINEY ASKS: " + q)

    def _symbols(self):
        eng = self.engine
        return [p["symbol"] for p in eng.plays if p.get("active", True)] or list(eng.syms)[:8]

    def packet_day(self, t, brief=False):
        from . import studies
        eng = self.engine
        day = studies.day_key(t)
        lines = [f"DATE {day} (New York). Desk mode: {(eng.connection or {}).get('state')}. Time now {_hm(t)} ET.",
                 "Prices are dollars. Times are New York. Every number below is the desk's own record; nothing else is known."]
        with eng.lock:
            syms = self._symbols()
            for sym in syms[:8]:
                st = eng.syms.get(sym)
                if st is None:
                    continue
                lines += self._symbol_block(st, t, day, brief)
        if not brief:
            lines += self._score_block(day)
            lines += self._desk_block(t, day)
        return "\n".join(lines)

    def _symbol_block(self, st, t, day, brief=False):
        from . import story as story_mod, studies
        eng = self.engine
        sym = st.symbol
        last = st.price()
        out = [f"\n=== {sym} === last {_px(last)}"]
        drows = [[k] + list(st.daily[k][:4]) for k in sorted(st.daily)]
        live = bool(drows) and studies.day_key(drows[-1][0] + 43200) == day
        ctx = story_mod.daily_context(drows, live, last) if drows and last else None
        try:
            atr = st.play.get("atr") or eng._atr(st, st.bar_list())
        except Exception:
            atr = None
        out.append(f"ATR (daily) {_px(atr)}")
        if ctx:
            out.append("DAILY: " + ctx.get("text", ""))
        for r in drows[-6:]:
            out.append(f"daily {studies.day_key(r[0] + 43200)}: O {_px(r[1])} H {_px(r[2])} L {_px(r[3])} C {_px(r[4])}" + ("  (today, still forming)" if r is drows[-1] and live else ""))
        play = st.play or {}
        drawn = [f"{k.replace('_', ' ')} {_px(play[k])}" for k in ("trigger", "second_entry", "target", "stop") if play.get(k)]
        if drawn:
            out.append(f"TWINEY'S LINES ({play.get('side', 'long')}): " + " · ".join(drawn).replace("trigger", "pivot"))
        try:
            lv = eng.key_levels(st, t)
        except Exception:
            lv = []
        if lv:
            out.append("LEVELS: " + " · ".join(f"{L['code']} {_px(L['price'])}" for L in sorted(lv, key=lambda x: -x['price'])[:16]))
        h = self._hourly(st, day)
        if h:
            out.append("60-MINUTE CANDLES today: " + " | ".join(h))
        s = st.story or {}
        if s.get("ctx") and not ctx:
            out.append("DAILY: " + str(s["ctx"].get("text") or ""))
        if s.get("now"):
            out.append(f"STORY NOW ({s.get('tone')}): {s['now']}")
        ln = s.get("lean") or {}
        if ln.get("text"):
            out.append(f"LEAN: {ln['text']} (regime {ln.get('regime') or '?'})")
        if s.get("flow") and s["flow"].get("state"):
            out.append(f"OPTION FLOW STATE: {s['flow']['state']}")
        if brief:
            return out
        sb = getattr(st, "storybook", None)
        if sb is not None and getattr(sb, "feed", None):
            feed = [x for x in list(sb.feed) if studies.day_key(x[0]) == day][-14:]
            if feed:
                out.append("THE STORY (newest last):")
                out += [f"  {_hm(x[0])} {x[1]}" for x in feed[::-1]]
        al = [a for a in list(eng.alerts) if a.get("symbol") == sym and studies.day_key(a.get("t", t)) == day and a.get("label") != "PS60 STORY"]
        if al:
            out.append("CALLS (newest first):")
            out += [f"  {_hm(a['t'])} {a['label']} @ {_px(a.get('price'))}: {str(a.get('text') or '')[:140]}" for a in al[:24]]
        try:
            fl = [p for p in list(eng.flow.recent) if p.get("symbol") == sym and studies.day_key(p.get("t", t)) == day]
        except Exception:
            fl = []
        if fl:
            fl.sort(key=lambda p: -(p.get("premium") or 0))
            out.append("OPTION FLOW (biggest first): " + " · ".join(
                f"{_hm(p['t'])} {p.get('cp')} {p.get('strike')} exp {p.get('expiry')} ${_k(p.get('premium'))} at the {p.get('side') or '?'}" + (f" {p['otm_pct']}% OTM" if p.get('otm_pct') is not None else "")
                for p in fl[:10]))
        return out

    def _hourly(self, st, day):
        from . import studies
        buckets = {}
        for k in sorted(st.bars):
            if studies.day_key(k) != day:
                continue
            secs = studies.ny_secs(k)
            if secs < 9 * 3600 + 1800 or secs >= 16 * 3600:
                continue
            b = int((secs - (9 * 3600 + 1800)) // 3600)
            o, h, l, c = st.bars[k][:4]
            cur = buckets.get(b)
            if cur is None:
                buckets[b] = [o, h, l, c]
            else:
                cur[1] = max(cur[1], h); cur[2] = min(cur[2], l); cur[3] = c
        names = ["9:30", "10:30", "11:30", "12:30", "13:30", "14:30", "15:30"]
        return [f"{names[b]} O {_px(v[0])} H {_px(v[1])} L {_px(v[2])} C {_px(v[3])}" for b, v in sorted(buckets.items()) if b < len(names)]

    def _score_block(self, day):
        sc = getattr(self.engine, "score", None)
        if sc is None:
            return []
        rows = [r for r in list(sc.done)]
        out = []
        if sc.by:
            out.append("\n=== THE DESK SCORE today (call: hits / misses / flat) ===")
            for kind, b in sorted(sc.by.items(), key=lambda kv: -kv[1]["n"]):
                out.append(f"  {kind}: {b['hit']} hit / {b['miss']} miss / {b['flat']} flat of {b['n']}")
        if rows:
            out.append("JUDGED CALLS (newest first): " + " · ".join(f"{_hm(r['t'])} {r['symbol']} {r['kind']} {'up' if r['dir'] > 0 else 'down'} from {_px(r['p0'])} = {r.get('outcome')}" for r in rows[::-1][:24]))
        return out

    def _desk_block(self, t, day):
        from . import studies
        eng = self.engine
        out = []
        desk = getattr(eng, "desk", None)
        notes = [n for n in (desk.notes if desk else getattr(eng, "notes_list", []) or []) if studies.day_key(n.get("t", t)) == day]
        if notes:
            out.append("\n=== TWINEY'S NOTES ===")
            out += [f"  {_hm(n['t'])} {n.get('symbol') or ''} {n.get('text')}" for n in notes[-20:]]
        fills = [f for f in list(eng.fills.values()) if studies.day_key(f.get("t", t)) == day]
        fills += [f for f in getattr(eng, "opt_fills", []) or [] if studies.day_key(f.get("t", t)) == day]
        if fills:
            out.append("=== FILLS ===")
            out += [f"  {f.get('time') or _hm(f['t'])} {f.get('symbol')} {f.get('side')} {f.get('shares') or f.get('qty')} @ {f.get('price')}" for f in sorted(fills, key=lambda f: f["t"])[-30:]]
        try:
            pnl = eng.day_pnl()
            out.append(f"DAY P&L: realized {pnl['realized']:+,.0f} · open {pnl['open']:+,.0f} · total {pnl['total']:+,.0f}")
        except Exception:
            pass
        return out

    def packet_explain(self, t, sym, text, key=None):
        from . import studies
        eng = self.engine
        lines = [f"DATE {studies.day_key(t)} (New York), {_hm(t)} ET."]
        with eng.lock:
            st = eng.syms.get(sym)
            if st is not None:
                lines += self._symbol_block(st, t, studies.day_key(t))
        a = None
        if key:
            a = next((x for x in list(eng.alerts) if x.get("key") == key), None)
        if a:
            text = f"{_hm(a['t'])} {a.get('label')} @ {_px(a.get('price'))}: {a.get('text')}"
        lines.append("\nTHE CALL TO EXPLAIN: " + (text or "the latest story line above"))
        return "\n".join(lines)

    def packet_notes(self, t):
        from . import studies
        eng = self.engine
        day = studies.day_key(t)
        desk = getattr(eng, "desk", None)
        notes = [n for n in (desk.notes if desk else getattr(eng, "notes_list", []) or []) if studies.day_key(n.get("t", t)) == day]
        marks = [m for m in (desk.marks if desk else getattr(eng, "marks_list", []) or []) if studies.day_key(m.get("t", t)) == day]
        lines = [f"DATE {day}. Twiney's notes and markers today, as typed or spoken into the mic (raw, with mistakes):"]
        lines += [f"  NOTE {_hm(n['t'])} {n.get('symbol') or ''}: {n.get('text')}" for n in notes]
        lines += [f"  MARK {_hm(m['t'])} {m.get('symbol') or ''} {m.get('price') or ''}: {m.get('note')}" + (f" ({m['headline']})" if m.get('headline') else "") for m in marks]
        if not notes and not marks:
            lines.append("  (no notes or markers today)")
        return "\n".join(lines)

    def packet_study(self, t, days=20):
        """The storyline, the score and the daily bars over the last N recorded days."""
        from . import studies
        eng = self.engine
        today = studies.day_key(t)
        lines = [f"CROSS-DAY STUDY up to {today}: the desk's storyline turns and judged calls over the last {days} recorded days."]
        turns = _read_jsonl(getattr(eng, "storyline_path", None), 20000)
        score = _read_jsonl(getattr(getattr(eng, "score", None), "path", None), 20000)
        by_day = {}
        for r in turns:
            if r.get("live", True):
                by_day.setdefault(int(r.get("day") or 0), []).append(r)
        days_seen = sorted(d for d in by_day if d)[-days:]
        sdays = {}
        for r in score:
            d = studies.day_key(float(r.get("t") or 0))
            sdays.setdefault(d, []).append(r)
        if not days_seen:
            lines.append("No recorded storyline days yet (the storyline is written on live days only).")
        for d in days_seen:
            lines.append(f"\n--- {d} ---")
            for r in by_day[d][:40]:
                lines.append(f"  {_hm(float(r['t']))} {r.get('symbol')} [{r.get('topic')}] {str(r.get('text') or '')[:150]}")
            sc = sdays.get(d) or []
            if sc:
                hit = sum(1 for r in sc if r.get("outcome") == "HIT"); miss = sum(1 for r in sc if r.get("outcome") == "MISS")
                lines.append(f"  SCORE that day: {hit} hit / {miss} miss / {len(sc) - hit - miss} flat of {len(sc)}")
        with eng.lock:
            for sym in self._symbols()[:6]:
                st = eng.syms.get(sym)
                if st is None or not st.daily:
                    continue
                rows = [[k] + list(st.daily[k][:4]) for k in sorted(st.daily)][-days:]
                lines.append(f"\n{sym} DAILY BARS: " + " | ".join(f"{studies.day_key(r[0] + 43200)} O {_px(r[1])} H {_px(r[2])} L {_px(r[3])} C {_px(r[4])}" for r in rows))
        return "\n".join(lines)


# ---- the asks ------------------------------------------------------------------------------------------------------
ASK_RECAP = """WRITE TWO PARTS, in PS60 words, from the data above only.

PART 1 — TODAY'S RECAP (per stock, then one line on the day as a whole):
- The Daily context and what the day did against it (supply to supply or demand to demand; which levels buyers took,
  which sellers took, where the reload buyers / sellers showed and what happened to them).
- The 60-minute candles: which confirmed, which failed, where a second entry structure was or was not there.
- What the option flow said and whether the tape agreed.
- What the desk called right and wrong by THE DESK SCORE, in one or two lines. Twiney's own notes and fills, if any.

PART 2 — TOMORROW'S PLAN (per stock):
- Bias from the Daily (above / below the 50-day) and the objective that follows (prior-day high or low = today's).
- The levels that matter tomorrow in price order, from the LEVELS and today's candles: today's high / low / close,
  VWAP, the 50-day, the reject / bounce lines, Twiney's lines.
- LONG side: the pivot, what CONFIRMS it (another candle through it), the second entry structure to wait for, MP in
  dollars to the next supply, MP against ATR (CLEAR or THIN), the max pain.
- SHORT side: the same, to the next demand.
- What would make it a PASS. What the option flow would need to show.
- One line on what you are watching in the first 60-minute candle.
Say "the data does not show it" where it does not. Never say a level will hold or break. End with one short line
that this is analysis for Twiney's own judgment, not advice."""

ASK_EXPLAIN = """Explain THE CALL above to Twiney in plain words: what the desk saw (name the levels, the sizes, the
prints, the flow in the data above), why that is a PS60 read, and what it does NOT mean (what still has to confirm).
Five to ten short sentences. If the data above does not back the call, say so plainly."""

ASK_NOTES = """Rewrite Twiney's notes and markers above as a clean journal for the day: fix the transcription mistakes,
keep every ticker, price and level exactly, group by stock, newest last, and keep his own words where they are
clear. Then list, in one line each, the levels and tickers he mentioned. Add nothing that is not in the notes."""

ASK_STUDY = """From the storyline turns and scores above, write the cross-day study in PS60 words:
1. The patterns that repeat: what the regime did after the first 45 minutes, how often "buyers are trying" after a
   lost level turned into TOOK vs FAILED, where the reload buyers / sellers showed up, which calls earned their
   airtime by the score and which did not.
2. The bias a trader should carry into the next day from these days, and what would flip it.
3. What to tune on the desk (thresholds, patience, which calls to trust), with the day and the turn that shows it.
Count where you can; say "too few days" where the sample is thin. Name the days you lean on."""

ASK_QUESTION = """Answer Twiney's question below from the data above and PS60. Short. If the data does not show it,
say what you would need to see."""


# ---- small helpers -----------------------------------------------------------------------------------------------
def _px(v):
    try:
        return f"{float(v):.2f}" if v is not None else "?"
    except (TypeError, ValueError):
        return "?"


def _k(v):
    try:
        v = float(v or 0)
    except (TypeError, ValueError):
        return "?"
    return f"{v / 1e6:.1f}M" if v >= 1e6 else f"{v / 1e3:.0f}K" if v >= 1e3 else f"{v:.0f}"


def _hm(t):
    try:
        from . import studies
        d = studies.ny(float(t))
        return d.strftime("%H:%M")
    except Exception:
        return "?"


def _read_jsonl(path, limit):
    if not path or not os.path.exists(path):
        return []
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except OSError:
        return []
    return out[-limit:]
