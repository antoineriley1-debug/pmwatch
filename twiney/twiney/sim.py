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

from .book import ASK, BID, DELETE, INSERT, UPDATE
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


# day types: a scenario tilts which regimes tend to come next, so some sessions trend, some chop, some flush
SCENARIOS = {
    "mixed":        {},
    "trend_up":     {"trend_up": 3, "grind_up": 2, "squeeze": 1.5, "fade": 0.6, "trend_down": 0.4, "grind_down": 0.4, "capitulation": 0.2},
    "trend_down":   {"trend_down": 3, "grind_down": 2, "capitulation": 1.5, "bounce": 0.7, "trend_up": 0.4, "grind_up": 0.4, "squeeze": 0.2},
    "chop":         {"chop": 3, "grind_up": 0.7, "grind_down": 0.7, "trend_up": 0.4, "trend_down": 0.4, "squeeze": 0.3, "capitulation": 0.3},
    "capitulation": {"trend_down": 2, "capitulation": 3, "bounce": 2, "chop": 0.6, "trend_up": 0.3},
    "squeeze":      {"trend_up": 2, "squeeze": 3, "fade": 1.5, "chop": 0.6, "trend_down": 0.3},
}


# Episodes: the market styles that have a SHAPE over time. Each stage: (lean, tape speed, print size, book on the
# side being hit (1 = normal, lower = bids / offers pulled), seconds lo, hi). Mirrors are built for the other side.
EPISODES = {
    # buyers run out: the move speeds up into a climax of big fast prints, then the tape dries up, price stalls and rolls
    "exhaustion_top": [(0.66, 2.0, 1.2, 1.0, 60, 120), (0.72, 3.2, 1.6, 0.8, 40, 80), (0.76, 5.5, 2.6, 0.6, 15, 30),
                       (0.50, 0.40, 0.7, 1.0, 40, 90), (0.38, 1.6, 1.1, 1.0, 60, 120)],
    # the flush: heavy selling, bids pulled, a waterfall of huge prints, then the V: buyers slam it back
    "capitulation":   [(0.34, 2.2, 1.3, 0.8, 60, 120), (0.25, 3.6, 1.9, 0.55, 40, 80), (0.14, 6.5, 3.3, 0.35, 15, 35),
                       (0.74, 4.2, 2.3, 1.0, 20, 45), (0.56, 1.4, 1.0, 1.0, 90, 180)],
}
EPISODES["exhaustion_bottom"] = [(1 - b, r, z, th, lo, hi) for b, r, z, th, lo, hi in EPISODES["exhaustion_top"]]
EPISODES["squeeze_up"] = [(1 - b, r, z, th, lo, hi) for b, r, z, th, lo, hi in EPISODES["capitulation"]]


# how hard each name follows the market (the Nasdaq / QQQ factor). 1.0 = moves with QQQ, 2 = twice as hard,
# near 0 = its own thing, negative = the other way. Anything not listed trades like a mid-cap tech name.
BETAS = {"QQQ": 1.0, "SPY": 0.85, "SPX": 0.85, "IWM": 0.9, "DIA": 0.7,
         "NVDA": 1.7, "AMD": 1.7, "TSLA": 1.8, "PLTR": 1.7, "SMCI": 2.0, "MSTR": 2.2, "COIN": 1.9, "ARM": 1.8, "MU": 1.5,
         "AVGO": 1.4, "META": 1.3, "AMZN": 1.2, "AAPL": 1.1, "MSFT": 1.0, "GOOGL": 1.1, "NFLX": 1.1, "SHOP": 1.5, "SNOW": 1.4,
         "SOFI": 1.4, "HOOD": 1.8, "UBER": 1.2, "INTC": 1.1, "RIVN": 1.5, "NIO": 1.3, "BABA": 0.9, "CVNA": 1.8,
         "DIS": 0.7, "BA": 0.8, "JPM": 0.6, "XOM": 0.3, "GLD": 0.0, "TLT": -0.3}
INDEX = {"QQQ", "SPY", "SPX", "IWM", "DIA"}


def beta_of(sym):
    return BETAS.get(sym, 1.2)


class _Mkt:
    """The market: one regime process everybody leans on. The session's day type tilts this one."""
    __slots__ = ("regime", "regime_until", "bias", "level", "prev_level")

    def __init__(self):
        self.regime, self.regime_until, self.bias = "chop", 0.0, 0.5
        self.level = self.prev_level = 488.0      # QQQ-like




def roundness(price):
    """How much a price draws size: whole dollars most, then halves, quarters, dimes, nickels. Institutions work
    their orders at round numbers, so that is where the liquidity (and the reloaders) sit and where the tape is heavy."""
    if not price or price < 1:
        return 1.0
    c = int(round(price * 100)) % 100
    if c == 0:
        return 4.0
    if c == 50:
        return 3.0
    if c in (25, 75):
        return 2.0
    if c % 10 == 0:
        return 1.5
    if c % 5 == 0:
        return 1.2
    return 1.0


def _r100(x):
    return max(100, int(round(x / 100.0)) * 100)


class _Sym:
    __slots__ = ("play", "tk", "asks", "bids", "last", "vol", "regime", "regime_until", "script", "big",
                 "big_home", "parts", "level_cooldown", "hidden_next", "prev", "l1", "base", "mid0", "beta", "sym", "eff", "owed",
                 "hot", "hot_dir", "mom", "spent", "now", "last_mid", "episode", "ep_next", "thin", "ep_script")

    def __init__(self, play, mid, t):
        self.play = play
        self.tk = tick_size(mid)
        self.mid0 = mid
        self.base = min(7500, max(500, 1500 * math.sqrt(50.0 / max(mid, 1.0))))   # typical resting size
        self.asks, self.bids = [], []
        self.last = mid
        self.vol = 0
        self.regime, self.regime_until = "chop", t
        self.script = []            # [(bias, rate, until_t)] scripted stages that override the regime
        self.big = {}               # (side, price) -> until
        self.spent = {}             # (side, price) -> until: a reloader was just cleaned / pulled there, it stays thin
        self.now = 0.0
        self.big_home = {ASK: None, BID: None}
        self.parts = []             # participants working a level: the one at the pivot, and hidden ones anywhere
        self.level_cooldown = t
        self.hidden_next = t
        self.sym = play.get("symbol", "")
        self.beta = beta_of(self.sym)
        self.eff = (0.5, 1.2, 1.0)   # this step's blended lean, rate, size: own regime + beta x market
        self.owed = 0.0              # dollars of move the index / basket desks still have to push through this name
        self.hot = 0.0               # tape heat: price moving brings more orders (chasers, stops), fading in seconds
        self.hot_dir = 0             # which way it last moved
        self.mom = 0.0               # the market's push on this name over the last ~10 s, in ticks (signed)
        self.last_mid = mid
        self.episode = None          # (name, stage index) while an exhaustion / capitulation / squeeze plays out
        self.ep_next = None          # first episode time is drawn from the feed's own (seeded) random
        self.ep_script = None
        self.thin = 1.0              # the book on the side being hit (pulled bids in a flush, pulled offers in a squeeze)
        self.prev = {ASK: [], BID: []}
        self.l1 = {}


class DemoFeed:
    def __init__(self, engine, plays, seed=7, scenario=None):
        self.engine = engine
        self.rng = random.Random(seed if seed is not None else int(__import__("time").time() * 1000) % 1000003)
        names = list(SCENARIOS)
        self.scenario = scenario if scenario in SCENARIOS else self.rng.choices(names, weights=[3, 2, 2, 2, 1, 1])[0]
        self.mkt = _Mkt()
        self.pushes = {}   # symbol -> (time, direction): a move the option flow saw coming
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
        from .flow import SimFlow
        known = {k: v for k, v, _b in SimFlow.MARKET}
        base = known.get(p["symbol"])
        s = _Sym(p, round(base * self.rng.uniform(0.98, 1.02), 2) if base else round(self.rng.uniform(20, 300), 2), t)
        self._history_one(p["symbol"], s, t)
        self._seed_book(s, t)
        s.regime_until = t
        self.state[p["symbol"]] = s     # published only once it has a book: the market loop never sees it half-built

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
            if ((day0 + off) // 86400) % 7 in (2, 3):   # skip Sat / Sun (epoch day 0 is a Thursday: 2 = Sat, 3 = Sun)
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
            # a day's volume: bigger on the big-range days, like the real thing
            rng_pct = (h - l) / max(c, 0.01)
            vol = int(rng.lognormvariate(math.log(s.base * 3000), 0.3) * (0.6 + 25 * rng_pct))
            self.engine.on_daily_bar(sym, day0, o, h, l, c, vol)
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

    @staticmethod
    def _rn(s, side, price):
        """How much size a price draws: round numbers more - except one where a reloader was just cleaned or
        pulled. That size is gone; for a while there is less there than anywhere around it, not a new wall."""
        until = s.spent.get((side, round(price, 4))) if price is not None else None
        if until is not None:
            if s.now < until:
                return 0.4
            del s.spent[(side, round(price, 4))]
        return roundness(price)

    def _fresh(self, s, side, price=None):
        b = s.eff[0]
        against = (side == ASK and b > 0.5) or (side == BID and b < 0.5)
        target = s.base * (max(0.3, 1 - 2.5 * abs(b - 0.5)) if against else 1.2) * self._rn(s, side, price)
        return _r100(self.rng.lognormvariate(math.log(target), 0.7))

    def _seed_book(self, s, t):
        tk = s.tk
        bid = round(s.mid0 - tk, 2)
        s.asks = [[round(bid + tk * (i + 1), 2), self._fresh(s, ASK, round(bid + tk * (i + 1), 2))] for i in range(ROWS + 4)]
        s.bids = [[round(bid - tk * i, 2), self._fresh(s, BID, round(bid - tk * i, 2))] for i in range(ROWS + 4)]
        s.last = s.asks[0][0]

    def _extend(self, s):
        tk = s.tk
        while len(s.asks) < ROWS + 4:
            p = round((s.asks[-1][0] if s.asks else s.bids[0][0]) + tk, 2)
            s.asks.append([p, self._fresh(s, ASK, p)])
        while len(s.bids) < ROWS + 4:
            p = round((s.bids[-1][0] if s.bids else s.asks[0][0]) - tk, 2)
            s.bids.append([p, self._fresh(s, BID, p)])

    def _churn(self, s, t):
        """Passive flow: rows add, cancel, thin out and refill; big size shows up, sits, gets pulled or hit."""
        rng, rg = self.rng, REGIMES[s.regime]
        if s.thin < 1.0 and rng.random() < 0.35:
            # a flush pulls the bids (a squeeze the offers): the side in the way thins out and price falls through
            hit = s.bids if s.eff[0] < 0.5 else s.asks
            for row in hit[:5]:
                row[1] = max(100, _r100(row[1] * s.thin))
        for side, rows in ((ASK, s.asks), (BID, s.bids)):
            b = s.eff[0]
            against = (side == ASK and b > 0.5) or (side == BID and b < 0.5)
            target = s.base * (max(0.3, 1 - 2.5 * abs(b - 0.5)) if against else 1.2)
            for i in range(min(ROWS, len(rows))):
                row = rows[i]
                key = (side, row[0])
                if key in s.big:
                    if t >= s.big[key]:
                        del s.big[key]
                        # away from the touch, big size often gets pulled (it was there to be seen). At the touch
                        # it mostly stays and has to be traded through; a pull right there is the rare spoof.
                        if rng.random() < (0.6 if i >= 2 else 0.15):   # pulled
                            row[1] = _r100(rng.lognormvariate(math.log(target), 0.5))
                    continue
                if any(pt["side"] == side and abs(row[0] - pt["price"]) < 1e-9 for pt in s.parts):
                    continue                            # a participant manages this row
                if i < 2:
                    # the inside queue: it only goes down when prints take it or someone cancels, and grows when
                    # someone joins - a few hundred at a time. It is never re-dealt, so a print that takes 300 off
                    # the bid shows as 300 less on the ladder.
                    if rng.random() < 0.18:
                        if rng.random() < 0.6:
                            row[1] = row[1] + rng.choice((100, 100, 200, 200, 300, 500))           # joins
                        else:
                            row[1] = max(100, row[1] - rng.choice((100, 100, 200, 300)))        # cancels
                    continue
                if rng.random() < 0.12:
                    tg = target * self._rn(s, side, row[0])
                    row[1] = _r100(row[1] + 0.2 * (tg - row[1]) + rng.gauss(0, 0.25 * tg))
            # big resting size: 5k-40k, mostly at a fresh price, sometimes back at the same one (a repeat)
            if rng.random() < 0.006 and len(rows) > 6:
                # big size goes where institutions work: round numbers first
                cand = list(range(1, min(9, len(rows))))
                i = rng.choices(cand, weights=[self._rn(s, side, rows[j][0]) ** 2 for j in cand])[0]
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
            hit_side = ASK if is_buy else BID
            lv = next((pt for pt in s.parts if pt["side"] == hit_side and abs(price - pt["price"]) < 1e-9), None)
            if take <= 0:
                if lv is not None and lv["refill_at"] is not None:
                    break                  # he is reloading this very moment: the order waits, nothing trades
                rows.pop(0)
                self._extend(s)
                continue
            # the engine sees the book this order trades against before it sees the print (as on a real feed,
            # the quote is out before the trade): so the print is read against the quote it hit
            self._emit(sym, s, t, emit_depth)
            self.engine.on_print(sym, price, int(take), rng.choice(EXCH), t)
            s.last = price
            s.vol += take
            rows[0][1] -= take
            remaining -= take
            if lv is not None:
                lv["hit"] += take
                if rows[0][1] <= 0 and lv["reserve"] > 0:
                    # the reload: size comes back a moment later, sometimes quick, sometimes after a beat
                    lv["refill_at"] = t + (rng.uniform(0.2, 0.9) if rng.random() < 0.6 else rng.uniform(1.0, 3.0))
                    lv["refills"] += 1
                    rows[0][1] = 0
                    break
            if rows[0][1] <= 0:
                rows.pop(0)
                if lv is not None:
                    lv["done"] = "clean"
                self._extend(s)
                follow = 0.85 if (s.eff[0] > 0.5) == is_buy else 0.55
                if rng.random() < follow and not any(pt["side"] == (BID if is_buy else ASK) and abs(price - pt["price"]) < 1e-9 for pt in s.parts):
                    opp.insert(0, [price, self._fresh(s, BID if is_buy else ASK, price)])
                if rng.random() < 0.55:
                    break   # most orders don't sweep several levels
        # sizes from sweeps that reached nothing left are just lost (the book is contiguous, price moved)

    @staticmethod
    def _heat(s):
        """How hot the tape is: a level that just broke, or the market pushing this name (past a few ticks)."""
        return min(5.0, s.hot + max(0.0, abs(s.mom) - 3.0) / 3.0)

    def _tempo(self, s):
        """How fast the tape runs right now, and which way it leans on top of the regime:
        - moving price draws orders (momentum chasers, stops): the tape speeds up with the move and leans with it
        - price coming into a level (a reloader, a round number a few ticks ahead) makes it slow down: people wait
          to see who holds it; AT the level the prints stay heavy (absorption) while price goes nowhere"""
        heat = self._heat(s)
        tempo = 1.0
        lean = 0.0
        d = s.hot_dir or (1 if s.eff[0] > 0.5 else -1)
        rows = s.asks if d > 0 else s.bids
        ahead = rows[1:4]
        levels = {round(pt["price"], 4) for pt in s.parts}
        if any(round(r[0], 4) in levels or roundness(r[0]) >= 2 for r in ahead) and heat < 2.5:
            tempo *= 0.5                                  # approaching a level: the tape slows
        if rows and (round(rows[0][0], 4) in levels):
            tempo = max(tempo, 1.3)                       # at the level: steady, heavy prints into it
        return tempo, lean

    def _flow(self, sym, s, t, dt, emit_depth):
        rng = self.rng
        bias, rate, mult = s.eff
        tempo, lean = self._tempo(s)
        base_rate = rate
        rate *= tempo
        lam = rate * dt * self._tod(t)
        # chasers: a moving price pulls in orders on the side it is moving to (momentum, stops) - the tape speeds up
        # WITH the move; most moves start with the market, so this amplifies the market's move, not noise
        heat = self._heat(s)
        if s.hot_dir and heat > 0.3:
            lc = base_rate * dt * self._tod(t) * 0.9 * heat
            nc = int(lc) + (1 if rng.random() < lc - int(lc) else 0)
            for _ in range(nc):
                size = _r100(rng.lognormvariate(5.2, 0.7) * mult)
                self._market(sym, s, s.hot_dir > 0, size, t, emit_depth)
        n = int(lam) + (1 if rng.random() < lam - int(lam) else 0)
        for _ in range(n):
            is_buy = rng.random() < bias
            touch = (s.asks if is_buy else s.bids)
            r = roundness(touch[0][0]) if touch else 1.0
            if rng.random() < 0.22:
                size = rng.randint(1, 99)                       # odd lots
            else:
                size = _r100(rng.lognormvariate(5.4, 0.75) * mult * (1 + 0.35 * (r - 1)))   # heavier into a round number
                if rng.random() < 0.03:
                    size *= 6                                   # a sweep
                if r >= 2 and rng.random() < 0.04 * r:
                    size = max(size, rng.choice((2000, 3000, 5000, 8000, 10000)))   # a block at the round number
            self._market(sym, s, is_buy, size, t, emit_depth)

    def _params(self, s, t):
        rg = REGIMES[s.regime]
        while s.script and t >= s.script[0][2]:
            s.script.pop(0)
        m = self.mkt.bias - 0.5
        heat = 1.0 + 1.2 * abs(m)                               # a fast tape makes every name busier
        if s.episode and s.script is not getattr(s, "ep_script", None):
            s.episode = None          # a level's own script took over: the episode is over
        if s.script:
            st = s.script[0]
            b, r = st[0], st[1]
            size = st[3] if len(st) > 3 else rg["size"]
            s.thin = st[4] if len(st) > 4 else 1.0
            b = 0.5 + 0.8 * (b - 0.5) + (1.0 if s.episode else 0.6) * s.beta * m   # still feels the market
            return min(0.9, max(0.1, b)), r * heat, size
        s.thin = 1.0
        s.episode = None
        own = 0.25 if s.sym in INDEX else 0.4                   # an index is mostly the market; a stock is part itself
        b = 0.5 + own * (rg["bias"] - 0.5) + 1.0 * s.beta * m
        return min(0.9, max(0.1, b)), rg["rate"] * heat, rg["size"]

    def _close_spread(self, s):
        """Market makers: a gap between bid and ask gets stepped into within a moment. Who steps in follows the
        lean, so in a rally the bids step up and in a sell-off the offers step down."""
        rng, tk = self.rng, s.tk
        for _ in range(3):
            if not s.asks or not s.bids:
                return
            gap = int(round((s.asks[0][0] - s.bids[0][0]) / tk))
            if gap <= 1 or rng.random() > 0.8:
                return
            if rng.random() < s.eff[0]:
                p = round(s.bids[0][0] + tk, 2)
                s.bids.insert(0, [p, _r100(self._fresh(s, BID, p) * 0.6)])
            else:
                p = round(s.asks[0][0] - tk, 2)
                s.asks.insert(0, [p, _r100(self._fresh(s, ASK, p) * 0.6)])

    def _market_step(self, t, dt):
        mk, rng = self.mkt, self.rng
        self._regime(mk, t)
        target = REGIMES[mk.regime]["bias"]
        # the market's lean wanders on a minute scale (a slow mean-reverting drift toward the regime), it does not jump
        target = 0.5 + 0.6 * (target - 0.5)
        mk.bias += 0.004 * dt / 0.25 * (target - mk.bias) + rng.gauss(0, 0.004 * math.sqrt(dt / 0.25))
        mk.bias = min(0.7, max(0.3, mk.bias))
        mk.prev_level = mk.level
        mk.level *= math.exp((mk.bias - 0.5) * 6.4e-5 * dt + rng.gauss(0, 1.0e-4 * math.sqrt(dt)))

    REPRICE = 0.6   # share of that move that is quotes repricing rather than prints
    BASKET = 1.7    # share of each name's move that comes from index / ETF / basket flow

    def _basket(self, sym, s, t, slotted):
        """When QQQ moves, the ETF and basket desks buy or sell every component at once. Each name owes
        beta x the market's move; they lift offers / hit bids at the touch until it is paid. A big resting
        participant at the touch stops them, as it would: the rally stalls into the seller."""
        mk = self.mkt
        if not mk.prev_level:
            return
        s.owed += self.BASKET * s.beta * math.log(mk.level / mk.prev_level) * s.last
        # basket desks work in clips at the touch, never the whole level in one print. A wall (big resting size)
        # takes a lot of clips to get through and bleeds the push while they chip at it: price stalls into it,
        # the way it does on a real ladder, and only goes through once the size has actually traded.
        cap = s.owed / s.tk
        if abs(cap) > 6:
            s.owed = 6 * s.tk * (1 if cap > 0 else -1)
        for _ in range(4):
            if abs(s.owed) < s.tk:
                return
            is_buy = s.owed > 0
            rows = s.asks if is_buy else s.bids
            if not rows:
                return
            side = ASK if is_buy else BID
            if any(pt["side"] == side and abs(rows[0][0] - pt["price"]) < 1e-9 for pt in s.parts):
                s.owed *= 0.9      # parked into a real participant: the move leaks away instead
                return
            touch = rows[0][1]
            wall = touch >= max(5 * s.base, 5000)
            opp = s.bids if is_buy else s.asks
            if s.hot >= 2.0 and s.hot_dir and (s.hot_dir > 0) != is_buy:
                s.owed *= 0.5      # a level just broke: for a few seconds the break's momentum wins over the index
                return
            with_push = abs(s.mom) >= 1 and (s.mom > 0) == is_buy
            if not wall and len(rows) > 1 and opp and (not with_push or self.rng.random() < self.REPRICE):
                # the market makers move their quotes with the index: the offer lifts / the bid drops, no print.
                # A wiggle against the last few seconds' push is only ever that; the desks trade WITH the push
                rows.pop(0)
                step = s.tk if is_buy else -s.tk
                p = round(opp[0][0] + step, 2)
                if (p < rows[0][0]) if is_buy else (p > rows[0][0]):
                    opp.insert(0, [p, _r100(self._fresh(s, BID if is_buy else ASK, p) * 0.6)])
                self._extend(s)
                s.owed -= step
                continue
            clip = _r100(self.rng.lognormvariate(math.log(max(100.0, s.base * 0.9)), 0.6))
            if touch - clip < 100:
                clip = int(touch)          # the last of the level
            before = rows[0][0]
            self._market(sym, s, is_buy, int(min(touch, max(1, clip))), t, slotted)
            if (s.asks[0][0] if is_buy else s.bids[0][0]) != before:
                s.owed -= s.tk if is_buy else -s.tk
            else:
                s.owed *= 0.85     # a clip that didn't move it: the rest of the push is soaked up by resting size
            if wall:
                s.owed *= 0.99     # leaning on a wall: one clip a beat, a little of the push gives up
                return

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
        tilt = SCENARIOS.get(self.scenario, {}) if s is self.mkt else {}
        opts = [(n, w * tilt.get(n, 1.0)) for n, w in NEXT[s.regime]]
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

    def _new_part(self, s, side, price, t, pivot):
        """A participant working a price. Not two alike: iceberg (small shows, deep reserve), block
        (bigger shows), or a shallow one that pulls; refills vary; some hold, some get run over."""
        rng = self.rng
        r = roundness(price)
        # at a round number the one working the level is usually bigger and more often there to stay
        mode = rng.choices(("hold", "clean", "pull"), weights=(4 * r, 4, 2))[0]
        iceberg = rng.random() < 0.45
        base = rng.choice((200, 300, 400, 500, 700)) if iceberg else rng.choice((900, 1200, 1500, 2000, 2800, 3500))
        base = int(base * r ** 0.6 / 100) * 100 or 100
        reserve = {"hold": rng.randint(30000, 120000), "clean": rng.randint(3000, 18000), "pull": rng.randint(4000, 12000)}[mode]
        reserve = int(reserve * r ** 0.8)
        return {"side": side, "price": price, "mode": mode, "base": base, "reserve": reserve, "hit": 0, "refills": 0,
                "refill_at": None, "done": None, "started": t, "pivot": pivot,
                "hold_after": rng.randint(4, 10), "pull_after": rng.randint(2, 6)}

    def _episodes(self, s, t):
        """Now and then a name plays out a whole market style: exhaustion at a top / bottom, a capitulation flush,
        a squeeze. Random timing, random pick (leaning on how it has been trading); a flush or squeeze in the whole
        market pulls the high-beta names in with it."""
        rng = self.rng
        if s.ep_next is None:
            s.ep_next = t + rng.uniform(1800, 7200)      # a name's own episode: every hour or two at most
        if s.script or t < s.ep_next:
            return
        mk = self.mkt.regime
        with_market = mk in ("capitulation", "squeeze") and s.beta >= 1.2 and rng.random() < 0.5
        if not with_market and t < s.ep_next:
            return
        s.ep_next = t + rng.uniform(3600, 9000)
        if with_market:
            name = "capitulation" if mk == "capitulation" else "squeeze_up"
        else:
            lean = {"trend_up": "up", "grind_up": "up", "squeeze": "up", "bounce": "up",
                    "trend_down": "down", "grind_down": "down", "capitulation": "down", "fade": "down"}.get(s.regime)
            w = {"exhaustion_top": 2 if lean == "up" else 1, "squeeze_up": 1.2 if lean == "up" else 0.5,
                 "exhaustion_bottom": 2 if lean == "down" else 1, "capitulation": 1.2 if lean == "down" else 0.5}
            name = rng.choices(list(w), weights=list(w.values()))[0]
        at, script = t, []
        for b, r, z, th, lo, hi in EPISODES[name]:
            at += rng.uniform(lo, hi)
            script.append((b, r * rng.uniform(0.85, 1.15), at, z * rng.uniform(0.85, 1.2), th))
        s.script = script
        s.episode = name
        s.ep_script = script

    def _participants(self, sym, s, t):
        rng, p, tk = self.rng, s.play, s.tk
        pivot = p.get("trigger")
        # the one at the pivot: shows up when price comes into the level
        if pivot and t >= s.level_cooldown and not any(pt["pivot"] for pt in s.parts):
            seller = p["side"] == "long"                  # a long needs the offer at the pivot cleared
            side = ASK if seller else BID
            rows = s.asks if seller else s.bids
            best = rows[0][0]
            dist = (pivot - best) if seller else (best - pivot)
            steps = int(round(dist / tk))
            if steps < 0:
                if not s.script:
                    s.script = [(0.36 if seller else 0.64, 2.0, t + 45)]   # bring price back toward the level
            elif steps > 2:
                if not s.script and rng.random() < 0.5:
                    s.script = [(0.6 if seller else 0.4, 1.6, t + 40)]     # approach
            else:
                pt = self._new_part(s, side, pivot, t, True)
                rows[steps][1] = _r100(pt["base"] * rng.uniform(0.7, 1.3))
                s.parts.append(pt)
                # flow leans into the level, not always hard: sometimes it takes a while to get tested
                s.script = [(0.62 if seller else 0.38, rng.uniform(1.6, 2.8), t + rng.uniform(120, 300))]
        # hidden participants anywhere in the book, on either side: the ones you have to find yourself
        if t >= s.hidden_next:
            s.hidden_next = t + rng.uniform(240, 900)
            side = rng.choice((ASK, BID))
            rows = s.asks if side == ASK else s.bids
            # hidden reloaders sit where the liquidity is: whole / half / quarter dollars and dimes, far more often
            cand = list(range(1, min(9, len(rows) - 1) + 1))
            i = rng.choices(cand, weights=[self._rn(s, side, rows[j][0]) ** 3 for j in cand])[0]
            if not any(abs(pt["price"] - rows[i][0]) < 1e-9 for pt in s.parts):
                pt = self._new_part(s, side, rows[i][0], t, False)
                rows[i][1] = _r100(pt["base"] * rng.uniform(0.7, 1.3))
                s.parts.append(pt)
                if rng.random() < 0.4:                     # sometimes the flow finds it, sometimes it just sits
                    s.script = [(0.62 if side == ASK else 0.38, rng.uniform(1.4, 2.4), t + rng.uniform(60, 180))]
        # work every active participant
        for lv in list(s.parts):
            side, rows = lv["side"], (s.asks if lv["side"] == ASK else s.bids)
            seller = side == ASK
            idx = next((i for i, r in enumerate(rows) if abs(r[0] - lv["price"]) < 1e-9), None)
            if idx is None and lv["done"] is None:
                # price moved away and the row rolled out of view: he is still there, nothing to see for now
                if t - lv["started"] > 900:
                    s.parts.remove(lv)
                continue
            if lv["refill_at"] is not None and t >= lv["refill_at"] and idx is not None:
                lv["refill_at"] = None
                if lv["mode"] == "pull" and lv["refills"] >= lv["pull_after"]:
                    lv["done"] = "pull"
                else:
                    refill = min(lv["reserve"], _r100(lv["base"] * rng.uniform(0.5, 1.4)))
                    lv["reserve"] -= refill
                    rows[idx][1] = refill
            if idx is not None and rows[idx][1] <= 0 and lv["refill_at"] is None and lv["reserve"] <= 0:
                lv["done"] = "clean"
            if lv["mode"] == "hold" and lv["refills"] >= lv["hold_after"] and lv["done"] is None:
                lv["done"] = "hold"
            if lv["done"] is None and t - lv["started"] > 420:
                lv["done"] = "hold" if lv["refills"] >= 2 else "fade"
            if lv["done"] is None:
                continue
            # outcome
            if lv["done"] == "hold":
                if idx is not None and rng.random() < 0.5:
                    rows[idx][1] = _r100(rows[idx][1] + rng.choice((1500, 3000, 6000)))
                if lv["pivot"] or rng.random() < 0.5:
                    s.script = [(0.34 if seller else 0.66, 2.2, t + 80), (0.45 if seller else 0.55, 1.4, t + 200)]
            elif lv["done"] == "fade":
                pass                                       # never really tested: he just goes away
            else:
                s.spent[(side, round(lv["price"], 4))] = t + rng.uniform(45, 150)
                if lv["done"] == "clean":
                    s.hot += 5.0                               # the level broke: the tape bursts through it
                    s.hot_dir = 1 if seller else -1
                if lv["done"] == "pull" and idx is not None:
                    rows[idx][1] = _r100(rng.lognormvariate(math.log(s.base * 0.4), 0.4))
                if lv["pivot"]:
                    # break: momentum through, a retrace back toward the level, then continuation (the second entry)
                    s.script = [(0.72 if seller else 0.28, 3.0, t + 50), (0.38 if seller else 0.62, 1.8, t + 110),
                                (0.66 if seller else 0.34, 2.4, t + 260)]
                elif rng.random() < 0.6:
                    s.script = [(0.68 if seller else 0.32, 2.4, t + 60)]
            s.parts.remove(lv)
            if lv["pivot"]:
                s.level_cooldown = t + rng.uniform(300, 900)

    # ---- one step ------------------------------------------------------------------

    def step(self, t):
        dt = 0.25 if self.t is None else max(0.05, min(1.0, t - self.t))
        self.t = t
        self._market_step(t, dt)
        for sym, (at, d) in list(self.pushes.items()):          # the move the option flow was early on
            s = self.state.get(sym)
            if s is not None and t >= at and not s.script:
                s.script = [(0.5 + 0.17 * d, 2.4, t + self.rng.uniform(120, 300))]
                del self.pushes[sym]
            elif s is None or t > at + 900:
                self.pushes.pop(sym, None)
        for sym, s in list(self.state.items()):
            slotted = sym in self.engine.slots
            if not slotted:
                s.prev = {ASK: [], BID: []}
            s.now = t
            self._regime(s, t)
            self._episodes(s, t)
            s.eff = self._params(s, t)
            self._churn(s, t)
            self._participants(sym, s, t)
            self._flow(sym, s, t, dt, slotted)
            self._basket(sym, s, t, slotted)
            self._close_spread(s)
            # tape heat: every tick the price moves adds heat (in that direction); it cools off in a few seconds
            if s.bids and s.asks:
                mid = (s.bids[0][0] + s.asks[0][0]) / 2
                # what the market's move asks of this name (beta x the index move, in ticks), summed over ~10 s: a
                # quarter-second wiggle cancels out, a real push builds up. Chasers (momentum, stops) come in with
                # that push, so the tape speeds up when the whole tape moves, and a level breaking (below) bursts it
                mkt = self.mkt
                want = s.beta * math.log(mkt.level / mkt.prev_level) * mid / s.tk if mkt.prev_level else 0.0
                s.mom = s.mom * (0.975 ** (dt / 0.25)) + want
                s.hot = s.hot * (0.93 ** (dt / 0.25))
                if s.hot < 1.0:
                    s.hot_dir = (1 if s.mom > 0 else -1) if abs(s.mom) >= 3 else 0
                s.last_mid = mid
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
            # a price with nothing on it (a reloader between refills) is not a row on a real feed: it is deleted,
            # and inserted again when his size comes back
            cur = [(r[0], int(r[1])) for r in rows if r[1] > 0][:ROWS]
            prev = s.prev[side]
            for i in range(len(prev) - 1, len(cur) - 1, -1):
                eng.on_depth(sym, i, DELETE, side, prev[i][0], 0, "", t)
            for i, (price, size) in enumerate(cur):
                if i < len(prev) and prev[i] == (price, size):
                    continue
                eng.on_depth(sym, i, UPDATE if i < len(prev) else INSERT, side, price, size, "", t)
            s.prev[side] = cur
