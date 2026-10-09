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
    RELOADS        -> every confirmed reload buyer / seller counts; a whole / half dollar only gets a gold star
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


def round_tag(p):
    """A gold star on a whole / half dollar (x.00 / x.50): a highlight, never a rule."""
    return " ★" if qualifies(p) else ""


def sh(n):
    return f"{int(round(n or 0)):,}"


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
    """Dan's moving averages exactly as the chart draws them (SMA and EMA 5/10/20/50/100/150/200 on the daily and the
    60-minute, the 34/65/89 EMA on the daily only), the same Pine-exact numbers the chart and AIRSPACE use. They join a confluence (a pivot sitting on the
    60m 200 EMA), they never switch HIGH ATTENTION on alone (the 50 / 200-day are their own places)."""
    out = []
    for pack, tag, kind in ((daily_pack, "daily", "dma"), (h60_pack, "60m", "hma")):
        for nm, v in pack or []:
            if v is None or not nm.startswith(("EMA ", "SMA ")):
                continue
            if kind == "dma" and nm in ("SMA 50", "SMA 200"):
                continue
            if kind == "hma" and nm in ("EMA 34", "EMA 65", "EMA 89"):
                continue                          # the 34 / 65 / 89 EMA are on the daily chart only
            n, typ = nm.split(" ")[1], nm.split(" ")[0]
            out.append({"p": float(v), "name": f"{tag} {n} {typ}", "kind": kind})
    return out


# ---- THE MOVING-AVERAGE FRAMEWORK: who controls the 5, the 10 is the birth of the trade, rising 60-minute support ---

def _ma(pack, nm):
    return next((float(v) for n, v in (pack or []) if n == nm and v is not None), None)


def ma_framework(dpack, dprev, hpack, hprev, last, cfg):
    """Dan's read of the averages. The 50-day says bullish or bearish territory (the Daily context). Whoever controls
    the daily 5 controls the short-term sentiment; the 10 is the birth of the trade. Strong plays come into RISING
    60-minute support, the 60m 5 and 10: in an uptrend wait for the 60-minute retrace into them to buy (falling
    60-minute resistance to short, the reverse). dprev / hprev: the packs one bar back (are they rising?)."""
    if last is None:
        return None
    dt, ht = cfg.get("fw_daily_type", "SMA"), cfg.get("fw_60m_type", "SMA")
    d5, d10 = _ma(dpack, f"{dt} 5"), _ma(dpack, f"{dt} 10")
    h5, h10 = _ma(hpack, f"{ht} 5"), _ma(hpack, f"{ht} 10")
    h5p, h10p = _ma(hprev, f"{ht} 5"), _ma(hprev, f"{ht} 10")
    out = {"d5": d5, "d10": d10, "h5": h5, "h10": h10, "five": None, "ten": None, "h60": None, "zone": None, "bits": []}
    if d5 is not None:
        out["five"] = "buyers" if last > d5 else "sellers"
        out["bits"].append(f"{'Buyers' if last > d5 else 'Sellers'} control the 5-day ({px(d5)}): short-term sentiment {'bullish' if last > d5 else 'bearish'}")
    if d10 is not None:
        out["ten"] = "over" if last > d10 else "under"
        out["bits"].append(f"{'Over' if last > d10 else 'Under'} the 10-day ({px(d10)}): " + ("the long trade is born" if last > d10 else "the short trade is born"))
    if None not in (h5, h10, h5p, h10p):
        lo, hi = min(h5, h10), max(h5, h10)
        out["zone"] = (round(lo, 4), round(hi, 4))
        if h5 > h5p and h10 > h10p and h5 >= h10:
            out["h60"] = "rising"
            out["bits"].append(f"Rising 60-minute support at the 60m 5 / 10 ({px(h5)} / {px(h10)}): wait for the 60-minute retrace into it to buy")
        elif h5 < h5p and h10 < h10p and h5 <= h10:
            out["h60"] = "falling"
            out["bits"].append(f"Falling 60-minute resistance at the 60m 5 / 10 ({px(h5)} / {px(h10)}): wait for the 60-minute pop into it to short")
        else:
            out["h60"] = "flat"
            out["bits"].append(f"60m 5 / 10 ({px(h5)} / {px(h10)}) flat and tangled: no clean 60-minute trend")
    out["text"] = ". ".join(out["bits"])
    return out


def _ma_list(v):
    return [x.strip().upper() for x in (v.split(",") if isinstance(v, str) else (v or [])) if x.strip()]


def key_mas(dpack, hpack, cfg):
    """The averages whose reactions get called out (SETTINGS > PS60 story): exactly the chart's. SMA and EMA 5 / 10 /
    20 / 50 / 100 / 150 / 200 on the daily and the 60m, plus the 34 / 65 / 89 EMA on the daily only."""
    out = []
    for pack, tag, names in ((dpack, "daily", _ma_list(cfg.get("fw_daily_mas", "SMA 5, SMA 10, SMA 20, SMA 50, SMA 100, SMA 150, SMA 200, EMA 5, EMA 10, EMA 20, EMA 50, EMA 100, EMA 150, EMA 200, EMA 34, EMA 65, EMA 89"))),
                             (hpack, "60m", _ma_list(cfg.get("fw_60m_mas", "SMA 5, SMA 10, SMA 20, SMA 50, SMA 100, SMA 150, SMA 200, EMA 5, EMA 10, EMA 20, EMA 50, EMA 100, EMA 150, EMA 200")))):
        for nm in names:
            v = _ma(pack, nm)
            if v is None:
                continue
            typ, n = nm.split(" ")
            label = (f"{n}-day" if typ == "SMA" else f"daily {n} EMA") if tag == "daily" else f"60m {n} {typ}"
            out.append({"p": v, "name": label, "tf": tag, "n": int(n), "typ": typ})
    return out


def merge_mas(mas, band):
    """Averages sitting on top of each other are one place: '5-day / 60m 20 SMA'."""
    out = []
    for m in sorted(mas, key=lambda x: x["p"]):
        if out and abs(m["p"] - out[-1]["p"]) <= band:
            o = out[-1]
            o["name"] = o["name"] + " / " + m["name"]
            o["p"] = (o["p"] * o["k"] + m["p"]) / (o["k"] + 1)
            o["k"] += 1
        else:
            out.append(dict(m, k=1))
    return out


MA_WORDS = {
    "bounce": ["Bounce off the {nm} {p}. Demand held: technical buyers meeting emotional sellers{room}",
               "Buyers defended the {nm} {p}, that's demand. Bounced off it{room}",
               "{nm} {p} held as demand. Nice bounce{room}"],
    "reject": ["Rejected at the {nm} {p}. That's supply: technical sellers meeting emotional buyers{room}",
               "Sellers defended the {nm} {p}, supply did its job. Rejected{room}",
               "{nm} {p} turned it away. Supply{room}"],
    "through_up": ["Closed over the {nm} {p}. That supply is taken, next supply up{room}",
                   "Buyers closed it over the {nm} {p}. Supply to supply from here{room}"],
    "through_dn": ["Closed under the {nm} {p}. That demand is lost, next demand down{room}",
                   "Sellers closed it under the {nm} {p}. Demand to demand from here{room}"],
    "into": ["Coming into the {nm} {p}, {what}. Let's see if it {test}",
             "Price working into the {nm} {p}: {what}. Watch for {test2}"],
}
MA_TURN = {}


def ma_watch(sb, t, last, near, mas, cl, cl_t, all_points, cfg):
    """How price REACTS at each key moving average, daily and 60-minute: coming into it, the BOUNCE off it (demand
    held), the REJECT at it (supply held), or a CLOSE through it (taken). Returns [(kind, ma, text)] due now."""
    w = sb.__dict__.setdefault("maw", {})
    out = []

    def pick(kind, **kw):
        i = MA_TURN.get(kind, 0)
        MA_TURN[kind] = i + 1
        return MA_WORDS[kind][i % len(MA_WORDS[kind])].format(**kw)

    def room(up, frm):
        """Supply to supply / demand to demand: the next average or level past this one, and the MP to it."""
        nxt = [(abs(q["p"] - last), q) for q in all_points if (q["p"] > frm + near / 2 if up else q["p"] < frm - near / 2)]
        if not nxt:
            return f". Open air {'above' if up else 'below'}"
        d, q = min(nxt, key=lambda x: x[0])
        return f". Next {'supply' if up else 'demand'}: {q['name']} {px(q['p'])}, MP ${d:.2f}"
    away = max(near, 0.0)
    for m in mas:
        k = m["name"]
        s_ = w.setdefault(k, {"side": None, "touch": None, "said": -1e9})
        d = last - m["p"]
        side = "above" if d > near * 0.25 else "below" if d < -near * 0.25 else "at"
        if s_["touch"] is None and side != "at" and abs(d) <= near and s_["side"] == side and t - s_["said"] > float(cfg.get("ma_repeat_seconds", 600)):
            s_["touch"] = {"t": t, "from": side, "said_into": False}
        if s_["touch"] is not None:
            tch = s_["touch"]
            if not tch["said_into"] and abs(d) <= near * 0.6:
                tch["said_into"] = True
                frm_above = tch["from"] == "above"
                out.append(("into", m, pick("into", nm=m["name"], p=px(m["p"]),
                                            what="demand under price" if frm_above else "supply over price",
                                            test="holds as demand or gets closed under" if frm_above else "holds as supply or gets closed over",
                                            test2="the bounce, or a close under it" if frm_above else "the reject, or a close over it")))
            closed_through = cl is not None and cl_t is not None and cl_t > tch["t"] and (
                (tch["from"] == "above" and cl < m["p"]) or (tch["from"] == "below" and cl > m["p"]))
            if closed_through:
                up = tch["from"] == "below"
                out.append(("through_up" if up else "through_dn", m, pick("through_up" if up else "through_dn", nm=m["name"], p=px(m["p"]), room=room(up, m["p"]))))
                s_["touch"] = None; s_["said"] = t
            elif side == tch["from"] and abs(d) >= away and tch["said_into"]:
                up = tch["from"] == "above"
                kind = "bounce" if up else "reject"
                out.append((kind, m, pick(kind, nm=m["name"], p=px(m["p"]), room=room(up, m["p"]))))
                s_["touch"] = None; s_["said"] = t
            elif t - tch["t"] > float(cfg.get("ma_touch_minutes", 20)) * 60:
                s_["touch"] = None
        if side != "at":
            s_["side"] = side
    return out


# ---- THE TRADE YOU'RE IN: the levels against your position --------------------------------------------------------

def h60_confirm(sb, t, h60, last):
    """Every 60-minute candle is confirmed by the next one: building over the prior 60-minute high confirms the long,
    under the prior low confirms the short. h60: the last 60-minute rows [t0, o, h, l, c, v] (the newest may be the one
    forming). Returns (side, text) the first time the forming candle does it, else None."""
    if not h60 or len(h60) < 2 or last is None:
        return None
    cur = h60[-1] if h60[-1][0] + 3600 > t else None
    prev = h60[-2] if cur is not None else h60[-1]
    cur_t = cur[0] if cur is not None else int(t // 3600) * 3600
    c = sb.__dict__.setdefault("h60c", {})
    if c.get("t0") != cur_t:
        c.clear(); c["t0"] = cur_t
    if last > prev[2] and not c.get("up"):
        c["up"] = True
        return ("up", f"Building over the prior 60-minute high {px(prev[2])}: the new 60-minute candle is confirming the long")
    if last < prev[3] and not c.get("dn"):
        c["dn"] = True
        return ("down", f"Building under the prior 60-minute low {px(prev[3])}: the new 60-minute candle is confirming the short")
    return None


SE_STEPS = (1.00, 0.50, 0.25, 0.10)


def second_entry_watch(sb, t, play, last, near, pb, se_state, cfg):
    """YOUR SECOND ENTRY: once you mark it, the desk walks price into it: how far away it is at each step (a dollar,
    50 cents, a quarter, a dime), who is stepping up as it gets there, and the moment price goes through it (the
    second entry is live: it should go now). Then the build. Returns [(kind, text)]."""
    se = play.get("second_entry")
    w = sb.__dict__.setdefault("sew", {})
    if not se:
        w.clear()
        return []
    se = float(se)
    long_ = play.get("side", "long") != "short"
    if w.get("se") != se:
        w.clear(); w["se"] = se; w["steps"] = set(); w["through"] = False
        d = (se - last) if long_ else (last - se)
        return [("set", f"Second entry marked at {px(se)}, {abs(d) * 100:.0f} cents {'away' if d > 0 else 'under price' if long_ else 'over price'}. "
                        f"Price has to go back through it on a new candle for the trade to be live. I'll walk you in")]
    out = []
    d = (se - last) if long_ else (last - se)                       # how far price still has to go, the trade's way
    if d > 0:
        # the smallest step price has reached that has not been said; the bigger ones are passed with it
        reached = [x for x in SE_STEPS if d <= x + 0.005]
        if reached:
            step = min(reached)
            if step not in w["steps"]:
                w["steps"].update(x for x in SE_STEPS if x >= step)
                lbl = "a dollar" if step == 1.0 else "50 cents" if step == 0.5 else "a quarter" if step == 0.25 else "a dime"
                tail = f". {pb['tail']}" if pb and pb.get("tail") else ""
                out.append(("near", f"Second entry {px(se)} is {lbl} away, price {px(last)}{tail}" + (". Get ready" if step <= 0.25 else "")))
        w["through"] = False
    elif not w.get("through"):
        w["through"] = True
        w["t_through"] = t
        tail = f". {pb['tail']}" if pb and pb.get("tail") else ""
        out.append(("through", f"Through the second entry {px(se)}, price {px(last)}. The second entry is live, it should go now{tail}. "
                               f"If it doesn't go in a couple of minutes, that's your answer"))
    if w.get("through") and se_state and se_state == "SECOND_ENTRY" and not w.get("build_said") and t - w.get("t_through", t) >= 60:
        w["build_said"] = True
        out.append(("build", f"Second entry {px(se)} building: price keeps improving {'up' if long_ else 'down'} from it. Stay with it"))
    return out


def trade_read(sb, t, trade, foc, last, near, pb, rm, cfg, pace=None, market=None, fr=None):
    """You're in a trade (the stock or its options): say it as you enter it (risk to the stop, the first level in
    your way, the MP), when price comes into a new level with your position on (who is stepping up there), and when
    price closes in on your stop or your target. Returns [(kind, text)] due now."""
    tr = sb.__dict__.setdefault("trade", {})
    if not trade:
        tr.clear()
        return []
    out = []
    long_ = trade["dir"] == "long"
    what = trade["what"]
    pnl = trade.get("pnl")
    pnl_s = "" if pnl is None else f", {'up' if pnl >= 0 else 'down'} ${abs(pnl):,.0f}"
    key = trade["key"]
    if tr.get("key") != key:
        fresh = tr.get("key") is None or (tr.get("key") or (None,))[0] != key[0]   # a new trade, not an add / a partial
        t0, p0 = (t, last) if fresh else (tr.get("t0", t), tr.get("p0", last))
        tr.clear(); tr["key"] = key; tr["t0"], tr["p0"] = t, last
        if not fresh:
            tr["t0"], tr["p0"], tr["paid"], tr["r57"] = t0, p0, True, True
        bits = [f"You're in: {what}{pnl_s}"]
        if trade.get("stop") is not None:
            bits.append(f"Stop {px(trade['stop'])}, {abs(last - trade['stop']) * 100:.0f} cents away")
        if foc:
            bits.append(f"First level {'up' if long_ else 'down'}: {foc['name']} {px(foc['p']) if foc['kind'] != 'uzone' else ''}".rstrip())
        if rm and rm.get("to") is not None:
            bits.append(f"MP ${rm['dollars']:.2f} to {rm['name']} {px(rm['to'])}" + (f", {rm['atr_x']:g} ATR" if rm.get("atr_x") is not None else "")
                        + (". That's thin for options, be careful" if rm.get("thin") else ". Good room"))
        elif rm:
            bits.append("Open air, no supply in the way" if long_ else "Open air, no demand in the way")
        out.append(("enter", ". ".join(bits)))
    if foc and foc.get("approach") and tr.get("lvl") != foc["name"]:
        tr["lvl"] = foc["name"]
        with_ = (foc["p"] >= last) == long_
        say = f"With your {'long' if long_ else 'short'} on, {'coming into' if not foc['on'] else 'right at'} {foc['name']} {px(foc['p']) if foc['kind'] != 'uzone' else ''}".rstrip()
        say += (f": that's {'supply' if long_ else 'demand'} in your way, it needs a close {'over' if long_ else 'under'} it" if with_
                else f": that's {'demand' if long_ else 'supply'} under your trade, it has to hold")
        if pb and pb.get("tail"):
            say += f". {pb['tail']}"
        out.append(("level", say + pnl_s.replace(", up", ". You're up").replace(", down", ". You're down")))
    ref = trade.get("entry") or tr.get("p0") or last
    fav = (last - ref) if long_ else (ref - last)               # how far it has moved your way, in the stock
    mins = (t - tr.get("t0", t)) / 60.0
    lo57, hi57 = float(cfg.get("rule57_min", 5)), float(cfg.get("rule57_max", 7))
    if not tr.get("r57") and lo57 <= mins <= hi57 + 1 and fav < max(near * 0.5, 0.05):
        tr["r57"] = True
        who = "seller" if long_ else "buyer"
        out.append(("r57", f"It's been {mins:.0f} minutes and it's not going your way. 5-7 minute rule: if it's stuck, there may be a reload {who} "
                           f"sitting there, and you never win a battle with a reload {who}. Think about taking the scratch"))
    elif mins > hi57 + 1:
        tr["r57"] = True
    first = float(cfg.get("first_move_dollars", 0.25))
    risk = abs(ref - trade["stop"]) if trade.get("stop") is not None else None
    stop_at_be = risk is not None and ((trade["stop"] >= ref) if long_ else (trade["stop"] <= ref))
    if not tr.get("paid") and not stop_at_be and fav >= max(first, risk or 0):
        tr["paid"] = True
        out.append(("pay", f"There's your first move, {fav * 100:.0f} cents your way{pnl_s}. Pay yourself: take a third or half off "
                           "and move your stop to breakeven. Free trade"))
    # in the trade and it's working: how much MP / airspace is left, keep you encouraged
    every = float(cfg.get("trade_update_seconds", 90))
    if rm and rm.get("dollars") is not None and fav > max(near * 0.25, 0.02) and t - tr.get("upd_t", -1e9) >= every:
        left = rm["dollars"]
        k_ = round(left / max(0.05, near * 0.5))
        if k_ != tr.get("upd_k"):
            tr["upd_t"], tr["upd_k"] = t, k_
            n_ = tr["upd_n"] = tr.get("upd_n", 0) + 1
            if rm.get("thin"):
                msg = (f"Moving your way{pnl_s}. Only ${left:.2f} of airspace left to {rm['name']} {px(rm['to'])}. "
                       + ("If it can't close through it, pay yourself there" if not rm.get("beyond") else
                          f"Get a close through it and there's ${rm['beyond']['dollars']:.2f} to {rm['beyond']['name']}"))
            else:
                enc = ("Stay patient", "Let it work", "You're doing fine, let it breathe", "Stay with the plan")[n_ % 4]
                msg = (f"{enc}. You've got ${left:.2f} of MP left to {rm['name']} {px(rm['to'])}"
                       + (f", {rm['atr_x']:g} ATR" if rm.get("atr_x") is not None else "") + f"{pnl_s}")
            out.append(("mp", msg))
    # PS60: a trade is managed at its levels, never on a pullback. This warning is for a COMPLETE BREAKDOWN only, and
    # it has to hold: the tape one-sided against you for minutes (not a dip), the market (SPY / QQQ) going the other
    # way, AND tremendous option flow on the other side. All three, held for trade_weak_seconds, before a word is said.
    # A pullback with the tape still two-way, or flow that is merely present, never gets you worked out of the trade
    pc = pace or {}
    bp = pc.get("buy_pct")
    fast = pc.get("state") in ("FAST", "SURGE") or pc.get("ratio", 0) and pc["ratio"] >= 1.3
    heavy = float(cfg.get("trade_weak_tape_pct", 75))
    tape_bad = bp is not None and fast and ((100 - bp >= heavy) if long_ else (bp >= heavy))
    mkt_bad = bool(market and market.get("dir") and (market["dir"] == "up") != long_)
    me, them = ((fr or {}).get("C") or {}, (fr or {}).get("P") or {}) if long_ else ((fr or {}).get("P") or {}, (fr or {}).get("C") or {})
    big = float(cfg.get("trade_weak_flow_min", 250000))
    opt_bad = (them.get("now_usd") or 0) >= big and (them.get("now_usd") or 0) >= 4 * (me.get("now_usd") or 0)
    if tape_bad and mkt_bad and opt_bad and fav > 0:
        tr.setdefault("weak_since", t)
        if t - tr["weak_since"] >= float(cfg.get("trade_weak_seconds", 180)) and t - tr.get("weak_t", -1e9) >= float(cfg.get("trade_weak_repeat_seconds", 600)):
            tr["weak_t"] = t
            what, other = ("puts", "calls") if long_ else ("calls", "puts")
            why = [f"{'sellers' if long_ else 'buyers'} own the tape, {100 - bp if long_ else bp:.0f}% and fast, for {(t - tr['weak_since']) / 60:.0f} minutes",
                   f"the market's going the other way ({market['text'].rstrip('.')})",
                   f"tremendous {what} flow: {versus(them.get('now_usd') or 0, me.get('now_usd') or 0, what, other)}"]
            mp_s = f" This is not a pullback, it may not make the MP to {rm['name']} {px(rm['to'])}." if rm and rm.get("to") is not None else " This is not a pullback."
            out.append(("weak", f"Heads up{pnl_s}: " + ", ".join(why) + "." + mp_s + " Think about paying yourself here"))
    else:
        tr.pop("weak_since", None)
    st_ = trade.get("stop")
    if st_ is not None:
        dist = abs(last - st_)
        warn = max(near, abs((trade.get("entry") or last) - st_) * 0.35)
        if dist <= warn and t - tr.get("stop_t", -1e9) > float(cfg.get("trade_repeat_seconds", 120)):
            tr["stop_t"] = t
            out.append(("stop", f"Getting close to your stop {px(st_)}, {dist * 100:.0f} cents away{pnl_s}. Know your plan"))
    tg = trade.get("target")
    if tg is not None and abs(last - tg) <= near and t - tr.get("tgt_t", -1e9) > float(cfg.get("trade_repeat_seconds", 120)):
        tr["tgt_t"] = t
        out.append(("target", f"Price is at your target {px(tg)}{pnl_s}. Pay yourself"))
    return out


# ---- STRUCTURE: higher highs / lower lows on the 60-minute and the daily, said in Dan's words --------------------

def structure_read(sb, t, h60, drows, live, last, fw, cfg):
    """Lower lows on the 60 (the 60-minute channel is stepping down: demand to demand), higher highs on the 60 (stepping
    up: supply to supply); on the Daily, a higher high or a lower low against the prior days (the brain of the
    trade). Each one said once when it happens. Returns [(kind, text)]."""
    st = sb.__dict__.setdefault("struct", {})
    out = []
    if h60 and len(h60) >= 3:
        cur = h60[-1] if h60[-1][0] + 3600 > t else None
        done = h60[:-1] if cur is not None else h60
        if len(done) >= 2:
            a, b = done[-2], done[-1]
            k60 = b[0]
            if st.get("h60_k") != k60:
                st["h60_k"] = k60
                if b[3] < a[3] and b[2] < a[2]:
                    n = st["ll"] = st.get("ll", 0) + 1; st["hh"] = 0
                    out.append(("ll60", f"Lower low on the 60-minute, {px(b[3])} under {px(a[3])}" + (f", {n} in a row" if n > 1 else "")
                                + ". The 60-minute channel is stepping down, demand to demand"
                                + (f". Next demand: {px(fw['h10'])}, the 60m 10" if fw and fw.get("h10") and fw["h10"] < last else "")))
                elif b[2] > a[2] and b[3] > a[3]:
                    n = st["hh"] = st.get("hh", 0) + 1; st["ll"] = 0
                    out.append(("hh60", f"Higher high on the 60-minute, {px(b[2])} over {px(a[2])}" + (f", {n} in a row" if n > 1 else "")
                                + ". The 60-minute channel is stepping up, supply to supply"))
    # intraday: the live 60-minute candle taking out the prior 60-minute low / high is said by h60_confirm; here the
    # DAILY: today's range against the prior days
    if drows and live and len(drows) >= 3:
        today, prev = drows[-1], drows[-2]
        hh_ref = max(r[2] for r in drows[-6:-1])
        ll_ref = min(r[3] for r in drows[-6:-1])
        dk = studies.day_key(t)
        if st.get("day") != dk:
            st["day"] = dk; st["dhh"] = st["dll"] = False
        if not st.get("dhh") and today[2] > hh_ref:
            st["dhh"] = True
            out.append(("hhD", f"Higher high on the Daily: {px(today[2])} takes out the last five days' high {px(hh_ref)}. "
                               "Daily supply taken, the Daily is building, supply to supply"))
        elif not st.get("dhh2") and today[2] > prev[2] and today[2] <= hh_ref:
            st["dhh2"] = True
            out.append(("hhD1", f"Over the prior-day high {px(prev[2])} on the Daily, higher high against yesterday. "
                                f"Next Daily supply: the five-day high {px(hh_ref)}"))
        if not st.get("dll") and today[3] < ll_ref:
            st["dll"] = True
            out.append(("llD", f"Lower low on the Daily: {px(today[3])} takes out the last five days' low {px(ll_ref)}. "
                               "Daily demand lost, the Daily is breaking down, demand to demand"))
        elif not st.get("dll2") and today[3] < prev[3] and today[3] >= ll_ref:
            st["dll2"] = True
            out.append(("llD1", f"Under the prior-day low {px(prev[3])} on the Daily, lower low against yesterday. "
                                f"Next Daily demand: the five-day low {px(ll_ref)}"))
    return out


def daily_brief(ctx, fw, rm_up, rm_dn, drows, live, atr, cfg):
    """The Daily, the brain of the trade, in one read: where we are against the 50-day, who controls the 5, the 10,
    the airspace both ways to the next Daily supply / demand (the averages, the prior highs / lows) against the ATR."""
    if not ctx or not ctx.get("bias"):
        return None
    bull = ctx["bias"] == "bull"
    bits = [ctx["text"].rstrip(".")]
    if fw and fw.get("bits"):
        bits += [b for b in fw["bits"] if "-day" in b]
    r = rm_up if bull else rm_dn
    if r:
        if r.get("to") is None:
            bits.append(f"Airspace {'above' if bull else 'below'} is clear: open air, no {'supply' if bull else 'demand'} in the way")
        else:
            bits.append(f"MP ${r['dollars']:.2f} to the next {'supply' if bull else 'demand'}, {r['name']} {px(r['to'])}"
                        + (f", {r['atr_x']:g} ATR" if r.get("atr_x") is not None else "")
                        + (": THIN" if r.get("thin") else ": room to work"))
            if r.get("beyond"):
                bits.append(f"Through it there's ${r['beyond']['dollars']:.2f} to {r['beyond']['name']}")
    other = rm_dn if bull else rm_up
    if other and other.get("to") is not None:
        bits.append(f"{'Demand' if bull else 'Supply'} {'under' if bull else 'over'} us: {other['name']} {px(other['to'])}, ${other['dollars']:.2f} away")
    if atr:
        bits.append(f"Daily ATR ${atr:.2f}")
    return ". ".join(bits) + "."


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
        r2 = [p for p in rows if now - p["t"] <= float(cfg.get("pbp_flow_seconds", 120))]
        recent = sum(p["premium"] for p in rows if now - p["t"] <= 300)
        before = sum(p["premium"] for p in rows if 300 < now - p["t"] <= 600)
        out[cp] = {"usd": round(usd), "w": round(w), "prints": len(rows), "deep": n_deep, "otm": n_otm,
                   "minutes": len({int(p["t"] // 60) for p in rows}),
                   "rising": recent > before and recent > 0, "recent": round(recent),
                   "now_usd": round(sum(p["premium"] for p in r2)), "now_prints": len(r2),
                   "now_big": _big(r2), "now_hot": _hot(r2, deep)}
    return out


def _big(rows):
    if not rows:
        return None
    b = max(rows, key=lambda p: p["premium"])
    return {"strike": b.get("strike"), "premium": b["premium"], "dte": b.get("dte"), "id": b.get("id")}


def versus(me_usd, them_usd, what, other):
    """Puts against calls in dollars, and how far one is out in front: 'puts $1.2M vs calls $300K, puts out in front
    by $900K, 4 to 1'."""
    me_usd, them_usd = float(me_usd or 0), float(them_usd or 0)
    if them_usd <= 0 < me_usd:
        return f"{what} {money(me_usd)}, no {other} against them"
    if me_usd <= 0 < them_usd:
        return f"{other} {money(them_usd)}, no {what}"
    head = f"{what} {money(me_usd)} vs {other} {money(them_usd)}"
    lead, lag, who = (me_usd, them_usd, what) if me_usd >= them_usd else (them_usd, me_usd, other)
    if lead <= 0:
        return head
    r = lead / lag
    if r < 1.2:
        return f"{head}, about even"
    ratio = f"{r:.0f} to 1" if r >= 3 else f"{r:.1f} to 1"
    return f"{head}, {who} out in front by {money(lead - lag)}, {ratio}"


def _hot(rows, deep):
    """The strike they keep coming for in the last couple of minutes: the most premium on one strike, how many
    separate prints, how far out of the money."""
    by = {}
    for p in rows:
        k = p.get("strike")
        if k is None:
            continue
        b = by.setdefault(k, {"strike": k, "usd": 0.0, "prints": 0, "otm": p.get("otm_pct"), "ids": []})
        b["usd"] += p["premium"]; b["prints"] += 1
        if p.get("id") is not None:
            b["ids"].append(p["id"])
    if not by:
        return None
    h = max(by.values(), key=lambda b: b["usd"])
    h["deep"] = h["otm"] is not None and h["otm"] >= deep
    h["usd"] = round(h["usd"])
    return h


HYPE = {
    "deep": ["Oh my God, they're coming for the {k}s! {n} prints on the {k} {what}, {usd} in two minutes, way out of the money",
             "Whoa, look at this, they're going after the {k} {what}! {usd}, {n} prints, deep out of the money",
             "Here they come! Somebody wants the {k}s, {usd} on the {k} {what}, {otm} out of the money"],
    "pound": ["Oh my God, they're pounding the {k}s non stop! {n} prints on the {k} {what}, {usd}",
              "They will not stop buying the {k}s! {n} prints, {usd} on the {k} {what}",
              "Again and again on the {k} {what}! {n} prints, {usd}. Somebody really wants these"],
}
HYPE_TURN = {}


def hype(fr, cfg):
    """The excitement: deep out-of-the-money calls / puts getting hit, or one strike pounded again and again, in the
    last couple of minutes. Returns {"cp", "kind", "key", "text"} or None."""
    best = None
    for cp in ("C", "P"):
        h = ((fr or {}).get(cp) or {}).get("now_hot")
        if not h or h["usd"] < float(cfg.get("hype_min_premium", 75000)):
            continue
        pound = h["prints"] >= int(cfg.get("hype_pound_prints", 4))
        if not (h["deep"] or pound):
            continue
        if best is None or h["usd"] > best[1]["usd"]:
            best = (cp, h, "pound" if pound else "deep")
    if not best:
        return None
    cp, h, kind = best
    i = HYPE_TURN.get(kind, 0)
    HYPE_TURN[kind] = i + 1
    k = f"{float(h['strike']):g}"
    text = HYPE[kind][i % len(HYPE[kind])].format(k=k, n=h["prints"], what="calls" if cp == "C" else "puts", usd=money(h["usd"]),
                                                  otm=f"{h['otm']:.0f}%" if h.get("otm") is not None else "way")
    # said again only when it grows: a new key every doubling of the money / every 3 more prints
    return {"cp": cp, "kind": kind, "strike": h["strike"], "ids": h.get("ids") or [], "text": text,
            "key": (cp, h["strike"], kind, int(h["usd"] // max(1.0, float(cfg.get("hype_min_premium", 75000)))).bit_length(), h["prints"] // 3)}


def flow_state(fr, up, cfg):
    """NOT YET CONFIRMED / DEVELOPING / CONFIRMED / CONFLICTING for a move in this direction."""
    me, them = (fr["C"], fr["P"]) if up else (fr["P"], fr["C"])
    what = "calls" if up else "puts"
    other = "puts" if up else "calls"
    dev, conf = float(cfg.get("develop_premium", 50000)), float(cfg.get("confirm_premium", 250000))
    rep = int(cfg.get("confirm_repeats", 2))
    tag = ("deep OTM " if me["deep"] and me["deep"] >= me["otm"] else "OTM ") + what
    out = {"cp": "C" if up else "P", "usd": me["usd"], "against": them["usd"], "prints": me["prints"], "deep": me["deep"], "rising": me["rising"]}
    vs = versus(them["usd"], me["usd"], other, what) if them["usd"] >= me["usd"] else versus(me["usd"], them["usd"], what, other)
    out["versus"] = vs
    if them["w"] >= dev and them["w"] > me["w"] * 1.25:
        t_tag = ("deep OTM " if them["deep"] and them["deep"] >= them["otm"] else "") + other
        out.update(state="CONFLICTING", text=f"the flow is against it: {money(them['usd'])} of {t_tag} bought at the ask{' and still coming' if them['rising'] else ''} ({vs})")
    elif me["w"] >= conf and me.get("minutes", me["prints"]) >= rep and me["w"] >= them["w"] * 1.5:
        out.update(state="CONFIRMED", text=f"{tag} scooped up again and again ({money(me['usd'])}, {me['prints']} prints; {vs}). The dough is here: flow confirming")
    elif me["w"] >= dev:
        out.update(state="DEVELOPING", text=f"{tag} {'starting to come in' if me['rising'] else 'showing up'} ({money(me['usd'])}; {vs}). The flow is starting, not confirmed yet")
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


# ---- PLAY-BY-PLAY: at the place, who is doing what right now -----------------------------------------------------

PBP_OPEN = {
    "on": ["Right on {nm}", "Sitting on {nm}", "At {nm}", "Price on {nm}"],
    "near": ["Coming into {nm}", "Closing in on {nm}", "Working toward {nm}", "Getting near {nm}"],
}
PBP_READ = {
    "defend": ["buyers are defending it", "buyers are holding the line", "demand is showing up at the level"],
    "press_sup": ["sellers are pressing it, the level is in danger", "sellers leaning on it, watch for the break down",
                  "buyers are not stepping in, it could give way"],
    "press_res": ["buyers are leaning on it, watch for the break", "buyers pushing into it, it could give way",
                  "buyers keep coming at it"],
    "reject": ["sellers are defending it", "sellers are turning it away", "supply is showing up at the level"],
    "mixed": ["tape and options disagree, let it show its hand", "mixed signals, no side has it yet",
              "it's a fight, wait for one side to win"],
    "quiet": ["nobody is committing yet", "quiet at the level, no side stepping up", "waiting on a side to show up"],
}


def play_by_play(sb, t, foc, last, near, pace, fr, reloads, consumed, cfg):
    """What is happening at the place right now, said like a play-by-play: where price is against the place, who is
    stepping up on the tape, the reload buyer / seller sitting there, and the calls / puts being bought at the ask in the
    last couple of minutes, then what it adds up to. Returns {"key", "text", "tone"} or None (no place in play)."""
    if not foc or not foc.get("approach") or last is None:
        return None
    nm = foc["name"] + (f" {px(foc['p'])}" if foc["kind"] != "uzone" else "")
    lo, hi = foc["lo"], foc["hi"]
    if last > hi:
        pos, d = "above", last - hi
    elif last < lo:
        pos, d = "below", lo - last
    else:
        pos, d = "on", 0.0
    # the side price CLOSED on: above the place it is support, below it resistance. Trading through it without a
    # candle close there does not change that
    closed_side = sb.side.get(foc["name"])
    if closed_side not in ("above", "below"):
        closed_side = pos if pos != "on" else ("above" if foc.get("dir") == "down" else "below")
    sup = closed_side == "above"
    n = sb.__dict__.setdefault("pbp_turn", {})

    def pick(kind, opts):
        i = n.get(kind, 0)
        n[kind] = i + 1
        return opts[i % len(opts)]
    head = pick("open_" + ("on" if foc["on"] else "near"), PBP_OPEN["on" if foc["on"] else "near"]).format(nm=nm)
    c_n = round(d * 100)
    cents = (f"{c_n} cent" + ("" if c_n == 1 else "s")) if d < 1 else f"${d:.2f}"
    where = f"price {px(last)}, " + ("right on it" if pos == "on" or d < 0.005 else f"{cents} {'over' if pos == 'above' else 'under'} it")
    if pos in ("above", "below") and pos != closed_side:
        where += f", no close {'under' if pos == 'below' else 'over'} it yet"
    bits = []
    # the tape
    pc = pace or {}
    bp, st = pc.get("buy_pct"), pc.get("state")
    tape = 0
    fast = st in ("FAST", "SURGE") or pc.get("accel") == "SPEEDING UP"
    if bp is not None and st not in (None, "QUIET", "WARMING UP"):
        if bp >= 60:
            tape = 1
            bits.append(f"buyers stepping up, {bp:.0f}% of the tape lifting the offer" + (" and speeding up" if fast else ""))
        elif bp <= 40:
            tape = -1
            bits.append(f"sellers stepping up, {100 - bp:.0f}% of the tape hitting the bid" + (" and speeding up" if fast else ""))
        else:
            bits.append("two-way tape, buyers and sellers trading even")
    elif st in ("QUIET", "DRYING UP", "SLOW"):
        bits.append("the tape is quiet")
    # the book at the place
    book = 0
    for c in consumed:
        if lo - near <= c["price"] <= hi + near:
            who = "seller" if c["side"] == "ask" else "buyer"
            bits.append(f"the {who} at {px(c['price'])} is CLEANED UP")
            book = 1 if who == "seller" else -1
            break
    else:
        for r in reloads:
            if lo - near <= r["price"] <= hi + near:
                who = "seller" if r["side"] == "ask" else "buyer"
                stg = r.get("stage") or "RELOADING"
                ab = r.get("absorbed")
                bits.append(f"reload {who} at {px(r['price'])} {stg}" + (f", {sh(ab)} shares traded into him" if ab else ""))
                book = -1 if who == "seller" else 1
                break
    # the options in the last couple of minutes
    c_, p_ = (fr or {}).get("C") or {}, (fr or {}).get("P") or {}
    cu, pu = c_.get("now_usd") or 0, p_.get("now_usd") or 0
    small = float(cfg.get("pbp_flow_min", 25000))
    opt = 0

    def big(x, what):
        b = x.get("now_big")
        return f" (biggest {fmt_strike(b['strike'])} {what[:-1]} {money(b['premium'])})" if b and b.get("strike") else ""
    if max(cu, pu) >= small:
        if cu >= 2 * pu:
            opt = 1
            bits.append(f"calls being bought at the ask" + big(c_, "calls") + f": {versus(cu, pu, 'calls', 'puts')} in the last two minutes")
        elif pu >= 2 * cu:
            opt = -1
            bits.append(f"puts being bought at the ask" + big(p_, "puts") + f": {versus(pu, cu, 'puts', 'calls')} in the last two minutes")
        else:
            bits.append(f"calls and puts both getting bought: {versus(cu, pu, 'calls', 'puts') if cu >= pu else versus(pu, cu, 'puts', 'calls')}")
    else:
        bits.append("no real option flow in the last two minutes")
    votes = [v for v in (tape, book, opt) if v]
    score = sum(votes)
    if not votes:
        read, tone = "quiet", "neutral"
    elif len(set(votes)) > 1 and abs(score) < 2:
        read, tone = "mixed", "warn"
    elif score > 0:
        read, tone = ("defend" if sup else "press_res"), "bull"
    else:
        read, tone = ("press_sup" if sup else "reject"), "bear"
    rd = pick(read, PBP_READ[read])
    text = f"{head}: {where}. " + ". ".join(b[0].upper() + b[1:] for b in bits) + ". " + rd[0].upper() + rd[1:]
    key = (foc["name"], "on" if foc["on"] else "near", tape, book, opt, read)
    tail = ". ".join(b[0].upper() + b[1:] for b in bits if not b.startswith("no real option flow")) if read != "quiet" else ""
    return {"key": key, "text": text, "tone": tone, "read": read, "tail": tail}


COACH = {
    "pre": ["Premarket. Let's see the open before we get involved",
            "Still premarket, guys. Let the open show us something first",
            "It's premarket. Mark it, but let the bell set the tone"],
    "early": ["It's before 10. Let's give it until 10 o'clock to see what the market gives us",
              "Early in the session. Let's give it until 10 and see what the market wants to do",
              "Before 10 o'clock, things whip around. Let's give it some time and see what we get"],
    "first": ["This is the first pivot of the day. Let's get some more context",
              "First pivot of the day, guys. Let's see how it reacts before we lean on it",
              "First test of the pivot today. Let's get some more context first"],
    "patience": ["Stay patient, guys. Hang in there",
                 "Hang in there. Give it some time",
                 "No need to force it. Let it come to us",
                 "Stay patient. We wait for one side to show its hand",
                 "Give it some time, guys. The level will tell us"],
    "chop": ["This is choppy, guys. {x} No clean side. Sit on your hands",
             "Sloppy price action. {x} Let it clean up before we do anything",
             "Chop. {x} This is where accounts bleed, stay patient"],
    "clean_up": ["Clean price action. {x} Buyers in control",
                 "Nice and clean. {x} This is how a stock should act going up",
                 "That's clean. {x} Buyers own it right now"],
    "clean_down": ["Clean move down. {x} Sellers in control",
                   "Clean price action to the downside. {x} Sellers own it right now",
                   "That's clean selling. {x} No buyers stepping in"],
    "trapped": ["{who} are trapped. {x}",
                "Heads up, {who} got caught. {x}",
                "We've got trapped {who_l}. {x}"],
    "freed": ["The trapped {who_l} at {nm} are out. The break held",
              "{nm} break held. Whoever was trapped got out of jail",
              "No more trapped {who_l} at {nm}. That break held up"],
    "rl_buyer": ["There's a reload buyer at {p}, be careful guys. Don't go sticking your neck out on the short, wait till this guy is CLEANED UP",
                 "Reload buyer at {p}. Be careful guys, he keeps reloading. Wait till he's confirmed CLEANED UP before you go short",
                 "Careful, reload buyer sitting at {p}{ab}. Don't fight him. Wait for him to get CLEANED UP",
                 "Reload buyer at {p}, guys. Let's wait for this guy to get cleaned up"],
    "rl_seller": ["There's a reload seller at {p}, be careful guys. Don't go sticking your neck out on the long, wait till this guy is CLEANED UP",
                  "Reload seller at {p}. Be careful guys, he keeps reloading. Wait till he's confirmed CLEANED UP before you go long",
                  "Careful, reload seller sitting at {p}{ab}. Don't fight him. Wait for him to get CLEANED UP",
                  "Reload seller at {p}, guys. Let's wait for this guy to get cleaned up"],
    "rl_still_buyer": ["Reload buyer at {p} STILL THERE{ab}. Still not cleaned up, guys. Be patient",
                       "That buyer at {p} is STILL THERE, still reloading. Don't stick your neck out yet",
                       "Buyer at {p} STILL THERE. Let's wait for this guy to get cleaned up"],
    "rl_still_seller": ["Reload seller at {p} STILL THERE{ab}. Still not cleaned up, guys. Be patient",
                        "That seller at {p} is STILL THERE, still reloading. Don't stick your neck out yet",
                        "Seller at {p} STILL THERE. Let's wait for this guy to get cleaned up"],
    "rl_clean_buyer": ["The reload buyer at {p} is CLEANED UP! Sellers took him out. Now we've got something",
                       "There it is, the buyer at {p} is CLEANED UP. That's what we were waiting for"],
    "rl_clean_seller": ["The reload seller at {p} is CLEANED UP! Buyers took him out. Now we've got something",
                        "There it is, the seller at {p} is CLEANED UP. That's what we were waiting for"],
    "rl_pulled_buyer": ["The buyer at {p} PULLED his order. Not cleaned up, he just left. Careful, that's not the same thing"],
    "rl_pulled_seller": ["The seller at {p} PULLED his order. Not cleaned up, he just left. Careful, that's not the same thing"],
    "mkt_with": ["The market's with us. {x}",
                 "Market's on our side. {x}",
                 "Tailwind from the market. {x}"],
    "mkt_against": ["Careful, the market's going the other way. {x}",
                    "The market isn't helping here. {x}",
                    "Headwind from the market. {x} Be picky"],
}
COACH_TURN = {}          # kind -> how many times said, across every stock: two stocks never get the same line together


def price_action(mins, level, n=8):
    """Clean or choppy, from the last n one-minute candles: how efficient the path was (net move over the total
    distance travelled), how often the candles overlap, and how many closes crossed the level.
    Returns {"kind": "chop" / "clean_up" / "clean_down" / None, "crosses", "eff", "text"}."""
    rows = [r for r in (mins or []) if r and r[4] is not None][-n:]
    if len(rows) < 5:
        return {"kind": None}
    closes = [r[4] for r in rows]
    path = sum(abs(b - a) for a, b in zip(closes, closes[1:])) or 1e-9
    eff = abs(closes[-1] - closes[0]) / path
    over = sum(1 for a, b in zip(rows, rows[1:]) if min(a[2], b[2]) - max(a[3], b[3]) > 0.6 * min(a[2] - a[3], b[2] - b[3]))
    crosses = 0
    if level is not None:
        sides = [1 if c > level else -1 if c < level else 0 for c in closes]
        sides = [x for x in sides if x]
        crosses = sum(1 for a, b in zip(sides, sides[1:]) if a != b)
    m = len(rows)
    hl_up = sum(1 for a, b in zip(rows, rows[1:]) if b[3] >= a[3])
    lh_dn = sum(1 for a, b in zip(rows, rows[1:]) if b[2] <= a[2])
    if crosses >= 3 or (eff < 0.25 and over >= m - 3):
        bits = []
        if crosses >= 3:
            bits.append(f"{crosses} closes back and forth across the level in {m} minutes.")
        if over >= m - 3:
            bits.append("Candles all on top of each other.")
        return {"kind": "chop", "crosses": crosses, "eff": round(eff, 2), "text": " ".join(bits)}
    if eff >= 0.6 and closes[-1] > closes[0] and hl_up >= m - 2:
        return {"kind": "clean_up", "crosses": crosses, "eff": round(eff, 2), "text": "Higher lows, every dip getting bought."}
    if eff >= 0.6 and closes[-1] < closes[0] and lh_dn >= m - 2:
        return {"kind": "clean_down", "crosses": crosses, "eff": round(eff, 2), "text": "Lower highs, every pop getting sold."}
    return {"kind": None, "crosses": crosses, "eff": round(eff, 2)}


def coach(sb, t, foc, pb, cfg, mins=None, traps=None, market=None, up=None, reloads=None, consumed=None, pulled=None):
    """The desk talking to you like a room that knows what it's looking at: before 10 o'clock give it time, the first
    pivot of the day wants more context, clean price action or chop, who is trapped and who got out, what the market
    is doing against this trade, and patience while it fights. Returns [(kind, text)] due now."""
    if not cfg.get("coach", True) or not foc or not pb:
        return []
    secs = studies.ny_secs(t)
    day = studies.day_key(t)
    c = sb.__dict__.setdefault("coach", {})
    if c.get("day") != day:
        c.clear()
        c["day"] = day
    every = float(cfg.get("coach_seconds", 180))

    def pick(kind, **kw):
        i = COACH_TURN.get(kind, 0)
        COACH_TURN[kind] = i + 1
        return COACH[kind][i % len(COACH[kind])].format(**kw).replace("  ", " ").strip()

    def due(kind, gap):
        if t - c.get("t_" + kind, -1e9) < gap:
            return False
        c["t_" + kind] = t
        return True
    out = []
    active = pb["read"] != "quiet"                # nothing going on (no tape, no book, no option flow): the chart stays quiet
    ps60 = foc["kind"] in PS60_KINDS or (foc.get("conf") or {}).get("ps60")
    if active and foc["on"] and ps60 and not c.get("first") and 9.5 * 3600 <= secs < 16 * 3600:
        c["first"] = foc["name"]
        out.append(("first", pick("first")))
    if not active:
        pass
    elif secs < 9.5 * 3600:
        if not c.get("pre"):
            c["pre"] = True
            out.append(("pre", pick("pre")))
    elif secs < float(cfg.get("coach_wait_until_hour", 10)) * 3600 and due("early", every * 2):
        out.append(("early", pick("early")))
    # clean or choppy
    pa = price_action(mins, foc["p"] if foc["kind"] != "uzone" else (foc["lo"] + foc["hi"]) / 2)
    if active and pa.get("kind") and (pa["kind"] != c.get("pa") or due("pa_" + pa["kind"], every * 2)):
        if pa["kind"] != c.get("pa"):
            c["t_pa_" + pa["kind"]] = t
        c["pa"] = pa["kind"]
        out.append((pa["kind"], pick(pa["kind"], x=pa["text"])))
    elif not pa.get("kind"):
        c["pa"] = None
    # the reload buyer / seller at the place: be careful until he is CLEANED UP (said again while he is STILL THERE)
    rl = c.setdefault("rl", {})
    near = abs(foc["hi"] - foc["lo"]) / 2 + max(0.05, abs(foc["p"]) * 0.0015)
    for r in (reloads or []):
        if not (foc["lo"] - near <= r["price"] <= foc["hi"] + near):
            continue
        who = "buyer" if r["side"] == "bid" else "seller"
        k = (r["price"], r["side"])
        ab = f", {sh(r['absorbed'])} shares traded into him" if r.get("absorbed") else ""
        prev = rl.get(k)
        if prev is None:
            rl[k] = {"t": t, "n": 1}
            out.append(("rl_" + who, pick("rl_" + who, p=px(r["price"]), ab=ab)))
        elif t - prev["t"] >= float(cfg.get("coach_reload_repeat_seconds", 120)):
            prev["t"] = t; prev["n"] += 1
            out.append(("rl_still_" + who, pick("rl_still_" + who, p=px(r["price"]), ab=ab)))
    for cu in (consumed or []):
        k = (cu["price"], cu["side"])
        if k in rl and not rl[k].get("done"):
            rl[k]["done"] = True
            who = "buyer" if cu["side"] == "bid" else "seller"
            out.append(("rl_clean_" + who, pick("rl_clean_" + who, p=px(cu["price"]))))
    for k, v in list(rl.items()):
        if v.get("done") or any((r["price"], r["side"]) == k for r in (reloads or [])):
            continue
        if (pulled or {}).get(k):
            v["done"] = True
            who = "buyer" if k[1] == "bid" else "seller"
            out.append(("rl_pulled_" + who, pick("rl_pulled_" + who, p=px(k[0]))))
    # who is trapped
    for b in (traps or [])[:2]:
        key = (b["name"], round(b["level"], 2))
        st_ = b.get("state")
        if st_ in ("TRAPPED", "AT EXIT") and c.get(("trap",) + key) != st_:
            c[("trap",) + key] = st_
            who = "Longs" if b.get("up") else "Shorts"
            avg = b.get("avg")
            x = (f"They {'bought' if b.get('up') else 'sold'} the break {'over' if b.get('up') else 'under'} {b['name']} {px(b['level'])}, "
                 f"{sh(b.get('shares'))} shares" + (f" averaging {px(avg)}" if avg else "") + ". "
                 + (f"Price is {abs(b['under']) * 100:.0f} cents {'under' if b.get('up') else 'over'} them. " if b.get("under") and b["under"] > 0 and b["under"] < 1 else "")
                 + (f"Back at their exit {px(avg)}, watch them {'sell' if b.get('up') else 'cover'} into it" if st_ == "AT EXIT" and avg else
                    f"Their pain is fuel for the move {'down' if b.get('up') else 'up'}, and {px(avg)} is where they get out" if avg else ""))
            out.append(("trapped", pick("trapped", who=who, who_l=who.lower(), x=x.strip())))
        elif st_ == "RECLAIMED" and c.get(("trap",) + key) in ("TRAPPED", "AT EXIT"):
            c[("trap",) + key] = st_
            who = "longs" if b.get("up") else "shorts"
            out.append(("freed", pick("freed", who_l=who, nm=b["name"])))
    # the market against / with this trade
    if active and market and up is not None and market.get("dir"):
        side = "with" if (market["dir"] == "up") == up else "against"
        if c.get("mkt") != side or due("mkt", every * 3):
            if c.get("mkt") != side:
                c["t_mkt"] = t
            c["mkt"] = side
            out.append(("mkt_" + side, pick("mkt_" + side, x=market["text"])))
    # patience while nobody wins
    if pb["read"] == "mixed":                     # a real fight (both sides showing): quiet is not a fight, the chart stays quiet
        c.setdefault("fight", t)
        if t - c["fight"] >= float(cfg.get("coach_patience_seconds", 90)) and pa.get("kind") != "chop":
            out.append(("patience", pick("patience")))
            c["fight"] = t
    else:
        c.pop("fight", None)
    return out


def fmt_strike(k):
    try:
        k = float(k)
    except (TypeError, ValueError):
        return str(k)
    return f"{k:g}"


def clusters(levels, band):
    """[(price, name)] sorted along the path -> [{"near", "far", "names"}]: levels within `band` of each other (chained)
    are ONE supply / ONE demand (several MAs sitting close against the ATR)."""
    out = []
    for p, nm in levels:
        if out and abs(p - out[-1]["far"]) <= band:
            out[-1]["far"] = p
            if nm not in out[-1]["names"]:
                out[-1]["names"].append(nm)
        else:
            out.append({"near": p, "far": p, "names": [nm]})
    return out


def _cl_name(c):
    n = c["names"]
    return n[0] if len(n) == 1 else " / ".join(n[:3]) + (f" +{len(n) - 3}" if len(n) > 3 else "")


def room_read(up, ctx, foc, points, zones, last, near, atr, cfg):
    """MEASURED POTENTIAL, Dan's way (the hard law): MP = dollars from price to the next supply (up) / demand (down).
    Above the 50-day it is SUPPLY TO SUPPLY, below it DEMAND TO DEMAND. Several MAs sitting close against the ATR are
    ONE supply / demand: MP runs to its FAR edge. Always against the ATR (THIN under mp_min_atr); when the first air is
    thin the next MP beyond it is said too. The ATR levels are never supply or demand."""
    if up is None or last is None:
        return None
    start = max(last, foc["hi"]) if (foc and up) else min(last, foc["lo"]) if foc else last
    gap = near / 2.0
    lv = []
    for p in points:
        if p["kind"] == "inst":
            continue
        if (up and p["p"] > start + gap) or (not up and p["p"] < start - gap):
            lv.append((p["p"], p["name"]))
    for z in zones:
        edge_ = z["lo"] if up else z["hi"]
        if (up and edge_ > start + gap) or (not up and edge_ < start - gap):
            lv.append((edge_, z["short"]))
    lv.sort(key=lambda x: x[0] if up else -x[0])
    frame = "supply to supply" if up else "demand to demand"
    with50 = bool(ctx and ctx.get("bias") and (ctx["bias"] == "bull") == up)
    nxt = "supply" if up else "demand"
    if not lv:
        return {"frame": frame, "with50": with50, "to": None, "name": "open air: nothing in the way", "dollars": None, "atr_x": None, "thin": False,
                "map": [], "text": f"{frame.capitalize()}: open air {'above' if up else 'below'}, no {nxt} in the way"}
    band = max(near * 0.25, (atr or 0) * float(cfg.get("mp_merge_atr_pct", 8)) / 100.0)
    cs = clusters(lv, band)
    c0 = cs[0]
    d = abs(c0["far"] - last)
    ax = round(d / atr, 2) if atr else None
    thin = ax is not None and ax < float(cfg.get("mp_min_atr", 0.5))
    nm = _cl_name(c0)
    one = len(c0["names"]) > 1
    text = (f"{frame.capitalize()}: MP ${d:.2f} of airspace to the next {nxt}, {nm} "
            + (f"{px(c0['near'])}–{px(c0['far'])} (one {nxt}, far edge)" if one else px(c0["far"]))
            + (f" ({ax:g} ATR)" if ax is not None else ""))
    beyond = None
    if thin and len(cs) > 1:
        c1 = cs[1]
        beyond = {"to": c1["far"], "name": _cl_name(c1), "dollars": round(abs(c1["far"] - last), 2)}
        text += f" — THIN; next MP beyond it: ${beyond['dollars']:.2f} to {beyond['name']} {px(c1['far'])}"
    elif thin:
        text += " — THIN, not enough airspace"
    if not with50:
        text += " · against the 50-day framework"
    mp_map = [{"near": round(c["near"], 4), "far": round(c["far"], 4), "name": _cl_name(c), "dollars": round(abs(c["far"] - last), 2),
               "room": round(abs(c["near"] - (cs[i - 1]["far"] if i else last)), 2)} for i, c in enumerate(cs[:6])]
    return {"frame": frame, "with50": with50, "to": c0["far"], "name": nm, "dollars": round(d, 2), "atr_x": ax, "thin": thin,
            "beyond": beyond, "map": mp_map, "text": text}


def mp_layout(last, points, atr, near, cfg):
    """Where every average and level sits around price, both ways: the supply clusters above and the demand clusters
    below, nearest first, with the room between each (the airspace the trade has to travel)."""
    if last is None:
        return None
    out = {}
    for up in (True, False):
        r = room_read(up, None, None, points, [], last, near, atr, cfg)
        out["above" if up else "below"] = (r or {}).get("map") or []
    return out


def edge_read(up, ctx, foc, se_state, pace, reloads, consumed, fs, resp, last, near, room=None):
    """THE EDGE: seven independent reads, each asked the same question: does it agree with this move?
    DAILY (the 50-day framework, and the 200-day on the right side) · PS60 (a PS60 place, or the 2nd entry live) ·
    LOCATION (a major confluence: levels, moving averages, a zone together) · TAPE (fast, and the aggressive shares on
    this side) · LEVEL II (a reloader with you, or the one against you consumed) · FLOW (short-dated OTM
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
        add("LEVEL II", None, "no reloader here")
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
        self.memory = {}          # "C" / "P" -> {"t", "usd"}: unusual flow seen with no PS60 pivot in play
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


def _closed_n(mins, t, n):
    """The completed n-minute candles from 1-minute rows [t0, o, h, l, c, v]: [t0, o, h, l, c, v] per n-minute block."""
    out = {}
    for r in mins or []:
        k = int(r[0] // (60 * n)) * 60 * n
        if k + 60 * n > t + 1e-6:
            continue
        b = out.get(k)
        out[k] = [k, r[1], r[2], r[3], r[4], r[5]] if b is None else [k, b[1], max(b[2], r[2]), min(b[3], r[3]), r[4], b[5] + r[5]]
    return [out[k] for k in sorted(out)]


def build(sb, t, last, tick, atr, play, se_state, ctx, points, zones, conf, fr, pace, reloads, consumed, mins, cfg,
          traps=None, market=None, pulled=None, fw=None, mas=None, trade=None, h60=None, drows=None, live=False):
    """One read: the line for now, plus whatever new moments go on the feed. sb: the symbol's Story.
    reloads: confirmed reloaders [{price, side, stage, absorbed}]. consumed: reloaders
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
            "focus": 60.0, "room": 600.0, "reload": 120.0,
            "daily": float(cfg.get("daily_repeat_minutes", 45)) * 60 / 3, "struct": 300.0, "fw": 300.0, "ma": 120.0,
            "h60": 600.0, "hype": 120.0}

    # what gets said first when several things happen at once (the page's one mouth): 1 your trade and your second
    # entry, 2 the reload buyer / seller and the money, 3 the levels taken, the averages, the Daily, 4 the colour
    PRI = {"trade": 1, "se": 1, "reload": 2, "consumed": 2, "hype": 2, "coach_rl": 2, "break": 3, "h60": 3, "retrace": 3, "fw": 3,
           "struct": 3, "ma": 3, "daily": 3, "fail": 3, "held": 3, "maflow": 3, "flow": 3, "align": 3, "edge": 3}

    def note(topic, key, text, tone, repeat=600.0, loud=False):
        if sb.say(topic, key, text, tone, t, repeat, GAPS.get(topic.split(":")[0], 0.0)) and loud:
            k0 = topic.split(":")[0]
            pri = PRI.get(k0, PRI.get(k0.split("_")[0] if not k0.startswith("coach_rl") else "coach_rl", 4))
            said.append({"topic": topic, "text": text, "tone": tone, "pri": pri})

    if ctx and ctx.get("text"):
        note("ctx", (ctx.get("bias"), ctx.get("taken")), ctx["text"], "bull" if ctx.get("bias") == "bull" else "bear" if ctx.get("bias") == "bear" else "neutral",
             repeat=4 * 3600)
    # breaks and retests of every place (not only the nearest): who got through, who came back
    places = [(p["name"], p["p"], p["p"], p["kind"]) for p in points if p["kind"] not in ("inst",) + MA_PACK_KINDS] + \
             [(z["short"], z["lo"], z["hi"], "uzone") for z in zones]
    held, failed = {"up": [], "down": []}, {"up": [], "down": []}
    band = max(tick / 2, 0.25 * near)         # a break is a real move through the place, not a one-tick wiggle
    # a place is only TAKEN on a CLOSE: the last completed candle closed through it. Trading through it on the way
    # (fast or not) is pressing, not a break
    cmin = max(1, int(cfg.get("close_minutes", 1)))
    done = [r for r in (mins or []) if r[0] + 60 * cmin <= t + 1e-6] if cmin == 1 else _closed_n(mins, t, cmin)
    cl = done[-1][4] if done else None
    out["close"] = cl
    pressing = {}
    for name, lo, hi, kind in places:
        side_live = "above" if last > hi + band else "below" if last < lo - band else "in"
        side = side_live if cl is None else "above" if cl > hi else "below" if cl < lo else "in"
        if side_live in ("above", "below") and sb.side.get(name) not in (None, side_live) and side != side_live:
            pressing[name] = side_live                # through it right now, no close there yet
        # a break already on the books: is the retest holding, or did it fail? (before a new break replaces it)
        b = sb.breaks.get(name)
        if b and t - b["t"] <= float(cfg.get("retest_minutes", 30)) * 60:
            up = b["dir"] == "up"
            edge = hi if up else lo
            if b["state"] == "broke" and abs(last - edge) <= near and t - b["t"] >= 30:
                b["state"] = "retest"
            back = cl if cl is not None else last
            if b["state"] in ("broke", "retest") and ((up and back < lo) or (not up and back > hi)) and (cl is None or done[-1][0] + 60 > b["t"]):
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
            note("memory:" + cp, "seen", f"Unusual OTM {what} detected ({money(s['usd'])}). No PS60 pivot in play yet. Watching", "neutral", repeat=1800)
    mem_win = float(cfg.get("memory_minutes", 120)) * 60
    if ps60_on and up is not None:
        cp = "C" if up else "P"
        m = sb.memory.get(cp)
        if m and t - m["t"] <= mem_win and t - m["t"] >= 120 and not m.get("said_align"):
            m["said_align"] = True
            note("align:" + foc["name"], cp, f"Earlier OTM {'call' if up else 'put'} activity ({money(m['usd'])}, {_hm(m['t'])}) now aligning with {foc['name']}",
                 "bull" if up else "bear", loud=True)

    out["play"] = None
    hy = hype(fr, cfg) if cfg.get("hype", True) else None
    out["hype"] = hy["text"] if hy else None
    if hy and sb.say("hype:" + hy["cp"] + str(hy["strike"]), hy["key"], hy["text"] + ("" if hy["text"].endswith("!") else "!"),
                     "bull" if hy["cp"] == "C" else "bear", t, float(cfg.get("hype_repeat_seconds", 180))):
        said.append({"topic": "hype", "text": hy["text"], "tone": "bull" if hy["cp"] == "C" else "bear", "pri": 2})
    if cfg.get("play_by_play", True):
        pb = play_by_play(sb, t, foc, last, near, pace, fr, reloads, consumed, cfg)
        if pb and pb["read"] == "quiet" and not cfg.get("pbp_quiet", False):
            out["play"] = None                    # nothing going on: the chart stays quiet (no tape, no book, no option flow)
        elif pb:
            out["play"] = pb["text"]
            lk = sb.__dict__.get("pbp_loud") or (None, -1e9)
            # said out loud only when it says something (a quiet read stays on the story) and the read changed
            loud = pb["read"] != "quiet" and pb["key"] != lk[0] and t - lk[1] >= float(cfg.get("pbp_say_seconds", 60))
            if sb.say("pbp", pb["key"], pb["text"], pb["tone"], t, float(cfg.get("pbp_repeat_seconds", 90)),
                      float(cfg.get("pbp_seconds", 30))) and loud:
                sb.pbp_loud = (pb["key"], t)
                said.append({"topic": "pbp", "text": pb["text"], "tone": pb["tone"], "pri": 4})
        for kind, text in coach(sb, t, foc, pb, cfg, mins, traps, market, up, reloads, consumed, pulled):
            tone = {"rl_buyer": "warn", "rl_seller": "warn", "rl_still_buyer": "warn", "rl_still_seller": "warn",
                    "rl_clean_buyer": "bear", "rl_clean_seller": "bull", "rl_pulled_buyer": "warn", "rl_pulled_seller": "warn","trapped": "warn", "chop": "warn", "mkt_against": "warn", "clean_up": "bull", "clean_down": "bear"}.get(kind, "neutral")
            gap_ = float(cfg.get("coach_seconds", 180)) if kind in ("patience", "chop", "clean_up", "clean_down", "early", "mkt_with", "mkt_against") else 0.0
            # each kind of coaching has its own gap: the first pivot of the day never silences the reload warning
            if sb.say("coach_" + kind + ":" + kind, (kind, text), text, tone, t, 600.0, gap_):
                said.append({"topic": "coach", "text": text, "tone": tone, "pri": 2 if kind.startswith("rl_") else 4})
    # the moving-average framework: who controls the 5, the 10, rising / falling 60-minute support
    out["framework"] = fw
    out["layout"] = mp_layout(last, [q for q in points if q["kind"] != "inst"], atr, near, cfg)
    if out["layout"] is not None:
        out["layout"]["last"] = last
    if out["layout"] is not None:
        out["layout"]["last"] = last
    if fw:
        fs_ = sb.__dict__.setdefault("fw", {})
        for k_, now_ in (("five", fw.get("five")), ("ten", fw.get("ten")), ("h60", fw.get("h60"))):
            if now_ is None:
                continue
            was = fs_.get(k_)
            fs_[k_] = now_
            if was is None or was == now_:
                continue
            txt = {("five", "buyers"): f"Buyers just took the 5-day {px(fw['d5'])}. They control the short-term sentiment now",
                   ("five", "sellers"): f"Sellers just took the 5-day {px(fw['d5'])}. They control the short-term sentiment now",
                   ("ten", "over"): f"Back over the 10-day {px(fw['d10'])}. That's the birth of the long trade",
                   ("ten", "under"): f"Under the 10-day {px(fw['d10'])}. That's the birth of the short trade",
                   ("h60", "rising"): f"The 60m 5 and 10 are rising: rising 60-minute support at {px(fw['h5'])} / {px(fw['h10'])}. Strong plays come into it, wait for the retrace",
                   ("h60", "falling"): f"The 60m 5 and 10 are falling: falling 60-minute resistance at {px(fw['h5'])} / {px(fw['h10'])}. Wait for the pop into it to short",
                   ("h60", "flat"): "The 60m 5 and 10 flattened out. No clean 60-minute trend right now"}[(k_, now_)]
            note("fw:" + k_, now_, txt, "bull" if now_ in ("buyers", "over", "rising") else "bear" if now_ in ("sellers", "under", "falling") else "neutral",
                 repeat=900, loud=True)
        z = fw.get("zone")
        if z and fw.get("h60") in ("rising", "falling"):
            rising = fw["h60"] == "rising"
            inside = z[0] - near * 0.5 <= last <= z[1] + near * 0.5
            came = (last >= z[0] - near * 0.5) if rising else (last <= z[1] + near * 0.5)
            if inside and came and t - fs_.get("retrace_t", -1e9) > float(cfg.get("retrace_repeat_minutes", 30)) * 60:
                fs_["retrace_t"] = t
                note("retrace", (fw["h60"], round(t // 1800)),
                     (f"Here's the 60-minute retrace into rising support, the 60m 5 / 10 at {px(fw['h5'])} / {px(fw['h10'])}. "
                      "This is where we look to buy: technical buyers meeting emotional sellers. Wait for the reload buyer or a close off it")
                     if rising else
                     (f"Here's the 60-minute pop into falling resistance, the 60m 5 / 10 at {px(fw['h5'])} / {px(fw['h10'])}. "
                      "This is where we look to short: technical sellers meeting emotional buyers. Wait for the reload seller or a close off it"),
                     "bull" if rising else "bear", repeat=1800, loud=True)
    # structure: lower lows / higher highs on the 60 and on the Daily
    for kind, txt in structure_read(sb, t, h60, drows, live, last, fw, cfg):
        note("struct:" + kind, (kind, round(t // 60)), txt, "bear" if kind.startswith("ll") else "bull", repeat=1800, loud=True)
    # THE DAILY BRIEF: the brain of the trade, said once a day and again whenever it changes (the 50, the 5 / 10, the MP)
    dr_up = room_read(True, ctx, None, points, zones, last, near, atr, cfg)
    dr_dn = room_read(False, ctx, None, points, zones, last, near, atr, cfg)
    db = daily_brief(ctx, fw, dr_up, dr_dn, drows, live, atr, cfg)
    out["daily"] = db
    if db:
        # said again only when the Daily itself changes (the 50, the 5, the 10, room or thin), never because the nearest
        # average moved a cent; and never more often than daily_repeat_minutes whatever changed
        mine = (dr_up if ctx.get("bias") == "bull" else dr_dn) or {}
        dkey = (ctx.get("bias"), (fw or {}).get("five"), (fw or {}).get("ten"), "thin" if mine.get("thin") else "open" if mine.get("to") is None else "room")
        note("daily", dkey, db, "bull" if ctx["bias"] == "bull" else "bear", repeat=float(cfg.get("daily_repeat_minutes", 45)) * 60, loud=True)
    # how price reacts at the averages, daily and 60-minute: bounce off demand, reject at supply, close through
    if mas:
        mas = merge_mas(mas, max(tick, near * 0.2))
        cl_t = (done[-1][0] + 60 * cmin) if done else None
        room_pts = [q for q in points if q["kind"] != "inst"]
        active_ = bool(out.get("play"))
        for kind, m, txt in ma_watch(sb, t, last, near, mas, cl, cl_t, room_pts, cfg):
            tone_ = {"bounce": "bull", "reject": "bear", "through_up": "bull", "through_dn": "bear"}.get(kind, "neutral")
            note("ma:" + m["name"], (kind, round(t // 60)), txt, tone_, repeat=600, loud=kind != "into" or active_)
    # YOUR SECOND ENTRY: walked in, step by step, then live
    for kind, txt in second_entry_watch(sb, t, play or {}, last, near, locals().get("pb"), se_state, cfg):
        note("se:" + kind, (kind, txt[:40]), txt, "bull" if (play or {}).get("side", "long") != "short" else "bear", repeat=30, loud=True)
    # the 60-minute candle confirmation (PS60 rule 2)
    hc = h60_confirm(sb, t, h60, last)
    if hc:
        note("h60:" + hc[0], (hc[0], round(t // 3600)), hc[1], "bull" if hc[0] == "up" else "bear", repeat=3600,
             loud=bool(trade) or bool(foc and foc.get("approach") and out.get("play")))
    # the trade you're in, against the levels
    if trade:
        rm_t = room_read(trade["dir"] == "long", ctx, foc, points, zones, last, near, atr, cfg)
        pb_ = locals().get("pb")
        for kind, txt in trade_read(sb, t, trade, foc, last, near, pb_, rm_t, cfg, pace, market, fr):
            note("trade:" + kind, (kind, txt[:60]), txt, "warn" if kind in ("stop", "r57", "weak") else "bull" if kind in ("pay", "mp") else "neutral", repeat=60, loud=True)
    else:
        trade_read(sb, t, None, foc, last, near, None, None, cfg)
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
        head = f"{where} {verb}: a candle closed {'over' if br['dir'] == 'up' else 'under'} it" + (f" at {px(cl)}" if cl is not None else "")
        tone = "bull" if br["dir"] == "up" else "bear"
    elif br and br["state"] in ("broke", "retest", "held") and t - br["t"] <= float(cfg.get("retest_minutes", 30)) * 60:
        head = f"{'Holding above' if br['dir'] == 'up' else 'Holding below'} {where[0].lower() + where[1:] if where.startswith('Major') else where}" + (" on the retest" if br["state"] == "retest" else "")
        tone = "bull" if br["dir"] == "up" else "bear"
    elif foc["name"] in pressing:
        dn = pressing[foc["name"]] == "below"
        head = (f"Trading {'under' if dn else 'over'} {where[0].lower() + where[1:] if where.startswith('Major') else where}{at}, "
                f"no close {'under' if dn else 'over'} it yet. Not taken until a candle closes {'under' if dn else 'over'} it")
        tone = "warn"
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
    # the reloaders at this place (any price: round numbers only get a star)
    at_rl = [r for r in reloads if foc["lo"] - near <= r["price"] <= foc["hi"] + near]
    for r in at_rl[:1]:
        who = "seller" if r["side"] == "ask" else "buyer"
        # the tell: repeated execution at one price and how much traded there (round numbers only highlighted)
        took = (f"buyers absorbed {sh(r.get('absorbed'))} shares" if who == "seller" else f"sellers hit him for {sh(r.get('absorbed'))} shares") if r.get("absorbed") else ""
        what = f"{who.capitalize()} reloading at {px(r['price'])}{round_tag(r['price'])}" + (f" · {took}" if took else "")
        parts.append(what)
        note("reload:" + str(r["price"]) + r["side"], r.get("stage") or "RELOADING",
             f"{head[0].upper() + head[1:]}. {what}: {'supply' if who == 'seller' else 'demand'} sitting on it", "warn", loud=True)
        bp = (pace or {}).get("buy_pct")
        if bp is not None and ((who == "seller" and bp >= 60) or (who == "buyer" and bp <= 40)):
            parts.append(f"{'Buyers keep lifting' if who == 'seller' else 'Sellers keep hitting'} {px(r['price'])} and the {who} keeps reloading")
    for c in consumed:
        if foc["lo"] - near <= c["price"] <= foc["hi"] + near:
            who = "seller" if c["side"] == "ask" else "buyer"
            # his liquidity is gone and price went through: exhausted
            bit = (f"{who.capitalize()} exhausted at {px(c['price'])}" + (f" after {sh(c.get('absorbed'))} shares" if c.get("absorbed") else "")
                   + f" · {'buyers breaking through' if who == 'seller' else 'sellers breaking through'}")
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
