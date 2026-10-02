"""Tick-by-tick prints and a plain-language tape read."""

from collections import deque
from itertools import islice

BUY, SELL, MID = "buy", "sell", "mid"


def classify(price, bid, ask):
    """Aggressor side from the quote in force when the print arrived. A locked / crossed quote (bid >= ask, one
    venue against another) says nothing about who was in a rush: mid."""
    if bid is not None and ask is not None and bid >= ask - 1e-9:
        return MID
    if ask is not None and price >= ask - 1e-9:
        return BUY
    if bid is not None and price <= bid + 1e-9:
        return SELL
    return MID


class Tape:
    def __init__(self, cfg):
        self.cfg = cfg
        # at least every print of the read window, however busy the tape: keep_prints is the floor, not the cap
        self.prints = deque(maxlen=max(int(cfg["keep_prints"]), 20000))
        self.total_volume = 0.0

    def add(self, t, price, size, bid, ask, exchange="", side=None):
        side = side or classify(price, bid, ask)
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
            state = "BUYERS PAYING UP"     # impatient buyers: they wanted in now
        elif sell / directional >= self.cfg["control_ratio"]:
            state = "SELLERS HITTING OUT"  # impatient sellers: they wanted out now
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

    def speed(self, now, span=90, bucket=3, fast=10):
        """How fast the tape is running: prints and shares per second over the last `fast` seconds, measured against
        the minute before it (so SPEEDING UP / SLOWING is this stock against itself, not against another name), and
        a per-`bucket` series of buy / sell / other shares for the sparkline, oldest first."""
        nb = span // bucket
        series = [[0, 0, 0, 0] for _ in range(nb)]     # buy shares, sell shares, other shares, prints
        n_fast = sh_fast = n_before = 0
        for p in reversed(self.prints):
            age = now - p["t"]
            if age >= span:
                break
            if age < 0:
                age = 0
            row = series[nb - 1 - int(age // bucket)]
            row[0 if p["side"] == BUY else 1 if p["side"] == SELL else 2] += p["size"]
            row[3] += 1
            if age < fast:
                n_fast += 1
                sh_fast += p["size"]
            elif age < fast + 60:
                n_before += 1
        pps, base = n_fast / fast, n_before / 60.0
        if n_fast + n_before < 5:
            trend = "QUIET"
        elif base == 0 or pps >= 1.5 * base:
            trend = "SPEEDING UP"
        elif pps <= 0.6 * base:
            trend = "SLOWING"
        else:
            trend = "STEADY"
        return {"pps": round(pps, 1), "sps": round(sh_fast / fast), "base_pps": round(base, 1), "trend": trend,
                "bucket": bucket, "series": [[round(a), round(b), round(c), d] for a, b, c, d in series]}

    def recent(self, limit=12):
        return list(islice(reversed(self.prints), limit))

    def big(self, now, last_price=None):
        """The BIG TAPE: what a trader filters the tape for to catch large orders and see who is building a
        position. Two lists, newest first, over the last big_tape_minutes:
          prints:   every print of big_tape_shares or more, or big_tape_dollars or more (a block)
          builders: the same side hitting the same price again and again inside build_window_seconds — at least
                    build_prints prints adding up to big_tape_shares or build_dollars — someone working an order there:
                    PAID UP at one price over and over = a buyer building; HIT = a seller unloading
        Each builder: side, price, prints, shares, dollars, first / last age, still (last print inside the window)."""
        c = self.cfg
        mins = float(c.get("big_tape_minutes", 30))
        sh = float(c.get("big_tape_shares", c.get("large_print_shares", 5000)))
        usd = float(c.get("big_tape_dollars", 250000))
        win = float(c.get("build_window_seconds", 90))
        need = int(c.get("build_prints", 3))
        busd = float(c.get("build_dollars", 500000))
        cut = now - mins * 60
        rows = [p for p in self.prints if p["t"] >= cut and p["side"] in ("buy", "sell")]
        prints = [p for p in rows if p["size"] >= sh or p["size"] * p["price"] >= usd]
        # builders: runs of the same side at the same price with no gap longer than the window
        groups, runs = {}, []
        for p in rows:
            k = (p["side"], round(p["price"], 4))
            g = groups.get(k)
            if g is None or p["t"] - g["last_t"] > win:
                g = {"side": p["side"], "price": p["price"], "prints": 0, "shares": 0.0, "dollars": 0.0,
                     "first_t": p["t"], "last_t": p["t"], "biggest": 0.0}
                groups[k] = g
                runs.append(g)
            g["prints"] += 1
            g["shares"] += p["size"]
            g["dollars"] += p["size"] * p["price"]
            g["last_t"] = p["t"]
            g["biggest"] = max(g["biggest"], p["size"])
        builders = [dict(g, still=now - g["last_t"] <= win, first_age=round(now - g["first_t"]), last_age=round(now - g["last_t"]),
                         shares=round(g["shares"]), dollars=round(g["dollars"]))
                    for g in runs if g["prints"] >= need and (g["shares"] >= sh or g["dollars"] >= busd)]
        builders.sort(key=lambda g: (-g["still"], g["last_age"]))
        return {"prints": list(reversed(prints))[:60], "builders": builders[:20],
                "shares": sh, "dollars": usd, "minutes": mins, "window": win, "need": need}
