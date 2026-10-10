"""PS60 process, encoded as pure functions over bars.

Dan Shapiro's Pivot System 60, as handed off by Antoine:
  Daily room -> 60m pivot (or sneaky pivot) -> confirm -> second entry -> build
  -> pay yourself (cash flow) -> runner to measured potential (MP).

Nothing here invents a signal. Every object is derived from candles the trader
can see on the chart. Language lock: supply, demand, pivot, confirmation,
second entry, build, measured potential, ATR, cash flow, runner, max pain,
remount, rejection, sneaky pivot, macro / micro channel, reload buyer / seller.
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .prices import fmt_price, tick_size

NY = ZoneInfo("America/New_York")
SESSION_OPEN = 9 * 3600 + 30 * 60  # 9:30 New York, in seconds after midnight

# states of the pivot -> second entry engine
IDLE, BROKE, RETRACE, SECOND_ENTRY = "IDLE", "BROKE", "RETRACE", "SECOND_ENTRY"

DEFAULTS = {
    # candle size the second entry is judged on (1 or 5 minutes; Dan: "always on a new candle")
    "second_entry_tf": 1,
    # a pullback counts as the retrace once it is this fraction of the move from the pivot to the new extreme
    "min_retrace_fraction": 0.25,
    # after the second entry, price should be going the right way within this long
    "build_seconds": 120,
    # measured potential judged against the daily ATR: CLEAR at or above this ratio, THIN below
    "clear_ratio": 0.5,
    # sneaky pivot: micro range height cap vs ATR, minimum candles, minimum MP dollars
    "sneaky_max_height_atr": 1.25,
    "sneaky_min_candles": 2,
    "sneaky_min_mp": 0.50,
    # remount / rejection: price through the level then back through it within this window
    "remount_window_seconds": 1800,
}


def ny_day(t):
    """Calendar day in New York for a timestamp (so 60m candles and ATR respect the session)."""
    return datetime.fromtimestamp(t, tz=timezone.utc).astimezone(NY).date()


def ny_seconds(t):
    d = datetime.fromtimestamp(t, tz=timezone.utc).astimezone(NY)
    return d.hour * 3600 + d.minute * 60 + d.second


def is_rth(t):
    """True inside the regular session: a weekday, 9:30 to 4:00 New York."""
    d = datetime.fromtimestamp(t, tz=timezone.utc).astimezone(NY)
    s = d.hour * 3600 + d.minute * 60 + d.second
    return d.weekday() < 5 and 34200 <= s < 57600


def ny_offset(t):
    """Seconds to add to a UTC timestamp to get New York wall-clock seconds."""
    return datetime.fromtimestamp(t, tz=timezone.utc).astimezone(NY).utcoffset().total_seconds()


def session_bars(bars):
    """Only the current New York day's bars (the day of the last bar)."""
    if not bars:
        return []
    off = ny_offset(bars[-1][0])
    start = (bars[-1][0] + off) // 86400 * 86400 - off
    return [b for b in bars if b[0] >= start]


def aggregate(bars, minutes):
    """Aggregate 1-minute bars [t, o, h, l, c, v, ...] to ``minutes``; 60m anchored at 9:30."""
    if minutes <= 1:
        return [list(b[:6]) for b in bars]
    span = minutes * 60
    out = []
    off = ny_offset(bars[-1][0]) if bars else 0
    for b in bars:
        secs = (b[0] + off) % 86400
        anchor = SESSION_OPEN if minutes >= 30 else 0
        t0 = b[0] - ((secs - anchor) % span)
        if out and out[-1][0] == t0:
            last = out[-1]
            last[2] = max(last[2], b[2])
            last[3] = min(last[3], b[3])
            last[4] = b[4]
            last[5] += b[5]
        else:
            out.append([t0, b[1], b[2], b[3], b[4], b[5]])
    return out


# ---------------------------------------------------------------------------
# ATR and measured potential

def daily_from_bars(bars):
    """[date, o, h, l, c] per New York day from 1-minute bars (fallback when no daily bars)."""
    days = {}
    off = ny_offset(bars[-1][0]) if bars else 0
    for b in bars:
        d = int((b[0] + off) // 86400)
        row = days.get(d)
        if row is None:
            days[d] = [d, b[1], b[2], b[3], b[4]]
        else:
            row[2] = max(row[2], b[2])
            row[3] = min(row[3], b[3])
            row[4] = b[4]
    return [days[k] for k in sorted(days)]


def atr(daily, n=14):
    """Average true range of the completed days ``daily`` ([t, o, h, l, c] rows), Wilder's smoothing exactly like
    TradingView's ta.atr(n) (= ta.rma(ta.tr(true), n)): ONE ATR for the desk, the chart studies and the play grades.
    With fewer days than ``n`` it is the plain average of what there is. None with fewer than 2 days."""
    if len(daily) < 2:
        return None
    from .studies import atr_rma
    hs = [float(b[2]) for b in daily]; ls = [float(b[3]) for b in daily]; cs = [float(b[4]) for b in daily]
    if len(daily) < n:
        trs = [hs[0] - ls[0]] + [max(hs[i] - ls[i], abs(hs[i] - cs[i - 1]), abs(ls[i] - cs[i - 1])) for i in range(1, len(daily))]
        return round(sum(trs) / len(trs), 4)
    v = atr_rma(hs, ls, cs, n)[-1]
    return round(v, 4) if v is not None else None


def measured_potential(play, price, atr_value, cfg):
    """MP is the trader's number (plays.json "mp"): the distance from price to the nearest moving
    average / supply / demand on the Daily, read off the chart. TWINEY has no moving averages, so it
    never computes MP. Without it the play has no room on the board and grades PASS."""
    level = play.get("target") or play.get("mp")
    pivot = play.get("trigger")
    if not level or not pivot:
        return {"dollars": None, "level": level, "atr": atr_value, "ratio": None, "verdict": "NO MP", "manual": False}
    dollars = round(abs(float(level) - float(pivot)), 4)   # the room: from the pivot to your MP level
    if not atr_value:
        return {"dollars": dollars, "level": level, "atr": None, "ratio": None, "verdict": "MP", "manual": True}
    ratio = round(dollars / atr_value, 2)
    return {"dollars": dollars, "level": level, "atr": atr_value, "ratio": ratio, "manual": True,
            "verdict": "CLEAR" if ratio >= cfg["clear_ratio"] else "THIN"}


# ---------------------------------------------------------------------------
# pivot -> confirm -> second entry -> build

def second_entry(bars, play, now, cfg):
    """Run the second-entry engine over today's candles.

    Long: break the pivot -> new high -> retrace -> back through that high on a
    NEW candle = second entry. Short is the mirror. Returns a dict with the
    state, the prices that matter and a plain-English line.
    """
    pivot = play.get("trigger")
    long_ = play["side"] == "long"
    tf = int(cfg.get("second_entry_tf") or 1)
    if not pivot:
        return {"state": IDLE, "pivot": None, "extreme": None, "retrace": None, "second_entry": None, "se_t": None,
                "build": None, "fails": 0, "tf": tf, "text": "No pivot on this play yet — mark one on the chart (＋ mark… → pivot)."}
    candles = aggregate(session_bars(bars), tf)
    tk = tick_size(pivot)
    out = {"state": IDLE, "pivot": pivot, "extreme": None, "retrace": None, "second_entry": None,
           "se_t": None, "build": None, "fails": 0, "tf": tf}
    state, ext, ext_i, retr = IDLE, None, None, None
    se_price = se_t = se_i = None
    for i, c in enumerate(candles):
        t, o, h, l, cl = c[0], c[1], c[2], c[3], c[4]
        beyond = h > pivot if long_ else l < pivot          # traded through the pivot
        failed = cl < pivot - tk if long_ else cl > pivot + tk  # closed back on the wrong side
        if state == IDLE:
            if beyond and failed:
                out["fails"] += 1          # a wick through that closed back on the wrong side is a failed break
            elif beyond:
                state, ext, ext_i, retr = BROKE, (h if long_ else l), i, None
            continue
        if state in (BROKE, RETRACE):
            if failed:
                out["fails"] += 1
                state, ext, ext_i, retr = IDLE, None, None, None
                continue
            new_ext = h > ext if long_ else l < ext
            if i == ext_i:
                continue  # the candle that made the high / low can never be the entry candle
            # the retrace: how far price pulled back from the extreme on this new candle
            dip = l if long_ else h
            pulled = (ext - dip) if long_ else (dip - ext)
            if pulled > 0:
                retr = dip if retr is None else (min(retr, dip) if long_ else max(retr, dip))
            move = abs(ext - pivot)
            need = max(3 * tk, cfg["min_retrace_fraction"] * move)
            real_retrace = pulled >= need
            # the pullback so far, from the extreme to the deepest point since: only a REAL one makes a retrace
            deepest = None if retr is None else ((ext - retr) if long_ else (retr - ext))
            closed_through = cl > ext if long_ else cl < ext
            if state == RETRACE and new_ext:
                state, se_price, se_t, se_i = SECOND_ENTRY, ext, t, i      # back through the extreme
            elif state == BROKE and new_ext and real_retrace and closed_through:
                state, se_price, se_t, se_i = SECOND_ENTRY, ext, t, i      # retraced and re-took it inside one new candle
            elif new_ext:
                ext, ext_i, retr = (h if long_ else l), i, None             # no real retrace yet: a higher extreme
            elif deepest is not None and deepest >= need:
                state = RETRACE                                            # a real pullback (min fraction, 3 ticks)
            continue
        # SECOND_ENTRY: watch the build
        if failed:
            out["fails"] += 1
            state, ext, ext_i, retr, se_price = IDLE, None, None, None, None
    out["state"] = state
    out["extreme"] = fmt_price(ext)
    out["retrace"] = fmt_price(retr)
    if state == SECOND_ENTRY and candles:
        last = candles[-1]
        out["second_entry"], out["se_t"] = fmt_price(se_price), se_t
        age = now - se_t
        going = last[4] > se_price if long_ else last[4] < se_price
        if going:
            out["build"] = "building"
        elif age < cfg["build_seconds"]:
            out["build"] = "early"
        else:
            out["build"] = "not building"
    out["text"] = second_entry_text(out, play)
    return out


def second_entry_text(se, play):
    long_ = play["side"] == "long"
    p = _px(se["pivot"])
    word_hi, word_lo = ("high", "low") if long_ else ("low", "high")
    tfw = f"{se['tf']}-minute " if se.get("tf", 1) > 1 else ""
    if se["state"] == IDLE:
        base = f"Pivot {p} has not broken yet today" if not se["fails"] else \
            f"Pivot {p} broke and failed {se['fails']}x today — it is back to waiting"
        return base + ". Nothing to do until price goes through it and puts in a new " + word_hi + "."
    if se["state"] == BROKE:
        return (f"Pivot {p} broke — new {word_hi} {_px(se['extreme'])}. Now let it retrace (a bigger retrace is better). "
                f"The second entry is back through {_px(se['extreme'])} on a new {tfw}candle — the candle that made "
                f"the {word_hi} can't be the entry.")
    if se["state"] == RETRACE:
        return (f"Retracing off {_px(se['extreme'])} (so far to {_px(se['retrace'])}). "
                f"SECOND ENTRY = through {_px(se['extreme'])}. That is the safest entry.")
    build = se["build"]
    depth = f" after a retrace to {_px(se['retrace'])}" if se.get("retrace") else ""
    if build == "building":
        return (f"SECOND ENTRY taken through {_px(se['second_entry'])}{depth} and it is building — price keeps "
                f"improving. Cash flow first, then breakeven stop, runner to the measured potential.")
    if build == "early":
        return (f"SECOND ENTRY through {_px(se['second_entry'])}{depth} just went through. It should go now — if there "
                f"is no aggressive move in the next minute or two, use breakeven as the out.")
    return (f"SECOND ENTRY through {_px(se['second_entry'])} is NOT building after two minutes — high probability "
            f"it is wrong. Out at breakeven or your max pain.")


# ---------------------------------------------------------------------------
# sneaky pivots on the 60-minute

def sneaky_pivots(bars, atr_value, cfg):
    """Micro ranges inside the macro channel on 60-minute candles.

    A sneaky pivot is the meat of the channel, not its edges: at least
    ``sneaky_min_candles`` consecutive 60m candles whose highs (supply) or lows
    (demand) cluster tightly, inset from the macro high / low, with a tight
    micro height vs ATR and real measured potential to the next macro edge.
    Returns at most one supply and one demand pivot, the most recent of each.
    """
    if not atr_value:
        return []
    c60 = aggregate(bars, 60)
    if len(c60) < 4:
        return []
    macro_hi = max(c[2] for c in c60)
    macro_lo = min(c[3] for c in c60)
    inset = 0.25 * atr_value
    tol = 0.15 * atr_value
    min_n = int(cfg["sneaky_min_candles"])
    found = {}
    for kind in ("supply", "demand"):
        best = None
        for end in range(len(c60), min_n - 1, -1):
            for n in range(min(6, end), min_n - 1, -1):
                win = c60[end - n:end]
                if kind == "supply":
                    level = max(c[2] for c in win)
                    touches = sum(1 for c in win if level - c[2] <= tol)
                    height = level - min(c[3] for c in win)
                    mp = macro_hi - level
                    inset_ok = level <= macro_hi - inset and level >= macro_lo + inset
                else:
                    level = min(c[3] for c in win)
                    touches = sum(1 for c in win if c[3] - level <= tol)
                    height = max(c[2] for c in win) - level
                    mp = level - macro_lo
                    inset_ok = level >= macro_lo + inset and level <= macro_hi - inset
                if touches >= min_n and inset_ok and height <= cfg["sneaky_max_height_atr"] * atr_value \
                        and mp >= cfg["sneaky_min_mp"]:
                    cand = {"kind": kind, "price": fmt_price(level), "touches": touches, "room": round(mp, 2),
                            "t0": win[0][0], "t1": win[-1][0], "candles": n,
                            "macro_high": fmt_price(macro_hi), "macro_low": fmt_price(macro_lo)}
                    if best is None or cand["touches"] > best["touches"]:
                        best = cand
            if best:
                break
        if best:
            best["label"] = f"SNEAKY PIVOT · {kind.upper()}"
            best["text"] = (f"SNEAKY PIVOT · {kind.upper()} {_px(best['price'])}: {best['touches']} 60-minute candles "
                            f"{'rejected into' if kind == 'supply' else 'held at'} it inside the macro channel "
                            f"{_px(best['macro_low'])}–{_px(best['macro_high'])}. Room to the macro "
                            f"{'high' if kind == 'supply' else 'low'} ${best['room']:.2f} (your Daily MP still rules). "
                            f"Path: break it → new {'high' if kind == 'supply' else 'low'} → retrace → second entry.")
            found[kind] = best
    return [found[k] for k in ("supply", "demand") if k in found]


# ---------------------------------------------------------------------------
# remount / rejection at a level

def remount(bars, level, now, cfg):
    """Through the level, then reclaimed (remount) or lost again (rejection), within the window.

    Returns {"kind": "remount"|"rejection", "t", "extreme"} for the most recent
    completed sequence whose reclaim candle closed inside the window, else None.
    """
    tk = tick_size(level)
    window = [b for b in bars if now - b[0] <= cfg["remount_window_seconds"]]
    if len(window) < 3:
        return None
    result = None
    below_since = above_since = None
    ext_lo = ext_hi = None
    prev_side = None
    for b in window:
        cl = b[4]
        side = "below" if cl < level - tk else "above" if cl > level + tk else prev_side
        if side == "below":
            ext_lo = b[3] if ext_lo is None else min(ext_lo, b[3])
            if prev_side == "above":
                result = {"kind": "rejection", "t": b[0], "extreme": fmt_price(ext_hi)} if above_since else result
            if below_since is None:
                below_since = b[0]
            above_since, ext_hi = None, None
        elif side == "above":
            ext_hi = b[2] if ext_hi is None else max(ext_hi, b[2])
            if prev_side == "below":
                result = {"kind": "remount", "t": b[0], "extreme": fmt_price(ext_lo)} if below_since else result
            if above_since is None:
                above_since = b[0]
            below_since, ext_lo = None, None
        prev_side = side
    return result


# ---------------------------------------------------------------------------
# the trade decision gate

def grade(play, price, se, mp, shares, stop_known, caps):
    """READY / WATCH / PASS with the four questions answered.

    1. Is the pivot valid?  2. Comfortable with size?  3. In control?  4. Know the risk?
    Plus room: no measured potential on the board = PASS (especially for options).
    """
    long_ = play["side"] == "long"
    gates = []
    valid = bool(play.get("trigger")) and mp["dollars"] is not None
    gates.append({"q": "Pivot valid?", "ok": valid,
                  "why": f"pivot {_px(play['trigger'])} with ${mp['dollars']:.2f} of measured potential" if valid
                  else "no measured potential on this play — set MP in PLAY SETUP"})
    dollars = (shares or 0) * (price or 0)
    size_ok = bool(shares) and shares <= caps["max_shares_per_order"] and dollars <= caps["max_dollars_per_order"]
    gates.append({"q": "Comfortable with size?", "ok": size_ok,
                  "why": f"{shares:,} shares ≈ ${dollars:,.0f}" if size_ok else
                  f"{shares:,} shares ≈ ${dollars:,.0f} is over your cap"})
    control = stop_known and bool(play.get("target"))
    gates.append({"q": "In control of the trade?", "ok": control,
                  "why": "stop and target ride with every entry" if control else "attach a stop and a target first"})
    if stop_known and price:
        risk = abs(price - play["stop"]) * (shares or 0)
        gates.append({"q": "Know the risk?", "ok": True,
                      "why": f"max pain {_px(play['stop'])} = ${risk:,.0f} on {shares:,} shares"})
    else:
        gates.append({"q": "Know the risk?", "ok": False, "why": "no stop on this play"})
    reasons = []
    if not play.get("trigger"):
        reasons.append("no pivot yet — mark one on the chart")
    if mp["verdict"] == "NO MP":
        reasons.append("no measured potential on the board — set MP in PLAY SETUP")
    elif mp["verdict"] == "THIN":
        reasons.append(f"measured potential ${mp['dollars']:.2f} is THIN against a ${mp['atr']:.2f} ATR")
    if not stop_known:
        reasons.append("no stop = risk not known")
    if reasons:
        return {"grade": "PASS", "why": "; ".join(reasons), "gates": gates}
    if se["state"] == SECOND_ENTRY and se["build"] != "not building":
        return {"grade": "READY", "why": f"second entry through {_px(se['second_entry'])} — "
                + ("building" if se["build"] == "building" else "just went through"), "gates": gates}
    why = {IDLE: f"waiting for the pivot {_px(play.get('trigger'))} to break",
           BROKE: f"pivot broke — waiting for the retrace, then the second entry through {_px(se['extreme'])}",
           RETRACE: f"retracing — the second entry is through {_px(se['extreme'])} on a new candle",
           SECOND_ENTRY: "second entry is not building — stand aside"}[se["state"]]
    return {"grade": "WATCH", "why": why, "gates": gates}


def cash_flow_legs(play, action, qty, entry_price, plan):
    """Scale-out legs: pay yourself along the way, runner to the measured potential.

    plan: [{"fraction": 0.5, "dollars": 0.5}, {"fraction": 0.25, "dollars": 1.5}] etc.
    Whatever fraction is left runs to the play's target. Sizes are whole shares;
    a leg that rounds to zero is dropped and its shares join the runner.
    """
    exit_action = "SELL" if action == "BUY" else "BUY"
    sign = 1 if action == "BUY" else -1
    legs, used = [], 0
    for i, leg in enumerate(plan):
        n = int(qty * leg["fraction"])
        if n <= 0:
            continue
        used += n
        legs.append({"action": exit_action, "qty": n, "type": "LMT",
                     "price": round(entry_price + sign * leg["dollars"], 2), "role": f"cash_flow_{i + 1}"})
    runner = qty - used
    if runner > 0 and play.get("target"):
        legs.append({"action": exit_action, "qty": runner, "type": "LMT", "price": play["target"], "role": "runner"})
    return legs


def _px(p):
    v = fmt_price(p)
    if v is None:
        return "—"
    return f"{v:.2f}" if v >= 1 else f"{v:.4f}"



class SignalProvider:
    """The PS60 -> ladder interface. The ladder and the setup panel ask this, never the engine internals, so the
    PS60 logic behind it can change without touching them. Everything comes from the real play and the live
    PS60 read: no made-up signals. Fields are None until the trader (or PS60) has them. supply / demand are the
    [from, to] price spans of the play (pivot to target for a short, stop to pivot for a long)."""

    def __init__(self, engine):
        self.engine = engine

    def signals(self, symbol):
        e = self.engine
        with e.lock:
            st = e.syms.get(str(symbol).upper()) if symbol else None
            if st is None:
                return {"symbol": symbol, "available": False}
            play = st.play
            cache = getattr(st, "_ps60_cache", None)
            ps = cache[1] if cache else {}
            picked = play.get("side_set") or (play.get("stop") and play.get("target")) or (play.get("trigger") and play.get("second_entry"))
            se = (ps.get("state") if ps else None)
            mp = ps.get("mp") if ps else None
            atr_v = play.get("atr")
            try:
                atr_v = atr_v or _atr_of(e, st)
            except Exception:
                atr_v = None
            return {
                "symbol": st.symbol, "available": True, "source": "PS60",
                "direction": (play.get("side") or "long").upper() if picked else None,
                "entry": play.get("second_entry") or play.get("trigger"),
                "pivot": play.get("trigger"), "second_entry": play.get("second_entry"),
                "target_1": play.get("target"), "target_2": (mp or {}).get("level") if isinstance(mp, dict) and (mp or {}).get("level") != play.get("target") else None,
                "stop": play.get("stop"), "atr": atr_v,
                "supply": [play.get("trigger"), play.get("target")] if play.get("side") == "short" and play.get("trigger") else None,
                "demand": [play.get("stop"), play.get("trigger")] if play.get("side") == "long" and play.get("trigger") else None,
                "setup_state": se, "grade": ps.get("grade") if ps else None, "why": ps.get("why") if ps else None,
                "extra_levels": list(play.get("extra_levels") or []),
            }


def _atr_of(engine, st):
    bars = st.bar_list(400)
    return engine._atr(st, bars) if bars else None
