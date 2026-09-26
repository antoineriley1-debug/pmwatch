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
            drift = self.rng.uniform(0.004, 0.03) * self.rng.choice((-1, 1))
            self.state[p["symbol"]] = {
                "play": p, "mid": round(p["trigger"] * (1 + drift), 2),
                "phase": "drift", "n": 0, "outcome": None, "rows": {ASK: 0, BID: 0},
            }

    def start(self, t):
        self.engine.on_connection("DEMO", "SYNTHETIC DEMO FEED — not market data", t, market_data_type=None)
        # sample account data so the orders panel can be seen in the demo (all fake)
        plays = [s["play"] for s in self.state.values()]
        for n, p in enumerate(plays[:2]):
            buy = p["side"] == "long"
            level = p.get("second_entry") or p["trigger"]
            self.engine.on_order(f"demo{n}", t, symbol=p["symbol"], action="BUY" if buy else "SELL", qty=100.0,
                                 remaining=100.0, type="LMT", lmt=level, tif="DAY", status="Submitted")
        if len(plays) > 2:
            p = plays[2]
            self.engine.on_position("DEMO", p["symbol"], 200.0 if p["side"] == "long" else -200.0,
                                    round(p["trigger"] * 1.001, 2), t)
            self.engine.on_fill("demo-fill", p["symbol"], "BOT" if p["side"] == "long" else "SLD", 200.0,
                                round(p["trigger"] * 1.001, 2), "09:41:07", t)

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
        level = p["trigger"]
        seller = p["side"] == "long"  # longs need the offer at the trigger cleared
        if s["phase"] == "drift" and abs(s["mid"] - level) <= 3 * tk:
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
