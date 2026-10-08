"""DARK POOL PRINTS: the trades that print off the exchanges (FINRA's trade reporting facilities, ADF, OTC). Funds
route much of their size there, so a large off-exchange print, or the same price soaking up dark volume again and
again, is the closest public data comes to an institution's footprint.

Per stock, for the day (New York):
- every LARGE off-exchange print (``big_shares`` or ``big_usd``): size, dollars, where it printed against the quote
  (over the ask / at the ask / mid / at the bid / under the bid) and against VWAP at that moment;
- every price's off-exchange shares and dollars (all sizes): where dark execution keeps happening;
- the dark share of the day's volume.
"""

from collections import deque

OFF_EXCHANGE = ("FINRA", "ADF", "TRF", "OTC", "DARK")


def is_dark(exchange):
    ex = str(exchange or "").upper()
    return any(ex.startswith(x) for x in OFF_EXCHANGE)


class DarkBook:
    def __init__(self):
        self.day = None
        self.big = deque(maxlen=200)       # the large prints, oldest first
        self.levels = {}                   # price key -> {"price", "shares", "usd", "prints", "big", "last_t"}
        self.shares = 0.0
        self.usd = 0.0
        self.total_shares = 0.0            # every print today, lit and dark (the dark share)

    def reset(self, day):
        self.day = day
        self.big.clear(); self.levels.clear()
        self.shares = self.usd = self.total_shares = 0.0

    def count(self, size):
        self.total_shares += size

    def add(self, t, price, size, exchange, bid, ask, vwap, cfg):
        """An off-exchange print. Returns the record when it is LARGE (else None)."""
        usd = price * size
        self.shares += size; self.usd += usd
        k = round(price, 2)
        lv = self.levels.setdefault(k, {"price": k, "shares": 0.0, "usd": 0.0, "prints": 0, "big": 0, "last_t": t})
        lv["shares"] += size; lv["usd"] += usd; lv["prints"] += 1; lv["last_t"] = t
        if not (size >= float(cfg.get("big_shares", 10000)) or usd >= float(cfg.get("big_usd", 200000))):
            return None
        lv["big"] += 1
        tk = 0.01 if price >= 1 else 0.0001
        if bid and ask and ask >= bid:
            at = ("over the ask" if price > ask + tk / 2 else "at the ask" if price >= ask - tk / 2
                  else "under the bid" if price < bid - tk / 2 else "at the bid" if price <= bid + tk / 2 else "mid")
        else:
            at = ""
        rec = {"t": t, "price": price, "size": size, "usd": usd, "exchange": str(exchange or ""), "at": at,
               "vs_vwap": None if not vwap else round(price - vwap, 4)}
        self.big.append(rec)
        return rec

    def view(self, t, last=None, n_big=25, n_levels=8):
        lv = sorted(self.levels.values(), key=lambda x: -x["usd"])[:n_levels]
        return {"usd": round(self.usd), "shares": round(self.shares),
                "pct": round(100.0 * self.shares / self.total_shares, 1) if self.total_shares else None,
                "big": [dict(r, age=round(t - r["t"], 1), usd=round(r["usd"])) for r in list(self.big)[-n_big:][::-1]],
                "levels": [{"price": x["price"], "shares": round(x["shares"]), "usd": round(x["usd"]), "prints": x["prints"],
                            "big": x["big"], "ago": round(t - x["last_t"])} for x in lv]}
