"""Tick-size helpers so price comparisons never depend on float equality."""


def tick_size(price):
    """US-equity minimum increment: $0.01 at/above $1, $0.0001 below."""
    return 0.01 if price >= 1.0 else 0.0001


def price_key(price, tick=None):
    """Integer tick index for a price (stable dict key / comparison unit)."""
    t = tick if tick is not None else tick_size(price)
    return int(round(price / t))


def same_level(a, b, band_ticks=0, tick=None):
    """True when two prices sit within ``band_ticks`` ticks of each other."""
    t = tick if tick is not None else tick_size(min(a, b))
    return abs(price_key(a, t) - price_key(b, t)) <= band_ticks


def fmt_price(price):
    if price is None:
        return None
    return round(price, 2 if price >= 1.0 else 4)
