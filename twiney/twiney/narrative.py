"""Plain-English commentary: what price is doing at the trader's levels.

Every sentence is derived from the same evidence the calls use; nothing here
invents a signal. Buyer/seller always means "resting liquidity on that side",
never an identified participant.
"""

from .prices import fmt_price, price_key, tick_size

ROLE_NAMES = {
    "trigger": "your trigger",
    "second_entry": "your 2nd entry",
    "extra": "your level",
    "auto": "a big level",
}


def role_name(role):
    first = (role or "").split("+")[0]
    return ROLE_NAMES.get(first, "your level")


def who(side):
    """Resting side -> who is sitting there."""
    return "BUYER" if side == "bid" else "SELLER"


def aggressors(side):
    """Who is trading INTO that resting side."""
    return "sellers" if side == "bid" else "buyers"


def shares(n):
    return f"{int(round(n or 0)):,}"


def px(p):
    v = fmt_price(p)
    if v is None:
        return "—"
    return f"{v:.2f}" if v >= 1 else f"{v:.4f}"


def play_context(play, side, role):
    """What a buyer/seller at this level means for the PS60 play."""
    first = (role or "").split("+")[0]
    long_ = play["side"] == "long"
    if first == "trigger":
        if long_ and side == "ask":
            return "This is the supply your long needs cleared. CLEANED UP here = the break is real."
        if not long_ and side == "bid":
            return "This is the demand your short needs cleared. CLEANED UP here = the break is real."
        if long_ and side == "bid":
            return "Buyers defending your trigger from below — supportive for the long."
        return "Sellers defending your trigger from above — supportive for the short."
    if first == "second_entry":
        if long_ and side == "bid":
            return "A buyer holding your 2nd entry — that's the support you want to see."
        if not long_ and side == "ask":
            return "A seller holding your 2nd entry — that's the resistance you want to see."
    return ""


def alert_text(alert, play):
    side, role = alert["side"], alert.get("role", "")
    where = f"{px(alert['price'])} ({role_name(role)})"
    label = alert["label"]
    if label.startswith("RELOAD"):
        return (f"A {who(side)} keeps reloading at {where}. {shares(alert['absorbed'])} shares have traded into it "
                f"and it refilled {alert.get('refreshes', 0)}x — {aggressors(side)} are being absorbed. "
                + play_context(play, side, role)).strip()
    if label == "CLEANED UP":
        return (f"The {who(side)} at {where} got CLEANED UP — {shares(alert['absorbed'])} shares traded there "
                f"and price broke through.")
    if label == "PULLED":
        return (f"The {who(side)} at {where} PULLED — the size vanished without trading. "
                f"That level was not real; don't lean on it.")
    return f"{label} at {where}"


def level_tests(bars, level, lookback=30):
    """How price behaved at ``level`` over the last ``lookback`` bars.

    bars: [[t, o, h, l, c, v, bv, sv], ...] oldest first.
    Returns (touches, side_now) where side_now is 'below'/'above'/'at' for the last close.
    """
    if not bars:
        return 0, None
    tk = tick_size(level)
    recent = bars[-lookback:]
    touches = sum(1 for b in recent if b[3] <= level + tk and b[2] >= level - tk)
    last = recent[-1][4]
    k, lk = price_key(last, tk), price_key(level, tk)
    side_now = "at" if abs(k - lk) <= 1 else ("below" if k < lk else "above")
    return touches, side_now


def proximity_line(play, price):
    """'Price is approaching your trigger 128.40 — 6¢ away (0.05%).'"""
    if price is None:
        return None, None
    options = [("trigger", play["trigger"])]
    if play.get("second_entry"):
        options.append(("second_entry", play["second_entry"]))
    role, level = min(options, key=lambda o: abs(price - o[1]))
    gap = price - level
    pct = abs(gap) / price * 100
    tk = tick_size(level)
    ticks = abs(price_key(price, tk) - price_key(level, tk))
    dist = f"{abs(gap) * 100:.0f}¢" if price >= 1 else f"{abs(gap):.4f}"
    direction = "above" if gap > 0 else "below"
    name = f"{role_name(role)} {px(level)}"
    if ticks <= 1:
        return f"Price is AT {name}.", "at"
    if pct <= 0.5:
        return f"Price is approaching {name} — {dist} {direction} it ({pct:.2f}%).", "near"
    return f"Price is {pct:.2f}% from {name} ({dist} {direction}).", "far"


def story(play, price, levels, bars, tape, now, recent_alerts, min_shares=1000, max_lines=5):
    """Headline + bullet lines for one symbol.

    levels: tracker snapshots (price, side, role, state, displayed, absorbed_total,
            absorbed_window, refreshes, last_verdict, last_verdict_age)
    Returns (headline, tone, lines) where tone is one of
    'cleaned', 'pulled', 'reload', 'watch', 'at', 'near', 'far'.
    """
    lines = []
    headline, tone = None, None

    # 1. a fresh verdict dominates
    for a in recent_alerts:
        if now - a["t"] > 30:
            break
        if a["label"] in ("CLEANED UP", "PULLED"):
            headline = alert_text(a, play)
            tone = "cleaned" if a["label"] == "CLEANED UP" else "pulled"
            break

    # 2. live reloads
    live = [lv for lv in levels if lv["state"] == "RELOAD"]
    live.sort(key=lambda lv: -lv["absorbed_total"])
    for lv in live:
        text = (f"A {who(lv['side'])} keeps reloading at {px(lv['price'])} ({role_name(lv['role'])}): "
                f"{shares(lv['absorbed_total'])} shares traded into it, refilled {lv['refreshes']}x, "
                f"{shares(lv['displayed'])} still showing. {aggressors(lv['side']).capitalize()} are being absorbed.")
        ctx = play_context(play, lv["side"], lv["role"])
        if headline is None:
            headline, tone = text, "reload"
            if ctx:
                lines.append(ctx)
        else:
            lines.append(text)

    # 3. levels being defended but not yet confirmed (only with real evidence)
    cands = []
    for lv in levels:
        mine = lv["role"] != "auto"
        need_shares = min_shares * (0.5 if mine else 1.0)
        need_refills = 1 if mine else 2
        if lv["state"] == "BUILDING" and lv["refreshes"] >= need_refills and lv["absorbed_window"] >= need_shares:
            cands.append(lv)
    cands.sort(key=lambda lv: (lv["role"] == "auto", -lv["absorbed_window"]))
    for lv in cands[:2]:
            text = (f"Possible {who(lv['side'])} at {px(lv['price'])} ({role_name(lv['role'])}): "
                    f"{shares(lv['absorbed_window'])} shares traded there and it refilled {lv['refreshes']}x. Watching.")
            if headline is None:
                headline, tone = text, "watch"
            else:
                lines.append(text)

    # 4. proximity to the PS60 levels
    prox, where = proximity_line(play, price)
    if prox:
        if headline is None:
            headline, tone = prox, where
        else:
            lines.insert(0, prox)

    # 5. is price stopping at the levels?
    for role in ("trigger", "second_entry"):
        level = play.get(role)
        if not level:
            continue
        touches, side_now = level_tests(bars, level)
        if touches >= 2 and side_now in ("below", "above"):
            lines.append(f"Price has tested {role_name(role)} {px(level)} {touches}x recently and is back "
                         f"{side_now} it — the level is holding so far.")

    # 6. tape
    if tape and tape.get("state") not in (None, "QUIET"):
        pct = tape.get("buy_pct")
        mix = f" ({pct:.0f}% buys)" if pct is not None else ""
        lines.append(f"Tape: {tape['state'].lower()}{mix} over the last {int(tape['window_seconds'])}s.")

    return headline or "Waiting for data…", tone or "far", lines[:max_lines]


def short_status(play, price):
    text, where = proximity_line(play, price)
    if text is None:
        return "no price yet"
    return text.replace("Price is ", "").rstrip(".")
