"""Synthetic demo feed (``--demo``) for trying the dashboard without IBKR.

Clearly labelled DEMO everywhere; it is not market data. It walks each price
toward its PS60 levels and, on depth symbols, stages reload episodes at the
trigger that end either CLEANED UP or PULLED, so every dashboard state shows.
"""

import random

from .book import ASK, BID, INSERT, UPDATE
from .prices import tick_size

ROWS = 10


class DemoFeed:
    def __init__(self, engine, plays, seed=7):
        self.engine = engine
        self.rng = random.Random(seed)
        self.state = {}
        for p in plays:
            if not p["active"]:
                continue
            drift = self.rng.uniform(0.002, 0.008) * self.rng.choice((-1, 1))
            mid = round(p["trigger"] * (1 + drift), 2)
            # start inside the play's stop / target band so the demo doesn't retire the play at once
            lo, hi = sorted(x for x in (p.get("stop"), p.get("target")) if x) or (None, None)
            if lo and hi:
                mid = round(min(max(mid, lo + (hi - lo) * 0.15), hi - (hi - lo) * 0.15), 2)
            self.state[p["symbol"]] = {
                "play": p, "mid": mid,
                "phase": "drift", "n": 0, "outcome": None, "rows": {ASK: 0, BID: 0},
            }

    def start(self, t):
        self.engine.on_connection("DEMO", "SYNTHETIC DEMO FEED — not market data", t, market_data_type=None)
        self._history(t)
        self.engine.play_listeners.append(self.add_play)

    def add_play(self, p):
        """A typed-in ticker in the demo: a made-up price that wanders."""
        mid = round(self.rng.uniform(20, 300), 2)
        self.state[p["symbol"]] = {"play": p, "mid": mid, "phase": "cooldown", "n": 0, "outcome": None, "rows": {ASK: 0, BID: 0}}
        import time as _t
        self._history_one(p["symbol"], self.state[p["symbol"]], _t.time())

    def _history(self, t):
        """Five synthetic sessions of 1-minute bars and 20 daily bars per play (labelled demo, not data)."""
        for sym, s in self.state.items():
            self._history_one(sym, s, t)

    def _history_one(self, sym, s, t):
        from .ps60 import ny_offset, SESSION_OPEN
        rng = self.rng
        if True:
            p = s["play"]
            tk = tick_size(s["mid"])
            atr_ = max(tk * 20, (p.get("trigger") or s["mid"]) * 0.018)
            off = ny_offset(t)
            today0 = (t + off) // 86400 * 86400 - off
            # daily bars, ending yesterday, drifting into today's level
            px = s["mid"] * (1 + rng.uniform(-0.03, 0.03))
            day_bars = []
            for d in range(20, 0, -1):
                day0 = today0 - d * 86400
                if ((day0 + off) // 86400) % 7 in (3, 4):   # skip Sat / Sun (epoch day 0 is a Thursday)
                    continue
                o = px
                c = round(o + rng.uniform(-atr_, atr_) * 0.7, 2)
                h = round(max(o, c) + rng.uniform(0, atr_ * 0.4), 2)
                l = round(min(o, c) - rng.uniform(0, atr_ * 0.4), 2)
                day_bars.append((day0, o, h, l, c))
                px = c
            for day0, o, h, l, c in day_bars:
                self.engine.on_daily_bar(sym, day0, o, h, l, c)
            # 1-minute bars for the last 5 sessions, ending at the current demo price
            sessions = [b[0] for b in day_bars[-5:]]
            n_total = 390 * len(sessions)
            end_px = s["mid"]
            start_px = day_bars[-5][1] if len(day_bars) >= 5 else end_px
            walk = [start_px]
            for _ in range(n_total - 1):
                walk.append(walk[-1] + rng.gauss(0, atr_ / 40))
            drift = (end_px - walk[-1]) / max(1, n_total - 1)
            walk = [w + drift * i for i, w in enumerate(walk)]
            k = 0
            for day0 in sessions:
                for m in range(390):
                    t0 = day0 + SESSION_OPEN + m * 60
                    if t0 >= t:
                        break
                    o = walk[k]
                    c = walk[min(k + 1, n_total - 1)]
                    h = max(o, c) + abs(rng.gauss(0, atr_ / 80))
                    l = min(o, c) - abs(rng.gauss(0, atr_ / 80))
                    self.engine.on_hist_bar(sym, t0, round(o, 2), round(h, 2), round(l, 2), round(c, 2),
                                            rng.randint(500, 20000))
                    k += 1

    def step(self, t):
        for sym, s in self.state.items():
            self._walk(s)
            tk = tick_size(s["mid"])
            bid = round(s["mid"], 2) if s["phase"] != "reload" else s["bid"]
            ask = round(bid + tk, 2) if s["phase"] != "reload" else s["ask"]
            self.engine.on_l1(sym, "bid", bid, t)
            self.engine.on_l1(sym, "ask", ask, t)
            self.engine.on_l1(sym, "last", s.get("last", s["mid"]), t)
            if sym in self.engine.slots:
                self._depth(sym, s, bid, ask, t)
            else:
                s["rows"] = {ASK: 0, BID: 0}
                s["phase"] = "drift" if s["phase"] != "cooldown" else s["phase"]
        for cmd in self.engine.tick(t):
            pass

    # price path -------------------------------------------------------------
    def _walk(self, s):
        p, rng = s["play"], self.rng
        tk = tick_size(s["mid"])
        if s["phase"] == "drift" and not p.get("trigger"):
            s["phase"] = "cooldown"
        if s["phase"] == "drift":
            gap = p["trigger"] - s["mid"]
            s["mid"] = round(s["mid"] + (tk if gap > 0 else -tk) * rng.choice((0, 1, 1, 2)) + tk * rng.choice((-1, 0, 0, 1)), 2)
            s["last"] = s["mid"]
        elif s["phase"] == "cooldown":
            s["n"] += 1
            s["mid"] = round(s["mid"] + tk * rng.choice((-2, -1, 0, 1, 2)), 2)
            s["last"] = s["mid"]
            if s["n"] > 160:
                s["phase"], s["n"] = "drift", 0

    def _depth(self, sym, s, bid, ask, t):
        p, rng, eng = s["play"], self.rng, self.engine
        tk = tick_size(s["mid"])
        level = p.get("trigger")
        seller = p["side"] == "long"  # longs need the offer at the trigger cleared
        if level and s["phase"] == "drift" and abs(s["mid"] - level) <= 3 * tk:
            s["phase"], s["n"] = "reload", 0
            s["outcome"] = rng.choice(("clean", "pull"))
            s["shown"] = 1500
            if seller:
                s["ask"], s["bid"] = level, round(level - tk, 2)
            else:
                s["bid"], s["ask"] = level, round(level + tk, 2)
        if s["phase"] == "reload":
            s["n"] += 1
            bid, ask = s["bid"], s["ask"]
            hit_px = ask if seller else bid
            ending = s["n"] > 40
            if ending and s["outcome"] == "pull":
                # the displayed size simply leaves: no prints at the level
                self._emit_book(sym, s, bid, ask, t, skip_level=True)
                self._to_cooldown(s, level + (tk if seller else -tk) * 2)
                return
            if ending and s["outcome"] == "clean":
                eng.on_print(sym, hit_px, s["shown"], "NSDQ", t)
                self._emit_book(sym, s, bid, ask, t, skip_level=True)
                through = round(level + (tk if seller else -tk), 2)
                eng.on_print(sym, through, 300, "ARCA", t + 0.01)
                self._to_cooldown(s, through)
                return
            if s["n"] % 2 == 1:
                size = rng.choice((300, 400, 500, 600, 800))
                eng.on_print(sym, hit_px, size, rng.choice(("NSDQ", "ARCA", "BATS", "EDGX")), t)
                s["shown"] = max(s["shown"] - size, 100)
                s["last"] = hit_px
            else:
                s["shown"] = 1500  # refill
            self._emit_book(sym, s, bid, ask, t)
            return
        self._emit_book(sym, s, bid, ask, t)
        if rng.random() < 0.6:
            side_px = ask if rng.random() < 0.5 else bid
            eng.on_print(sym, side_px, rng.choice((100, 100, 200, 300, 500, 1200)), rng.choice(("NSDQ", "ARCA", "BATS")), t)

    def _to_cooldown(self, s, mid):
        s["phase"], s["n"] = "cooldown", 0
        s["mid"] = round(mid, 2)
        s["last"] = s["mid"]

    def _emit_book(self, sym, s, bid, ask, t, skip_level=False):
        tk = tick_size(s["mid"])
        level = s["play"]["trigger"]
        seller = s["play"]["side"] == "long"
        for side, best, sign in ((ASK, ask, 1), (BID, bid, -1)):
            for i in range(ROWS):
                price = round(best + sign * i * tk, 2)
                size = self.rng.choice((100, 200, 300, 500, 800, 1000, 2500))
                if s["phase"] == "reload" and i == 0 and ((side == ASK) == seller):
                    size = s["shown"]
                    if skip_level:
                        price = round(best + sign * tk, 2)
                        size = 400
                op = UPDATE if i < s["rows"][side] else INSERT
                self.engine.on_depth(sym, i, op, side, price, size, "", t)
            s["rows"][side] = ROWS
