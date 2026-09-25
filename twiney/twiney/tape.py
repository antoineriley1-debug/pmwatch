"""Tick-by-tick prints and a plain-language tape read."""

from collections import deque

BUY, SELL, MID = "buy", "sell", "mid"


def classify(price, bid, ask):
    """Aggressor side from the quote in force when the print arrived."""
    if ask is not None and price >= ask - 1e-9:
        return BUY
    if bid is not None and price <= bid + 1e-9:
        return SELL
    return MID


class Tape:
    def __init__(self, cfg):
        self.cfg = cfg
        self.prints = deque(maxlen=int(cfg["keep_prints"]))
        self.total_volume = 0.0

    def add(self, t, price, size, bid, ask, exchange=""):
        side = classify(price, bid, ask)
        rec = {"t": t, "price": price, "size": size, "side": side, "exchange": exchange,
               "large": size >= self.cfg["large_print_shares"]}
        self.prints.append(rec)
        self.total_volume += size
        return rec

    def last(self):
        return self.prints[-1] if self.prints else None

    def stats(self, now):
        window = self.cfg["window_seconds"]
        buy = sell = mid = 0.0
        n = large = 0
        for p in reversed(self.prints):
            if now - p["t"] > window:
                break
            n += 1
            large += p["large"]
            if p["side"] == BUY:
                buy += p["size"]
            elif p["side"] == SELL:
                sell += p["size"]
            else:
                mid += p["size"]
        directional = buy + sell
        if n < self.cfg["min_prints_for_read"] or directional <= 0:
            state = "QUIET"
        elif buy / directional >= self.cfg["control_ratio"]:
            state = "BUYERS LIFTING"
        elif sell / directional >= self.cfg["control_ratio"]:
            state = "SELLERS HITTING"
        else:
            state = "TWO-SIDED"
        return {
            "state": state,
            "window_seconds": window,
            "prints": n,
            "buy_volume": buy,
            "sell_volume": sell,
            "mid_volume": mid,
            "large_prints": large,
            "buy_pct": round(100.0 * buy / directional, 1) if directional else None,
        }

    def recent(self, limit=12):
        return list(self.prints)[-limit:][::-1]
