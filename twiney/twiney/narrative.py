"""Plain-English commentary: what price is doing at the trader's levels.

Every sentence is derived from the same evidence the calls use; nothing here
invents a signal. Buyer/seller always means "resting liquidity on that side",
never an identified participant.
"""

from .prices import fmt_price, price_key, tick_size

ROLE_NAMES = {
    "trigger": "your pivot",
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


def say_dollars(v):
    """Money the way it is SAID: '300 thousand dollars', '1.2 million dollars', '850 dollars'."""
    v = float(v or 0)
    if v >= 1e6:
        return f"{v / 1e6:.1f}".rstrip("0").rstrip(".") + " million dollars"
    if v >= 1e3:
        return f"{round(v / 1e3):,.0f} thousand dollars"
    return f"{v:,.0f} dollars"


def dollars(v):
    """$134,900 · $1.2M — money traded at a level, said the way a trader says it."""
    v = float(v or 0)
    if v >= 1e6:
        return f"${v / 1e6:.1f}M"
    if v >= 1e4:
        return f"${round(v / 1e3):,.0f}K"
    return f"${v:,.0f}"


def px(p):
    v = fmt_price(p)
    if v is None:
        return "—"
    return f"{v:.2f}" if v >= 1 else f"{v:.4f}"


def wall(side):
    """A resting seller is a wall of supply (resistance); a buyer is demand (support)."""
    return "supply / resistance" if side == "ask" else "demand / support"


def play_context(play, side, role):
    """What a buyer/seller at this level means for the PS60 play, in plain words."""
    first = (role or "").split("+")[0]
    long_ = play["side"] == "long"
    if first == "trigger":
        if long_ and side == "ask":
            return "That's supply sitting on your pivot. Your long needs it cleared. Wait for CLEANED UP — then the break is real."
        if not long_ and side == "bid":
            return "That's demand sitting on your pivot. Your short needs it cleared. Wait for CLEANED UP — then the break is real."
        if long_ and side == "bid":
            return "That's demand under your pivot — a buyer has your back. Good for the long."
        return "That's supply over your pivot — a seller has your back. Good for the short."
    if first == "second_entry":
        # PS60: the 2nd entry is the new high (long) / new low (short) after the pivot broke;
        # the entry is back through it after the retrace
        if long_ and side == "ask":
            return "That's supply sitting on your 2nd entry — the high you need back through. Wait for CLEANED UP, then the entry is real."
        if not long_ and side == "bid":
            return "That's demand sitting on your 2nd entry — the low you need back through. Wait for CLEANED UP, then the entry is real."
        if long_ and side == "bid":
            return "Demand at your 2nd entry — a buyer is holding the level you got in through. That's the build you want."
        return "Supply at your 2nd entry — a seller is holding the level you got in through. That's the build you want."
    if first == "auto":
        return f"Not one of your levels, but big {wall(side)} showed up here."
    return ""


def alert_text(alert, play):
    side, role = alert["side"], alert.get("role", "")
    where = f"{px(alert['price'])} ({role_name(role)})"
    label = alert["label"]
    if label.startswith("RELOAD"):
        # the way a prop desk teaches it: who, where, how much traded (shares AND dollars), how much you could see
        n, usd = alert["absorbed"], dollars(alert.get("dollars", alert["absorbed"] * float(alert["price"])))
        shown = alert.get("peak_shown") or alert.get("showing") or 0
        did = "bought" if side == "bid" else "sold"            # a reload buyer has BOUGHT that much, a seller has SOLD it
        hidden = (f" He only ever showed {shares(shown)} on the {'bid' if side == 'bid' else 'ask'} — {shares(n)} traded, so he put it "
                  f"back {alert.get('refreshes', 0)} times. The rest was hidden size (an iceberg).") if shown and n > shown else \
                 f" He put it back {alert.get('refreshes', 0)} times."
        back = alert.get("back")
        if back:
            mins = max(1, int(round(back.get("away", 0) / 60)))
            prior = "cleaned up" if back.get("prior") == "CLEANED UP" else "pulled" if back.get("prior") == "PULLED" else "gone"
            nth = {2: "2nd", 3: "3rd"}.get(back.get("n"), f"{back.get('n')}th")
            tot = alert.get("absorbed_all") or n
            return (f"RELOAD {who(side)} BACK at {where} — the same {who(side).lower()}, {nth} visit: {prior} {mins} min ago, "
                    f"refilling again now. He has {did} {shares(n)} this visit, {shares(tot)} across every visit. "
                    f"{'He keeps defending this price: a stronger floor than a first-time buyer' if side == 'bid' else 'He keeps defending this price: a stronger ceiling than a first-time seller'}"
                    f"{' — but he pulled last time, so trust it less' if prior == 'pulled' else ''}. " + play_context(play, side, role)).strip()
        return (f"RELOAD {who(side)} at {where}. He has {did} {shares(n)} shares at {px(alert['price'])} = {usd}.{hidden} "
                f"{'Price is having trouble going lower' if side == 'bid' else 'Price is having trouble going higher'} "
                f"while he's there. " + play_context(play, side, role)).strip()
    if label == "CLEANED UP":
        vis = alert.get("episodes") or 0
        nth = {2: "2nd", 3: "3rd"}.get(vis, f"{vis}th")
        again = f" for now — his {nth} visit; if he is back at this price within 20 minutes the desk says so" if vis >= 2 else ""
        return (f"CLEANED UP — the {who(side)} at {where} is gone. He had {'bought' if side == 'bid' else 'sold'} "
                f"{shares(alert['absorbed'])} shares ({dollars(alert.get('dollars', alert['absorbed'] * float(alert['price'])))}) "
                f"before price went through him. That {wall(side).split(' / ')[0]} is done{again}.")

    if label == "PULLED":
        return (f"PULLED — the {who(side)} at {where} vanished without getting hit. "
                f"That size was never real. Don't lean on that level.")
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
    """'Price is approaching your pivot 128.40 — 6¢ away (0.05%).'"""
    if price is None:
        return None, None
    options = [(r, play.get(r)) for r in ("trigger", "second_entry") if play.get(r)]
    if not options:
        return None, None
    role, level = min(options, key=lambda o: abs(price - o[1]))
    gap = price - level
    pct = abs(gap) / price * 100
    tk = tick_size(level)
    ticks = abs(price_key(price, tk) - price_key(level, tk))
    dist = f"{abs(gap) * 100:.0f}¢" if price >= 1 else f"{abs(gap):.4f}"
    direction = "above" if gap > 0 else "below"
    name = f"{role_name(role)} {px(level)}"
    if ticks <= 1:
        return f"Price is AT {name}. Watch the ladder.", "at"
    if pct <= 0.5:
        return f"Price is coming into {name} — {dist} {direction} it.", "near"
    return f"Price is {dist} {direction} {name} ({pct:.1f}% away).", "far"


def trap_lines(trap, reloaders, play, price):
    """Trapped traders, in plain words, and what it means for the play."""
    if not trap:
        return []
    out = []
    long_ = play["side"] == "long"
    L, S = trap.get("longs"), trap.get("shorts")
    if L:
        held = [r for r in (reloaders or {}).get("above", []) if r["side"] == "ask"]
        why = f" A seller reloading at {px(held[0]['price'])} absorbed them — that's the trap." if held else ""
        out.append(f"TRAPPED LONGS{' (heavy)' if L['heavy'] else ''}: {shares(L['shares'])} shares paid up between "
                   f"{px(L['low'])} and {px(L['high'])} in the last {trap['window_minutes']} min and price is now "
                   f"below them.{why} If support gives way they bail — that's fuel for the drop"
                   + (", which is what your short wants." if not long_ else ". Your long is fighting them."))
    if S:
        held = [r for r in (reloaders or {}).get("below", []) if r["side"] == "bid"]
        why = f" A buyer reloading at {px(held[0]['price'])} absorbed them — that's the trap." if held else ""
        out.append(f"TRAPPED SHORTS{' (heavy)' if S['heavy'] else ''}: {shares(S['shares'])} shares hit out between "
                   f"{px(S['low'])} and {px(S['high'])} in the last {trap['window_minutes']} min and price is now "
                   f"above them.{why} If resistance breaks they have to cover — that's fuel for the squeeze"
                   + (", which is what your long wants." if long_ else ". Your short is fighting them."))
    return out


def reloader_line(reloaders):
    """'Reloaders — below: BUYER 128.40 ×5 (6,200 hit) · above: SELLER 128.60 ×3 (likely)'"""
    if not reloaders or not (reloaders["below"] or reloaders["above"]):
        return None

    def one(r):
        tag = "" if r["kind"] == "confirmed" else " (likely)"
        return f"{who(r['side'])} {px(r['price'])} ×{r['refills']}, {shares(r['absorbed'])} hit{tag}"
    parts = []
    if reloaders["below"]:
        parts.append("below: " + "; ".join(one(r) for r in reloaders["below"]))
    if reloaders["above"]:
        parts.append("above: " + "; ".join(one(r) for r in reloaders["above"]))
    return "Reloaders — " + " · ".join(parts)


def story(play, price, levels, bars, tape, now, recent_alerts, min_shares=1000, max_lines=6,
          trap=None, reloaders=None):
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
        text = (f"RELOAD {who(lv['side'])} at {px(lv['price'])} ({role_name(lv['role'])}): "
                f"{shares(lv['absorbed_total'])} shares hit it, {lv['refreshes']} refills, "
                f"{shares(lv['displayed'])} still showing. {aggressors(lv['side']).capitalize()} are getting absorbed — "
                f"{wall(lv['side'])} is holding.")
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
            text = (f"Maybe a {who(lv['side'])} at {px(lv['price'])} ({role_name(lv['role'])}): "
                    f"{shares(lv['absorbed_window'])} shares hit it and it came back {lv['refreshes']}x. Not confirmed yet.")
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

    # 4b. where the reloaders sit, and who is trapped
    rl = reloader_line(reloaders)
    if rl:
        lines.append(rl)
    lines.extend(trap_lines(trap, reloaders, play, price))

    # 5. is price stopping at the levels?
    for role in ("trigger", "second_entry"):
        level = play.get(role)
        if not level:
            continue
        touches, side_now = level_tests(bars, level)
        if touches >= 2 and side_now in ("below", "above"):
            kind = "Resistance" if side_now == "below" else "Support"
            lines.append(f"{kind} at {role_name(role)} {px(level)} is holding: tested {touches}x, price is still "
                         f"{side_now} it.")

    # 6. tape
    if tape and tape.get("state") not in (None, "QUIET"):
        pct = tape.get("buy_pct")
        mix = f" ({pct:.0f}% buys)" if pct is not None else ""
        words = {"BUYERS PAYING UP": "impatient buyers paying the offer (they want in now)",
                 "SELLERS HITTING OUT": "impatient sellers hitting the bid (they want out now)",
                 "TWO-SIDED": "two-sided, no one in control"}
        lines.append(f"Tape: {words.get(tape['state'], tape['state'].lower())}{mix}, last {int(tape['window_seconds'])}s.")

    return headline or "Waiting for data…", tone or "far", lines[:max_lines]


def short_status(play, price):
    text, where = proximity_line(play, price)
    if text is None:
        return "no price yet" if price is None else "no pivot yet — mark one on the chart"
    return text.replace("Price is ", "").rstrip(".")


def _ny_hm(t):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    try:
        return datetime.fromtimestamp(t, ZoneInfo("America/New_York")).strftime("%-I:%M")
    except Exception:
        return ""


def day_trap_text(symbol, dt, price):
    """TRAPPED on the day, in words: the move, who is underwater, by how much, and where their exit is."""
    hi, lo, L, S = dt.get("high"), dt.get("low"), dt.get("longs"), dt.get("shorts")
    bits = []
    if dt.get("side") == "long" and L and hi:
        bits.append(f"High {px(hi['price'])} at {_ny_hm(hi['t'])}, now {px(price)} ({hi['drop_pct']:+.1f}% from it)." if False else
                    f"High {px(hi['price'])} at {_ny_hm(hi['t'])}, now {px(price)}, {hi['drop_pct']:.1f}% under it.")
        bits.append(f"{shares(L['shares'])} shares ({dollars(L['dollars'])}) were bought above here since the open, {int(L['fraction'] * 100)}% of the day: "
                    f"average {px(L['avg'])}, {L['under_pct']:.1f}% underwater.")
        bits.append(f"Their way out is a push back to {px(L['avg'])}: expect supply there. Their max pain is the session low {px(lo['price'])}." if lo else
                    f"Their way out is a push back to {px(L['avg'])}: expect supply there.")
    elif dt.get("side") == "short" and S and lo:
        bits.append(f"Low {px(lo['price'])} at {_ny_hm(lo['t'])}, now {px(price)}, {lo['rise_pct']:.1f}% over it.")
        bits.append(f"{shares(S['shares'])} shares ({dollars(S['dollars'])}) were sold below here since the open, {int(S['fraction'] * 100)}% of the day: "
                    f"average {px(S['avg'])}, {S['under_pct']:.1f}% underwater.")
        bits.append(f"Their way out is a dip back to {px(S['avg'])}: expect demand there. Their max pain is the session high {px(hi['price'])}." if hi else
                    f"Their way out is a dip back to {px(S['avg'])}: expect demand there.")
    if dt.get("side") in ("long", "short"):
        bits.append(day_trap_flow_text(dt))
    else:
        if L and L["shares"]:
            bits.append(f"{shares(L['shares'])} bought above here today ({int(L['fraction'] * 100)}% of the day), average {px(L['avg'])}.")
        if S and S["shares"]:
            bits.append(f"{shares(S['shares'])} sold below here today ({int(S['fraction'] * 100)}% of the day), average {px(S['avg'])}.")
        if not bits:
            return "nobody underwater on the day yet"
    return " ".join(b for b in bits if b)


def day_trap_flow_text(dt):
    """The option money on the trap, in words: flow pressing the trapped crowd is the confirmation; flow the other
    way says somebody is paying for the trapped side's recovery."""
    f, side = dt.get("flow"), dt.get("side")
    if not f or not side:
        return ""
    what, other = ("puts", "calls") if side == "long" else ("calls", "puts")
    who = "trapped longs" if side == "long" else "trapped shorts"
    if f["verdict"] == "PRESSES":
        return (f"Option flow PRESSES them: {dollars(f['presses'])} of {what} bought at the ask since the "
                f"{'high' if side == 'long' else 'low'}{' vs ' + dollars(f['fades']) + ' of ' + other if f['fades'] else ''}.")
    if f["verdict"] == "FADES":
        return (f"Option flow FADES the trap: {dollars(f['fades'])} of {other} bought since the {'high' if side == 'long' else 'low'}"
                f"{' vs ' + dollars(f['presses']) + ' of ' + what if f['presses'] else ''} — somebody is paying for the {who} to get out.")
    if f["verdict"] == "MIXED":
        return f"Option flow is mixed: {dollars(f['calls'])} calls vs {dollars(f['puts'])} puts since the move."
    return "No option flow on it yet."


def day_trap_flow_words(dt):
    f, side = dt.get("flow"), dt.get("side")
    if not f or not side or not f["verdict"]:
        return ""
    from .board import say_money
    what, other = ("puts", "calls") if side == "long" else ("calls", "puts")
    if f["verdict"] == "PRESSES":
        return f" The option flow is pressing them, {say_money(f['presses'])} in {what}."
    if f["verdict"] == "FADES":
        return f" Careful, the option flow is fading the trap, {say_money(f['fades'])} in {other}."
    return " The option flow is mixed."


def day_trap_words(dt):
    L, S, hi, lo = dt.get("longs"), dt.get("shorts"), dt.get("high"), dt.get("low")
    if dt.get("side") == "long" and L:
        return (f"longs are trapped{' heavy' if 'HEAVY' in dt['state'] else ''}. {int(L['fraction'] * 100)} percent of today's volume was bought above here, "
                f"average {px(L['avg'])}, {L['under_pct']:.1f} percent underwater. A push back to {px(L['avg'])} is where they sell." + day_trap_flow_words(dt))
    if dt.get("side") == "short" and S:
        return (f"shorts are trapped{' heavy' if 'HEAVY' in dt['state'] else ''}. {int(S['fraction'] * 100)} percent of today's volume was sold below here, "
                f"average {px(S['avg'])}, {S['under_pct']:.1f} percent underwater. A dip back to {px(S['avg'])} is where they cover." + day_trap_flow_words(dt))
    return ""
