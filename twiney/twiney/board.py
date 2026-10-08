"""CONVICTION BOARD — Dan Shapiro's option-flow timing, encoded.

Source of truth: "PS60 Option Flow Conviction Board — Bot Source of Truth" (twelve Access A Trader videos plus the
locked notes). Every rule here carries its code from that document's §8 (R1..R17); nothing is invented.

The law (R8): option flow SUPPORTS a pivot thesis. It never replaces Daily room → pivot → confirm → second entry →
build → MP. READY TO GO needs the chart gate AND the flow gate (§7). One gate alone is ARMED — WAITING OTHER GATE.
"""

from . import ps60
from .narrative import px as _px
from .prices import fmt_price

RULES = {
    "R2": "premium meaningful, at least ~$100K (V3)",
    "R3": "prefer weeklies / the shortest expiry; months out is not the same trade (V3, ysshM1blOFA, URaAZxC23YU)",
    "R4": "short-dated + out of the money + size = a directional premium bet (V3, handoff §11)",
    "R5": "multiple repeat buyers with a short-term expiration = the formula (ysshM1blOFA)",
    "R6": "more flow, greater chance of the measured potential (V3, V4, t67SFwBMcys)",
    "R7": "daily chart + option flow = results; off-beta names need flow (V4 §4)",
    "R8": "flow supports the pivot; never replaces confirm, the second entry or the Daily MP (handoff §11)",
    "R9": "near-spot puts in an uptrend are a hedge, not a bet (V3)",
    "R10": "after a sweep: let the 5m put in a high / low past the sweep price, then trade the structure (V3)",
    "R11": "an options trade is stopped at the prior 5m low / high, never breakeven without a confirm pivot (V3, §9.6)",
    "R12": "reload seller stuck on the offer / buyer on the bid while thousands print: get out even (cheatsheets)",
    "R13": "two kinds of bettors: the lottery (no confirm) and the bet after the stock confirms — only the second (URaAZxC23YU)",
    "R14": "boxes checked on the flow before the level confirms is preparation, not an early entry (EQk_vs-wXfw)",
    "R15": "aggressive put buying into weakness is a sell-side clue, the mirror of call aggression (Z02b30weOrU)",
}

G, Y, R = "GREEN", "YELLOW", "RED"


def _k(v):
    v = float(v or 0)
    return f"${v / 1e6:.1f}M" if v >= 1e6 else f"${v / 1e3:.0f}K"


def _up_days(closes, n):
    """True when the last n daily closes each rose on the one before (a multi-day up move)."""
    if len(closes) < n + 1:
        return False
    tail = closes[-(n + 1):]
    return all(tail[i] > tail[i - 1] for i in range(1, len(tail)))


def flow_gate(prints, side, price, daily_closes, now, cfg):
    """§2 / §7 flow gate for one symbol. prints: this symbol's prints (any order). side: 'long' / 'short'."""
    c = cfg
    prem_min = float(c.get("of_premium_min", 100000))
    dte_green, dte_max = float(c.get("of_dte_green", 10)), float(c.get("of_dte_max", 21))
    otm_min = float(c.get("of_otm_min_pct", 1.0))
    rep_min = int(c.get("of_repeat_min", 2))
    fresh = float(c.get("of_fresh_minutes", 30)) * 60.0
    updays = int(c.get("of_hedge_updays", 3))
    cp = "C" if side == "long" else "P"
    other = "P" if cp == "C" else "C"

    def gather(which):
        rows = [p for p in prints if p.get("cp") == which and p.get("side") == "ask" and (p.get("premium") or 0) > 0]
        rows.sort(key=lambda p: p["t"])
        return rows

    # R3: only short-term contracts are the same trade. Expiry, out-of-the-money and repeats are all judged on this
    # one subset (a $1K weekly can never lend its expiry to $1M of contracts two months out)
    short = lambda rows: [p for p in rows if p.get("dte") is not None and p["dte"] <= dte_max]
    mine_all, theirs = gather(cp), short(gather(other))
    mine = short(mine_all)
    out = {"side": side, "cp": cp, "rules": [], "lanes": {}, "gate": False, "state": "FLOW_DEAD",
           "cluster": None, "opposing": round(sum(p["premium"] for p in theirs)), "hedge": False}
    if not mine and mine_all:
        far = sum(p["premium"] for p in mine_all)
        out["lanes"]["L5_FLOW_SIDE"] = (R, f"only {_k(far)} of {'calls' if cp == 'C' else 'puts'} more than {dte_max:.0f} days out (or no expiry) — months out is not the same trade (R3)")
        out["lanes"]["L6_FLOW_QUALITY"] = (Y, "months out: somebody positioning, not the short-term bet (R3)")
        out.update(dte_lane=R, premium_ok=far >= prem_min, otm_ok=False, repeats_ok=False, sweep=False)
        return out
    if not mine:
        out["lanes"]["L5_FLOW_SIDE"] = (R, f"no {'call' if cp == 'C' else 'put'} flow bought at the ask on this name — no flow, no dough")
        out["lanes"]["L6_FLOW_QUALITY"] = (R, "nothing to judge")
        if theirs:
            out["lanes"]["L5_FLOW_SIDE"] = (R, f"only {'put' if cp == 'C' else 'call'} flow here ({_k(out['opposing'])}) — the flow is against this {side}")
            out["state"] = "FLOW_OPPOSITE"
        return out
    dollars = sum(p["premium"] for p in mine)
    biggest = max(p["premium"] for p in mine)
    last_t, first_t = mine[-1]["t"], mine[0]["t"]
    # the series: same side + same expiry = the same bet, bought over and over (R5)
    series = {}
    for p in mine:
        series.setdefault(p.get("expiry") or "?", []).append(p)
    best_series = max(series.values(), key=lambda rows: sum(x["premium"] for x in rows))
    # R5 repeat buyers: separate MINUTES inside the fresh window (one order split into two prints is one buyer)
    repeats = len({int(x["t"] // 60) for x in best_series if now - x["t"] <= fresh})
    sweeps = sum(1 for p in mine if p.get("kind") in ("sweep", "block", "split", "multi"))
    sweep_urgent = any(p.get("kind") in ("sweep", "split", "multi") for p in mine)
    with_dte = [p for p in mine if p.get("dte") is not None]
    shortest = min((p["dte"] for p in with_dte), default=None)
    # OTM judged dollar-weighted (R4); a cluster sitting on the spot is not a directional bet
    otm_rows = [p for p in mine if p.get("otm_pct") is not None]
    otm_w = (sum(p["otm_pct"] * p["premium"] for p in otm_rows) / sum(p["premium"] for p in otm_rows)) if otm_rows else None
    hedge = False
    if otm_w is not None and otm_w < otm_min and daily_closes:
        # R9: puts near the spot after a multi-day run up = protection; calls near the spot after a multi-day dump the same
        hedge = _up_days(daily_closes, updays) if cp == "P" else _up_days([-x for x in daily_closes], updays)
    premium_ok = biggest >= prem_min or dollars >= prem_min
    dte_lane = R if shortest is None or shortest > dte_max else (G if shortest <= dte_green else Y)
    otm_ok = otm_w is not None and otm_w >= otm_min and not hedge
    repeats_ok = repeats >= rep_min
    alive = now - last_t <= fresh
    top = max(mine, key=lambda p: p["premium"])
    out.update(cluster={"dollars": round(dollars), "biggest": round(biggest), "prints": len(mine), "repeats": repeats,
                        "series_expiry": max(series, key=lambda e: sum(x["premium"] for x in series[e])), "sweeps": sweeps,
                        "dte": shortest, "otm_pct": None if otm_w is None else round(otm_w, 1), "last_t": last_t, "first_t": first_t,
                        "strike": top.get("strike"), "spot": top.get("spot"), "alive": alive,
                        "ids": [p["id"] for p in mine if p.get("id") is not None]},
               hedge=hedge, premium_ok=premium_ok, dte_lane=dte_lane, otm_ok=otm_ok, repeats_ok=repeats_ok, sweep=sweep_urgent)
    what = "calls" if cp == "C" else "puts"
    # L5: the side
    if out["opposing"] > dollars * 1.5 and out["opposing"] >= prem_min:
        out["lanes"]["L5_FLOW_SIDE"] = (R, f"{_k(out['opposing'])} of {'puts' if cp == 'C' else 'calls'} vs {_k(dollars)} of {what}: the flow is against this {side}")
        out["state"] = "FLOW_OPPOSITE"
    elif hedge:
        out["lanes"]["L5_FLOW_SIDE"] = (R, f"{_k(dollars)} of {what} near the spot after a {updays}-day {'run up' if cp == 'P' else 'dump'} — a HEDGE, not a bet (R9)")
        out["state"] = "FLOW_HEDGE"
    elif repeats_ok:
        out["lanes"]["L5_FLOW_SIDE"] = (G, f"{_k(dollars)} of {what} bought at the ask, {repeats}x on the {out['cluster']['series_expiry']} series" + ("" if alive else f" — nothing new for {int((now - last_t) // 60)} min"))
        out["state"] = ("FLOW_ALIVE_LONG" if side == "long" else "FLOW_ALIVE_SHORT") if alive else "FLOW_FADING"
    else:
        out["lanes"]["L5_FLOW_SIDE"] = (Y, f"{_k(dollars)} of {what} in {len(mine)} print{'s' if len(mine) != 1 else ''} — one print is a guess; waiting for the repeat (R5)")
        out["state"] = "FLOW_STARTING" if alive else "FLOW_FADING"
    # L6: the quality — premium, expiry, OTM, repeats, sweep
    bits, miss = [], []
    (bits if premium_ok else miss).append(f"premium {_k(biggest)} biggest / {_k(dollars)} in all" + ("" if premium_ok else f" (under {_k(prem_min)}, R2)"))
    if shortest is None:
        miss.append("no expiry on the prints")
    else:
        (bits if dte_lane != R else miss).append(f"{shortest:.0f}d to expiry" + (" weeklies ✓" if dte_lane == G else " — still short-term" if dte_lane == Y else " — months out is not the same trade (R3)"))
    (bits if otm_ok else miss).append((f"{otm_w:.1f}% out of the money" if otm_w is not None else "OTM unknown") + ("" if otm_ok else (" — a hedge (R9)" if hedge else " — near the spot, not a directional bet")))
    (bits if repeats_ok else miss).append(f"{repeats}x repeat" + ("" if repeats_ok else f" (needs {rep_min}, R5)"))
    if sweep_urgent:
        bits.append("sweeps: they do not care what they pay (V3)")
    q = G if (premium_ok and dte_lane != R and otm_ok and repeats_ok) else (R if hedge else Y)
    out["lanes"]["L6_FLOW_QUALITY"] = (q, " · ".join(bits) + ((" · MISSING: " + "; ".join(miss)) if miss else ""))
    out["gate"] = bool(premium_ok and dte_lane != R and otm_ok and repeats_ok and not hedge
                       and out["state"] in ("FLOW_ALIVE_LONG", "FLOW_ALIVE_SHORT"))
    for code in ("R2", "R3", "R4", "R5"):
        out["rules"].append(code)
    if hedge:
        out["rules"].append("R9")
    if sweep_urgent:
        out["rules"].append("R10")
    return out


def chart_gate(play, price, se, mp, reloaders, tape, now, cfg):
    """§4.1 ordered gate from the chart (plus the Level II reload check in L4)."""
    lanes, long_ = {}, play.get("side", "long") == "long"
    v = (mp or {}).get("verdict")
    if v == "CLEAR":
        lanes["L0_DAILY_MP"] = (G, f"Daily room ${mp['dollars']:.2f} to the next level, {mp.get('ratio')}× ATR — CLEAR")
    elif v == "MP":
        lanes["L0_DAILY_MP"] = (G, f"Daily room ${mp['dollars']:.2f} to your target (no ATR to judge it against)")
    elif v == "THIN":
        lanes["L0_DAILY_MP"] = (Y, f"Daily room ${mp['dollars']:.2f} is THIN against a ${mp['atr']:.2f} ATR — PASS by the MP law")
    elif not play.get("trigger") and (play.get("target") or play.get("mp")):
        lanes["L0_DAILY_MP"] = (R, f"target {_px(play.get('target') or play.get('mp'))} is on the chart but the room is measured from the pivot — mark the pivot")
    elif play.get("trigger"):
        lanes["L0_DAILY_MP"] = (R, "no target on the chart — right-click the chart: TARGET here (the room runs pivot → target)")
    else:
        lanes["L0_DAILY_MP"] = (R, "no pivot and no target yet — right-click the chart to put them on")
    pivot = play.get("trigger")
    lanes["L1_PIVOT"] = (G, f"pivot {_px(pivot)}") if pivot else (R, "no pivot marked — right-click the chart: PIVOT here (or press L, then click)")
    stt = (se or {}).get("state")
    fails = (se or {}).get("fails") or 0
    through = pivot and price and (price > pivot if long_ else price < pivot)
    if stt in (ps60.BROKE, ps60.RETRACE, ps60.SECOND_ENTRY):
        lanes["L2_CONFIRM"] = (G, f"pivot {_px(pivot)} broke and held" + (f" (after {fails} failed break{'s' if fails > 1 else ''})" if fails else ""))
    elif through:
        lanes["L2_CONFIRM"] = (Y, f"price is through {_px(pivot)} inside the candle — not confirmed until it holds")
    else:
        lanes["L2_CONFIRM"] = (R, (f"{fails} failed break{'s' if fails > 1 else ''} — " if fails else "") + f"waiting for the pivot {_px(pivot)} to break" if pivot else "no pivot")
    if stt == ps60.SECOND_ENTRY:
        lanes["L3_SECOND_ENTRY"] = (G, f"second entry through {_px(se.get('second_entry'))}")
    elif stt == ps60.RETRACE:
        lanes["L3_SECOND_ENTRY"] = (Y, f"retraced to {_px(se.get('retrace'))} — the second entry is back through {_px(se.get('extreme'))} on a new candle")
    elif stt == ps60.BROKE:
        lanes["L3_SECOND_ENTRY"] = (Y, f"new {'high' if long_ else 'low'} {_px(se.get('extreme'))} — waiting for the retrace")
    else:
        lanes["L3_SECOND_ENTRY"] = (R, "no second entry: break → new extreme → retrace → back through it")
    # L4 build + the reload trap (R12)
    rl = reloaders or {"below": [], "above": []}
    # every confirmed reloader counts (SETTINGS > PS60 story can still limit it to whole / half dollars)
    against = [r for r in (rl["above"] if long_ else rl["below"]) if r.get("kind") == "confirmed" and r.get("ps60", True)
               and r.get("side") == ("ask" if long_ else "bid") and (r.get("stage") or "RELOADING") in ("RELOADING", "STILL THERE")]
    tp = tape or {}
    tape_txt = (f" · tape {tp['buy_pct']:.0f}% paying up" if tp.get("buy_pct") is not None else "")
    if against:
        r = against[0]
        lanes["L4_BUILD"] = (R, f"reload {'seller' if long_ else 'buyer'} stuck on the {'offer' if long_ else 'bid'} at {_px(r['price'])}, {r.get('absorbed', 0):,} sh and still there — get out even (R12)")
    elif stt == ps60.SECOND_ENTRY and se.get("build") == "building":
        lanes["L4_BUILD"] = (G, "building: price improving past the second entry" + tape_txt)
    elif stt == ps60.SECOND_ENTRY and se.get("build") == "early":
        lanes["L4_BUILD"] = (G, "just triggered — inside the two-minute grace" + tape_txt)
    elif stt == ps60.SECOND_ENTRY:
        lanes["L4_BUILD"] = (R, "second entry is not building — stand aside" + tape_txt)
    else:
        lanes["L4_BUILD"] = (Y if stt in (ps60.BROKE, ps60.RETRACE) else R, "nothing to build yet" + tape_txt)
    gate = all(lanes[k][0] == G for k in ("L0_DAILY_MP", "L1_PIVOT", "L2_CONFIRM", "L3_SECOND_ENTRY", "L4_BUILD"))
    return {"lanes": lanes, "gate": gate, "reload_trap": bool(against), "rules": ["R8", "R13"] + (["R12"] if against else [])}


def prior_5m(bars, now, long_):
    """R11: the options stop — the prior completed 5-minute candle's low (long) / high (short)."""
    if not bars:
        return None
    cur = int(now // 300) * 300
    done = [b for b in bars if b[0] < cur and b[0] >= cur - 600]
    if not done:
        return None
    last_bucket = max(int(b[0] // 300) * 300 for b in done)
    rows = [b for b in done if int(b[0] // 300) * 300 == last_bucket]
    return fmt_price(min(b[3] for b in rows) if long_ else max(b[2] for b in rows))


def score(cg, fg):
    """§5.3: Daily MP 20 · pivot + confirm 20 · second entry 20 · premium 10 · short DTE 10 · OTM 10 · repeats 10 · sweep +5."""
    L = cg["lanes"]
    s = {G: 20, Y: 10}.get(L["L0_DAILY_MP"][0], 0)
    s += (10 if L["L1_PIVOT"][0] == G else 0) + {G: 10, Y: 5}.get(L["L2_CONFIRM"][0], 0)
    s += {G: 20, Y: 8}.get(L["L3_SECOND_ENTRY"][0], 0)
    if fg.get("cluster") and not fg.get("hedge") and fg.get("state") != "FLOW_OPPOSITE":
        s += 10 if fg.get("premium_ok") else 0
        s += {G: 10, Y: 5}.get(fg.get("dte_lane"), 0)
        s += 10 if fg.get("otm_ok") else 0
        s += 10 if fg.get("repeats_ok") else 0
        s += 5 if fg.get("sweep") else 0
    return max(0, min(100, s))


def side_picked(play):
    """Has the trader taken a side on this ticker? A pick (L / S, SIDE, flip) or levels that only fit one side:
    a stop and a target, or a pivot with a 2nd entry. Until then the desk has no idea which way you lean, so it
    talks about the flow itself — never 'with you' or 'against you'."""
    if play.get("side_set"):
        return True
    stop, target = play.get("stop"), play.get("target")
    if stop and target and stop != target:
        return True
    trigger, second = play.get("trigger"), play.get("second_entry")
    return bool(trigger and second and trigger != second)


def flow_leans(prints):
    """Which way the money leans on this name: ('long'|'short'|None, call $, put $) from prints bought at the ask."""
    c = sum(p.get("premium") or 0 for p in prints if p.get("cp") == "C" and p.get("side") == "ask")
    pt = sum(p.get("premium") or 0 for p in prints if p.get("cp") == "P" and p.get("side") == "ask")
    return (None if not c and not pt else "short" if pt > c else "long"), round(c), round(pt)


def say_expiry(dte):
    """When the contracts die, the way it is said: 'expiring today', 'expiring tomorrow', 'expiring in 3 days'."""
    if dte is None:
        return ""
    d = float(dte)
    if d < 1:
        return "expiring today"
    if d < 2:
        return "expiring tomorrow"
    return f"expiring in {int(round(d))} days"


def say_money(v):
    """Money the way it is said out loud: '300 thousand dollars', '1.2 million dollars'."""
    v = float(v or 0)
    if v >= 1e6:
        return f"{v / 1e6:.1f}".rstrip("0").rstrip(".") + " million dollars"
    if v >= 1e3:
        return f"{round(v / 1e3):,.0f} thousand dollars"
    return f"{v:,.0f} dollars"


def build(play, price, se, mp, reloaders, tape, prints, daily_closes, bars, now, cfg, prev_state=None):
    picked = side_picked(play)
    lean, call_usd, put_usd = flow_leans(prints)
    # no side yet: judge the flow on the side the money is on, and say so — never 'against you'
    side = play.get("side", "long") if picked else (lean or play.get("side", "long"))
    cg = chart_gate(play, price, se, mp, reloaders, tape, now, cfg)
    fg = flow_gate(prints, side, price, daily_closes, now, cfg)
    lanes = dict(cg["lanes"])
    lanes.update(fg["lanes"])
    if not picked:
        what = "calls" if side == "long" else "puts"
        lanes["L5_FLOW_SIDE"] = (lanes["L5_FLOW_SIDE"][0], f"no side picked — the money here is in {what}: {_k(call_usd)} calls / {_k(put_usd)} puts"
                                 if (call_usd or put_usd) else "no side picked — no option flow bought at the ask on this name yet")
    # L7: same side as the chart, and the chart has confirmed (§4.2: the bet AFTER the stock confirms)
    if fg["state"] in ("FLOW_OPPOSITE", "FLOW_HEDGE"):
        lanes["L7_CORRELATION"] = (R, "flow is against the chart" if fg["state"] == "FLOW_OPPOSITE" else "a hedge does not correlate with anything")
    elif fg.get("cluster") and lanes["L2_CONFIRM"][0] == G:
        lanes["L7_CORRELATION"] = (G, f"{'calls' if side == 'long' else 'puts'} with a confirmed {side}: the bet after the stock confirmed (R13)")
    elif fg.get("cluster"):
        lanes["L7_CORRELATION"] = (Y, "flow is on your side but the chart has not confirmed — preparation, not an entry (R14)")
    else:
        lanes["L7_CORRELATION"] = (R, "no flow to correlate")
    order = ["L0_DAILY_MP", "L1_PIVOT", "L2_CONFIRM", "L3_SECOND_ENTRY", "L4_BUILD", "L5_FLOW_SIDE", "L6_FLOW_QUALITY", "L7_CORRELATION"]
    chart_ok, flow_ok = cg["gate"], fg["gate"] and lanes["L7_CORRELATION"][0] == G
    reasons = []
    if chart_ok and flow_ok:
        state, light = "READY_TO_GO", G
    elif fg["state"] in ("FLOW_OPPOSITE", "FLOW_HEDGE"):
        state, light = "PASS", R
        reasons.append("opposing flow" if fg["state"] == "FLOW_OPPOSITE" else "hedge-only flow")
    elif chart_ok or (fg["gate"]):
        state, light = "ARMED", Y
    elif fg.get("cluster") or lanes["L2_CONFIRM"][0] != R or lanes["L3_SECOND_ENTRY"][0] != R:
        state, light = "WATCH", Y
    else:
        state, light = "PASS", R
    # INVALIDATED: it was armed or ready and something Dan names took it away (§5.4)
    if prev_state in ("ARMED", "READY_TO_GO", "INVALIDATED") and state != "READY_TO_GO":
        why = []
        if lanes["L2_CONFIRM"][0] != G:
            why.append("lost the confirm")
        if cg["reload_trap"]:
            why.append("reload " + ("seller" if side == "long" else "buyer") + " in the way")
        if fg["state"] == "FLOW_OPPOSITE":
            why.append("opposing " + ("put" if side == "long" else "call") + " flow")
        if lanes["L0_DAILY_MP"][0] == R:
            why.append("MP gone")
        if why:
            state, light, reasons = "INVALIDATED", R, why
    label = {"READY_TO_GO": f"{side.upper()} READY TO GO", "ARMED": f"{side.upper()} ARMED — WAITING {'FLOW' if chart_ok else 'CHART'} GATE",
             "WATCH": f"{side.upper()} WATCH", "PASS": "PASS", "INVALIDATED": f"{side.upper()} INVALIDATED"}[state]
    if not picked:
        # nothing is armed, ready or invalidated for a side nobody picked: the board only reports the flow
        if state in ("ARMED", "READY_TO_GO", "INVALIDATED"):
            state, light, reasons = "WATCH", Y, []
        lanes["L7_CORRELATION"] = (Y, "no side picked: draw a stop and a target (or hit L / S) and the desk judges the flow with you or against you")
        label = ("NO SIDE YET — FLOW LEANS " + ("CALLS" if side == "long" else "PUTS")) if lean else "NO SIDE YET — NO FLOW"
    long_ = side == "long"
    return {"symbol": play.get("symbol"), "side_bias": side.upper(), "side_picked": picked, "board_state": state, "label": label, "traffic_light": light,
            "score": score(cg, fg), "chart_gate": {"ok": chart_ok},
            "flow_gate": {"ok": flow_ok, "state": fg["state"], "cluster": fg.get("cluster"), "hedge": fg["hedge"],
                          "premium_ok": fg.get("premium_ok", False), "dte_lane": fg.get("dte_lane"), "repeats_ok": fg.get("repeats_ok", False)},
            "lanes": [{"id": k, "light": lanes[k][0], "text": lanes[k][1]} for k in order],
            "anti_early_entry": {"chart_ok": chart_ok, "flow_ok": flow_ok, "both_true": chart_ok and flow_ok},
            "max_pain": {"options": prior_5m(bars, now, long_), "equity": play.get("stop")},
            "reasons": reasons, "rules": sorted(set(cg["rules"] + fg["rules"] + (["R11"] if chart_ok else [])))}


def alert_text(b, play, mp, se):
    """§5.4 copy, filled in."""
    sym, side = b["symbol"], b["side_bias"]
    cl, fg = b["flow_gate"].get("cluster") or {}, b["flow_gate"]
    what = "CALL" if side == "LONG" else "PUT"
    flow_bit = (f"short-dated OTM {what} flow ({_k(cl.get('dollars'))}, {cl.get('dte') if cl.get('dte') is None else int(cl['dte'])}DTE, "
                f"strike {_px(cl.get('strike'))} vs spot {_px(cl.get('spot'))}, repeats={cl.get('repeats')})") if cl else "no flow"
    pivot = _px(play.get("trigger"))
    st = b["board_state"]
    if st == "WATCH":
        confirm = next(l['text'] for l in b['lanes'] if l['id'] == 'L2_CONFIRM')
        return (f"[PS60 OF] {sym} {side} WATCH — {flow_bit}." + (f" Hedge check={'true' if fg.get('hedge') else 'false'}." if side == "SHORT" else "")
                + f" Chart: {confirm}. NOT READY until second entry + flow correlation.")
    if st == "ARMED":
        waiting = "second entry through " + pivot if b["chart_gate"]["ok"] is False else "repeat short-dated OTM " + what.lower() + " flow"
        return f"[PS60 OF] {sym} {side} ARMED — {'chart gate GREEN' if b['chart_gate']['ok'] else 'daily confirm + ' + what + ' flow quality GREEN'}. Waiting {waiting}."
    if st == "READY_TO_GO":
        mp_usd = f"${mp['dollars']:.2f}" if mp and mp.get("dollars") is not None else "—"
        atr = f"${mp['atr']:.2f}" if mp and mp.get("atr") else "—"
        return (f"[PS60 OF] {sym} {side} READY TO GO — chart gate GREEN (2nd entry {_px((se or {}).get('second_entry'))}) AND flow gate GREEN "
                f"(repeat short-dated OTM {what.lower()}s{', hedge=false' if side == 'SHORT' else ''}). MP {mp_usd} / ATR {atr}. "
                f"Max pain: prior 5m {'low' if side == 'LONG' else 'high'} {_px(b['max_pain']['options'])} (options) / process stop {_px(b['max_pain']['equity'])} (equity).")
    if st == "INVALIDATED":
        return f"[PS60 OF] {sym} {side} INVALIDATED — {', '.join(b['reasons']) or 'setup gone'}."
    return f"[PS60 OF] {sym} PASS."


def watch_worthy(fg):
    """A WATCH is only called on flow with some quality: the premium floor met and a short-term expiry (R2, R3).
    One $4K print forty-five days out is nothing to watch."""
    return bool(fg.get("cluster")) and bool(fg.get("premium_ok")) and fg.get("dte_lane") in ("GREEN", "YELLOW") and not fg.get("hedge")


def market_watch_text(sym, side, fg, price):
    """§5.4 WATCH copy for a ticker that is NOT a play on the desk: the flow found it; the chart work is still to do."""
    cl = fg.get("cluster") or {}
    what = "CALL" if side == "long" else "PUT"
    return (f"[PS60 OF] {sym} {side.upper()} WATCH — short-dated OTM {what} flow ({_k(cl.get('dollars'))}, "
            f"{'' if cl.get('dte') is None else int(cl['dte'])}DTE, strike {_px(cl.get('strike'))} vs spot {_px(cl.get('spot') or price)}, repeats={cl.get('repeats')})."
            + (f" Hedge check={'true' if fg.get('hedge') else 'false'}." if side == "short" else "")
            + " Not a play on the desk: find the Daily room, mark the pivot, wait for the confirm. NOT READY from flow alone (R13).")


def words(b):
    """What the desk says out loud, in plain English: the state and the one thing that carries or blocks it."""
    sym, st, side = b["symbol"], b["board_state"], b["side_bias"].lower()
    cl = b["flow_gate"].get("cluster") or {}
    what = "calls" if side == "long" else "puts"
    if not b.get("side_picked", True):
        return None                                   # nothing to say for a side nobody picked
    if st == "READY_TO_GO":
        exp = say_expiry(cl.get("dte"))
        return (f"{sym} {side}, ready to go. The chart is confirmed and the flow is confirmed: {say_money(cl.get('dollars'))} "
                f"went into short term {what}{', ' + exp if exp else ''}, {cl.get('repeats')} times. They keep scooping up the {what}.")
    if st == "ARMED":
        return (f"{sym} {side} is armed. The chart is there, waiting on the option flow." if b["chart_gate"]["ok"]
                else f"{sym} {side} is armed. The option flow is there, waiting on the chart.")
    if st == "INVALIDATED":
        return f"{sym} {side} is off: {', '.join(b['reasons'])}."
    return None
