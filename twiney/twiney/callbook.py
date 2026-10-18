"""THE CALL BOOK: every call THE DESK SCORE judges, kept as a card you can look back at.

A card is what the desk saw the moment it made the call:
  the words, the time, the symbol, the price; the last 30 prints on the T&S; the top of the LEVEL II; who is in
  control; the option flow prints on that stock in the last 15 minutes (each print on its own, never added up);
  the candles with the levels; the option money reads.
Then what happened:
  the move at 5, 15 and 30 minutes; which came first, the target (or the MP) or the stop; the level-hold grade for a
  level that was taken (STRONG / HOLDING / NOT STRONG / LOST); HIT / MISS / FLAT (the DESK SCORE rule, at 15 min).
Twiney's own grade: 👍 / 👎 and a note. A picture of the chart, the T&S and the flow when the desk is open, and the
recording at that moment to replay.

THE WEEKLY REVIEW: by call kind, worst first, and when a setting changed during the days read, the hit rate before and
after it.

Cards live in <recordings>/callbook/cards-YYYYMMDD.jsonl (a card is written again whenever it changes: the last line
for an id wins), kept forever unless SETTINGS > Call book says otherwise; the pictures in callbook/pics, kept 60 days.
Nothing here is a call or an order.
"""

import json
import os
import re
import time

HORIZONS = (300, 900, 1800)

# the settings a card remembers: when one of them changes, THE WEEKLY REVIEW shows the hit rate before and after
TUNING = ("levels.took_hold_minutes", "levels.grade_minutes", "levels.dip_cents", "levels.away_ticks", "levels.zone_ticks",
          "flow.min_premium", "flow.index_min_premium", "flow.hammer_prints", "flow.repeat_minutes",
          "pace.breakout_ratio", "reload.min_absorbed_shares", "score.hit_atr", "callbook.target_atr", "callbook.stop_atr")


def _get(cfg, path):
    d = cfg
    for k in path.split("."):
        if not isinstance(d, dict) or k not in d:
            return None
        d = d[k]
    return d if isinstance(d, (int, float, str, bool)) else None


def _day(t):
    return time.strftime("%Y%m%d", time.localtime(t))


SAFE_ID = re.compile(r"^[0-9]{6,16}-[A-Z0-9.\-]{1,12}-[0-9]{1,4}$")


class CallBook:
    def __init__(self, directory, cfg=None):
        self.dir = os.path.join(directory, "callbook") if directory else None
        self.pics = os.path.join(self.dir, "pics") if self.dir else None
        self.cfg = cfg or {}
        self.open = {}          # id -> card still being followed (its 30 minutes)
        self.recent = {}        # id -> card, today's and the ones read back, for the panel
        self.n = 0
        self.want_pic = {}      # id -> (t, symbol): the page takes a picture of the chart / T&S / flow
        if self.dir:
            try:
                os.makedirs(self.pics, exist_ok=True)
                self.prune(time.time())
            except OSError:
                self.dir = None

    @property
    def c(self):
        return self.cfg.get("callbook") or {}

    # ---- a new call ---------------------------------------------------------------------------------------------

    def add(self, row, alert, ctx):
        """row: THE DESK SCORE's row for the call (kind, dir, p0, atr, t). ctx: what the desk saw (engine.callbook_ctx).
        Returns the card."""
        if not self.c.get("enabled", True):
            return None
        self.n += 1
        t = float(row["t"])
        cid = f"{int(t * 1000)}-{row['symbol']}-{self.n % 10000}"
        atr = row.get("atr") or (row["p0"] * 0.018)
        d = row["dir"]
        plan = ctx.get("plan") or {}
        target, stop, src = plan.get("target"), plan.get("stop"), "PLAY"
        # the play's own lines when they point the call's way, else the ATR: target / MP vs stop, which comes first
        if not (target and stop and (target - row["p0"]) * d > 0 and (row["p0"] - stop) * d > 0):
            target = round(row["p0"] + d * float(self.c.get("target_atr", 0.5)) * atr, 2)
            stop = round(row["p0"] - d * float(self.c.get("stop_atr", 0.25)) * atr, 2)
            src = "ATR"
        card = {"id": cid, "t": t, "symbol": row["symbol"], "kind": row["kind"], "dir": d, "label": alert.get("label"),
                "words": alert.get("words") or alert.get("text"), "text": alert.get("text"), "price": row["p0"],
                "atr": round(atr, 4), "src": row.get("src", "live"),
                "tape": ctx.get("tape") or [], "book": ctx.get("book") or {}, "control": ctx.get("control"),
                "flow": ctx.get("flow") or [], "candles": ctx.get("candles") or [], "levels": ctx.get("levels") or [],
                "reads": row.get("reads") or {}, "target": target, "stop": stop, "plan_src": src,
                "moves": {}, "first": None, "hold": None, "outcome": None, "thumb": 0, "note": "",
                "pic": None, "replay": ctx.get("replay"), "myread": ctx.get("myread"),
                "settings": {k: _get(self.cfg, k) for k in TUNING if _get(self.cfg, k) is not None},
                "hi": row["p0"], "lo": row["p0"]}
        if alert.get("lvl") is not None:
            card["lvl"] = float(alert["lvl"])
        self.open[cid] = card
        self.recent[cid] = card
        if self.c.get("pictures", True):
            self.want_pic[cid] = (t, row["symbol"])
        self._save(card)
        self._trim()
        return card

    def grade(self, symbol, lvl, took, grade):
        """The level-hold grade (10 minutes after a level was taken), onto the card that called it taken."""
        kind = "LEVEL " + took
        for c in sorted(self.open.values(), key=lambda c: -c["t"]):
            if c["symbol"] == symbol and c["kind"] == kind and abs(c.get("lvl", -1e9) - float(lvl)) < 1e-6:
                c["hold"] = grade
                self._save(c)
                return c
        return None

    # ---- what happened -------------------------------------------------------------------------------------------

    def tick(self, t, prices):
        for cid, c in list(self.open.items()):
            px = prices.get(c["symbol"])
            if not px:
                if t - c["t"] > HORIZONS[-1] + 600:
                    self._close(c)
                continue
            c["hi"], c["lo"] = max(c["hi"], px), min(c["lo"], px)
            if c["first"] is None:
                up = c["dir"] > 0
                hit_t = (c["hi"] >= c["target"]) if up else (c["lo"] <= c["target"])
                hit_s = (c["lo"] <= c["stop"]) if up else (c["hi"] >= c["stop"])
                if hit_t or hit_s:
                    # both inside one read: the stop is counted first (the honest answer)
                    c["first"] = "STOP" if hit_s else "TARGET"
                    c["first_t"] = round(t - c["t"])
                    self._save(c)
            changed = False
            for h in HORIZONS:
                k = str(h)
                if k not in c["moves"] and t >= c["t"] + h:
                    c["moves"][k] = round((px - c["price"]) * c["dir"], 4)
                    changed = True
                    if h == 900:
                        thr = float((self.cfg.get("score") or {}).get("hit_atr", 0.1)) * c["atr"]
                        m = c["moves"][k]
                        c["outcome"] = "HIT" if m >= thr else "MISS" if m <= -thr else "FLAT"
            if changed:
                self._save(c)
            if len(c["moves"]) == len(HORIZONS):
                self._close(c)

    def _close(self, c):
        if c["first"] is None and len(c["moves"]) == len(HORIZONS):
            c["first"] = "NEITHER"
        self.open.pop(c["id"], None)
        self._save(c)

    # ---- Twiney's grade, the picture ------------------------------------------------------------------------------

    def rate(self, cid, thumb=None, note=None):
        c = self.recent.get(cid) or self._find(cid)
        if c is None:
            return None
        if thumb is not None:
            c["thumb"] = 1 if int(thumb) > 0 else -1 if int(thumb) < 0 else 0
        if note is not None:
            c["note"] = str(note)[:1000]
        self._save(c)
        return c

    def save_pic(self, cid, data):
        """A JPEG / PNG the page made of the chart, the T&S and the flow at the call."""
        if not self.pics or not SAFE_ID.match(cid or ""):
            return None
        c = self.recent.get(cid) or self._find(cid)
        if c is None:
            return None
        ext = "png" if data[:8] == b"\x89PNG\r\n\x1a\n" else "jpg" if data[:2] == b"\xff\xd8" else None
        if ext is None or len(data) > 4_000_000:
            return None
        name = f"{cid}.{ext}"
        with open(os.path.join(self.pics, name), "wb") as fh:
            fh.write(data)
        c["pic"] = name
        self.want_pic.pop(cid, None)
        self._save(c)
        return name

    def pic_path(self, name):
        if not self.pics or not re.match(r"^[0-9A-Za-z.\-]+\.(jpg|png)$", name or ""):
            return None
        p = os.path.join(self.pics, name)
        return p if os.path.isfile(p) else None

    def wanted(self, t):
        """The calls of the last minute still waiting for their picture."""
        for cid, (t0, _s) in list(self.want_pic.items()):
            if t - t0 > 60:
                del self.want_pic[cid]
        return [{"id": cid, "symbol": s} for cid, (_t, s) in self.want_pic.items()]

    # ---- storage ---------------------------------------------------------------------------------------------------

    def _save(self, c):
        if not self.dir:
            return
        try:
            with open(os.path.join(self.dir, f"cards-{_day(c['t'])}.jsonl"), "a", encoding="utf-8") as fh:
                fh.write(json.dumps(c, default=str, separators=(",", ":")) + "\n")
        except OSError:
            pass

    def _trim(self):
        if len(self.recent) > 400:
            for cid in sorted(self.recent, key=lambda k: self.recent[k]["t"])[:len(self.recent) - 400]:
                if cid not in self.open:
                    del self.recent[cid]

    def read(self, days=7, now=None):
        """Every card of the last ``days`` days, newest first (the last line for an id wins)."""
        if not self.dir:
            return sorted(self.recent.values(), key=lambda c: -c["t"])
        now = now or time.time()
        keep = {_day(now - i * 86400) for i in range(max(1, int(days)))}
        out = {}
        for f in sorted(os.listdir(self.dir)):
            m = re.match(r"^cards-(\d{8})\.jsonl$", f)
            if not m or m.group(1) not in keep:
                continue
            try:
                with open(os.path.join(self.dir, f), encoding="utf-8") as fh:
                    for ln in fh:
                        try:
                            c = json.loads(ln)
                            out[c["id"]] = c
                        except (ValueError, KeyError):
                            continue
            except OSError:
                continue
        out.update({k: v for k, v in self.recent.items() if k in out or v["t"] >= now - days * 86400})
        return sorted(out.values(), key=lambda c: -c["t"])

    def _find(self, cid):
        m = re.match(r"^(\d+)-", cid or "")
        if not m or not self.dir:
            return None
        day = _day(int(m.group(1)) / 1000.0)
        for c in self.read(days=1, now=int(m.group(1)) / 1000.0):
            if c["id"] == cid:
                self.recent[cid] = c
                return c
        return None

    def prune(self, now):
        """Pictures older than pic_days (60) go; cards stay forever unless card_days is set."""
        if not self.dir:
            return
        pic_days, card_days = float(self.c.get("pic_days", 60)), float(self.c.get("card_days", 0))
        for f in os.listdir(self.pics):
            p = os.path.join(self.pics, f)
            try:
                if pic_days > 0 and now - os.path.getmtime(p) > pic_days * 86400:
                    os.remove(p)
            except OSError:
                pass
        if card_days > 0:
            cut = _day(now - card_days * 86400)
            for f in os.listdir(self.dir):
                m = re.match(r"^cards-(\d{8})\.jsonl$", f)
                if m and m.group(1) < cut:
                    try:
                        os.remove(os.path.join(self.dir, f))
                    except OSError:
                        pass

    # ---- THE WEEKLY REVIEW -----------------------------------------------------------------------------------------

    @staticmethod
    def review(cards):
        """By call kind, worst first; Twiney's 👍 / 👎; and for each setting that changed inside these days, the hit
        rate of each kind before and after the change."""
        judged = [c for c in cards if c.get("outcome")]
        by = {}
        for c in judged:
            b = by.setdefault(c["kind"], {"kind": c["kind"], "n": 0, "hit": 0, "miss": 0, "flat": 0, "sum15": 0.0, "up": 0, "down": 0,
                                          "target": 0, "stop": 0, "holds": {}})
            b["n"] += 1
            b[c["outcome"].lower()] += 1
            b["sum15"] += (c["moves"].get("900") or 0.0) / (c.get("atr") or 1)
            b["up"] += c.get("thumb", 0) > 0
            b["down"] += c.get("thumb", 0) < 0
            if c.get("first") == "TARGET":
                b["target"] += 1
            elif c.get("first") == "STOP":
                b["stop"] += 1
            if c.get("hold"):
                b["holds"][c["hold"]] = b["holds"].get(c["hold"], 0) + 1
        kinds = []
        for b in by.values():
            b["hit_pct"] = round(100.0 * b["hit"] / b["n"]) if b["n"] else None
            b["avg15"] = round(b.pop("sum15") / b["n"], 2) if b["n"] else None
            kinds.append(b)
        kinds.sort(key=lambda b: (b["hit_pct"] if b["hit_pct"] is not None else 101, -b["n"]))
        # a setting that changed: the hit rate under each value it had, per kind
        tuning = []
        keys = sorted({k for c in judged for k in (c.get("settings") or {})})
        for k in keys:
            vals = {}
            for c in judged:
                v = (c.get("settings") or {}).get(k)
                vals.setdefault(v, []).append(c)
            if len(vals) < 2:
                continue
            rows = []
            for v, cs in sorted(vals.items(), key=lambda kv: min(c["t"] for c in kv[1])):
                hit = sum(1 for c in cs if c["outcome"] == "HIT")
                rows.append({"value": v, "n": len(cs), "hit_pct": round(100.0 * hit / len(cs)), "from": min(c["t"] for c in cs),
                             "to": max(c["t"] for c in cs)})
            tuning.append({"setting": k, "values": rows})
        # MY READ: the desk's calls with your read and against it (BULLISH / BEARISH reads only)
        def _rate(cs):
            return {"n": len(cs), "hit_pct": round(100.0 * sum(1 for c in cs if c["outcome"] == "HIT") / len(cs)) if cs else None}
        sided = [c for c in judged if c.get("myread") in ("BULLISH", "BEARISH")]
        with_ = [c for c in sided if (c["myread"] == "BULLISH") == (c["dir"] > 0)]
        against = [c for c in sided if (c["myread"] == "BULLISH") != (c["dir"] > 0)]
        n = len(judged)
        return {"myread": {"with": _rate(with_), "against": _rate(against),
                           "hands_off": _rate([c for c in judged if c.get("myread") == "HANDS OFF"])},
                "n": n, "cards": len(cards), "hit_pct": round(100.0 * sum(1 for c in judged if c["outcome"] == "HIT") / n) if n else None,
                "kinds": kinds, "tuning": tuning}

    @staticmethod
    def brief(c):
        """A card in the list: no T&S / book / candles (the whole card is fetched when opened)."""
        return {k: c.get(k) for k in ("id", "t", "symbol", "kind", "dir", "label", "words", "price", "moves", "first", "first_t",
                                      "hold", "outcome", "thumb", "note", "pic", "control", "target", "stop", "plan_src", "src", "myread")}
