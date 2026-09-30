"""Smart Depth order-book reconstruction.

IBKR sends positional row operations per side:
  operation 0 = insert at position, 1 = update at position, 2 = delete at position
  side 0 = ask, 1 = bid
With Smart Depth several rows can share one price (one row per exchange / market
maker), so reads aggregate rows by price.
"""

from .prices import price_key

INSERT, UPDATE, DELETE = 0, 1, 2
ASK, BID = 0, 1


class Book:
    def __init__(self, rows_requested=10):
        self.rows_requested = rows_requested
        self.reset()

    def reset(self):
        self.asks = []  # list of [price, size, market_maker]
        self.bids = []
        self.anomalies = 0
        self.updates = 0
        self._cache = {ASK: None, BID: None}

    @property
    def synced(self):
        return bool(self.asks) and bool(self.bids)

    def _side(self, side):
        return self.asks if side == ASK else self.bids

    def apply(self, position, operation, side, price, size, market_maker=""):
        """Apply one IBKR depth row operation. Returns False on an anomaly."""
        rows = self._side(side)
        self.updates += 1
        self._cache[side] = None
        if position < 0:
            self.anomalies += 1
            return False
        if operation == INSERT:
            if position > len(rows):
                self.anomalies += 1
                position = len(rows)
            rows.insert(position, [price, size, market_maker])
            # never let the side grow beyond what was requested
            del rows[max(self.rows_requested, 1) * 4:]
            return True
        if operation == UPDATE:
            if position >= len(rows):
                # IBKR occasionally updates a row it never inserted; treat as insert
                self.anomalies += 1
                rows.append([price, size, market_maker])
                return False
            rows[position] = [price, size, market_maker]
            return True
        if operation == DELETE:
            if position >= len(rows):
                self.anomalies += 1
                return False
            del rows[position]
            return True
        self.anomalies += 1
        return False

    # ---- reads -------------------------------------------------------------

    def _agg(self, side):
        """Cached (levels best-first, {tick_key: size}) for one side."""
        cached = self._cache[side]
        if cached is not None:
            return cached
        agg = {}
        for price, size, _mm in self._side(side):
            if price is None or price <= 0:
                continue
            k = price_key(price)
            row = agg.get(k)
            if row is None:
                agg[k] = [price, size, 1]
            else:
                row[1] += size
                row[2] += 1
        out = sorted((tuple(r) for r in agg.values()), key=lambda r: r[0], reverse=(side == BID))
        cached = (out, {k: r[1] for k, r in agg.items()})
        self._cache[side] = cached
        return cached

    def levels(self, side, limit=None):
        """Rows aggregated by price, best first: [(price, size, row_count)]."""
        out = self._agg(side)[0]
        return out[:limit] if limit else list(out)

    def best(self, side):
        out = self._agg(side)[0]
        return out[0][0] if out else None

    def size_at(self, side, price, band_ticks=0):
        by_key = self._agg(side)[1]
        target = price_key(price)
        if band_ticks == 0:
            return by_key.get(target, 0.0)
        return sum(by_key.get(target + d, 0.0) for d in range(-band_ticks, band_ticks + 1))

    def in_view(self, side, price):
        """Whether a resting order at ``price`` on ``side`` would be visible.

        When the side holds fewer levels than requested everything is visible.
        Otherwise the price must be at or better than the worst visible level.
        """
        rows = [r for r in self._side(side) if r[0] and r[0] > 0]
        if not rows:
            return False
        # IBKR sends N ROWS per side; with SMART depth several rows (one per exchange) share a price, so the
        # window is the raw rows, not the distinct prices. A side holding fewer rows than asked shows everything.
        if len(self._side(side)) < self.rows_requested:
            return True
        worst = min(r[0] for r in rows) if side == BID else max(r[0] for r in rows)
        k, wk = price_key(price), price_key(worst)
        # the worst visible price itself may be cut off (more size there beyond the window): not judgeable
        return k < wk if side == ASK else k > wk
