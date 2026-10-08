"""PS60 STORY: the existing PS60 read, told as one short running story with the Daily chart, the price structure,
the tape, the Level II, the option flow and the price response put together.

Nothing here replaces PS60. The pivot, the second entry, the sneaky pivots, the targets, the ATR, the conviction
board and every call the desk already makes stay exactly as they are. This layer only adds awareness:

    DAILY CONTEXT  -> above the daily 50-day: the bullish PS60 framework, the prior-day high is the objective;
                      below it: the bearish framework, the prior-day low is the objective
    LOCATIONS      -> the PS60 levels (pivot, 2nd entry, sneaky pivots, target) + prior-day / prior-week / month /
                      52-week highs and lows + your own lines and zones (no automatic support / resistance)
    CONFLUENCE     -> locations that sit together are one place, not four: "MAJOR PS60 CONFLUENCE around $145.00"
    HIGH ATTENTION -> price close to any of them: everything below is read against THAT place
    RELOADS        -> only a reload buyer / seller at a whole or half dollar (x.00 / x.50) counts for PS60
    OPTION FLOW    -> NOT YET CONFIRMED / DEVELOPING / CONFIRMED / CONFLICTING, always said with where price is
    PRICE RESPONSE -> is price doing what the flow and the tape say it should?

Everything is a pure function of the data handed in, so the same inputs always tell the same story (and a replay
tells it again).
"""

from collections import deque

from . import studies
from .narrative import px

FLOW_STATES = ("NOT YET CONFIRMED", "DEVELOPING", "CONFIRMED", "CONFLICTING")
_NUM = {1: "ONE", 2: "TWO", 3: "THREE", 4: "FOUR", 5: "FIVE", 6: "SIX", 7: "SEVEN", 8: "EIGHT", 9: "NINE", 10: "TEN"}

# what each kind of place is called, and how much it weighs in a confluence
PS60_KINDS = ("pivot", "second", "sneaky", "target")
WEIGHT = {"pivot": 3, "second": 3, "sneaky": 2, "target": 2, "user": 3, "uzone": 3, "pdh": 2, "pdl": 2, "pwh": 2, "pwl": 2,
          "mh": 2, "ml": 2, "yh": 3, "yl": 3, "inst": 1, "d50": 3, "d200": 3, "dma": 2, "hma": 1}
JOIN_ONLY = ("inst", "uzone", "dma", "hma")      # these make a place stronger; they never make one alone
MA_PACK_KINDS = ("dma", "hma")
MA_KINDS = ("d50", "d200")


def num_word(n):
    return _NUM.get(n, str(n))


def money(v):
    v = float(v or 0)
    return f"${v / 1e6:.1f}M" if v >= 1e6 else f"${v / 1e3:.0f}K"


def qualifies(price, tick=0.01):
    """A PS60 reload price: a whole dollar (x.00) or a half dollar (x.50). 142.00 and 142.50 count; 142.23, 142.75
    and 143.17 do not (they stay on the Level II, they just do not count for PS60)."""
    if price is None:
        return False
    v = float(price) * 2.0
    return abs(v - round(v)) / 2.0 <= max(tick, 1e-4) / 2.0 + 1e-9


def inst_name(p):
    return "whole dollar" if abs(p - round(p)) < 1e-6 else "half dollar"


# ---- the Daily chart -------------------------------------------------------------------------------------------

def daily_context(drows, live, last, n=50):
    """Above / below the daily 50-day (the chart's 50 SMA, today's bar included, like the chart draws it) and the
    objective that follows: the prior-day high (bullish) or the prior-day low (bearish)."""
    if last is None or not drows:
        return None
    done = drows[:-1] if live else drows
    if not done:
        return None
    closes = [r[4] for r in drows]
    ma = sum(closes[-n:]) / n if len(closes) >= n else None
    ma200 = sum(closes[-200:]) / 200 if len(closes) >= 200 else None
    pdh, pdl = done[-1][2], done[-1][3]
    today_h = drows[-1][2] if live else None
    today_l = drows[-1][3] if live else None
    out = {"sma50": None if ma is None else round(ma, 4), "sma200": None if ma200 is None else round(ma200, 4), "pdh": pdh, "pdl": pdl, "bias": None, "objective": None, "taken": False}
    if ma is None:
        out["text"] = f"Daily: not enough history for the 50-day yet ({len(closes)} days). Prior-day high {px(pdh)}, low {px(pdl)}."
        return out
    bull = last >= ma
    out["bias"] = "bull" if bull else "bear"
    two = "" if ma200 is None else f", {'above' if last >= ma200 else 'below'} the 200-day ({px(ma200)})"
    if bull:
        out["objective"] = [pdh, "prior-day high"]
        out["taken"] = bool((today_h is not None and today_h > pdh) or last > pdh)
        out["text"] = (f"Daily above the 50-day ({px(ma)}){two}: bullish PS60, supply to supply. "
                       + (f"Prior-day high {px(pdh)} taken: on to the next supply." if out["taken"]
                          else f"Objective: take the prior-day high {px(pdh)}."))
    else:
        out["objective"] = [pdl, "prior-day low"]
        out["taken"] = bool((today_l is not None and today_l < pdl) or last < pdl)
        out["text"] = (f"Daily below the 50-day ({px(ma)}){two}: bearish PS60, demand to demand. "
                       + (f"Prior-day low {px(pdl)} taken: on to the next demand." if out["taken"]
                          else f"Objective: take the prior-day low {px(pdl)}."))
    return out


# ---- the places price can react ---------------------------------------------------------------------------------

def ps60_points(play, sneaky_auto=None):
    """The existing PS60 levels as places: pivot, 2nd entry, sneaky pivots, target (both sides when both are drawn),
    and your own lines."""
    out = []
    long_ = play.get("side", "long") == "long"

    def add(p, name, kind):
        if p:
            out.append({"p": float(p), "name": name, "kind": kind})
    add(play.get("trigger"), "PS60 pivot", "pivot")
    add(play.get("second_entry"), "PS60 Second Entry", "second")
    add(play.get("target"), "PS60 target", "target")
    alt = play.get("alt") or {}
    other = "short" if long_ else "long"
    add(alt.get("trigger"), f"PS60 {other} pivot", "pivot")
    add(alt.get("second_entry"), f"PS60 {other} Second Entry", "second")
    for p in play.get("sneaky_levels") or []:
        add(p, "PS60 Sneaky Pivot", "sneaky")
    for s in sneaky_auto or []:
        p = s.get("price") if isinstance(s, dict) else None
        if p and not any(abs(p - x["p"]) < 1e-6 for x in out):
            add(p, "Sneaky Pivot", "sneaky")
    for p in play.get("extra_levels") or []:
        add(p, "your line", "user")
    return out


def ma_points(ctx):
    """The daily 50-day and 200-day as places: the big money watches them, so the option flow is read against them."""
    out = []
    if ctx and ctx.get("sma50"):
        out.append({"p": ctx["sma50"], "name": "daily 50-day", "kind": "d50"})
    if ctx and ctx.get("sma200"):
        out.append({"p": ctx["sma200"], "name": "daily 200-day", "kind": "d200"})
    return out


def ma_stack_points(daily_pack, h60_pack):
    """Dan's moving-average pack (EMA 5/10/20/34/50/65/89/100/150/200, SMA 5/10/20/50/100/150/200) on the daily and the
    60-minute, the same Pine-exact numbers the chart and AIRSPACE use. They join a confluence (a pivot sitting on the
    60m 200 EMA), they never switch HIGH ATTENTION on alone (the 50 / 200-day are their own places)."""
    out = []
    for pack, tag, kind in ((daily_pack, "daily", "dma"), (h60_pack, "60m", "hma")):
        for nm, v in pack or []:
            if v is None or not nm.startswith(("EMA ", "SMA ")):
                continue
            if kind == "dma" and nm in ("SMA 50", "SMA 200"):
                continue
            n, typ = nm.split(" ")[1], nm.split(" ")[0]
            out.append({"p": float(v), "name": f"{tag} {n} {typ}", "kind": kind})
    return out


def structure_points(drows, live, t):
    """Prior-day, prior-week, prior-month and 52-week highs and lows from the daily bars."""
    out = []
    done = drows[:-1] if live else drows
    if not done:
        return out
    out.append({"p": done[-1][2], "name": "prior-day high", "kind": "pdh"})
    out.append({"p": done[-1][3], "name": "prior-day low", "kind": "pdl"})
    weeks = studies.weekly_from(done)
    if weeks:
        cur = studies.ny(t).isocalendar()[:2]
        wk = [w for w in weeks if studies.ny(w[0] + 43200).isocalendar()[:2] != cur]
        if wk:
            out.append({"p": wk[-1][2], "name": "prior-week high", "kind": "pwh"})
            out.append({"p": wk[-1][3], "name": "prior-week low", "kind": "pwl"})
    mh, ml = studies.prev_month_hl(done, t)
    if mh is not None:
        out.append({"p": mh, "name": "prior-month high", "kind": "mh"})
        out.append({"p": ml, "name": "prior-month low", "kind": "ml"})
    yr = drows[-252:]
    if len(yr) >= 60:
        out.append({"p": max(r[2] for r in yr), "name": "52-week high", "kind": "yh"})
        out.append({"p": min(r[3] for r in yr), "name": "52-week low", "kind": "yl"})
    return out


def user_zones(play):
    out = []
    for z in play.get("zones") or []:
        try:
            lo, hi = sorted((float(z[0]), float(z[1])))
        except (TypeError, ValueError, IndexError):
            continue
        out.append({"lo": lo, "hi": hi, "kind": "user", "tests": 0, "name": f"YOUR ZONE {px(lo)}–{px(hi)}",
                    "short": f"your zone {px(lo)}–{px(hi)}", "user": True})
    return out


def confluence(points, zones, last, atr, tick, cfg):
    """Places that sit together, read as ONE place. A group needs two different kinds (a pivot and a prior-day high,
    not two whole numbers); whole / half dollars and zones join a group, they never make one alone."""
    if last is None:
        return []
    tol = max(3 * tick, min((atr or 0) * float(cfg.get("confluence_atr_pct", 6)) / 100.0, last * 0.002), last * 0.0004)
    pts = sorted([p for p in points if p["kind"] != "inst"], key=lambda p: p["p"])
    groups, cur = [], []
    for p in pts:
        if cur and (p["p"] - cur[-1]["p"] > tol or p["p"] - cur[0]["p"] > 2 * tol):
            groups.append(cur)
            cur = []
        cur.append(p)
    if cur:
        groups.append(cur)
    reach = max((atr or 0) * 1.5, last * 0.03)
    out = []
    for g in groups:
        center = sum(p["p"] for p in g) / len(g)
        if abs(center - last) > reach:
            continue
        mem = list(g)
        for q in (round(center), round(center * 2) / 2):
            if abs(q - center) <= tol and not any(m["kind"] == "inst" and abs(m["p"] - q) < 1e-6 for m in mem):
                mem.append({"p": float(q), "name": inst_name(q), "kind": "inst"})
                break
        for z in zones:
            if z["lo"] - tol <= center <= z["hi"] + tol:
                mem.append({"p": center, "name": z["short"], "kind": "uzone", "zone": z})
        names = {m["name"] for m in mem if m["kind"] != "inst"}
        anchor = any(m["kind"] not in JOIN_ONLY for m in mem)
        if not anchor or len(names) < 2:
            continue
        # moving averages add at most 2 to the weight: a forest of MAs on top of a level is one more reason, not six
        score = sum(WEIGHT.get(m["kind"], 1) for m in mem if m["kind"] not in MA_PACK_KINDS) + \
            min(2, sum(WEIGHT.get(m["kind"], 1) for m in mem if m["kind"] in MA_PACK_KINDS))
        major = score >= int(cfg.get("major_score", 6))
        at = round(center * 2) / 2 if any(m["kind"] == "inst" for m in mem) else center
        names = " · ".join(f"{m['name']} {px(m['p'])}" if m["kind"] != "uzone" else m["name"] for m in mem)
        ps60 = any(m["kind"] in PS60_KINDS for m in mem)
        out.append({"p": round(at, 4), "lo": min(m["p"] for m in mem), "hi": max(m["p"] for m in mem), "major": major, "score": score,
                    "members": [m["name"] for m in mem], "ps60": ps60, "mas": [m["name"] for m in mem if m["kind"] in MA_PACK_KINDS + MA_KINDS],
                    "text": f"{'Major ' if major else ''}{'PS60 ' if ps60 else ''}confluence around {px(at)}: {names}"})
    out.sort(key=lambda c: abs(c["p"] - last))
    return out[:4]


# ---- where price is now ----------------------------------------------------------------------------------------

def near_dist(last, atr, tick, cfg):
    return max(float(cfg.get("near_ticks", 8)) * tick, (atr or 0) * float(cfg.get("near_atr_pct", 12)) / 100.0,
               last * float(cfg.get("near_pct", 0.15)) / 100.0)


def attention(points, zones, conf, last, near):
    """HIGH ATTENTION: price close to a place that matters (whole / half dollars alone never switch it on). Returns
    the nearest one: the place everything else is read against."""
    if last is None:
        return None
    cands = []
    for p in points:
        if p["kind"] in ("inst",) + MA_PACK_KINDS:
            continue
        cands.append({"name": p["name"], "p": p["p"], "lo": p["p"], "hi": p["p"], "kind": p["kind"], "d": abs(p["p"] - last)})
    for z in zones:
        d = 0.0 if z["lo"] <= last <= z["hi"] else min(abs(last - z["lo"]), abs(last - z["hi"]))
        cands.append({"name": z["short"], "p": (z["lo"] + z["hi"]) / 2, "lo": z["lo"], "hi": z["hi"], "kind": "uzone",
                      "d": d, "zone": z})
    if not cands:
        return None
    best = min(cands, key=lambda c: (c["d"], -WEIGHT.get(c["kind"], 1)))
    for c in conf:
        if c["lo"] - near <= best["p"] <= c["hi"] + near:
            best["conf"] = c
            break
    best["on"] = best["d"] <= near
    best["approach"] = best["d"] <= 2.5 * near
    best["dir"] = "up" if best["lo"] > last else "down" if best["hi"] < last else None
    return best


# ---- the option flow, read against a direction ----------------------------------------------------------------

def _up_days(closes, n):
    return len(closes) >= n + 1 and all(closes[-n - 1 + i + 1] > closes[-n - 1 + i] for i in range(n))


def flow_read(prints, now, cfg, daily_closes=None):
    """Option prints bought at the ask in the window, per side: dollars, prints, how far out of the money (deep OTM
    counts more, near the money counts less), and whether it is picking up."""
    win = float(cfg.get("flow_minutes", 20)) * 60.0
    deep = float(cfg.get("deep_otm_pct", 5.0))
    max_dte = float(cfg.get("flow_max_dte", 21))
    out = {"C": None, "P": None}
    for cp in ("C", "P"):
        # the same trade only: bought at the ask, short-dated, out of the money (in the money is stock replacement,
        # not a bet); near-the-money puts after a run up (calls after a dump) are a hedge, not a bet (R9)
        hedge_otm = float(cfg.get("hedge_otm_pct", 1.0))
        hedged = bool(daily_closes) and (_up_days(daily_closes, 3) if cp == "P" else _up_days([-x for x in daily_closes], 3))
        rows = [p for p in prints if p.get("cp") == cp and p.get("side") == "ask" and (p.get("premium") or 0) > 0
                and now - p.get("t", 0) <= win and p.get("dte") is not None and p["dte"] <= max_dte
                and (p.get("otm_pct") is None or p["otm_pct"] >= 0.5)
                and not (hedged and p.get("otm_pct") is not None and p["otm_pct"] < hedge_otm)]
        usd = sum(p["premium"] for p in rows)
        w = 0.0
        n_deep = n_otm = 0
        for p in rows:
            o = p.get("otm_pct")
            f = 0.7 if o is None else 1.5 if o >= deep else 1.0 if o >= 0.5 else 0.4
            if o is not None and o >= deep:
                n_deep += 1
            elif o is not None and o >= 0.5:
                n_otm += 1
            if p.get("dte") is not None and p["dte"] <= 7:
                f *= 1.2
            w += p["premium"] * f
        recent = sum(p["premium"] for p in rows if now - p["t"] <= 300)
        before = sum(p["premium"] for p in rows if 300 < now - p["t"] <= 600)
        out[cp] = {"usd": round(usd), "w": round(w), "prints": len(rows), "deep": n_deep, "otm": n_otm,
                   "minutes": len({int(p["t"] // 60) for p in rows}),
                   "rising": recent > before and recent > 0, "recent": round(recent)}
    return out


def flow_state(fr, up, cfg):
    """NOT YET CONFIRMED / DEVELOPING / CONFIRMED / CONFLICTING for a move in this direction."""
    me, them = (fr["C"], fr["P"]) if up else (fr["P"], fr["C"])
    what = "calls" if up else "puts"
    other = "puts" if up else "calls"
    dev, conf = float(cfg.get("develop_premium", 50000)), float(cfg.get("confirm_premium", 250000))
    rep = int(cfg.get("confirm_repeats", 2))
    tag = ("deep OTM " if me["deep"] and me["deep"] >= me["otm"] else "OTM ") + what
    out = {"cp": "C" if up else "P", "usd": me["usd"], "against": them["usd"], "prints": me["prints"], "deep": me["deep"], "rising": me["rising"]}
    if them["w"] >= dev and them["w"] > me["w"] * 1.25:
        t_tag = ("deep OTM " if them["deep"] and them["deep"] >= them["otm"] else "") + other
        out.update(state="CONFLICTING", text=f"the flow is against it: {money(them['usd'])} of {t_tag} bought at the ask{' and still coming' if them['rising'] else ''}")
    elif me["w"] >= conf and me.get("minutes", me["prints"]) >= rep and me["w"] >= them["w"] * 1.5:
        out.update(state="CONFIRMED", text=f"{tag} scooped up again and again ({money(me['usd'])}, {me['prints']} prints). The dough is here: flow confirming")
    elif me["w"] >= dev:
        out.update(state="DEVELOPING", text=f"{tag} {'starting to come in' if me['rising'] else 'showing up'} ({money(me['usd'])}). The flow is starting, not confirmed yet")
    else:
        out.update(state="NOT YET CONFIRMED", text=f"no {what[:-1]} flow yet: no flow, no dough")
    return out


# ---- is price doing what the flow says? -------------------------------------------------------------------------

def response(mins, fr, pace, near, cfg):
    """The final test: price against the flow and the tape over the last few minutes. mins: [t0, o, h, l, c, v]."""
    look = int(cfg.get("response_minutes", 5))
    if len(mins) < 2:
        return None
    ref = mins[-min(len(mins), look + 1)][4]
    last = mins[-1][4]
    move = last - ref
    bull = flow_state(fr, True, cfg)
    bear = flow_state(fr, False, cfg)
    pc = pace or {}
    bp = pc.get("buy_pct")
    busy = (pc.get("ratio") or 0) >= 1.0
    small = 0.25 * near
    if bear["state"] in ("DEVELOPING", "CONFIRMED") and move >= -small:
        return {"tone": "warn", "key": "bear_flow_no_resp", "text": "Puts coming in, but it's not breaking down: no follow-through"}
    if bull["state"] in ("DEVELOPING", "CONFIRMED") and move <= small:
        return {"tone": "warn", "key": "bull_flow_no_resp", "text": "Calls coming in, but it's not building: no follow-through"}
    if bp is not None and busy and bp <= 40 and move >= -small:
        return {"tone": "warn", "key": "sell_absorbed", "text": "Sellers hitting it and it won't go down: they're getting absorbed"}
    if bp is not None and busy and bp >= 60 and move <= small:
        return {"tone": "warn", "key": "buy_absorbed", "text": "Buyers paying up and it won't go up: they're getting absorbed"}
    if bull["state"] in ("DEVELOPING", "CONFIRMED") and move >= 2 * small:
        return {"tone": "bull", "key": "bull_resp", "text": f"It's building with the calls: +{move:.2f} in {look} min"}
    if bear["state"] in ("DEVELOPING", "CONFIRMED") and move <= -2 * small:
        return {"tone": "bear", "key": "bear_resp", "text": f"It's building down with the puts: {move:.2f} in {look} min"}
    return None


# ---- the running story -----------------------------------------------------------------------------------------

def tape_words(pace, up):
    """Buyers / sellers stepping up, the tape accelerating, or stalling — from the PACE OF TAPE read."""
    if not pace or pace.get("state") in (None, "QUIET", "WARMING UP"):
        return None
    bp, st, acc = pace.get("buy_pct"), pace.get("state"), pace.get("accel")
    fast = st in ("FAST", "SURGE") or acc == "SPEEDING UP"
    if fast and bp is not None and bp >= 60:
        return "Buyers stepping up" if up is not False else "Buyers pushing back"
    if fast and bp is not None and bp <= 40:
        return "Sellers stepping up" if up is not True else "Sellers pushing back"
    if st == "DRYING UP":
        return "Tape drying up"
    if st == "SLOW":
        return "Tape slowing"
    return None


def room_read(up, ctx, foc, points, zones, last, near, atr, cfg):
    """MEASURED POTENTIAL, Dan's way: price travels from one level to the next. Above the 50-day it is SUPPLY TO
    SUPPLY: the room up to the next supply overhead (a moving average, a prior high, your zone). Below it,
    DEMAND TO DEMAND: the room down to the next demand underneath. The room past the place being tested is the MP;
    measured against the daily ATR (THIN under mp_min_atr of an ATR)."""
    if up is None or last is None:
        return None
    start = max(last, foc["hi"]) if (foc and up) else min(last, foc["lo"]) if foc else last
    gap = near / 2.0
    obst = []
    for p in points:
        if p["kind"] == "inst":
            continue
        if (up and p["p"] > start + gap) or (not up and p["p"] < start - gap):
            obst.append((abs(p["p"] - last), p["p"], p["name"]))
    for z in zones:
        edge_ = z["lo"] if up else z["hi"]
        if (up and edge_ > start + gap) or (not up and edge_ < start - gap):
            obst.append((abs(edge_ - last), edge_, z["short"]))
    frame = "supply to supply" if up else "demand to demand"
    with50 = bool(ctx and ctx.get("bias") and (ctx["bias"] == "bull") == up)
    if not obst:
        return {"frame": frame, "with50": with50, "to": None, "name": "open air: nothing in the way", "dollars": None, "atr_x": None, "thin": False,
                "text": f"{frame.capitalize()}: open air {'above' if up else 'below'}, no {'supply' if up else 'demand'} in the way"}
    d, p, nm = min(obst)
    ax = round(d / atr, 2) if atr else None
    thin = ax is not None and ax < float(cfg.get("mp_min_atr", 0.5))
    nxt = "supply" if up else "demand"
    return {"frame": frame, "with50": with50, "to": p, "name": nm, "dollars": round(d, 2), "atr_x": ax, "thin": thin,
            "text": f"{frame.capitalize()}: MP ${d:.2f} of airspace to the next {nxt}, {nm} {px(p)}" + (f" ({ax:g} ATR)" if ax is not None else "")
                    + (" — THIN, not enough airspace" if thin else "") + ("" if with50 else " · against the 50-day framework")}


def edge_read(up, ctx, foc, se_state, pace, reloads, consumed, fs, resp, last, near, room=None):
    """THE EDGE: seven independent reads, each asked the same question: does it agree with this move?
    DAILY (the 50-day framework, and the 200-day on the right side) · PS60 (a PS60 place, or the 2nd entry live) ·
    LOCATION (a major confluence: levels, moving averages, a zone together) · TAPE (fast, and the aggressive shares on
    this side) · LEVEL II (an x.00 / x.50 reloader with you, or the one against you consumed) · FLOW (short-dated OTM
    flow on this side, CONFIRMED; DEVELOPING counts half) · PRICE (responding the way the flow says).
    ROOM (the measured potential to the next supply / demand, not THIN against the ATR).
    It counts agreement, it does not invent odds: all but one agreeing is HIGH PROBABILITY, more than half BUILDING."""
    if up is None or not foc:
        return None
    side = "LONG" if up else "SHORT"
    checks = []

    def add(k, ok, why):
        checks.append({"k": k, "ok": ok, "why": why})
    c = ctx or {}
    if c.get("bias"):
        with50 = (c["bias"] == "bull") == up
        s200 = c.get("sma200")
        with200 = s200 is None or ((last >= s200) == up)
        add("DAILY", with50 and with200, ("with the 50-day" if with50 else "against the 50-day")
            + ("" if s200 is None else (", right side of the 200-day" if with200 else ", wrong side of the 200-day")))
    else:
        add("DAILY", None, "no 50-day yet")
    cf = foc.get("conf") or {}
    ps60 = foc["kind"] in PS60_KINDS or bool(cf.get("ps60")) or se_state == "SECOND_ENTRY"
    add("PS60", ps60, "at a PS60 place" + (" · 2nd entry live" if se_state == "SECOND_ENTRY" else "") if ps60 else "no PS60 place here")
    major = bool(cf.get("major"))
    add("LOCATION", major, (f"major confluence ({len(cf.get('members') or [])} together"
                            + (f", {len(cf['mas'])} moving averages" if cf.get("mas") else "") + ")") if major
        else "a single level" if not cf else "confluence, not major")
    pc = pace or {}
    bp = pc.get("buy_pct")
    fast = pc.get("state") in ("FAST", "SURGE") or pc.get("accel") == "SPEEDING UP"
    aligned = bp is not None and (bp >= 60 if up else bp <= 40)
    add("TAPE", bool(fast and aligned) if bp is not None else None,
        "no tape read yet" if bp is None else f"{pc.get('state', '').lower()}, {bp if up else 100 - bp}% {'buyers' if up else 'sellers'}")
    mine_side, their_side = ("bid", "ask") if up else ("ask", "bid")
    near_rl = [r for r in reloads if foc["lo"] - 2 * near <= r["price"] <= foc["hi"] + 2 * near]
    eaten = [c_ for c_ in consumed if c_["side"] == their_side]
    against = [r for r in near_rl if r["side"] == their_side]
    withme = [r for r in near_rl if r["side"] == mine_side]
    if eaten:
        add("LEVEL II", True, f"reload {'seller' if up else 'buyer'} at {px(eaten[0]['price'])} CLEANED UP")
    elif against:
        add("LEVEL II", False, f"reload {'seller' if up else 'buyer'} still sitting on {px(against[0]['price'])}")
    elif withme:
        add("LEVEL II", True, f"reload {'buyer' if up else 'seller'} holding {px(withme[0]['price'])}")
    else:
        add("LEVEL II", None, "no x.00 / x.50 reloader here")
    st_ = fs.get("state")
    add("FLOW", True if st_ == "CONFIRMED" else 0.5 if st_ == "DEVELOPING" else False,
        {"CONFIRMED": "option flow confirming", "DEVELOPING": "option flow developing", "CONFLICTING": "option flow against",
         "NOT YET CONFIRMED": "no option flow yet"}.get(st_, ""))
    if room is not None:
        add("ROOM", None if room["atr_x"] is None and room["to"] is not None else not room["thin"],
            room["text"].split(": ", 1)[-1] if room else "")
    want = "bull" if up else "bear"
    add("PRICE", None if not resp else resp["tone"] == want, "no clear response yet" if not resp else resp["text"].lower())
    score = sum(1.0 if c_["ok"] is True else 0.5 if c_["ok"] == 0.5 else 0.0 for c_ in checks)
    hard_no = any(c_["ok"] is False for c_ in checks if c_["k"] in ("FLOW", "LEVEL II", "PRICE")) and st_ == "CONFLICTING"
    n = len(checks)
    label = ("HIGH PROBABILITY" if score >= n - 1 and not hard_no else "BUILDING" if score >= n / 2 + 0.5 else "LOW")
    return {"side": side, "score": score, "of": len(checks), "label": label, "checks": checks}


class Story:
    """One symbol's running story: the moments, newest first, each said once."""

    def __init__(self, keep=60):
        self.feed = deque(maxlen=keep)
        self.said = {}            # topic -> (key, t)
        self.breaks = {}          # place name -> {"dir", "t", "p", "lo", "hi", "state"}
        self.memory = {}          # "C" / "P" -> {"t", "usd"}: unusual flow seen with no PS60 trigger
        self.side = {}            # place name -> last side of price ("above" / "below" / "in")
        self.day = None

    def say(self, topic, key, text, tone, t, repeat=600.0, gap=0.0):
        prev = self.said.get(topic)
        if prev and prev[0] == key and t - prev[1] < repeat:
            return False
        if prev and gap and t - prev[1] < gap:
            return False                          # this kind of call, whatever it says, at most once per gap
        k2 = topic.split(":")[0]
        last_kind = self.said.get("#" + k2)
        if last_kind and gap and t - last_kind[1] < gap:
            return False
        self.said["#" + k2] = (key, t)
        self.said[topic] = (key, t)
        text = text.rstrip() if text.rstrip().endswith((".", "!", "?")) else text.rstrip() + "."
        if self.feed and self.feed[0][1] == text:
            return False
        self.feed.appendleft([round(t, 1), text, tone, topic])
        return True


def build(sb, t, last, tick, atr, play, se_state, ctx, points, zones, conf, fr, pace, reloads, consumed, mins, cfg):
    """One read: the line for now, plus whatever new moments go on the feed. sb: the symbol's Story.
    reloads: qualifying reloaders [{price, side, stage, absorbed}] (x.00 / x.50 only). consumed: qualifying reloaders
    cleaned up in the last minute [{price, side}]."""
    out = {"ctx": ctx, "attention": False, "focus": None, "now": None, "tone": "neutral", "flow": None, "response": None, "edge": None, "room": None,
           "confluence": conf, "zones": zones, "reloads": reloads, "said": []}
    if last is None:
        return out
    day = studies.day_key(t)
    if sb.day != day:
        sb.day = day
        sb.breaks.clear()
        sb.side.clear()
    near = near_dist(last, atr, tick, cfg)
    said = out["said"]

    # how often each kind of moment may be said, whatever it says (a stock chopping around a level must not
    # call "cleared / lost / cleared" every few seconds)
    GAPS = {"break": 300.0, "flow": 240.0, "resp": 180.0, "maflow": 600.0, "fail": 600.0, "held": 600.0,
            "focus": 60.0, "room": 600.0, "reload": 120.0}

    def note(topic, key, text, tone, repeat=600.0, loud=False):
        if sb.say(topic, key, text, tone, t, repeat, GAPS.get(topic.split(":")[0], 0.0)) and loud:
            said.append({"topic": topic, "text": text, "tone": tone})

    if ctx and ctx.get("text"):
        note("ctx", (ctx.get("bias"), ctx.get("taken")), ctx["text"], "bull" if ctx.get("bias") == "bull" else "bear" if ctx.get("bias") == "bear" else "neutral",
             repeat=4 * 3600)
    # breaks and retests of every place (not only the nearest): who got through, who came back
    places = [(p["name"], p["p"], p["p"], p["kind"]) for p in points if p["kind"] not in ("inst",) + MA_PACK_KINDS] + \
             [(z["short"], z["lo"], z["hi"], "uzone") for z in zones]
    held, failed = {"up": [], "down": []}, {"up": [], "down": []}
    band = max(tick / 2, 0.25 * near)         # a break is a real move through the place, not a one-tick wiggle
    for name, lo, hi, kind in places:
        side = "above" if last > hi + band else "below" if last < lo - band else "in"
        # a break already on the books: is the retest holding, or did it fail? (before a new break replaces it)
        b = sb.breaks.get(name)
        if b and t - b["t"] <= float(cfg.get("retest_minutes", 30)) * 60:
            up = b["dir"] == "up"
            edge = hi if up else lo
            if b["state"] == "broke" and abs(last - edge) <= near and t - b["t"] >= 30:
                b["state"] = "retest"
            if b["state"] in ("broke", "retest") and ((up and last < lo - 0.3 * near) or (not up and last > hi + 0.3 * near)):
                b["state"] = "failed"                     # closed back through it
                failed[b["dir"]].append((name, round(b["t"])))
            elif b["state"] == "retest" and ((up and last >= edge + 0.6 * near) or (not up and last <= edge - 0.6 * near)):
                b["state"] = "held"
                held[b["dir"]].append((name, round(b["t"])))
        frm = sb.side.get(name)                  # the last side price was on (inside the place does not count)
        if side != "in":
            if frm == "below" and side == "above":
                sb.breaks[name] = {"dir": "up", "t": t, "lo": lo, "hi": hi, "state": "broke"}
            elif frm == "above" and side == "below":
                sb.breaks[name] = {"dir": "down", "t": t, "lo": lo, "hi": hi, "state": "broke"}
            sb.side[name] = side

    def names(rows):
        n = [r[0] for r in rows]
        return n[0] if len(n) == 1 else ", ".join(n[:-1]) + " and " + n[-1]
    for d_, rows in failed.items():
        if rows:
            note("fail:" + d_, tuple(rows), f"Back {'below' if d_ == 'up' else 'above'} {names(rows)}: failed break",
                 "warn", loud=True)
    for d_, rows in held.items():
        if rows:
            note("held:" + d_, tuple(rows), f"Held the retest of {names(rows)}. Watch the second entry back through the {'high' if d_ == 'up' else 'low'}",
                 "bull" if d_ == "up" else "bear", loud=True)

    foc = attention(points, zones, conf, last, near)
    out["focus"] = foc
    up = None
    if foc:
        # the move's direction: a fresh break of this place (still holding) says which way; otherwise the side it
        # is approached from; inside it, the Daily
        # a break of this place that held says which way, for the rest of the session; otherwise the Daily framework
        # decides (above the 50-day: long, supply to supply; below it: short, demand to demand); only with no Daily
        # read does the side price comes from decide
        br = sb.breaks.get(foc["name"])
        if br and br["state"] in ("broke", "retest", "held"):
            up = br["dir"] == "up"
        elif ctx and ctx.get("bias"):
            up = ctx["bias"] == "bull"
        elif foc["dir"] is not None:
            up = foc["dir"] == "up"
    if up is None and ctx and ctx.get("bias"):
        up = ctx["bias"] == "bull"
    fs = flow_state(fr, up if up is not None else True, cfg)
    out["flow"] = fs
    resp = response(mins, fr, pace, near, cfg)
    out["response"] = resp

    # unusual flow with no PS60 place in play: remember it, and say it once
    in_play = bool(foc and foc["approach"])
    ps60_on = bool(in_play and (foc["kind"] in PS60_KINDS or (foc.get("conf") or {}).get("ps60")))
    for cp in ("C", "P"):
        s = flow_state(fr, cp == "C", cfg)
        if s["state"] in ("DEVELOPING", "CONFIRMED") and not in_play:     # remembered only when nothing was in play
            m = sb.memory.get(cp)
            if m is None or t - m["t"] > 1800:
                sb.memory[cp] = {"t": t, "usd": s["usd"], "said_align": False}
            else:
                m["usd"] = max(m["usd"], s["usd"])
            what = "calls" if cp == "C" else "puts"
            note("memory:" + cp, "seen", f"Unusual OTM {what} detected ({money(s['usd'])}). No immediate PS60 trigger. Watching", "neutral", repeat=1800)
    mem_win = float(cfg.get("memory_minutes", 120)) * 60
    if ps60_on and up is not None:
        cp = "C" if up else "P"
        m = sb.memory.get(cp)
        if m and t - m["t"] <= mem_win and t - m["t"] >= 120 and not m.get("said_align"):
            m["said_align"] = True
            note("align:" + foc["name"], cp, f"Earlier OTM {'call' if up else 'put'} activity ({money(m['usd'])}, {_hm(m['t'])}) now aligning with {foc['name']}",
                 "bull" if up else "bear", loud=True)

    if not foc or not foc["approach"]:
        sb.said["att"] = (False, t)
        out["now"] = (f"Watching. Nearest: {foc['name']} {px(foc['p']) if foc['kind'] != 'uzone' else ''}".rstrip()
                      + f", ${foc['d']:.2f} away." if foc else (ctx or {}).get("text") or "Waiting for price to come to a PS60 place.")
        out["tone"] = "neutral"
        if resp:
            note("resp", resp["key"], resp["text"], resp["tone"], repeat=300)
        return out

    out["attention"] = bool(foc["on"])
    cf = foc.get("conf") if foc.get("conf") and foc["conf"].get("major") else None
    where = cf["text"].split(":")[0] if cf else foc["name"]
    lvl = None if cf or foc["kind"] == "uzone" else foc["p"]
    at = f" at {px(lvl)}" if lvl is not None else ""
    br = sb.breaks.get(foc["name"])
    fresh_break = bool(br and t - br["t"] <= 120 and br["state"] == "broke")
    parts = []
    if fresh_break:
        verb = (("reclaimed" if br["dir"] == "up" else "lost") if foc["kind"] in MA_KINDS
                else ("cleared" if br["dir"] == "up" else "lost") if foc["kind"] in ("pdh", "pwh", "mh", "yh", "pdl", "pwl", "ml", "yl")
                else ("breaking" if br["dir"] == "up" else "breaking down"))
        head = f"{where} {verb}"
        tone = "bull" if br["dir"] == "up" else "bear"
    elif br and br["state"] in ("broke", "retest", "held") and t - br["t"] <= float(cfg.get("retest_minutes", 30)) * 60:
        head = f"{'Holding above' if br['dir'] == 'up' else 'Holding below'} {where[0].lower() + where[1:] if where.startswith('Major') else where}" + (" on the retest" if br["state"] == "retest" else "")
        tone = "bull" if br["dir"] == "up" else "bear"
    elif foc["on"]:
        head = f"Testing {where[0].lower() + where[1:] if where.startswith('Major') else where}{at}"
        tone = "neutral"
    else:
        head = f"Coming into {where[0].lower() + where[1:] if where.startswith('Major') else where}{at}"
        tone = "neutral"
    parts.append(head[0].upper() + head[1:])
    tw = tape_words(pace, up)
    if tw:
        parts.append(tw)
    # the reloaders at this place (only x.00 / x.50 count)
    at_rl = [r for r in reloads if foc["lo"] - near <= r["price"] <= foc["hi"] + near]
    for r in at_rl[:1]:
        who = "seller" if r["side"] == "ask" else "buyer"
        inst = inst_name(r["price"])
        parts.append(f"Reload {who} sitting on the {inst} {px(r['price'])}")
        note("reload:" + str(r["price"]) + r["side"], r.get("stage") or "RELOADING",
             f"{head[0].upper() + head[1:]}. Reload {who} on the {inst} {px(r['price'])}: {'supply' if who == 'seller' else 'demand'} sitting on it", "warn", loud=True)
        bp = (pace or {}).get("buy_pct")
        if bp is not None and ((who == "seller" and bp >= 60) or (who == "buyer" and bp <= 40)):
            parts.append(f"{'Buyers keep lifting' if who == 'seller' else 'Sellers keep hitting'} {px(r['price'])} and the {who} keeps reloading")
    for c in consumed:
        if foc["lo"] - near <= c["price"] <= foc["hi"] + near:
            who = "seller" if c["side"] == "ask" else "buyer"
            bit = (f"Reload {who} CLEANED UP at {px(c['price'])}. {foc['name'][0].upper() + foc['name'][1:]} "
                   f"{'breaking' if who == 'seller' else 'breaking down'}")
            parts.insert(0, bit)
            note("consumed:" + str(c["price"]), c["side"], bit + (f". {fs['text'][0].upper() + fs['text'][1:]}" if fs["state"] in ("CONFIRMED", "DEVELOPING") else ""),
                 "bull" if who == "seller" else "bear", loud=True)
            tone = "bull" if who == "seller" else "bear"
    # the flow, said with the place
    loc = f" as it {'comes into' if not foc['on'] else 'tests'} {foc['name']}" if not fresh_break and not (br and br["state"] in ("retest", "held")) else ""
    ftext = fs["text"]
    if fs["state"] == "NOT YET CONFIRMED":
        parts.append(ftext[0].upper() + ftext[1:])
    else:
        parts.append(ftext[0].upper() + ftext[1:] + (loc if fs["state"] != "CONFIRMED" else ""))
    if fs["state"] == "CONFLICTING":
        tone = "warn"
    elif fs["state"] == "CONFIRMED" and tone == "neutral":
        tone = "bull" if up else "bear"
    if resp:
        parts.append(resp["text"])
        if resp["tone"] == "warn":
            tone = "warn"
    out["now"] = ". ".join(p for p in parts if p) + "."
    out["tone"] = tone
    # the moments that go on the feed: the big one (a reload consumed, a break) says it all; the place itself only
    # when nothing bigger was said about it this second
    loud_now = bool(said)
    if fresh_break and t - br["t"] <= 5 and not any(x["topic"].startswith("consumed:") for x in said):
        note("break:" + foc["name"], (br["dir"], round(br["t"])), parts[0] + f". {ftext[0].upper() + ftext[1:]}.", tone, loud=True)
        loud_now = True
    first_on = foc["on"] and not sb.said.get("att", (None,))[0]
    sb.said["att"] = (bool(foc["on"]), t)
    if not loud_now and (first_on or t - sb.said.get("focus", (None, -1e9))[1] >= 60):
        note("focus", (head.split(" ")[-1] if foc["on"] else "near", foc["name"]), parts[0] + (f". {tw}" if tw and not foc["on"] else "") + ".", "neutral", repeat=900)
    ma = foc if foc["kind"] in MA_KINDS else next((m for m in points if m["kind"] in MA_KINDS and foc["lo"] - near <= m["p"] <= foc["hi"] + near), None)
    if ma and fs["state"] != "NOT YET CONFIRMED":
        # the 50 / 200 day with the option flow: the moment the money shows up at the line the big money watches
        note("maflow:" + ma["kind"], fs["state"] + fs["cp"],
             f"{ftext[0].upper() + ftext[1:]} at the {ma['name']} {px(ma['p'])} ({'testing it' if foc['on'] else 'coming into it'})",
             "warn" if fs["state"] == "CONFLICTING" else ("bull" if up else "bear"), repeat=900, loud=True)
    note("flow", (fs["state"], fs["cp"]), f"{ftext[0].upper() + ftext[1:]}{loc}.", "warn" if fs["state"] == "CONFLICTING" else
         ("bull" if up else "bear") if fs["state"] in ("CONFIRMED", "DEVELOPING") else "neutral",
         repeat=600, loud=fs["state"] in ("CONFIRMED", "CONFLICTING"))
    if resp:
        note("resp", resp["key"], resp["text"] + ".", resp["tone"], repeat=300)
    rm = room_read(up, ctx, foc, points, zones, last, near, atr, cfg)
    out["room"] = rm
    if rm:
        note("room", (rm["frame"], rm["name"], rm["thin"]), rm["text"] + ".", "warn" if rm["thin"] else "neutral", repeat=1800)
    eg = edge_read(up, ctx, foc, se_state, pace, reloads, consumed, fs, resp, last, near, rm)
    out["edge"] = eg
    if eg and eg["label"] == "HIGH PROBABILITY":
        agree = ", ".join(c_["k"].lower() for c_ in eg["checks"] if c_["ok"] is True)
        note("edge:" + eg["side"], round(eg["score"] * 2),
             f"HIGH PROBABILITY {eg['side']} at {where}: {agree} all agree ({eg['score']:g} of {eg['of']})",
             "bull" if up else "bear", repeat=900, loud=True)
    return out


def _hm(t):
    try:
        d = studies.ny(t)
        return d.strftime("%-I:%M")
    except Exception:
        return ""
