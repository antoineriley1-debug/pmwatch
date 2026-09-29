"""Synthetic market (``--demo``): a regime-driven order-flow simulator for practice without IBKR.

Clearly labelled DEMO everywhere; it is not market data. What it mimics:

* **Price comes from order flow.** Aggressive orders eat the queue at the touch; when a queue is
  gone the price steps a tick and the other side follows in. Nothing is drawn on the price directly.
* **Regimes.** Each symbol moves through chop, trends, grinds, squeezes, capitulation, bounces and
  fades. A regime sets the buy/sell bias of the aggressors, the trade rate, the size of prints and
  how thin the book is on the side being run over. Regimes hand off to each other the way sessions
  tend to (capitulation → bounce, squeeze → fade or chop, …), with an open and close that run hotter.
* **A living book.** Ten rows a side that add, cancel, thin out and refill on their own; big resting
  size shows up, gets hit or pulled, and sometimes comes back to the same price.
* **PS60 levels.** When price comes into a play's pivot a participant defends it with a reserve behind
  a displayed size that refills as it gets hit (a reload). Three outcomes: it HOLDS and price rejects,
  it gets CLEANED UP and price goes through, retraces and continues (the second entry), or it is
  PULLED and price runs.
"""

import math
import random

from .book import ASK, BID, INSERT, UPDATE
from .prices import tick_size

ROWS = 10
EXCH = ("NSDQ", "ARCA", "BATS", "EDGX", "NYSE", "IEX")

# bias: P(an aggressive order is a buy) · rate: aggressive orders per second · size: print size multiplier
# thin: size multiplier for the side being run over · dur: minutes the regime lasts
REGIMES = {
    "chop":         dict(bias=0.50, rate=1.2, size=1.0, thin=1.0, dur=(3, 9)),
    "trend_up":     dict(bias=0.63, rate=1.9, size=1.1, thin=0.55, dur=(3, 10)),
    "trend_down":   dict(bias=0.37, rate=1.9, size=1.1, thin=0.55, dur=(3, 10)),
    "grind_up":     dict(bias=0.56, rate=1.0, size=0.9, thin=0.8, dur=(5, 14)),
    "grind_down":   dict(bias=0.44, rate=1.0, size=0.9, thin=0.8, dur=(5, 14)),
    "squeeze":      dict(bias=0.76, rate=4.0, size=1.7, thin=0.3, dur=(1, 3)),
    "capitulation": dict(bias=0.22, rate=5.0, size=2.1, thin=0.3, dur=(1, 3)),
    "bounce":       dict(bias=0.68, rate=3.0, size=1.4, thin=0.5, dur=(1, 3)),
    "fade":         dict(bias=0.34, rate=2.2, size=1.2, thin=0.5, dur=(1, 3)),
}
NEXT = {
    "chop":         (("chop", 3), ("trend_up", 2), ("trend_down", 2), ("grind_up", 2), ("grind_down", 2), ("squeeze", 1), ("capitulation", 1)),
    "trend_up":     (("chop", 3), ("grind_up", 2), ("fade", 2), ("squeeze", 1), ("trend_up", 1)),
    "trend_down":   (("chop", 3), ("grind_down", 2), ("bounce", 2), ("capitulation", 1), ("trend_down", 1)),
    "grind_up":     (("chop", 3), ("trend_up", 2), ("fade", 1), ("grind_up", 1)),
    "grind_down":   (("chop", 3), ("trend_down", 2), ("bounce", 1), ("grind_down", 1)),
    "squeeze":      (("fade", 3), ("chop", 2), ("grind_up", 1)),
    "capitulation": (("bounce", 4), ("chop", 1), ("trend_down", 1)),
    "bounce":       (("chop", 3), ("grind_up", 2), ("fade", 1)),
    "fade":         (("chop", 3), ("grind_down", 2), ("bounce", 1)),
}


def _r100(x):
    return max(100, int(round(x / 100.0)) * 100)


class _Sym:
    __slots__ = ("play", "tk", "asks", "bids", "last", "vol", "regime", "regime_until", "script", "big",
                 "big_home", "level", "level_cooldown", "prev", "l1", "base", "mid0")

    def __init__(self, play, mid, t):
        self.play = play
        self.tk = tick_size(mid)
        self.mid0 = mid
        self.base = min(3000, max(200, 600 * math.sqrt(50.0 / max(mid, 1.0))))   # typical resting size
        self.asks, self.bids = [], []
        self.last = mid
        self.vol = 0
        self.regime, self.regime_until = "chop", t
        self.script = []            # [(bias, rate, until_t)] scripted stages that override the regime
        self.big = {}               # (side, price) -> until
        self.big_home = {ASK: None, BID: None}
        self.level = None           # the PS60 participant at the pivot
        self.level_cooldown = t
        self.prev = {ASK: [], BID: []}
        self.l1 = {}


class DemoFeed:
    def __init__(self, engine, plays, seed=7):
        self.engine = engine
        self.rng = random.Random(seed)
        self.state = {}
        self.t = None
        for p in plays:
            if not p["active"]:
                continue
            base = p.get("trigger") or self.rng.uniform(20, 300)
            mid = round(base * (1 + self.rng.uniform(0.002, 0.006) * self.rng.choice((-1, 1))), 2)
            lo, hi = sorted(x for x in (p.get("stop"), p.get("target")) if x) or (None, None)
            if lo and hi:   # start inside the play's band so the demo doesn't retire the play at once
                mid = round(min(max(mid, lo + (hi - lo) * 0.15), hi - (hi - lo) * 0.15), 2)
            self.state[p["symbol"]] = _Sym(p, mid, 0.0)

    # ---- lifecycle ---------------------------------------------------------

    def start(self, t):
        self.t = t
        self.engine.on_connection("DEMO", "SYNTHETIC DEMO FEED — not market data", t, market_data_type=None)
        for sym, s in self.state.items():
            self._history_one(sym, s, t)
            self._seed_book(s, t)
            s.regime_until = t
        self.engine.play_listeners.append(self.add_play)

    def add_play(self, p):
        """A typed-in ticker in the demo: a made-up price that trades like the others."""
        import time as _t
        t = self.t or _t.time()
        s = _Sym(p, round(self.rng.uniform(20, 300), 2), t)
        self.state[p["symbol"]] = s
        self._history_one(p["symbol"], s, t)
        self._seed_book(s, t)

    # ---- history -------------------------------------------------------------

    def _history_one(self, sym, s, t):
        """Five sessions of 1-minute bars and 20 daily bars, walked through regimes (labelled demo)."""
        from .ps60 import ny_offset, SESSION_OPEN
        rng = self.rng
        p = s.play
        tk = s.tk
        atr_ = max(tk * 20, (p.get("trigger") or s.mid0) * 0.018)
        off = ny_offset(t)
        today0 = (t + off) // 86400 * 86400 - off
        px = s.mid0 * (1 + rng.uniform(-0.03, 0.03))
        day_bars = []
        for d in range(300, 0, -1):
            day0 = today0 - d * 86400
            if ((day0 + off) // 86400) % 7 in (3, 4):   # skip Sat / Sun (epoch day 0 is a Thursday)
                continue
            o = px
            c = round(o + rng.uniform(-atr_, atr_) * 0.7, 2)
            h = round(max(o, c) + rng.uniform(0, atr_ * 0.4), 2)
            l = round(min(o, c) - rng.uniform(0, atr_ * 0.4), 2)
            day_bars.append((day0, o, h, l, c))
            px = c
        # anchor the daily history so it walks into today's price instead of ending somewhere else
        if day_bars:
            shift = (s.mid0 - day_bars[-1][4]) / len(day_bars)
            day_bars = [(d0, round(o + shift * (i + 1), 2), round(h + shift * (i + 1), 2), round(l + shift * (i + 1), 2), round(c + shift * (i + 1), 2))
                        for i, (d0, o, h, l, c) in enumerate(day_bars)]
        for day0, o, h, l, c in day_bars:
            self.engine.on_daily_bar(sym, day0, o, h, l, c)
        sessions = [b[0] for b in day_bars[-5:]]
        n_total = 390 * len(sessions)
        end_px = s.mid0
        start_px = day_bars[-5][1] if len(day_bars) >= 5 else end_px
        # a regime walk: segments of 20-90 minutes with their own drift and volatility
        walk = [start_px]
        i = 0
        while len(walk) < n_total:
            seg = rng.randint(20, 90)
            drift = rng.choice((-1.2, -0.6, 0, 0, 0.6, 1.2)) * atr_ / 120
            vol = atr_ / rng.choice((30, 40, 55))
            for _ in range(seg):
                if len(walk) >= n_total:
                    break
                walk.append(walk[-1] + drift + rng.gauss(0, vol))
            i += 1
        corr = (end_px - walk[-1]) / max(1, n_total - 1)
        walk = [w + corr * k for k, w in enumerate(walk)]
        k = 0
        for day0 in sessions:
            for m in range(390):
                t0 = day0 + SESSION_OPEN + m * 60
                if t0 >= t or k >= n_total - 1:
                    break
                o, c = walk[k], walk[k + 1]
                h = max(o, c) + abs(rng.gauss(0, atr_ / 80))
                l = min(o, c) - abs(rng.gauss(0, atr_ / 80))
                hot = 1.8 if m < 30 or m > 360 else 1.0
                self.engine.on_hist_bar(sym, t0, round(o, 2), round(h, 2), round(l, 2), round(c, 2),
                                        int(rng.lognormvariate(8.6, 0.6) * hot))
                k += 1

    # ---- the book ------------------------------------------------------------

    def _fresh(self, s, side):
        rg = REGIMES[s.regime]
        against = (side == ASK and rg["bias"] > 0.5) or (side == BID and rg["bias"] < 0.5)
        target = s.base * (rg["thin"] if against else 1.2)
        return _r100(self.rng.lognormvariate(math.log(target), 0.7))

    def _seed_book(self, s, t):
        tk = s.tk
        bid = round(s.mid0 - tk, 2)
        s.asks = [[round(bid + tk * (i + 1), 2), self._fresh(s, ASK)] for i in range(ROWS + 4)]
        s.bids = [[round(bid - tk * i, 2), self._fresh(s, BID)] for i in range(ROWS + 4)]
        s.last = s.asks[0][0]

    def _extend(self, s):
        tk = s.tk
        while len(s.asks) < ROWS + 4:
            s.asks.append([round((s.asks[-1][0] if s.asks else s.bids[0][0]) + tk, 2), self._fresh(s, ASK)])
        while len(s.bids) < ROWS + 4:
            s.bids.append([round((s.bids[-1][0] if s.bids else s.asks[0][0]) - tk, 2), self._fresh(s, BID)])

    def _churn(self, s, t):
        """Passive flow: rows add, cancel, thin out and refill; big size shows up, sits, gets pulled or hit."""
        rng, rg = self.rng, REGIMES[s.regime]
        for side, rows in ((ASK, s.asks), (BID, s.bids)):
            against = (side == ASK and rg["bias"] > 0.5) or (side == BID and rg["bias"] < 0.5)
            target = s.base * (rg["thin"] if against else 1.2)
            for i in range(min(ROWS, len(rows))):
                row = rows[i]
                key = (side, row[0])
                if key in s.big:
                    if t >= s.big[key]:
                        del s.big[key]
                        if rng.random() < 0.6:          # pulled
                            row[1] = _r100(rng.lognormvariate(math.log(target), 0.5))
                    continue
                if s.level is not None and s.level["side"] == side and abs(row[0] - s.level["price"]) < 1e-9:
                    continue                            # the PS60 participant manages this row
                p = 0.3 if i < 3 else 0.12
                if rng.random() < p:
                    row[1] = _r100(row[1] + 0.2 * (target - row[1]) + rng.gauss(0, 0.35 * target))
            # big resting size: 5k-40k, mostly at a fresh price, sometimes back at the same one (a repeat)
            if rng.random() < 0.006 and len(rows) > 6:
                i = rng.randint(1, 6)
                if s.big_home[side] is not None and rng.random() < 0.4:
                    for j in range(min(ROWS, len(rows))):
                        if abs(rows[j][0] - s.big_home[side]) < 1e-9:
                            i = j
                            break
                row = rows[i]
                row[1] = _r100(row[1] + rng.choice((5000, 8000, 12000, 18000, 25000, 40000)))
                s.big[(side, row[0])] = t + rng.uniform(15, 150)
                s.big_home[side] = row[0]

    # ---- aggressive flow -------------------------------------------------------

    def _market(self, sym, s, is_buy, size, t, emit_depth):
        """One aggressive order eats the touch; a gone queue moves the price a tick and the other side follows."""
        rng = self.rng
        rows = s.asks if is_buy else s.bids
        opp = s.bids if is_buy else s.asks
        remaining = size
        while remaining > 0 and rows:
            price, avail = rows[0][0], rows[0][1]
            take = min(remaining, avail)
            self.engine.on_print(sym, price, int(take), rng.choice(EXCH), t)
            s.last = price
            s.vol += take
            rows[0][1] -= take
            remaining -= take
            lv = s.level
            at_level = lv is not None and lv["side"] == (ASK if is_buy else BID) and abs(price - lv["price"]) < 1e-9
            if at_level:
                lv["hit"] += take
                if rows[0][1] <= 0 and lv["reserve"] > 0:
                    # the reload: size comes back a moment later (refill), never in the same instant
                    lv["refill_at"] = t + rng.uniform(0.3, 1.2)
                    lv["refills"] += 1
                    rows[0][1] = 0
                    break
            if rows[0][1] <= 0:
                rows.pop(0)
                if at_level:
                    lv["done"] = "clean"
                self._extend(s)
                follow = 0.85 if (REGIMES[s.regime]["bias"] > 0.5) == is_buy else 0.55
                if rng.random() < follow and not (s.level is not None and s.level["side"] == (BID if is_buy else ASK) and abs(price - s.level["price"]) < 1e-9):
                    opp.insert(0, [price, self._fresh(s, BID if is_buy else ASK)])
                if rng.random() < 0.55:
                    break   # most orders don't sweep several levels
        # sizes from sweeps that reached nothing left are just lost (the book is contiguous, price moved)

    def _flow(self, sym, s, t, dt, emit_depth):
        rng = self.rng
        bias, rate, mult = self._params(s, t)
        lam = rate * dt * self._tod(t)
        n = int(lam) + (1 if rng.random() < lam - int(lam) else 0)
        for _ in range(n):
            is_buy = rng.random() < bias
            if rng.random() < 0.22:
                size = rng.randint(1, 99)                       # odd lots
            else:
                size = _r100(rng.lognormvariate(5.4, 0.75) * mult)
                if rng.random() < 0.03:
                    size *= 6                                   # a sweep
            self._market(sym, s, is_buy, size, t, emit_depth)

    def _params(self, s, t):
        rg = REGIMES[s.regime]
        while s.script and t >= s.script[0][2]:
            s.script.pop(0)
        if s.script:
            b, r, _ = s.script[0]
            return b, r, rg["size"]
        return rg["bias"], rg["rate"], rg["size"]

    @staticmethod
    def _tod(t):
        from .ps60 import ny_offset, SESSION_OPEN
        off = ny_offset(t)
        sec = (t + off) % 86400 - SESSION_OPEN
        if sec < 0 or sec > 390 * 60:
            return 1.0
        if sec < 30 * 60:
            return 1.9
        if sec > 360 * 60:
            return 1.5
        if 150 * 60 < sec < 270 * 60:
            return 0.7
        return 1.0

    # ---- regimes ---------------------------------------------------------------

    def _regime(self, s, t):
        if t < s.regime_until:
            return
        rng = self.rng
        opts = NEXT[s.regime]
        tot = sum(w for _, w in opts)
        x = rng.uniform(0, tot)
        for name, w in opts:
            x -= w
            if x <= 0:
                break
        s.regime = name
        lo, hi = REGIMES[name]["dur"]
        s.regime_until = t + rng.uniform(lo, hi) * 60

    # ---- the PS60 participant at the pivot ---------------------------------------------

    def _level(self, sym, s, t):
        rng, p, tk = self.rng, s.play, s.tk
        pivot = p.get("trigger")
        lv = s.level
        if lv is None:
            if not pivot or t < s.level_cooldown:
                return
            seller = p["side"] == "long"                  # a long needs the offer at the pivot cleared
            side = ASK if seller else BID
            rows = s.asks if seller else s.bids
            best = rows[0][0]
            dist = (pivot - best) if seller else (best - pivot)
            steps = int(round(dist / tk))
            if steps < 0:
                # price is past the pivot already: bring it back toward the level with a scripted lean
                if not s.script:
                    s.script = [(0.36 if seller else 0.64, 2.0, t + 45)]
                return
            if steps > 2:
                if not s.script and rng.random() < 0.5:
                    s.script = [(0.6 if seller else 0.4, 1.6, t + 40)]   # approach the level
                return
            mode = rng.choice(("hold", "hold", "clean", "clean", "pull"))
            shown = rng.choice((1500, 2000, 2500, 3000, 4000))
            reserve = {"hold": rng.randint(60000, 120000), "clean": rng.randint(6000, 15000), "pull": rng.randint(8000, 14000)}[mode]
            rows[steps][1] = shown
            s.level = {"side": side, "price": pivot, "mode": mode, "shown": shown, "reserve": reserve, "hit": 0,
                       "refills": 0, "refill_at": None, "done": None, "started": t}
            s.script = [(0.66 if seller else 0.34, 2.6, t + 240)]      # flow leans into the level
            return
        # an active episode
        side, rows = lv["side"], (s.asks if lv["side"] == ASK else s.bids)
        seller = side == ASK
        idx = next((i for i, r in enumerate(rows) if abs(r[0] - lv["price"]) < 1e-9), None)
        if lv["refill_at"] is not None and t >= lv["refill_at"] and idx is not None:
            lv["refill_at"] = None
            if lv["mode"] == "pull" and lv["refills"] >= rng.randint(3, 6):
                lv["done"] = "pull"
            else:
                refill = min(lv["reserve"], rng.choice((1500, 2000, 2500, 3000, 4000)))
                lv["reserve"] -= refill
                rows[idx][1] = refill
        if idx is not None and rows[idx][1] <= 0 and lv["refill_at"] is None and lv["reserve"] <= 0:
            lv["done"] = "clean"
        if lv["mode"] == "hold" and lv["refills"] >= rng.randint(4, 8) and lv["done"] is None:
            lv["done"] = "hold"
        if lv["done"] is None and t - lv["started"] > 300:
            lv["done"] = "hold"
        if lv["done"] is None:
            return
        # outcome
        if lv["done"] == "hold":
            # rejection: the level held, price backs away
            if idx is not None:
                rows[idx][1] = _r100(rows[idx][1] + rng.choice((2000, 4000, 8000)))
            s.script = [(0.32 if seller else 0.68, 2.4, t + 90), (0.45 if seller else 0.55, 1.4, t + 240)]
        else:
            if lv["done"] == "pull" and idx is not None:
                rows[idx][1] = _r100(rng.lognormvariate(math.log(s.base * 0.4), 0.4))
            # break: momentum through, a retrace back toward the level, then continuation (the second entry)
            s.script = [(0.72 if seller else 0.28, 3.2, t + 50), (0.38 if seller else 0.62, 1.8, t + 110),
                        (0.66 if seller else 0.34, 2.4, t + 260)]
        s.level = None
        s.level_cooldown = t + rng.uniform(240, 600)

    # ---- one step ------------------------------------------------------------------

    def step(self, t):
        dt = 0.25 if self.t is None else max(0.05, min(1.0, t - self.t))
        self.t = t
        for sym, s in self.state.items():
            slotted = sym in self.engine.slots
            if not slotted:
                s.prev = {ASK: [], BID: []}
            self._regime(s, t)
            self._churn(s, t)
            self._level(sym, s, t)
            self._flow(sym, s, t, dt, slotted)
            self._extend(s)
            self._emit(sym, s, t, slotted)
        for _cmd in self.engine.tick(t):
            pass

    def _emit(self, sym, s, t, slotted):
        eng = self.engine
        bid, ask = s.bids[0][0], s.asks[0][0]
        for field, v in (("bid", bid), ("ask", ask), ("last", s.last)):
            if s.l1.get(field) != v:
                s.l1[field] = v
                eng.on_l1(sym, field, v, t)
        if not slotted:
            return
        for side, rows in ((ASK, s.asks), (BID, s.bids)):
            cur = [(r[0], int(r[1])) for r in rows[:ROWS]]
            prev = s.prev[side]
            for i, (price, size) in enumerate(cur):
                if i < len(prev) and prev[i] == (price, size):
                    continue
                eng.on_depth(sym, i, UPDATE if i < len(prev) else INSERT, side, price, size, "", t)
            s.prev[side] = cur
