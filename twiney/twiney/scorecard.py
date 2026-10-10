"""THE DESK SCORE: did the calls earn their airtime?

Every call with a direction in it (the second entry going live, a reload buyer / seller CLEANED UP, a level taken on
a close, a breakout with speed, a buy / sell program, the excitement over calls / puts, the open read, a reload buyer
/ seller detected) is noted with the price at the call. Five and fifteen minutes later the desk looks where price
went. A HIT moved at least score.hit_atr of the daily ATR the call's way at fifteen minutes, a MISS the other way,
FLAT neither. Per kind of call: how many, the hit rate, the average move. The review shows which calls earn their
airtime and which are noise; nothing here places or changes an order.
"""

import json
from collections import deque


def classify(alert):
    """(kind, direction) for a call with a direction in it, else None. direction +1 = up, -1 = down."""
    role, label = alert.get("role") or "", str(alert.get("label") or "")
    side = alert.get("side")
    up = 1 if side == "ask" else -1 if side == "bid" else 0
    if role == "story":
        key = str(alert.get("key") or "")
        topic = key.split("|", 3)[3] if key.count("|") >= 3 else ""
        if topic.startswith("se:through"):
            return ("SECOND ENTRY LIVE", up)
        if topic.startswith("hype"):
            return ("CALLS / PUTS POUNDED", up)
        if topic.startswith("break:"):
            return ("LEVEL BREAK (CLOSE)", up)
        if topic.startswith("openread"):
            return ("OPEN READ", up)
        if topic.startswith("retrace"):
            return ("60-MIN RETRACE", up)
        if topic.startswith("struct:"):
            return ("STRUCTURE (60 / DAILY)", up)
        if topic.startswith("h60:"):
            return ("60-MIN CANDLE", up)
        return None
    if label == "CLEANED UP":
        return ("CLEANED UP", 1 if side == "ask" else -1)          # the seller cleaned up: buyers go through
    if label.startswith("RELOAD BUYER"):
        return ("RELOAD BUYER", 1)
    if label.startswith("RELOAD SELLER"):
        return ("RELOAD SELLER", -1)
    if role == "level":
        if label in ("BUYERS TOOK", "BOUNCED", "DEFENDED", "RECLAIMED", "BROKE THROUGH"):
            return ("LEVEL " + label, 1)
        if label in ("SELLERS TOOK", "REJECTED", "HELD AS SUPPLY", "FAILED BREAKOUT", "LOST"):
            return ("LEVEL " + label, -1)
        return None
    if role == "pace":
        if label.startswith("BREAKOUT WITH SPEED"):
            return ("BREAKOUT WITH SPEED", 1)
        if label.startswith("BREAKDOWN WITH SPEED"):
            return ("BREAKDOWN WITH SPEED", -1)
        return None
    if role == "inst":
        if "BUY PROGRAM" in label or label.startswith("STEADY BUYING") or "WALKING UP" in label:
            return ("BUY PROGRAM", 1)
        if "SELL PROGRAM" in label or label.startswith("STEADY SELLING") or "WALKING DOWN" in label:
            return ("SELL PROGRAM", -1)
        return None
    return None


class Scorecard:
    HORIZONS = (300.0, 900.0)

    def __init__(self, path=None, cfg=None):
        self.path = path
        self.cfg = cfg or {}
        self.open = []                      # calls waiting for their 5 / 15 minutes
        self.done = deque(maxlen=400)       # resolved calls, newest last
        self.by = {}                        # kind -> {"n", "hit", "miss", "flat", "sum5", "sum15"}
        self.day = None

    def note(self, alert, t, price, atr):
        c = classify(alert)
        if not c or not price or not c[1]:
            return None
        kind, d = c
        row = {"t": float(t), "symbol": alert.get("symbol"), "kind": kind, "dir": d, "p0": float(price), "atr": float(atr or 0) or None,
               "text": str(alert.get("text") or "")[:160], "moves": {}}
        self.open.append(row)
        return row

    def tick(self, t, prices):
        """prices: {symbol: last}. Resolves the calls whose horizons have passed."""
        from . import studies
        day = studies.day_key(t)
        if self.day != day:                 # a new day: the review starts fresh
            self.day = day
            self.by = {}
            self.open = [r for r in self.open if t - r["t"] < 3600]
        keep = []
        for r in self.open:
            px = prices.get(r["symbol"])
            for h in self.HORIZONS:
                k = str(int(h))
                if k not in r["moves"] and t >= r["t"] + h and px:
                    r["moves"][k] = round((px - r["p0"]) * r["dir"], 4)
            if len(r["moves"]) == len(self.HORIZONS):
                self._resolve(r)
            elif t - r["t"] > self.HORIZONS[-1] + 600:
                continue                    # no price came for it: dropped
            else:
                keep.append(r)
        self.open = keep

    def _resolve(self, r):
        thr = float(self.cfg.get("hit_atr", 0.1)) * (r["atr"] or (r["p0"] * 0.018))
        m15 = r["moves"].get("900", 0.0)
        r["outcome"] = "HIT" if m15 >= thr else "MISS" if m15 <= -thr else "FLAT"
        r["pct15"] = round(m15 / r["p0"] * 100, 2) if r["p0"] else None
        self.done.append(r)
        b = self.by.setdefault(r["kind"], {"n": 0, "hit": 0, "miss": 0, "flat": 0, "sum5": 0.0, "sum15": 0.0})
        b["n"] += 1
        b[r["outcome"].lower()] += 1
        b["sum5"] += r["moves"].get("300", 0.0) / (r["atr"] or r["p0"] * 0.018)
        b["sum15"] += m15 / (r["atr"] or r["p0"] * 0.018)
        if self.path:
            try:
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(r, default=str) + "\n")
            except OSError:
                pass

    def view(self):
        kinds = []
        for kind, b in sorted(self.by.items(), key=lambda kv: -kv[1]["n"]):
            kinds.append({"kind": kind, "n": b["n"], "hit": b["hit"], "miss": b["miss"], "flat": b["flat"],
                          "hit_pct": round(100.0 * b["hit"] / b["n"]) if b["n"] else None,
                          "avg5": round(b["sum5"] / b["n"], 2) if b["n"] else None, "avg15": round(b["sum15"] / b["n"], 2) if b["n"] else None})
        recent = [{"t": r["t"], "symbol": r["symbol"], "kind": r["kind"], "dir": r["dir"], "p0": r["p0"], "outcome": r.get("outcome"),
                   "m5": r["moves"].get("300"), "m15": r["moves"].get("900"), "pct15": r.get("pct15"), "text": r["text"]} for r in list(self.done)[-25:]][::-1]
        return {"kinds": kinds, "recent": recent, "open": len(self.open)}
