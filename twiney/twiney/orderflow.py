"""Order-flow analytics for the ladder: rolling delta windows and readable pressure states.

Everything here is computed from the time & sales the desk has (price, size, side). The side of a print is
INFERRED from the quote it traded against (at the ask = buyer paid up, at the bid = seller hit), the way every
retail tape does it: IBKR does not send the aggressor side. So the numbers are an ESTIMATED delta, and they are
labelled that way; nothing here claims to be exchange-certified. Thresholds are documented in config
(``orderflow``) and the labels come only from them — never from anything random.

    delta:     buy shares - sell shares inside the window (prints between the quotes count for neither side)
    pressure:  ratio = delta / (buy + sell) over the long window
               ratio >= strong  -> BUYING PRESSURE STRONG
               ratio >= lean    -> BUYING PRESSURE
               ratio <= -strong -> SELLING PRESSURE STRONG
               ratio <= -lean   -> SELLING PRESSURE
               else             -> BALANCED
    momentum:  the short window's pace of delta against the long window's: INCREASING when the short window
               runs at 1.5x the long window's per-second rate in the same direction, FADING at under 0.5x,
               else blank. Fewer than min_prints prints in the long window: QUIET, no state.
"""
from collections import deque

DEFAULTS = {"short_seconds": 5, "long_seconds": 15, "lean": 0.25, "strong": 0.60, "min_prints": 8}


def delta(prints, now, seconds):
    """(delta, buy, sell, prints) over the last ``seconds``; prints: records with t / size / side."""
    buy = sell = n = 0.0
    for p in reversed(prints):
        age = now - p["t"]
        if age > seconds:
            break
        if age < 0:
            continue
        n += 1
        if p.get("side") == "buy":
            buy += p["size"]
        elif p.get("side") == "sell":
            sell += p["size"]
    return buy - sell, buy, sell, int(n)


def pressure(prints, now, cfg=None):
    c = dict(DEFAULTS, **(cfg or {}))
    s_sec, l_sec = float(c["short_seconds"]), float(c["long_seconds"])
    d5, b5, s5, n5 = delta(prints, now, s_sec)
    d15, b15, s15, n15 = delta(prints, now, l_sec)
    out = {"short_seconds": int(s_sec), "long_seconds": int(l_sec), "short_delta": round(d5), "long_delta": round(d15),
           "short_prints": n5, "long_prints": n15, "basis": "ESTIMATED", "basis_note": "side inferred from the quote each print hit; not exchange aggressor data",
           "state": "QUIET", "arrow": "", "momentum": "", "ratio": None}
    tot = b15 + s15
    if n15 < int(c["min_prints"]) or tot <= 0:
        return out
    ratio = d15 / tot
    out["ratio"] = round(ratio, 2)
    if ratio >= c["strong"]:
        out["state"], out["arrow"] = "BUYING PRESSURE STRONG", "↑"
    elif ratio >= c["lean"]:
        out["state"], out["arrow"] = "BUYING PRESSURE", "↑"
    elif ratio <= -c["strong"]:
        out["state"], out["arrow"] = "SELLING PRESSURE STRONG", "↓"
    elif ratio <= -c["lean"]:
        out["state"], out["arrow"] = "SELLING PRESSURE", "↓"
    else:
        out["state"] = "BALANCED"
    # momentum: the short window's delta pace against the long window's, in the long window's direction
    if d15 and n5 >= 2:
        pace_s, pace_l = d5 / s_sec, d15 / l_sec
        same = (pace_s > 0) == (pace_l > 0)
        if same and abs(pace_s) >= 1.5 * abs(pace_l):
            out["momentum"] = "MOMENTUM INCREASING ↑"
        elif not same or abs(pace_s) <= 0.5 * abs(pace_l):
            out["momentum"] = "MOMENTUM FADING ↓"
    return out
