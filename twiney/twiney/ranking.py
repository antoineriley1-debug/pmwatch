"""Proximity ranking and depth-slot allocation."""


def distances(play, price):
    """Fractional distance from ``price`` to the trigger and second entry."""
    if price is None or price <= 0:
        return None, None
    d_trig = abs(price - play["trigger"]) / price if play.get("trigger") else None
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


def allocate(current, ranked, slots, now, hysteresis, min_hold,
             pinned=(), protected=(), rotate=True):
    """Assign the scarce depth slots.

    ``current`` maps symbol -> time it got its slot.
    - ``pinned`` symbols always get a slot (evicting the worst unpinned holder if needed)
      and are never rotated out.
    - ``protected`` symbols (e.g. a live reload in progress) are never rotated out
      automatically.
    - Empty slots go to the closest symbols.
    - With ``rotate`` on, a held slot is only rotated when the incumbent has held it
      for ``min_hold`` seconds and a challenger is closer by more than the
      ``hysteresis`` fraction.
    Returns the new mapping.
    """
    inf = float("inf")
    dist = dict(ranked)
    pinned = set(pinned)
    protected = set(protected)
    # incumbents that dropped out of the ranking (no price / blocked) give up their slot
    held = {s: t for s, t in current.items() if s in dist or s in pinned}
    for p in sorted(pinned, key=lambda s: (dist.get(s, inf), s)):
        if p in held:
            continue
        if len(held) >= slots:
            victims = [s for s in held if s not in pinned]
            if not victims:
                continue
            del held[max(victims, key=lambda s: (dist.get(s, inf), s))]
        held[p] = now
    for sym, _d in ranked:
        if len(held) >= slots:
            break
        if sym not in held:
            held[sym] = now
    while rotate:
        challengers = [(s, d) for s, d in ranked if s not in held]
        if not challengers or not held:
            break
        best_sym, best_d = challengers[0]
        eligible = [s for s, t in held.items()
                    if s not in pinned and s not in protected and now - t >= min_hold]
        if not eligible:
            break
        worst = max(eligible, key=lambda s: (dist.get(s, inf), s))
        if best_d < dist.get(worst, inf) * (1.0 - hysteresis):
            del held[worst]
            held[best_sym] = now
        else:
            break
    return held
