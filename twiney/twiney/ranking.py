"""Proximity ranking and depth-slot allocation."""


def distances(play, price):
    """Fractional distance from ``price`` to the trigger and second entry."""
    if price is None or price <= 0:
        return None, None
    d_trig = abs(price - play["trigger"]) / price
    d_second = abs(price - play["second_entry"]) / price if play.get("second_entry") else None
    return d_trig, d_second


def nearest(play, price):
    d_trig, d_second = distances(play, price)
    vals = [d for d in (d_trig, d_second) if d is not None]
    return min(vals) if vals else None


def rank(plays, prices, blocked=()):
    """Rankable plays ordered by nearest PS60 level: [(symbol, distance)]."""
    out = []
    for play in plays:
        if not play["active"] or play["symbol"] in blocked:
            continue
        d = nearest(play, prices.get(play["symbol"]))
        if d is not None:
            out.append((play["symbol"], d))
    out.sort(key=lambda r: (r[1], r[0]))
    return out


def allocate(current, ranked, slots, now, hysteresis, min_hold):
    """Assign the scarce depth slots.

    ``current`` maps symbol -> time it got its slot. Empty slots go to the
    closest symbols. A held slot is only rotated when the incumbent has held it
    for ``min_hold`` seconds and a challenger is closer by more than the
    ``hysteresis`` fraction. Returns the new mapping.
    """
    dist = dict(ranked)
    held = {s: t for s, t in current.items() if s in dist}
    # incumbents that dropped out of the ranking (no price / blocked) give up their slot
    for sym, _d in ranked:
        if len(held) >= slots:
            break
        if sym not in held:
            held[sym] = now
    while True:
        challengers = [(s, d) for s, d in ranked if s not in held]
        if not challengers or not held:
            break
        best_sym, best_d = challengers[0]
        eligible = [s for s, t in held.items() if now - t >= min_hold]
        if not eligible:
            break
        worst = max(eligible, key=lambda s: (dist[s], s))
        if best_d < dist[worst] * (1.0 - hysteresis):
            del held[worst]
            held[best_sym] = now
        else:
            break
    return held
