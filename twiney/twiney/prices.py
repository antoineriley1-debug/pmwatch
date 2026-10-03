"""Tick-size helpers so price comparisons never depend on float equality."""


# the instrument's own minimum increment, when IBKR has told us (contract details): symbol -> tick
MIN_TICKS = {}


def set_min_tick(symbol, tick):
    """Remember the minimum price increment IBKR reports for a symbol (contractDetails.minTick)."""
    try:
        tick = float(tick)
    except (TypeError, ValueError):
        return
    if tick > 0:
        MIN_TICKS[str(symbol).upper()] = tick


def min_tick(symbol):
    return MIN_TICKS.get(str(symbol).upper()) if symbol else None


def tick_size(price, symbol=None):
    """Minimum increment at this price: the instrument's own (from IBKR contract details) when known, else the
    US-equity rule — $0.01 at / above $1, $0.0001 below. Never a hard-coded penny."""
    t = min_tick(symbol)
    if t:
        return t
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
