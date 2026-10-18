"""MY READ: how Twiney sees each stock, set by him and only by him (the desk never sets it).

BULLISH / BEARISH / NEUTRAL / HANDS OFF, with an optional one-line why, for today (until the close) or for the week
(until Friday's close). It labels and warns; it never blocks an order and never silences a call:
  - the tabs, the watchlist, the story line and THE SHOW carry it
  - a call against it is marked "against your read"; an order against it gets a warning on the order bar
  - every card in THE CALL BOOK keeps it, so THE WEEKLY REVIEW can show the desk's hit rate with your read and
    against it, and how your own reads did (BULLISH: did price close over where it was when you set it)

Kept in recordings/myread.json (what is set now) and recordings/myread.jsonl (every read, with its close).
"""

import json
import os
import threading
import time

READS = ("BULLISH", "BEARISH", "NEUTRAL", "HANDS OFF")


def _ny(t):
    from . import studies
    return studies.ny(t)


def _close_t(t, week=False):
    """The 16:00 New York close of the day (or of the Friday) the read was set on."""
    d = _ny(t)
    if week:
        from datetime import timedelta
        d = d + timedelta(days=max(0, 4 - d.weekday()))
    end = d.replace(hour=16, minute=0, second=0, microsecond=0)
    if _ny(t) >= end and not week:
        from datetime import timedelta
        end = end + timedelta(days=1)
        while end.weekday() >= 5:
            end = end + timedelta(days=1)
    return end.timestamp()


class MyRead:
    def __init__(self, directory=None):
        self.dir = directory
        self.lock = threading.Lock()
        self.now = {}              # symbol -> {"read", "why", "t", "until", "price", "week"}
        self.hist = []             # every read set: {"symbol", "read", "why", "t", "until", "price", "close"}
        self.warned = set()
        if directory:
            try:
                with open(os.path.join(directory, "myread.json"), encoding="utf-8") as fh:
                    self.now = {k: v for k, v in (json.load(fh) or {}).items() if v.get("read") in READS}
            except (OSError, ValueError):
                pass
            try:
                with open(os.path.join(directory, "myread.jsonl"), encoding="utf-8") as fh:
                    for ln in fh:
                        try:
                            self.hist.append(json.loads(ln))
                        except ValueError:
                            continue
            except OSError:
                pass

    def _save(self):
        if not self.dir:
            return
        try:
            tmp = os.path.join(self.dir, "myread.json.tmp")
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.now, fh)
            os.replace(tmp, os.path.join(self.dir, "myread.json"))
        except OSError:
            pass

    def _log(self, row):
        if not self.dir:
            return
        try:
            with open(os.path.join(self.dir, "myread.jsonl"), "a", encoding="utf-8") as fh:
                fh.write(json.dumps(row) + "\n")
        except OSError:
            pass

    def set(self, symbol, read, why="", week=False, t=None, price=None):
        """Set (or clear, read=None) the read on a stock. Returns the read now on it."""
        symbol = str(symbol or "").upper()
        t = t or time.time()
        if not symbol:
            return None
        with self.lock:
            if read is None or read == "":
                self.now.pop(symbol, None)
                self._save()
                return None
            if read not in READS:
                raise ValueError("a read is BULLISH, BEARISH, NEUTRAL or HANDS OFF")
            r = {"read": read, "why": str(why or "")[:200], "t": round(t), "until": round(_close_t(t, bool(week))),
                 "price": float(price) if price else None, "week": bool(week)}
            self.now[symbol] = r
            self._save()
            row = dict(r, symbol=symbol, close=None)
            self.hist.append(row)
            self._log(row)
            return dict(r)

    def get(self, symbol, t=None):
        r = self.now.get(str(symbol or "").upper())
        if r and (t or time.time()) < r["until"]:
            return r
        return None

    def view(self, t=None):
        t = t or time.time()
        return {s: dict(r) for s, r in self.now.items() if t < r["until"]}

    def tick(self, t, prices):
        """Past a read's close: its closing price is kept (for how your reads did), and the read comes off."""
        changed = False
        with self.lock:
            for s, r in list(self.now.items()):
                if t >= r["until"]:
                    del self.now[s]
                    changed = True
            for row in self.hist:
                if row.get("close") is None and t >= row["until"] and t - row["until"] < 3600 and prices.get(row["symbol"]):
                    row["close"] = float(prices[row["symbol"]])
                    self._log(row)          # the line with its close (the last line for a read wins)
            if changed:
                self._save()

    @staticmethod
    def against(read, direction):
        """A call (or an order) with this direction (+1 up, -1 down) against the read?"""
        if not read:
            return False
        if read == "HANDS OFF":
            return direction != 0
        return (read == "BULLISH" and direction < 0) or (read == "BEARISH" and direction > 0)

    def review(self, since=0.0):
        """How your own reads did: BULLISH right when price closed over where it was when you set it, BEARISH right
        when it closed under. The last version of each read counts (set again = the earlier one ends there)."""
        last = {}
        for row in self.hist:
            if row["t"] >= since:
                last[(row["symbol"], row["t"])] = row
        out = {}
        for row in last.values():
            if row.get("close") is None or not row.get("price") or row["read"] not in ("BULLISH", "BEARISH"):
                continue
            b = out.setdefault(row["read"], {"read": row["read"], "n": 0, "right": 0, "moves": []})
            mv = (row["close"] - row["price"]) * (1 if row["read"] == "BULLISH" else -1)
            b["n"] += 1
            b["right"] += mv > 0
            b["moves"].append(round(mv / row["price"] * 100, 2))
        for b in out.values():
            b["right_pct"] = round(100.0 * b["right"] / b["n"]) if b["n"] else None
            b["avg_pct"] = round(sum(b["moves"]) / len(b["moves"]), 2) if b["moves"] else None
            del b["moves"]
        return list(out.values())
