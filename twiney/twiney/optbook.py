"""The practice desk's book for one option contract: price levels with size on each side that trades, gets pulled,
refills and moves like a real book, so the contract's LEVEL II and T&S agree with each other.

Prices are kept in cents (integers) so levels line up exactly. Each ``step`` takes the model's fair bid / ask for
the contract right now and returns the prints that happened:
- when the fair price runs through the book, the size in the way is TAKEN (buyers lift the offers on the way up,
  sellers hit the bids on the way down) — unless a RELOADER sits there: he refills and holds the price a while;
- small trades come in at the touch and eat its size; a level that runs out is gone and the price ticks;
- size gets PULLED without trading, and new size shows up; market makers step in when the spread is wide.
"""

import random
from collections import deque


class PracticeOptBook:
    LEVELS = 10

    def __init__(self, seed=None):
        self.rng = random.Random(seed)
        self.bids = {}          # cents -> contracts
        self.asks = {}
        self.reload = {}        # (side, cents) -> [base size, refills left]
        self.last = None        # cents of the last trade
        self.g = 1              # price step in cents
        self.ev = deque(maxlen=2000)    # (t, "bid" | "ask", cents, +stacked | -pulled): PULL / STACK on the ladder
        self.t = 0.0

    # ---- helpers -------------------------------------------------------------

    def _size(self, near=True):
        r = self.rng
        s = r.choice((5, 10, 10, 15, 20, 25, 30, 40, 50, 75, 100))
        return s * (r.choice((2, 3)) if not near and r.random() < 0.3 else 1)

    def _grid(self, cents):
        return int(round(cents / self.g)) * self.g

    def best_bid(self):
        return max(self.bids) if self.bids else None

    def best_ask(self):
        return min(self.asks) if self.asks else None

    def _fill_out(self):
        """Ten levels each side, no holes next to the touch."""
        bb, ba = self.best_bid(), self.best_ask()
        if bb is not None:
            for i in range(self.LEVELS):
                p = bb - i * self.g
                if p <= 0:
                    break
                if p not in self.bids:
                    self.bids[p] = self._size(near=i < 3)
            for p in [p for p in self.bids if p < bb - self.LEVELS * self.g]:
                del self.bids[p]
        if ba is not None:
            for i in range(self.LEVELS):
                p = ba + i * self.g
                if p not in self.asks:
                    self.asks[p] = self._size(near=i < 3)
            for p in [p for p in self.asks if p > ba + self.LEVELS * self.g]:
                del self.asks[p]

    def _take(self, side, price, size, prints, t):
        """``size`` trades at ``price`` against ``side`` ('bid' = sellers hit it, 'ask' = buyers lift it). A reloader
        refills when his size runs out (until his refills are spent); anyone else's level is gone."""
        book = self.bids if side == "bid" else self.asks
        have = book.get(price, 0)
        n = min(size, have)
        if n <= 0:
            return 0
        prints.append((price / 100.0, int(n), "sell" if side == "bid" else "buy", t))
        self.last = price
        book[price] = have - n
        if book[price] <= 0:
            rl = self.reload.get((side, price))
            if rl and rl[1] > 0:
                rl[1] -= 1
                book[price] = rl[0]                     # the reloader is back at the same price
                self.ev.append((t, side, price, rl[0]))
            else:
                del book[price]
                self.reload.pop((side, price), None)
        return n

    # ---- the clock -----------------------------------------------------------

    def step(self, fair_bid, fair_ask, t, lean=0.0):
        """Advance the book to the model's fair bid / ask (dollars). ``lean`` > 0 = the stock is rising (buyers
        lead), < 0 = falling. Returns the prints [(price, contracts, 'buy' | 'sell', t)]."""
        r, prints = self.rng, []
        self.t = t
        mid = (fair_bid + fair_ask) / 2.0
        self.g = 1 if mid < 3 else 5
        fb, fa = self._grid(fair_bid * 100), self._grid(fair_ask * 100)
        if fa <= fb:
            fa = fb + self.g
        if not self.bids or not self.asks:
            self.bids = {fb - i * self.g: self._size(i < 3) for i in range(self.LEVELS) if fb - i * self.g > 0}
            self.asks = {fa + i * self.g: self._size(i < 3) for i in range(self.LEVELS)}
            # one or two reloaders near the touch: they refill and hold their price a while
            for side, base in (("bid", fb), ("ask", fa)):
                if r.random() < 0.6:
                    p = base + (-1 if side == "bid" else 1) * r.choice((1, 2, 3)) * self.g
                    if p > 0:
                        (self.bids if side == "bid" else self.asks)[p] = r.choice((100, 150, 200, 250))
                        self.reload[(side, p)] = [(self.bids if side == "bid" else self.asks)[p], r.choice((2, 3, 4))]
        # 1. the fair price runs through the book: buyers lift the offers below it, sellers hit the bids above it.
        #    A reloader in the way refills once per tick and holds the price there for now
        #    when the move is a nudge (within 3 ticks of him); a run far past him CLEANS HIM UP
        guard, top = 0, (max(self.asks) if self.asks else fb)
        while self.best_ask() is not None and self.best_ask() < fb and guard < 400:
            p = self.best_ask(); guard += 1
            if len(self.asks) == 1:                       # the run empties the offers: fresh size keeps showing in its path
                top = max(top, p) + self.g; self.asks[top] = self._size()
            had = (("ask", p) in self.reload)
            self._take("ask", p, self.asks[p], prints, t)
            if had and p in self.asks and fb - p <= 3 * self.g:
                break
        guard, bot = 0, (min(self.bids) if self.bids else fa)
        while self.best_bid() is not None and self.best_bid() > fa and guard < 400:
            p = self.best_bid(); guard += 1
            if len(self.bids) == 1 and min(bot, p) - self.g > 0:
                bot = min(bot, p) - self.g; self.bids[bot] = self._size()
            had = (("bid", p) in self.reload)
            self._take("bid", p, self.bids[p], prints, t)
            if had and p in self.bids and p - fa <= 3 * self.g:
                break
        # 2. trades at the touch: buyers lead when the stock rises, sellers when it falls
        for _ in range(r.choice((0, 1, 1, 2, 2, 3))):
            buy = r.random() < 0.5 + max(-0.3, min(0.3, lean))
            side = "ask" if buy else "bid"
            p = self.best_ask() if buy else self.best_bid()
            if p is None:
                continue
            size = r.choice((1, 1, 2, 3, 5, 5, 10, 10, 15, 20, 25)) * (10 if r.random() < 0.03 else 1)
            self._take(side, p, size, prints, t)
        # 3. size pulled without trading (often the touch backing away), and new size showing up
        if r.random() < 0.25:
            side = r.choice(("bid", "ask")); book = self.bids if side == "bid" else self.asks
            if book:
                ks = sorted(book, reverse=(side == "bid"))[:4]
                p = r.choice(ks)
                if (side, p) not in self.reload:
                    cut = max(1, int(book[p] * r.choice((0.3, 0.5, 1.0))))
                    book[p] -= cut
                    self.ev.append((t, side, p, -cut))
                    if book[p] <= 0:
                        del book[p]
        if r.random() < 0.35:
            side = r.choice(("bid", "ask")); book = self.bids if side == "bid" else self.asks
            if book:
                p = r.choice(sorted(book, reverse=(side == "bid"))[:5])
                add = r.choice((5, 10, 20, 25, 50))
                book[p] += add
                self.ev.append((t, side, p, add))
        # 4. market makers step in toward the fair price when the spread is wider than it should be
        bb, ba = self.best_bid(), self.best_ask()
        if bb is None:
            self.bids[min(fb, (ba or fa) - self.g)] = self._size()
        if ba is None:
            self.asks[max(fa, (bb or fb) + self.g)] = self._size()
        bb, ba = self.best_bid(), self.best_ask()
        if bb < fb and bb + self.g < ba:
            self.bids[min(fb, ba - self.g)] = self._size()
        bb = self.best_bid()
        if ba > fa and ba - self.g > bb:
            self.asks[max(fa, bb + self.g)] = self._size()
        self._fill_out()
        return prints

    def quote(self):
        bb, ba = self.best_bid(), self.best_ask()
        return {"bid": bb / 100.0 if bb else None, "ask": ba / 100.0 if ba else None,
                "bid_size": self.bids.get(bb) if bb else None, "ask_size": self.asks.get(ba) if ba else None,
                "last": self.last / 100.0 if self.last else None}

    def size_at(self, side, price):
        return (self.bids if side == "bid" else self.asks).get(int(round(price * 100)), 0)
