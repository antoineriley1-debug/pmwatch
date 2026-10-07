"""The chart studies, ported line for line from Twiney's TradingView scripts so the numbers match:

- GAS + ATR ("new PS60 Gas + ATR"): the tank (prior completed day's ATR), the 1 / 2 / 3 ATR ladder off today's
  range, prev day high / low / close, locked premarket high / low and 9:30 open, after hours, old supply / demand
  (last finished month), whole numbers, the daily box / tight box, the second-entry helper, continuation odds
  (30-minute sample), day-after stats, next stop.
- AIRSPACE ("PS60 MP Airspace"): Bounce / Reject (nearest Daily EMA / SMA / BB under / over the bar, tip cleared),
  the stacked band and its far edge = MP, next MP, Weekly fallback, the MT SUPPLY / DEMAND Nx lines, the lights
  board (MP / FUEL / 50 SMA, OVERALL).
- UNVISITED HIGHS / LOWS ("new Unvisited Highs Lows"): Daily pivots price never came back to; a touch within reach
  dashes the line, a Daily CLOSE through clears it; close levels merge into one line.

Everything is computed from IBKR bars: Daily (completed days + today's regular-session bar built from the minute
bars, exactly the candle the chart draws), the 30-minute regular-session history (the CONT sample, and the 60-minute
candles from 9:30 like TradingView's), and 5-minute extended-hours bars (premarket / after hours / the 9:30 open).
Moving averages use the same formulas as the chart (EMA seeded with the SMA, population-stdev Bollinger bands) and
ATR is Wilder's (TradingView's ta.atr), so a study's 20 EMA is the chart's 20 EMA to the cent.
"""

import math
from functools import lru_cache
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

# every colour and width comes from SETTINGS > Chart studies (defaults = the scripts' own)


def K(cfg, key):
    """A colour from SETTINGS > Chart studies (the scripts' defaults when not set)."""
    return str(cfg.get(key) or DEFAULT_COL.get(key, "#9e9e9e"))


def zone_col(cfg, key):
    h = K(cfg, key).lstrip("#")
    a = max(0.0, min(1.0, float(cfg.get("zone_opacity", 18)) / 100.0))
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{a:.2f})"


def _default_cols():
    from .config import DEFAULTS
    return {k: v for k, v in DEFAULTS["studies"].items() if k.startswith("col_")}


DEFAULT_COL = _default_cols()


# --------------------------------------------------------------------------------------------- time helpers

@lru_cache(maxsize=262144)
def ny(t):
    # the same bar times are converted again and again (every study, every second): remembered (pure, immutable)
    return datetime.fromtimestamp(t, tz=timezone.utc).astimezone(NY)


@lru_cache(maxsize=262144)
def day_key(t):
    d = ny(t)
    return d.year * 10000 + d.month * 100 + d.day


def ny_secs(t):
    d = ny(t)
    return d.hour * 3600 + d.minute * 60 + d.second


@lru_cache(maxsize=262144)
def session_open(t):
    """Epoch of 9:30 New York on t's New York date."""
    d = ny(t)
    return datetime(d.year, d.month, d.day, 9, 30, tzinfo=NY).timestamp()


@lru_cache(maxsize=262144)
def is_rth(t):
    d = ny(t)
    s = d.hour * 3600 + d.minute * 60 + d.second
    return d.weekday() < 5 and 34200 <= s < 57600


def fmt_key(k):
    y, m, d = k // 10000, (k // 100) % 100, k % 100
    return f"{MONTHS[m - 1]} {d} '{y % 100:02d}"


def f2(v):
    return None if v is None else round(v * 100.0) / 100.0


def s2(v):
    """Pine str.tostring(f2(v)): 141.5 prints as 141.5, 141.54 as 141.54."""
    if v is None:
        return "—"
    x = f2(v)
    return f"{x:.2f}".rstrip("0").rstrip(".") if abs(x - round(x)) > 1e-9 else str(int(round(x)))


def px(v):
    """A price the way the chart prints it (two decimals)."""
    return "—" if v is None else f"{v:.2f}"


# --------------------------------------------------------------------------------------------- series (Pine-exact)

def sma(src, n):
    out = [None] * len(src)
    s = 0.0
    for i, v in enumerate(src):
        s += v
        if i >= n:
            s -= src[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def ema(src, n):
    """EMA seeded with the SMA of the first n values (the chart's emaSeries)."""
    out = [None] * len(src)
    if len(src) < n:
        return out
    k = 2.0 / (n + 1)
    e = sum(src[:n]) / n
    out[n - 1] = e
    for i in range(n, len(src)):
        e = src[i] * k + e * (1 - k)
        out[i] = e
    return out


def rma(src, n):
    """Wilder's moving average (ta.rma): seeded with the SMA, then alpha = 1/n."""
    out = [None] * len(src)
    if len(src) < n:
        return out
    e = sum(src[:n]) / n
    out[n - 1] = e
    for i in range(n, len(src)):
        e = (src[i] + (n - 1) * e) / n
        out[i] = e
    return out


def wma(src, n):
    out = [None] * len(src)
    den = n * (n + 1) / 2.0
    for i in range(n - 1, len(src)):
        out[i] = sum(src[i - n + 1 + j] * (j + 1) for j in range(n)) / den
    return out


def true_range(h, l, c):
    """ta.tr(true): the first bar's TR is its high - low."""
    out = []
    for i in range(len(h)):
        out.append(h[i] - l[i] if i == 0 else max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])))
    return out


def atr_rma(h, l, c, n=14):
    return rma(true_range(h, l, c), n)


def atr_series(h, l, c, n=14, smoothing="RMA"):
    trv = true_range(h, l, c)
    return {"EMA": ema, "SMA": sma, "WMA": wma}.get(str(smoothing).upper(), rma)(trv, n)


def bbands(src, n=20, mult=2.0):
    up, dn = [None] * len(src), [None] * len(src)
    for i in range(n - 1, len(src)):
        w = src[i - n + 1:i + 1]
        m = sum(w) / n
        sd = math.sqrt(max(0.0, sum(x * x for x in w) / n - m * m))
        up[i], dn[i] = m + mult * sd, m - mult * sd
    return up, dn


def pivot_at(vals, i, left, right, high=True):
    """ta.pivothigh / ta.pivotlow evaluated on bar i: the value at i - right when it is above (below) every bar
    `left` to its left and not exceeded by the `right` bars to its right. None otherwise."""
    c = i - right
    if c - left < 0 or i >= len(vals):
        return None
    v = vals[c]
    if high:
        if any(vals[j] >= v for j in range(c - left, c)) or any(vals[j] > v for j in range(c + 1, i + 1)):
            return None
    else:
        if any(vals[j] <= v for j in range(c - left, c)) or any(vals[j] < v for j in range(c + 1, i + 1)):
            return None
    return v


# --------------------------------------------------------------------------------------------- the bars

def rth_minutes_today(st, t):
    """Today's regular-session minute bars [t0, o, h, l, c, v], oldest first."""
    dk = day_key(t)
    out = []
    any_time = getattr(st, "_any_session", False)        # the practice market trades whenever you run it
    for m in sorted(st.bars):
        if day_key(m) == dk and (any_time or is_rth(m)):
            b = st.bars[m]
            out.append([m, b[0], b[1], b[2], b[3], b[4]])
    return out


def daily_series(st, t):
    """Completed daily bars + today's regular-session bar built from the minute bars (the chart's daily candle).
    Rows [t0, o, h, l, c, v]; the second value says whether the last row is today's live bar."""
    dk = day_key(t)
    rows = [[k] + list(st.daily[k][:4]) + [float(st.daily_vol.get(k) or 0.0)] for k in sorted(st.daily) if day_key(k + 43200) < dk]
    mins = rth_minutes_today(st, t)
    live = False
    if mins:
        o = mins[0][1]
        h = max(b[2] for b in mins)
        l = min(b[3] for b in mins)
        rows.append([session_open(t) - 34200, o, h, l, mins[-1][4], sum(b[5] for b in mins)])
        live = True
    return rows, live


def weekly_from(daily):
    """Weekly bars (weeks start Monday, New York) from the daily rows."""
    out = []
    key = None
    for b in daily:
        d = ny(b[0] + 43200)
        k = d.isocalendar()[:2]
        if out and k == key:
            w = out[-1]
            w[2] = max(w[2], b[2]); w[3] = min(w[3], b[3]); w[4] = b[4]; w[5] += b[5]
        else:
            out.append(list(b)); key = k
    return out


def m30_series(st, t):
    """30-minute regular-session bars: IBKR's history for earlier days + today's built from the minute bars
    (aligned at 9:30, 10:00, ...). Rows [t0, o, h, l, c, v]."""
    dk = day_key(t)
    rows = [[k] + list(st.m30[k][:5]) for k in sorted(getattr(st, "m30", {}) or {}) if day_key(k) < dk and is_rth(k)]
    rows += bucket(rth_minutes_today(st, t), 1800)
    return rows


def bucket(mins, span):
    """Minute rows grouped into candles counted from that day's 9:30."""
    out = []
    for b in mins:
        o = session_open(b[0])
        t0 = o + math.floor((b[0] - o) / span) * span
        if out and out[-1][0] == t0:
            w = out[-1]
            w[2] = max(w[2], b[2]); w[3] = min(w[3], b[3]); w[4] = b[4]; w[5] += b[5]
        else:
            out.append([t0, b[1], b[2], b[3], b[4], b[5]])
    return out


def h60_from_m30(rows):
    """60-minute candles from 9:30 (9:30, 10:30, ... 15:30), two 30-minute bars each: TradingView's 60m."""
    out = []
    for b in rows:
        o = session_open(b[0])
        t0 = o + math.floor((b[0] - o) / 3600) * 3600
        if out and out[-1][0] == t0:
            w = out[-1]
            w[2] = max(w[2], b[2]); w[3] = min(w[3], b[3]); w[4] = b[4]; w[5] += b[5]
        else:
            out.append([t0, b[1], b[2], b[3], b[4], b[5]])
    return out


def ma_pack(closes, highs=None, lows=None, use_bb=True):
    """Dan's pack at the last bar: EMA 5/10/20/34/50/65/89/100/150/200, SMA 5/10/20/50/100/150/200, BB 20 / 2."""
    out = []
    for n in (5, 10, 20, 34, 50, 65, 89, 100, 150, 200):
        v = ema(closes, n)[-1] if closes else None
        out.append((f"EMA {n}", v))
    for n in (5, 10, 20, 50, 100, 150, 200):
        v = sma(closes, n)[-1] if closes else None
        out.append((f"SMA {n}", v))
    if use_bb and closes:
        up, dn = bbands(closes, 20, 2.0)
        out.append(("BB upper", up[-1])); out.append(("BB lower", dn[-1]))
    return out


# --------------------------------------------------------------------------------------------- GAS + ATR

def _f_tight(rows, win, sens):
    L = len(rows) - 1
    if L - win < 0:
        return None, None, 0, None
    rngs = [rows[L - i][2] - rows[L - i][3] for i in range(1, win + 1)]
    avg = sum(rngs) / len(rngs)
    wild = sum(1 for r in rngs if r > sens * avg)
    hh = max(rows[L - i][2] for i in range(1, win + 1))
    ll = min(rows[L - i][3] for i in range(1, win + 1))
    return hh, ll, wild, rows[L - win][0]


def prev_month_hl(rows, t):
    """Old supply / demand: the last FINISHED month's high and low."""
    d = ny(t)
    y, m = (d.year, d.month - 1) if d.month > 1 else (d.year - 1, 12)
    hs = [b[2] for b in rows if (ny(b[0] + 43200).year, ny(b[0] + 43200).month) == (y, m)]
    ls = [b[3] for b in rows if (ny(b[0] + 43200).year, ny(b[0] + 43200).month) == (y, m)]
    return (max(hs), min(ls)) if hs else (None, None)


def session_levels(st, t):
    """Locked premarket high / low (4:00-9:30 today), the last COMPLETED after-hours session's high / low
    (16:00-20:00) and today's 9:30 open, from the 5-minute extended-hours bars plus today's live minutes."""
    dk = day_key(t)
    # the 5-minute extended-hours bars AND the 1-minute bars (the same trades: highs and lows agree, either may hold
    # minutes the other is missing); the 1-minute bar, starting later, sets the close
    bars = [[k] + list(st.m5x[k][:4]) for k in sorted(getattr(st, "m5x", {}) or {})]
    bars += [[m, b[0], b[1], b[2], b[3]] for m, b in sorted(st.bars.items()) if m >= t - 5 * 86400]
    pm_h = pm_l = pm_c = pm_ct = open_ = open_t = None
    ah = {}
    # the 1-minute bars win where both exist (5-minute bars of the same minutes add nothing, the 1-minute close is
    # exact); bars are walked oldest first, so the last one before 9:30 / 20:00 sets the close
    for b in sorted(bars, key=lambda x: x[0]):
        k, s = day_key(b[0]), ny_secs(b[0])
        if k == dk and 4 * 3600 <= s < 34200:
            pm_h = b[2] if pm_h is None else max(pm_h, b[2])
            pm_l = b[3] if pm_l is None else min(pm_l, b[3])
            if pm_ct is None or b[0] >= pm_ct:
                pm_c, pm_ct = b[4], b[0]
        if k == dk and 34200 <= s < 57600 and (open_t is None or b[0] < open_t):
            open_, open_t = b[1], b[0]
        if 57600 <= s < 72000 and k < dk:
            a = ah.setdefault(k, [b[2], b[3], b[4], b[0]])
            a[0] = max(a[0], b[2]); a[1] = min(a[1], b[3])
            if b[0] >= a[3]:
                a[2], a[3] = b[4], b[0]
    last_ah = ah[max(ah)] if ah else None
    return {"pmh": pm_h, "pml": pm_l, "pmc": pm_c, "ahh": last_ah[0] if last_ah else None, "ahl": last_ah[1] if last_ah else None,
            "ahc": last_ah[2] if last_ah else None, "open": open_, "open_t": open_t}


def cont_odds(drows, m30, t, cfg, today_live, y_atr, prev_c):
    """The continuation odds (Gas f_prob30): each past day's ATR progress at the twelve 30-minute checkpoints
    (10:00 ... 15:30) and its finish; today's progress at the current checkpoint matched within the tolerance."""
    tol, t1, t2 = float(cfg["cont_tol"]), float(cfg["cont_t1"]), float(cfg["cont_t2"])
    max_days = int(cfg["cont_max_days"])
    # each day's ATR (prior completed day, the tank) and prior close
    hs = [b[2] for b in drows]; ls = [b[3] for b in drows]; cs = [b[4] for b in drows]
    a = atr_series(hs, ls, cs, int(cfg["atr_len"]), cfg["atr_smoothing"])
    prior = {}
    for i in range(1, len(drows)):
        prior[day_key(drows[i][0] + 43200)] = (a[i - 1], cs[i - 1])
    dk_now = day_key(t)
    days = {}
    for b in m30:
        days.setdefault(day_key(b[0]), []).append(b)
    sample = []          # (key, cp12, finish)
    for k in sorted(days):
        if k >= dk_now:
            continue
        pa, pc = prior.get(k, (None, None))
        if not pa or pa <= 0:
            continue
        cp, lp = _progress(days[k], pa, pc)
        if lp is not None:
            sample.append((k, cp, lp))
    sample = sample[-max_days:]
    k_now, lp_now = -1, None
    today = days.get(dk_now) or []
    if today and y_atr:
        mins = (today[-1][0] - session_open(today[-1][0])) / 60.0
        for k in range(12):
            if mins >= 30.0 * (k + 1):
                k_now = k
        _, lp_now = _progress(today, y_atr, prev_c)
    n = h1 = h2 = 0
    s = 0.0
    if k_now >= 0 and lp_now is not None:
        for _k, cp, fin in sample:
            v = cp[k_now]
            if v is not None and abs(v - lp_now) <= tol:
                n += 1; s += fin
                h1 += fin >= t1
                h2 += fin >= t2
    return {"n": n, "h1": h1, "h2": h2, "sum": s, "tot": len(sample), "first": sample[0][0] if sample else None,
            "prog": lp_now, "k": k_now, "t1": t1, "t2": t2, "min_days": int(cfg["cont_min_days"])}


def _progress(bars, atr_v, prev_c):
    cp = [None] * 12
    hh = ll = lp = None
    for b in bars:
        mins = (b[0] - session_open(b[0])) / 60.0
        if hh is not None:
            u = max(hh - ll, abs(hh - prev_c), abs(ll - prev_c)) if prev_c is not None else hh - ll
            pre = u / atr_v
            for k in range(12):
                if mins >= 30.0 * (k + 1) and cp[k] is None:
                    cp[k] = pre
        hh = b[2] if hh is None else max(hh, b[2])
        ll = b[3] if ll is None else min(ll, b[3])
        u = max(hh - ll, abs(hh - prev_c), abs(ll - prev_c)) if prev_c is not None else hh - ll
        lp = u / atr_v
    return cp, lp


def day_after(drows, live, cfg):
    """Day-after stats: every completed day bucketed by the tanks the day BEFORE burned; what the next day did."""
    hs = [b[2] for b in drows]; ls = [b[3] for b in drows]; cs = [b[4] for b in drows]
    a = atr_series(hs, ls, cs, int(cfg["atr_len"]), cfg["atr_smoothing"])
    trv = true_range(hs, ls, cs)
    x = [None] * len(drows)
    for i in range(1, len(drows)):
        if a[i - 1]:
            x[i] = trv[i] / a[i - 1]
    n = [0] * 4; sm = [0.0] * 4; dg = [0] * 4; tr_ = [0] * 4
    first = None
    last_conf = len(drows) - (2 if live else 1)
    for i in range(2, last_conf + 1):
        if x[i] is None or x[i - 1] is None:
            continue
        if first is None:
            first = day_key(drows[i][0] + 43200)
        b = 3 if x[i - 1] >= 1.5 else 2 if x[i - 1] >= 1.0 else 1 if x[i - 1] >= 0.5 else 0
        n[b] += 1; sm[b] += x[i]
        dg[b] += x[i] < 0.8
        tr_[b] += x[i] >= 1.2
    xref = x[-2] if live and len(x) > 1 else x[-1] if x else None
    if xref is None:
        return None
    b = 3 if xref >= 1.5 else 2 if xref >= 1.0 else 1 if xref >= 0.5 else 0
    lbl = ("quiet (under 0.5x)", "normal (0.5-1x)", "extended (1-1.5x)", "blowout (1.5x+)")[b]
    if n[b] < 5:
        return {"line": f"only {n[b]} {lbl} days in history — not enough to lean on", "line2": "", "col": "rgba(0,0,0,.8)", "txt": "#b2b5be"}
    run_p, chop_p = 100.0 * tr_[b] / n[b], 100.0 * dg[b] / n[b]
    verdict = "USUALLY KEEPS RUNNING" if run_p >= 40 else "USUALLY COOLS OFF" if chop_p >= 50 else "NO STRONG LEAN"
    col = "#26a69a" if run_p >= 40 else "#ffd500" if chop_p >= 50 else "#787b86"
    return {"line": f"DAY AFTER a {lbl} day: {verdict} · typical {s2(sm[b] / n[b])}x",
            "line2": f"{n[b]} days like the last one since {fmt_key(first)}: {tr_[b]} ran again (1.2x+) · "
                     f"{n[b] - dg[b] - tr_[b]} normal · {dg[b]} chopped (under 0.8x)",
            "col": col, "txt": "#ffffff" if run_p >= 40 else "#000000"}


def second_entry(st, t, cfg, y_atr, piv, side, tb):
    """The second-entry helper on today's regular-session minutes. Pivot = YOUR pivot on the chart (the play's), or
    the tight box edges when the Tight Box master is on and the box is real. 1st push through the pivot, then a
    retrace of retrace% of the push (and at least min × ATR) arms the 2nd; hourly reset = miss the 60, need a new one."""
    if not cfg["second_entry"]:
        return None
    auto = bool(cfg["tight_box"]) and tb and tb.get("valid")
    if not auto and not piv:
        return None
    mins = rth_minutes_today(st, t)
    thru, ext, pulled, s_side, pivot = False, None, False, side, piv
    hour = None
    floor_r = float(cfg["se_min_retrace_x"]) * y_atr if y_atr else 0.0
    pct = float(cfg["se_retrace_pct"])
    for b in mins:
        o = session_open(b[0])
        hk = math.floor((b[0] - o) / 3600)
        if cfg["se_hour_reset"] and hour is not None and hk != hour:
            ext, pulled = None, False
        hour = hk
        hi, lo = b[2], b[3]
        if not thru:
            if auto:
                if hi > tb["hi"]:
                    thru, s_side, pivot, ext = True, "Long", tb["hi"], hi
                elif lo < tb["lo"]:
                    thru, s_side, pivot, ext = True, "Short", tb["lo"], lo
            elif side == "Short":
                if lo < piv:
                    thru, s_side, pivot, ext = True, "Short", piv, lo
            elif hi > piv:
                thru, s_side, pivot, ext = True, "Long", piv, hi
        else:
            if s_side == "Long":
                ext = hi if ext is None else max(ext, hi)
                push = ext - pivot
                need = max(push * pct / 100.0, floor_r)
                if not pulled and push > 0 and need > 0 and lo <= ext - need:
                    pulled = True
            else:
                ext = lo if ext is None else min(ext, lo)
                push = pivot - ext
                need = max(push * pct / 100.0, floor_r)
                if not pulled and push > 0 and need > 0 and hi >= ext + need:
                    pulled = True
    last = st.price()
    # Rule 2: the 60-minute candle building over / under the one before it
    h60 = h60_from_m30(m30_series(st, t))
    conf60 = 0
    if len(h60) >= 2 and last is not None:
        p = h60[-2]
        conf60 = 1 if last > p[2] else -1 if last < p[3] else 0
    near = bool(thru and pulled and ext is not None and y_atr and last is not None and abs(last - ext) <= float(cfg["se_near_x"]) * y_atr)
    piv_txt = f"{s2(tb['hi'])} / {s2(tb['lo'])}" if auto and not thru else s2(pivot)
    c60 = (" · 60m ✔" if (conf60 == 1 if s_side == "Long" else conf60 == -1) else " · 60m ✖") if thru else ""
    text = ("WAIT through " + piv_txt if not thru else f"THROUGH  push {s2(ext)}  wait retrace" if not pulled
            else f"2ND NEAR  {s2(ext)}" if near else f"2ND ARMED  {s2(ext)}") + c60
    return {"thru": thru, "pulled": pulled, "near": near, "ext": ext, "pivot": pivot, "side": s_side, "text": text}


LADDER_COLS = ((0.25, "#26a69a"), (0.50, "#8bc34a"), (0.75, "#ffd500"), (1.00, "#ff9800"), (1.25, "#ef5350"),
               (1.50, "#e91e63"), (9.99, "#8a00ff"))
FRAC = {0.25: "¼", 0.5: "½", 0.75: "¾"}
LADDER_TXT = {"#8bc34a": "#4e8a1c", "#ffd500": "#a88a00"}      # lime / yellow words read darker, on any screen


def _rgba(h, a):
    h = h.lstrip("#")
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{a:.2f})"


def _rung_name(m):
    whole, part = int(m), round(m - int(m), 2)
    if not part:
        return f"{whole} ATR"
    return f"{'' if not whole else whole}{FRAC[part]} ATR"


def atr_ladder(dH, dL, used, y_atr, move_up, one_side, cfg, last=None):
    """THE ATR LADDER: today's tank cut into quarter-ATR rungs, measured from where the day's move started (the low
    for a move up, the high for a move down; a gap counts, the same true range the GAS readout uses). The slice of
    each rung that price has already EATEN is coloured, getting hotter as the tank empties (green, lime, yellow,
    orange at 1 ATR, red, pink, purple beyond 1½); what is still left stays a faint outline. Every rung not eaten
    yet says how many dollars it is away from the price now."""
    step = float(cfg.get("atr_ladder_step", 0.25)) or 0.25
    top = max(step, float(cfg.get("atr_ladder_max", 2.0)))
    a_on = max(0.0, min(1.0, float(cfg.get("atr_ladder_opacity", 32)) / 100.0))
    a_off = max(0.0, min(1.0, float(cfg.get("atr_ladder_left_opacity", 4)) / 100.0))
    zones, lines = [], []
    for up in (True, False):
        if one_side and up != move_up:
            continue
        base = dH - used if up else dL + used      # where the day's true range starts on this side
        reach = dH if up else dL                   # how far price has eaten on this side
        eaten = max(0.0, (reach - base) if up else (base - reach))
        if not one_side and up != move_up and eaten <= 0:
            continue
        m, k, told = step, 0, False
        while m <= top + 1e-9 and k < 40:
            lo_m = m - step
            col = next(c for lim, c in LADDER_COLS if m <= lim + 1e-9)
            a = base + (lo_m * y_atr if up else -lo_m * y_atr)
            b = base + (m * y_atr if up else -m * y_atr)
            band = abs(b - a)
            ate = max(0.0, min(band, eaten - lo_m * y_atr))
            if ate > 0:
                e = a + (ate if up else -ate)
                zones.append({"a": a, "b": e, "c": _rgba(col, a_on), "eat": round(m, 2)})
                if ate < band:
                    zones.append({"a": e, "b": b, "c": _rgba(col, a_off), "eat": 0})
            else:
                zones.append({"a": a, "b": b, "c": _rgba(col, a_off), "eat": 0})
            spent = eaten >= m * y_atr - 1e-9
            whole = abs(m - round(m)) < 1e-9
            if spent:
                lbl = f"{_rung_name(m)} EATEN {b:.2f}"
            else:
                away = f" · ${abs(b - last):.2f} away" if last is not None else ""
                if not told:                       # the next rung: how much of the tank is gone
                    told = True
                    lbl = f"{_rung_name(m)} {b:.2f}{away} · {round(eaten / y_atr * 100)}% eaten"
                else:
                    lbl = f"{_rung_name(m)} {b:.2f}{away}"
            lines.append({"p": b, "c": col, "w": 2 if whole else 1, "d": "solid" if whole else "dot", "l": lbl, "lc": LADDER_TXT.get(col, col),
                          "t0": None, "g": "gas", "rung": round(m, 2), "eaten": spent})
            m += step; k += 1
    return {"zones": zones, "lines": lines}


def gas(st, t, cfg, drows, live):
    """GAS + ATR, the whole script's chart output: levels, zones, box, readout rows."""
    if len(drows) < 3:
        return {"lines": [], "zones": [], "box": None, "rows": [{"t": "GAS · waiting for daily history from IBKR", "bg": "#787b86", "fg": "#000"}],
            "se": None}
    hs = [b[2] for b in drows]; ls = [b[3] for b in drows]; cs = [b[4] for b in drows]
    atr = atr_series(hs, ls, cs, int(cfg["atr_len"]), cfg["atr_smoothing"])
    L = len(drows) - 1
    y_atr, next_atr = atr[L - 1], atr[L]
    dT, dO, dH, dL = drows[L][0], drows[L][1], drows[L][2], drows[L][3]
    prev_c = cs[L - 1]
    is_today = live
    last = st.price() or cs[L]
    used = max(dH - dL, abs(dH - prev_c), abs(dL - prev_c)) if is_today else 0.0
    left = max(0.0, y_atr - used) if y_atr else None
    pct_left = max(0.0, 100.0 - used / y_atr * 100.0) if y_atr else None
    x_atr = used / y_atr if y_atr else None
    lines, zones = [], []

    def lv(y, col, name, w=1, dash="solid", lc=None, t0=None):
        if y is not None:
            lines.append({"p": y, "c": col, "w": w, "d": dash, "l": name, "lc": lc or col, "t0": t0, "g": "gas"})

    def nm(base, y):
        return f"{base} {s2(y)}" if y is not None and cfg.get("lbl_price", True) else base

    wpd, watr, wlv = int(cfg.get("lw_pd", 2)), int(cfg.get("lw_atr", 2)), int(cfg.get("lw_levels", 1))

    # box / tight box
    box = None
    hh, ll, wild, tb_t0 = _f_tight(drows, int(cfg["tb_window"]), float(cfg["tb_wild_x"]))
    ht_x = (hh - ll) / y_atr if hh is not None and y_atr else None
    tb = {"hi": hh, "lo": ll, "valid": ht_x is not None and ht_x <= float(cfg["tb_max_x"]) and (not cfg["tb_reject_wild"] or wild == 0),
          "wild": wild, "htx": ht_x, "t0": tb_t0}
    if cfg["tight_box"]:
        if tb["valid"]:
            box = {"t0": tb_t0, "hi": hh, "lo": ll, "c": K(cfg, "col_tight_box")}
            lv(hh, K(cfg, "col_tight_box"), f"TIGHT BOX EDGE {s2(hh)} · {s2(ht_x)}x ATR tall")
            lv(ll, K(cfg, "col_tight_box"), f"TIGHT BOX EDGE {s2(ll)}")
    elif cfg["daily_box"]:
        n = int(cfg["box_len"])
        if len(drows) >= n:
            bh = max(hs[-n:]); bl = min(ls[-n:])
            if not cfg["box_tight_only"] or (y_atr and bh - bl <= float(cfg["box_tight_x"]) * y_atr):
                box = {"t0": drows[-n][0], "hi": bh, "lo": bl, "c": K(cfg, "col_box")}
                lv(bh, K(cfg, "col_box"), f"BOX EDGE {s2(bh)}"); lv(bl, K(cfg, "col_box"), f"BOX EDGE {s2(bl)}")
    # the last completed session's levels (yesterday: today's bar is still forming)
    pdr = drows[L - 1] if live else drows[L]
    if cfg["old_supply_demand"]:
        osup, odem = prev_month_hl(drows, t)
        lv(osup, K(cfg, "col_old_supply"), nm("old supply", osup), wpd); lv(odem, K(cfg, "col_old_demand"), nm("old demand", odem), wpd)
    if cfg["prev_day"]:
        lv(pdr[2], K(cfg, "col_pd"), nm("PDH", pdr[2]), wpd); lv(pdr[3], K(cfg, "col_pd"), nm("PDL", pdr[3]), wpd)
        lv(pdr[4], K(cfg, "col_pdc"), nm("PDC", pdr[4]), wlv, "dot")
    sess = session_levels(st, t)
    if cfg["premarket"]:
        lv(sess["pmh"], K(cfg, "col_pm"), nm("PMH", sess["pmh"]), wlv, "dash"); lv(sess["pml"], K(cfg, "col_pm"), nm("PML", sess["pml"]), wlv, "dash")
        lv(sess["pmc"], K(cfg, "col_pm"), nm("PM CLOSE", sess["pmc"]), wlv, "dot")
    if cfg["after_hours"]:
        lv(sess["ahh"], K(cfg, "col_ah"), nm("AHH", sess["ahh"]), wlv, "dash"); lv(sess["ahl"], K(cfg, "col_ah"), nm("AHL", sess["ahl"]), wlv, "dash")
        lv(sess["ahc"], K(cfg, "col_ah"), nm("AH CLOSE", sess["ahc"]), wlv, "dot")
    if cfg["open_line"] and sess["open"] is not None:
        lv(sess["open"], K(cfg, "col_open"), nm("TODAY'S OPEN", sess["open"]), wlv, "solid", t0=sess["open_t"])
    er = earnings_range(drows, cfg)
    if er:
        lv(er[0], K(cfg, "col_earnings"), nm("EARN H", er[0]), wpd); lv(er[1], K(cfg, "col_earnings"), nm("EARN L", er[1]), wpd)
    # the ATR ladder: today's developing range; market closed = the last session's final ladder
    used_lad = used if is_today else max(dH - dL, abs(dH - prev_c), abs(dL - prev_c))
    if cfg["atr_levels"] and y_atr:
        r = {m: m * y_atr - used_lad for m in (1.0, 1.5, 2.0, 2.5, 3.0)}
        move_up = (dH - prev_c) >= (prev_c - dL)
        one = bool(cfg["atr_one_side"])
        keep_up = (lambda rv: move_up) if one else (lambda rv: rv > 0 or move_up)
        keep_dn = (lambda rv: not move_up) if one else (lambda rv: rv > 0 or not move_up)
        lv(dH, K(cfg, "col_hl"), nm("HIGH OF DAY", dH), wlv); lv(dL, K(cfg, "col_hl"), nm("LOW OF DAY", dL), wlv)

        def tag(ms, y, spent, m):
            return f"{ms} Traveled ${s2(m * y_atr)} @ {s2(y)}" if spent else f"{ms} ${s2(m * y_atr)} · {s2(y)} · ${abs(y - last):.2f} away"
        ys = {}
        for m in (1.0, 2.0, 3.0) + ((1.5, 2.5) if cfg["atr_halves"] else ()):
            ms = f"{m:g} ATR"
            sp = r[m] <= 0
            for up in (True, False):
                if (keep_up if up else keep_dn)(r[m]):
                    y = dH + r[m] if up else dL - r[m]
                    ys[(m, up)] = y
                    if cfg["atr_zones"]:
                        continue                # the ATR ladder below draws these rungs itself
                    lv(y, K(cfg, "col_atr_spent") if sp else K(cfg, "col_atr_live"), tag(ms, y, sp, m), watr if m == 1.0 else max(1, watr - 1))
        if cfg["atr_zones"]:
            lad = atr_ladder(dH, dL, used_lad, y_atr, move_up, one, cfg, last)
            zones += lad["zones"]
            lines += lad["lines"]
    if cfg["whole_numbers"]:
        step = whole_step(last, float(cfg["whole_step"]))
        base = round(last / step) * step
        for i in range(1, int(cfg["whole_above"]) + 1):
            lv(base + step * i, K(cfg, "col_whole"), f"WHOLE {base + step * i:.2f}", wlv)
        for i in range(1, int(cfg["whole_below"]) + 1):
            lv(base - step * i, K(cfg, "col_whole"), f"WHOLE {base - step * i:.2f}", wlv)
    play = st.play or {}
    side = "Short" if play.get("side") == "short" else "Long"
    se = second_entry(st, t, cfg, y_atr, play.get("trigger"), side, tb)
    if se and se["ext"] is not None:
        lv(se["ext"], K(cfg, "col_2nd"), "2ND" if se["pulled"] else "1st push", wpd)
        lv(se["pivot"], K(cfg, "col_2nd"), f"pivot {s2(se['pivot'])}", 1, "dot")
    # the readout (bottom right)
    rows = []
    if cfg["gas_readout"]:
        rvol = rvol_now(st, t)
        if not is_today:
            t1 = f"GAS waiting 9:30   tank {s2(y_atr)} · next session tank {s2(next_atr)}"
            ul = max(dH - dL, abs(dH - prev_c), abs(dL - prev_c))
            t2 = f"last session traveled {s2(ul / y_atr)}x ATR · used {s2(ul)} of {s2(y_atr)} tank" if y_atr else "—"
            bg = "#787b86"
        else:
            t1 = f"GAS {round(pct_left)}% left   {s2(x_atr)}x ATR traveled" + (f" · RVOL {s2(rvol)}x" if rvol else "")
            t2 = f"used {s2(used)} / tank {s2(y_atr)}   left {s2(left)}"
            bg = "#4caf50" if pct_left >= 40 else "#ffd500" if pct_left >= 15 else "#d78585"
        rows.append({"t": t1, "bg": bg, "fg": "#000"})
        rows.append({"t": t2, "bg": "rgba(0,0,0,.8)", "fg": "#fff"})
        if cfg["day_after"]:
            da = day_after(drows, live, cfg)
            if da:
                rows.append({"t": da["line"], "bg": da["col"], "fg": da["txt"]})
                if da["line2"]:
                    rows.append({"t": da["line2"], "bg": "rgba(0,0,0,.8)", "fg": "#b2b5be"})
        if cfg["cont_odds"]:
            rows += cont_rows(_cont(st, t, cfg, drows, live, y_atr, prev_c), "gas")
    se_row = None
    if se:
        se_row = {"t": se["text"], "bg": K(cfg, "col_2nd") if se["near"] else "rgba(0,0,0,.8)", "fg": "#fff"}
    elif cfg["second_entry"] and cfg["tight_box"]:
        why = ("building daily data" if tb["htx"] is None else f"{tb['wild']} wild bar(s) in window" if cfg["tb_reject_wild"] and tb["wild"] > 0
               else f"range {s2(tb['htx'])}x ATR > {s2(float(cfg['tb_max_x']))}x limit")
        se_row = {"t": "NO BOX — " + why, "bg": "rgba(0,0,0,.8)", "fg": "#ffd54f"}
    return {"lines": lines, "zones": zones, "box": box, "rows": rows, "se": se_row, "y_atr": y_atr, "left": left,
            "used": used, "today": is_today, "pdr": pdr, "sess": sess,
            "next_stop": next_stop_levels(drows, live, st, t, cfg, y_atr, used, is_today, sess, dH, dL) if cfg["next_stop"] else None}


def _cont(st, t, cfg, drows, live, y_atr, prev_c):
    """The CONT odds once per symbol per moment (GAS and the Airspace board read the same numbers)."""
    key = (int(t // 60), len(drows), len(getattr(st, "m30", {}) or {}))   # the 30-minute sample: once a minute is plenty
    memo = st.__dict__.setdefault("_cont_memo", {})
    if memo.get("k") != key:
        memo["k"], memo["v"] = key, cont_odds(drows, m30_series(st, t), t, cfg, live, y_atr, prev_c)
    return memo["v"]


def cont_rows(c, who):
    """The CONT readout lines (Gas wording)."""
    out = []
    if c["k"] < 0:
        return [{"t": "TODAY · odds start at 10:00", "bg": "#1a1a2e", "fg": "#4deeea"}]
    if c["tot"] < c["min_days"]:
        return [{"t": f"TODAY · building sample ({c['tot']} days stored)", "bg": "#1a1a2e", "fg": "#4deeea"}]
    if c["prog"] is None:
        return [{"t": "TODAY · no data yet", "bg": "#1a1a2e", "fg": "#4deeea"}]
    if c["n"] == 0:
        return [{"t": "TODAY · no similar days in sample", "bg": "#1a1a2e", "fg": "#4deeea"}]
    p1 = 100.0 * c["h1"] / c["n"]
    p2 = 100.0 * c["h2"] / c["n"]
    out.append({"t": f"TODAY · {c['n']} similar days  {round(p1)}% ≥{c['t1']:g}x  {round(p2)}% ≥{c['t2']:g}x  avg {s2(c['sum'] / c['n'])}x",
                "bg": "#1a1a2e", "fg": "#4deeea"})
    thin = " (thin sample, trust it less)" if c["n"] < 10 else ""
    out.append({"t": ("STRONG GO" if p1 >= 70 else "LEANS GO" if p1 >= 55 else "COIN FLIP" if p1 >= 45 else "USUALLY STALLS") + f" — {round(p1)}% continued{thin}",
                "bg": "#26a69a" if p1 >= 55 else "#ffd500" if p1 >= 45 else "#ef5350", "fg": "#000" if p1 >= 45 else "#fff"})
    out.append({"t": f"TODAY · {c['n']} days looked like today. {c['h1']} reached {c['t1']:g}x, {c['h2']} reached {c['t2']:g}x. Typical finish {s2(c['sum'] / c['n'])}x.",
                "bg": "#1a1a2e", "fg": "#4deeea"})
    out.append({"t": f"TODAY · {c['n']} of {c['tot']} days scanned, {fmt_key(c['first'])} – today ({round(100.0 * c['n'] / c['tot'])}% match)",
                "bg": "#1a1a2e", "fg": "rgba(77,238,234,.7)"})
    return out


def whole_step(p, step_in):
    return step_in if step_in > 0 else 5.0 if p >= 200 else 1.0 if p >= 80 else 0.5


def rvol_now(st, t):
    """Today's regular-session volume against the average of the last 20 sessions, scaled by how much of the session
    is done (the scripts' RVOL)."""
    mins = rth_minutes_today(st, t)
    if not mins:
        return None
    days = {}
    for k, b in (getattr(st, "m30", {}) or {}).items():
        dk = day_key(k)
        if dk < day_key(t) and is_rth(k):
            days[dk] = days.get(dk, 0.0) + float(b[4] or 0.0)
    vols = [days[k] for k in sorted(days)][-20:]
    if len(vols) < 5 or not sum(vols):
        return None
    cum = sum(b[5] for b in mins)
    frac = min(1.0, max(0.08, (t - session_open(t)) / 60.0 / 390.0))
    return cum / (sum(vols) / len(vols) * frac)


def earnings_range(drows, cfg):
    """Earnings reaction bar from the MANUAL release date (IBKR's API has no earnings calendar): the first full
    session after an after-close report, or the report day itself for a pre-market report."""
    raw = str(cfg.get("earnings_date") or "").strip()
    if not raw:
        return None
    try:
        y, m, d = (int(x) for x in raw.replace("/", "-").split("-"))
    except ValueError:
        return None
    mk = y * 10000 + m * 100 + d
    for i, b in enumerate(drows):
        k = day_key(b[0] + 43200)
        if (k == mk) if not cfg.get("earnings_next_session", True) else (k > mk and (i == 0 or day_key(drows[i - 1][0] + 43200) <= mk)):
            return (b[2], b[3], b[0])
    return None


def next_stop_levels(drows, live, st, t, cfg, y_atr, used, is_today, sess, dH, dL):
    """NEXT STOP candidates (the page adds the chart's own 65 EMA and picks the nearest above / below)."""
    out = []
    comp = drows[:-1] if live else drows
    cs = [b[4] for b in comp]
    for n in (4, 9, 10, 13, 20, 50, 65, 89, 100, 200):
        v = ema(cs, n)[-1] if cs else None
        if v is not None:
            out.append([v, f"EMA{n} D"])
    h60 = h60_from_m30(m30_series(st, t))
    hc = [b[4] for b in h60]
    for n in (4, 9, 10, 13, 20, 50, 65, 100, 200):
        v = ema(hc, n)[-1] if hc else None
        if v is not None:
            out.append([v, f"EMA{n} 60m"])
    pdr = drows[-2] if live else drows[-1]
    out += [[pdr[2], "PDH"], [pdr[3], "PDL"]]
    osup, odem = prev_month_hl(drows, t)
    for v, nmx in ((osup, "old supply"), (odem, "old demand"), (sess["pmh"], "PMH"), (sess["pml"], "PML")):
        if v is not None:
            out.append([v, nmx])
    if is_today and y_atr:
        for m in (1.0, 2.0, 3.0) + ((1.5, 2.5) if cfg["atr_halves"] else ()):
            rem = m * y_atr - used
            if rem > 0:
                out += [[dH + rem, f"{m:g} ATR"], [dL - rem, f"{m:g} ATR"]]
    sma50 = sma(cs, 50)[-1] if len(cs) >= 50 else None
    last10 = [[b[2], b[3], b[4]] for b in comp[-10:]][::-1]
    return {"levels": out, "sma50": sma50, "last10": last10, "y_atr": y_atr, "left": max(0.0, y_atr - used) if y_atr else None,
            "dH": dH if is_today else None, "dL": dL if is_today else None,
            "step": whole_step(st.price() or cs[-1], float(cfg["whole_step"]))}


# --------------------------------------------------------------------------------------------- AIRSPACE

def _tag(nm):
    """f_tag: "EMA 20" -> 20E, "SMA 50" -> 50S, BB upper -> BbU; Weekly names keep a W."""
    raw, w = nm, ""
    if nm.startswith("W "):
        raw, w = nm[2:], "W"
    if raw.startswith("EMA "):
        t = raw[4:] + "E"
    elif raw.startswith("SMA "):
        t = raw[4:] + "S"
    else:
        t = {"BB upper": "BbU", "BB lower": "BbL", "LR upper": "LR U", "LR lower": "LR L"}.get(raw, raw)
    return w + t


def _is_ind(nm):
    raw = nm[2:] if nm.startswith("W ") else nm
    return raw.startswith("EMA ") or raw.startswith("SMA ") or raw in ("BB upper", "BB lower")


def f_levels(rows, prefix, cfg, atr_v):
    """Airspace f_levels on one series (Daily or Weekly) at its last bar: Bounce (nearest indicator under the bar
    low, tip cleared), Reject (first indicator over the high / the MA forest), the stacked band to MP, next MP."""
    if len(rows) < 2:
        return None
    hs = [b[2] for b in rows]; ls = [b[3] for b in rows]; cs = [b[4] for b in rows]
    p = cs[-1]
    if atr_v is None:
        atr_v = atr_rma(hs, ls, cs, 14)[-1]
    if atr_v is None:
        return None
    dist = max(float(cfg["air_stack_dollars"]), float(cfg["air_stack_atr"]) * atr_v)
    vals = [(v, prefix + n) for n, v in ma_pack(cs, use_bb=bool(cfg["air_bb"]))]
    if cfg["air_range_structure"]:
        lb = int(cfg["air_rng_lookback"])
        if len(rows) > lb:
            vals.append((max(hs[-lb - 1:-1]), prefix + "RNG H"))
            vals.append((min(ls[-lb - 1:-1]), prefix + "RNG L"))
        pb = int(cfg["air_pivot_bars"])
        last_ph = last_pl = None
        for i in range(len(rows)):
            v = pivot_at(hs, i, pb, pb, True)
            if v is not None:
                last_ph = v
            v = pivot_at(ls, i, pb, pb, False)
            if v is not None:
                last_pl = v
        vals.append((last_ph, prefix + "PH")); vals.append((last_pl, prefix + "PL"))
    return band_levels(vals, p, hs[-1], ls[-1], atr_v, dist)


def band_levels(vals, p, high, low, atr_v, dist):
    """The heart of f_levels: sorted levels; Bounce = the nearest INDICATOR (EMA / SMA / BB, never PH / PL / RNG)
    under the bar low minus a tiny tip; Reject = the first indicator over the high (or over the MA forest around
    price); each extends through indicators stacked within `dist` to the far edge (= MP); next MP beyond the gap."""
    clean = sorted([(v, n) for v, n in vals if v is not None], key=lambda x: x[0])
    V = [v for v, _ in clean]; N = [n for _, n in clean]
    m = len(V)
    out = {"near_dem": None, "far_dem": None, "near_sup": None, "far_sup": None, "next_dem": None, "next_sup": None,
           "near_dem_n": "", "far_dem_n": "", "near_sup_n": "", "far_sup_n": "", "next_dem_n": "", "next_sup_n": "",
           "atr": atr_v, "dist": dist, "px": p}
    if not m:
        return out
    home_hi = p
    in_forest = False
    for v in V:
        if abs(v - p) <= dist:
            in_forest = True
            home_hi = max(home_hi, v)
    tip = max(0.02, atr_v * 0.01)
    dem_ceiling = low - tip
    sup_floor = max(home_hi if in_forest else high, high) + tip
    bi = ri = -1
    for i in range(m):
        if _is_ind(N[i]) and V[i] < dem_ceiling:
            bi = i
    for i in range(m):
        if _is_ind(N[i]) and V[i] > sup_floor:
            ri = i
            break
    if bi >= 0:
        out["near_dem"], out["near_dem_n"] = V[bi], N[bi]
        fi = bi
        k = bi
        while k > 0:
            gap = V[k] - V[k - 1]
            if _is_ind(N[k - 1]) and gap <= dist:
                fi = k - 1; k -= 1
            elif not _is_ind(N[k - 1]):
                k -= 1
            else:
                break
        out["far_dem"], out["far_dem_n"] = V[fi], N[fi]
        if fi > 0:
            j = fi - 1
            out["next_dem"], out["next_dem_n"] = V[j], N[j]
            while j > 0 and V[j] - V[j - 1] <= dist:
                out["next_dem"], out["next_dem_n"] = V[j - 1], N[j - 1]
                j -= 1
    if ri >= 0:
        out["near_sup"], out["near_sup_n"] = V[ri], N[ri]
        fi = ri
        k = ri
        while k < m - 1:
            gap = V[k + 1] - V[k]
            if _is_ind(N[k + 1]) and gap <= dist:
                fi = k + 1; k += 1
            elif not _is_ind(N[k + 1]):
                k += 1
            else:
                break
        out["far_sup"], out["far_sup_n"] = V[fi], N[fi]
        if fi < m - 1:
            j = fi + 1
            out["next_sup"], out["next_sup_n"] = V[j], N[j]
            while j < m - 1 and V[j + 1] - V[j] <= dist:
                out["next_sup"], out["next_sup_n"] = V[j + 1], N[j + 1]
                j += 1
    return out


def _pierce(hs, ls, level, tol, look, above=True):
    """Most recent bar offset (1 = yesterday) that went sharply above (below) level within look; None if none."""
    n = len(hs) - 1
    for j in range(1, look + 1):
        if n - j < 0:
            break
        if (hs[n - j] > level + tol) if above else (ls[n - j] < level - tol):
            return j
    return None


def mt_supply(rows, cfg, atr_v):
    """MT SUPPLY Nx: a cluster of daily highs touched again and again, only inside the window AFTER the last time
    price went sharply above it (a taken-out high is dead). Origin = the oldest peak of that cluster."""
    hs = [b[2] for b in rows]; ls = [b[3] for b in rows]; cs = [b[4] for b in rows]; ts = [b[0] for b in rows]
    n = len(rows) - 1
    look = min(int(cfg["air_mt_lookback"]), n)
    if look < 1 or atr_v is None:
        return None
    clust = max(float(cfg["air_mt_cluster_dollars"]), float(cfg["air_mt_cluster_atr"]) * atr_v)
    take = max(clust, float(cfg["air_mt_takeout_atr"]) * atr_v)
    tiny = max(0.02, clust * 0.05)
    p = cs[n]
    recent_hi = max(hs[n - look + 1:n + 1])
    best = None
    for i in range(1, look + 1):
        h = hs[n - i]
        pierce = _pierce(hs, ls, h, take, look, True)
        win_end = look if pierce is None else pierce - 1
        if win_end >= 1 and i <= win_end:
            cnt, s_, origin = 0, 0.0, None
            for j in range(1, win_end + 1):
                hj, cj = hs[n - j], cs[n - j]
                if abs(hj - h) <= clust:
                    if cj <= h + tiny:
                        cnt += 1; s_ += hj
                    if origin is None or j > origin:
                        origin = j
            if cnt >= int(cfg["air_mt_touches"]):
                avg = s_ / cnt
                if avg >= p - clust or abs(avg - recent_hi) <= clust * 2.0:
                    score = cnt * 10.0 - abs(avg - recent_hi) * 0.02 + (5.0 if avg >= p else 0.0) - origin * 0.01
                    if best is None or score > best[0]:
                        best = (score, avg)
    if best is None:
        return None
    out_px = best[1]
    pierce = _pierce(hs, ls, out_px, take, look, True)
    win_end = look if pierce is None else pierce - 1
    if win_end < 1:
        return None
    cnt, peak_j, peak = 0, None, None
    for j in range(1, win_end + 1):
        hj, cj = hs[n - j], cs[n - j]
        if abs(hj - out_px) <= clust:
            if cj <= out_px + tiny:
                cnt += 1
            if peak_j is None or j > peak_j:
                peak_j, peak = j, hj
    if peak is None or cnt < int(cfg["air_mt_touches"]):
        return None
    return {"p": peak, "n": cnt, "t0": ts[n - peak_j], "age": peak_j}


def mt_demand(rows, cfg, atr_v):
    """MT DEMAND Nx: the held demand area after the last sharp break below; holds count more than identical wicks."""
    hs = [b[2] for b in rows]; ls = [b[3] for b in rows]; cs = [b[4] for b in rows]; ts = [b[0] for b in rows]
    n = len(rows) - 1
    look = min(int(cfg["air_mt_lookback"]), n)
    if look < 1 or atr_v is None:
        return None
    clust = max(float(cfg["air_mt_cluster_dollars"]), float(cfg["air_mt_cluster_atr"]) * atr_v)
    take = max(clust, float(cfg["air_mt_takeout_atr"]) * atr_v)
    tiny = max(0.02, clust * 0.05)
    p = cs[n]
    recent_lo = min(ls[n - look + 1:n + 1])
    best = None
    for i in range(1, look + 1):
        lv = ls[n - i]
        pierce = _pierce(hs, ls, lv, take, look, False)
        win_end = look if pierce is None else pierce - 1
        if win_end >= 1 and i <= win_end:
            cnt = holds = 0
            s_, origin = 0.0, None
            for j in range(1, win_end + 1):
                lj, cj = ls[n - j], cs[n - j]
                if abs(lj - lv) <= clust:
                    if origin is None or j > origin:
                        origin = j
                    if cj >= lv - tiny:
                        cnt += 1; s_ += lj
                    if cj >= lv:
                        holds += 1
            taken_after = pierce is not None and origin is not None and pierce < origin
            if not taken_after and cnt >= int(cfg["air_mt_touches"]) and origin is not None:
                avg = s_ / cnt
                if avg <= p + clust:
                    score = holds * 20.0 + cnt * 2.0 + (avg - recent_lo) * 0.05 + (5.0 if avg <= p else 0.0) - origin * 0.5
                    if best is None or score > best[0]:
                        best = (score, avg)
    if best is None:
        return None
    out_px = best[1]
    pierce = _pierce(hs, ls, out_px, take, look, False)
    win_end = look if pierce is None else pierce - 1
    if win_end < 1:
        return None
    cnt, tj, trough = 0, None, None
    for j in range(1, win_end + 1):
        lj, cj = ls[n - j], cs[n - j]
        if abs(lj - out_px) <= clust:
            if cj >= out_px - tiny:
                cnt += 1
            if tj is None or j > tj:
                tj, trough = j, lj
    if trough is None or cnt < int(cfg["air_mt_touches"]):
        return None
    return {"p": trough, "n": cnt, "t0": ts[n - tj], "age": tj}


def fuel_words(need_atr, need_dollars, left):
    if need_atr is None or need_dollars is None or left is None:
        return "—", "#787b86"
    s = f"{s2(need_atr)} ATR"
    if need_dollars <= left:
        return "ENOUGH · " + s, "#26A69A"
    if need_atr <= 1.0:
        return "STRETCH · " + s, "#FFD54F"
    if need_atr <= 2.0:
        return "STRETCH · " + s, "#FF9800"
    return "NOT ENOUGH · " + s, "#EF5350"


def airspace(st, t, cfg, drows, live, g):
    """AIRSPACE: Bounce / Reject stubs, MT SUPPLY / DEMAND lines and the lights board."""
    if len(drows) < 3:
        return {"lines": [], "board": [], "bounce": None, "reject": None}
    hs = [b[2] for b in drows]; ls = [b[3] for b in drows]; cs = [b[4] for b in drows]
    atr_all = atr_rma(hs, ls, cs, 14)
    # Airspace's own ATR: the live day's (TradingView Airspace), or the one tank ATR (prior completed day) like GAS
    atr_d = atr_all[-1] if cfg["air_atr_live"] else (g.get("y_atr") or atr_all[-1])
    d = f_levels(drows, "", cfg, atr_d)
    weekly = weekly_from(drows)
    wk = f_levels(weekly, "W ", cfg, None) if len(weekly) > 2 else None
    p = cs[-1]
    sup_w = bool(cfg["air_weekly_fallback"]) and d["far_sup"] is None and wk and wk["far_sup"] is not None
    dem_w = bool(cfg["air_weekly_fallback"]) and d["far_dem"] is None and wk and wk["far_dem"] is not None
    src = lambda w: "Weekly " if w else "Daily "
    bounce, bounce_n = (wk["near_dem"], wk["near_dem_n"]) if dem_w else (d["near_dem"], d["near_dem_n"] if d["near_dem"] is not None else "")
    dem, dem_n = (wk["far_dem"], wk["far_dem_n"]) if dem_w else (d["far_dem"], d["far_dem_n"])
    reject, reject_n = (wk["near_sup"], wk["near_sup_n"]) if sup_w else (d["near_sup"], d["near_sup_n"])
    sup, sup_n = (wk["far_sup"], wk["far_sup_n"]) if sup_w else (d["far_sup"], d["far_sup_n"])
    next_sup, next_sup_n = (d["next_sup"], d["next_sup_n"]) if d["next_sup"] is not None else ((wk["next_sup"], wk["next_sup_n"]) if sup_w else (None, ""))
    next_dem, next_dem_n = (d["next_dem"], d["next_dem_n"]) if d["next_dem"] is not None else ((wk["next_dem"], wk["next_dem_n"]) if dem_w else (None, ""))
    b_src, dem_src = src(dem_w), src(dem_w)
    # Weekly retarget: a Bounce that is blank (or tagged by the bar) takes the nearest Weekly indicator under the tip
    tip = max(0.02, (atr_d or 0.0) * 0.01)
    ceil_c = ls[-1] - tip
    if not (bounce is not None and bounce < ceil_c) and cfg["air_weekly_fallback"] and len(weekly) > 2:
        wpack = [(v, n) for n, v in ma_pack([b[4] for b in weekly], use_bb=bool(cfg["air_bb"]))]
        under = sorted([(v, n) for v, n in wpack if v is not None and v < ceil_c], key=lambda x: -x[0])
        if under:
            bounce, bounce_n, b_src = under[0][0], "W " + under[0][1], "Weekly "
            dem, dem_n = (under[1][0], "W " + under[1][1]) if len(under) > 1 else (under[0][0], "W " + under[0][1])
            dem_src = "Weekly "
            dem_w = True
        else:
            bounce, bounce_n = None, ""
    d_px = p
    mp_up = sup - d_px if sup is not None else None
    mp_dn = d_px - dem if dem is not None else None
    mp_nu = next_sup - d_px if next_sup is not None else None
    mp_nd = d_px - next_dem if next_dem is not None else None
    min_air = float(cfg["air_min_air"])
    up_clear = mp_up is not None and mp_up >= min_air
    dn_clear = mp_dn is not None and mp_dn >= min_air
    up_atr = mp_up / atr_d if mp_up is not None and atr_d else None
    dn_atr = mp_dn / atr_d if mp_dn is not None and atr_d else None
    up_take = not up_clear and mp_up is not None and atr_d and atr_d > mp_up and mp_nu is not None and mp_nu >= min_air
    dn_take = not dn_clear and mp_dn is not None and atr_d and atr_d > mp_dn and mp_nd is not None and mp_nd >= min_air
    sma50 = sma(cs, 50)[-1] if len(cs) >= 50 else None
    above50 = sma50 is not None and d_px > sma50
    below50 = sma50 is not None and d_px < sma50
    left = g.get("left")
    if left is None and atr_d:
        left = max(atr_d - g.get("used", 0.0), 0.0)
    fu_w, fu_c = fuel_words(up_atr, mp_up, left)
    fd_w, fd_c = fuel_words(dn_atr, mp_dn, left)
    fuel_up = mp_up is not None and left is not None and left >= mp_up
    fuel_dn = mp_dn is not None and left is not None and left >= mp_dn
    up_go = (up_clear or bool(up_take)) and fuel_up and above50
    dn_go = (dn_clear or bool(dn_take)) and fuel_dn and below50
    lines = []
    lbl_px = lambda v: f"{v:.2f}"
    if cfg["air_bounce_reject"]:
        if bounce is not None:
            lines.append({"p": bounce, "c": K(cfg, "col_bounce"), "w": int(cfg.get("lw_bounce", 2)), "d": "dash", "l": f"BOUNCE {b_src}{_tag(bounce_n)} @ {lbl_px(bounce)}", "lc": K(cfg, "col_bounce"), "g": "air", "stub": True})
        if reject is not None:
            lines.append({"p": reject, "c": K(cfg, "col_reject"), "w": int(cfg.get("lw_bounce", 2)), "d": "dash", "l": f"REJECT {src(sup_w)}{_tag(reject_n)} @ {lbl_px(reject)}", "lc": K(cfg, "col_reject"), "g": "air", "stub": True})
    if cfg["air_mt_supply"]:
        ms = mt_supply(drows, cfg, atr_all[-1])
        if ms:
            lines.append({"p": ms["p"], "c": K(cfg, "col_mt_supply"), "w": int(cfg.get("lw_mt", 3)), "d": "dash", "l": mt_label(ms, "high"), "lc": K(cfg, "col_mt_supply"), "g": "air", "t0": ms["t0"]})
    if cfg["air_mt_demand"]:
        md = mt_demand(drows, cfg, atr_all[-1])
        if md:
            lines.append({"p": md["p"], "c": K(cfg, "col_mt_demand"), "w": int(cfg.get("lw_mt", 3)), "d": "dash", "l": mt_label(md, "low"), "lc": K(cfg, "col_mt_demand"), "g": "air", "t0": md["t0"]})
    # the board
    board = []
    if cfg["air_board"]:
        gm = "#78909C"
        mp_up_s = ("CLEAR W" if sup_w else "CLEAR") if up_clear else ("TAKEOUT W" if sup_w else "TAKEOUT") if up_take else "THIN / not enough"
        mp_dn_s = ("CLEAR W" if dem_w else "CLEAR") if dn_clear else ("TAKEOUT W" if dem_w else "TAKEOUT") if dn_take else "THIN / not enough"
        lit_u, lit_d = up_clear or bool(up_take), dn_clear or bool(dn_take)
        dol = lambda v: "" if v is None else f" ${v:.2f}"
        board.append([["LIGHTS", "#787b86"], ["UPSIDE", "#fff"], ["DOWNSIDE", "#fff"]])
        board.append([["MP", "#fff"], [("● " if lit_u else "○ ") + mp_up_s + dol(mp_up), "#26A69A" if lit_u else "#EF5350"],
                      [("● " if lit_d else "○ ") + mp_dn_s + dol(mp_dn), "#26A69A" if lit_d else "#EF5350"]])
        board.append([["level", "#787b86"], ["—" if sup is None else f"supply {src(sup_w)}{_tag(sup_n)} @ {sup:.2f}", gm],
                      ["—" if dem is None else f"demand {dem_src}{_tag(dem_n)} @ {dem:.2f}", gm]])
        if up_take or dn_take or mp_nu is not None or mp_nd is not None:
            board.append([["next MP", "#787b86"],
                          ["—" if mp_nu is None else f"${mp_nu:.2f} {src(sup_w and d['next_sup'] is None)}{_tag(next_sup_n)}", "#FF9800" if up_take else gm],
                          ["—" if mp_nd is None else f"${mp_nd:.2f} {src(dem_w and d['next_dem'] is None)}{_tag(next_dem_n)}", "#FF9800" if dn_take else gm]])
        board.append([["FUEL", "#fff"], [("● " if fuel_up else "○ ") + fu_w, "#26A69A" if fuel_up else "#EF5350"],
                      [("● " if fuel_dn else "○ ") + fd_w, "#26A69A" if fuel_dn else "#EF5350"]])
        y_atr = g.get("y_atr")
        if g.get("today") and y_atr:
            used = g.get("used", 0.0)
            pct = max(0.0, 100.0 - used / y_atr * 100.0)
            gbg = "#4caf50" if pct >= 40 else "#ffd500" if pct >= 15 else "#d78585"
            board.append([[f"{round(pct)}% left · {s2(used / y_atr)}x ATR", "#fff", gbg], [f"used {s2(used)} / tank {s2(y_atr)}", "#fff", gbg],
                          [f"left {s2(max(0.0, y_atr - used))}", "#fff", gbg]])
        else:
            board.append([["waiting 9:30", "#fff", "#787b86"], ["—", "#fff", "#787b86"], ["—", "#fff", "#787b86"]])
        side50 = "—" if sma50 is None else "above" if d_px > sma50 else "below" if d_px < sma50 else "on"
        dist50 = None if sma50 is None else d_px - sma50
        d50 = "—" if dist50 is None else ("+$" if dist50 > 0 else "−$" if dist50 < 0 else "$") + f"{abs(dist50):.2f}"
        board.append([["50 SMA", "#fff"], [("● " if above50 else "○ ") + f"{side50} {d50}", "#26A69A" if above50 else "#EF5350"],
                      [("● " if below50 else "○ ") + f"{side50} {d50}", "#26A69A" if below50 else "#EF5350"]])
        atr_txt = lambda v: "—" if v is None or not atr_d else f"{s2((d_px - v) / atr_d if v < d_px else (v - d_px) / atr_d)} ATR"
        bfull = "—" if bounce is None else f"{b_src}{_tag(bounce_n)} @ {bounce:.2f} · {atr_txt(bounce)}"
        rfull = "—" if reject is None else f"{src(sup_w)}{_tag(reject_n)} @ {reject:.2f} · {atr_txt(reject)}"
        board.append([["BOUNCE", "#fff"], [bfull, K(cfg, "col_bounce")], [bfull, K(cfg, "col_bounce")]])
        board.append([["REJECT", "#fff"], [rfull, K(cfg, "col_reject")], [rfull, K(cfg, "col_reject")]])
        board.append("CONFLUENCE")            # the page fills this row: the chart's own MAs at the Bounce / Reject price
        if cfg["cont_odds"]:
            c = _cont(st, t, cfg, drows, live, g.get("y_atr"), drows[-2][4] if live else drows[-1][4])
            for r in cont_rows(c, "air"):
                board.append({"t": r["t"], "bg": r["bg"], "fg": r["fg"]})
        if g.get("se"):
            board.append(dict(g["se"]))
        overall = ("OVERALL · BOTH WAYS GREEN" if up_go and dn_go else "OVERALL · UPSIDE ALL GREEN" if up_go else
                   "OVERALL · DOWNSIDE ALL GREEN" if dn_go else "OVERALL · PARTIAL · WAIT" if lit_u or lit_d else "OVERALL · NO MP · PASS")
        board.append({"t": ("● " if up_go or dn_go else "○ ") + overall, "bg": "#26A69A" if up_go or dn_go else "rgba(239,83,80,.75)",
                      "fg": "#E8F5E9" if up_go or dn_go else "#FFCDD2", "big": True})
    # the minimized board (Pine's "AIRSPACE ▸" strip): both lanes' air and the tank on one line
    yb = g.get("y_atr")
    gas_pct = (f"{round(max(0.0, 100.0 - g.get('used', 0.0) / yb * 100.0))}% left" if g.get("today") and yb else "waiting 9:30")
    mini = (("●UP " if up_go else "○UP ") + ("—" if mp_up is None else f"${mp_up:.2f}") + "  " +
            ("●DN " if dn_go else "○DN ") + ("—" if mp_dn is None else f"${mp_dn:.2f}") + "  · " + gas_pct)
    # 60-minute pack for the confluence row on a Daily chart (the intraday charts use their own MAs)
    h60 = h60_from_m30(m30_series(st, t))
    pack60 = [[_tag(n), v] for n, v in ma_pack([b[4] for b in h60], use_bb=bool(cfg["air_bb"]))] if h60 else []
    return {"lines": lines, "board": board, "bounce": [bounce, b_src.strip(), _tag(bounce_n)] if bounce is not None else None,
            "reject": [reject, src(sup_w).strip(), _tag(reject_n)] if reject is not None else None, "pack60": pack60,
            "atr": atr_d, "tol": max(float(cfg["air_merge_tol"]), 0.02, (atr_d or 0.0) * 0.01),
            "mp_up": mp_up, "mp_dn": mp_dn, "mini": mini}


def mt_label(m, side):
    d = ny(m["t0"] + 43200)
    # the date, high / low, price and how many trading days since it formed
    return f"{MONTHS[d.month - 1]} {d.day} {side} @ {m['p']:.2f}" + (f"  {m['age']}d" if m.get("age") is not None else "")


# --------------------------------------------------------------------------------------------- UNVISITED HIGHS / LOWS

def unvisited(drows, live, cfg):
    """Daily pivots price has not come back to. Breaks and touches are judged on COMPLETED daily bars (a Daily CLOSE
    through clears); today's live bar only flags a level as being tested / closing through, it never clears it."""
    L, R = int(cfg["uv_left"]), int(cfg["uv_right"])
    reach, soft, keep = float(cfg["uv_reach_pct"]), bool(cfg["uv_soft_touch"]), int(cfg["uv_max"])
    comp = drows[:-1] if live else drows
    hs = [b[2] for b in comp]; ls = [b[3] for b in comp]; cs = [b[4] for b in comp]
    his, los = [], []                                       # [px, t0, touches, bar index, near]
    for i in range(len(comp)):
        if cfg["uv_highs"]:
            v = pivot_at(hs, i, L, R, True)
            if v is not None and not any(abs(h[0] - v) <= 0.01 for h in his):
                his.append([v, comp[i - R][0], 0, i - R, False])
                while len(his) > keep:
                    his.pop(0)
        if cfg["uv_lows"]:
            v = pivot_at(ls, i, L, R, False)
            if v is not None and not any(abs(h[0] - v) <= 0.01 for h in los):
                los.append([v, comp[i - R][0], 0, i - R, False])
                while len(los) > keep:
                    los.pop(0)
        for arr, up in ((his, True), (los, False)):
            for j in range(len(arr) - 1, -1, -1):
                p_ = arr[j][0]
                band = p_ * reach / 100.0
                near = (hs[i] >= p_ - band and cs[i] <= p_) if up else (ls[i] <= p_ + band and cs[i] >= p_)
                broken = cs[i] > p_ if up else cs[i] < p_
                if broken or (not soft and near):
                    arr.pop(j)
                else:
                    if soft and near and not arr[j][4]:
                        arr[j][2] += 1
                    arr[j][4] = near
    today = drows[-1] if live else None
    day_i = len(drows) - 1
    lines = []
    for arr, up in ((his, True), (los, False)):
        order = sorted(arr, key=lambda a: a[0])
        i = 0
        while i < len(order):
            p0 = order[i][0]
            band0 = p0 * float(cfg["uv_cluster_pct"]) / 100.0
            grp = []
            ssum = 0.0
            j = i
            while j < len(order):
                mid = ssum / len(grp) if grp else p0
                band = mid * float(cfg["uv_cluster_pct"]) / 100.0
                if j == i or abs(order[j][0] - mid) <= band or abs(order[j][0] - p0) <= band0:
                    grp.append(order[j]); ssum += order[j][0]; j += 1
                else:
                    break
            y = ssum / len(grp)
            oldest = min(grp, key=lambda a: a[1])
            tou = sum(a[2] for a in grp)
            age = day_i - oldest[3]
            multi = len(grp) > 1
            col = (K(cfg, "col_uv_high_cluster") if multi else K(cfg, "col_uv_high")) if up else (K(cfg, "col_uv_low_cluster") if multi else K(cfg, "col_uv_low"))
            # the date, high / low, price and the age in trading days (no touch count)
            label = f"{_date(oldest[1])} {'high' if up else 'low'} @ " + " / ".join(f"{a[0]:.2f}" for a in sorted(grp, key=lambda a: a[0]))
            if cfg["uv_age"]:
                label += f"  {age}d"
            testing = closing = False
            if today is not None:
                band = y * reach / 100.0
                testing = (today[2] >= y - band and today[4] <= y) if up else (today[3] <= y + band and today[4] >= y)
                closing = today[4] > y if up else today[4] < y
                if closing:
                    label += "  · CLOSING THROUGH (clears at the close)"
                elif testing:
                    label += "  · testing now"
            lines.append({"p": y, "c": col, "w": int(cfg.get("lw_uv", 1)) + (2 if multi else 0), "d": "dash" if tou > 0 or testing else "solid", "l": label, "lc": col,
                          "t0": oldest[1], "g": "uv", "fade": closing})
            i = j
    return {"lines": lines}


def _date(t0):
    d = ny(t0 + 43200)
    return f"{MONTHS[d.month - 1]} {d.day} '{d.year % 100:02d}"


# --------------------------------------------------------------------------------------------- all of it

def compute(st, t, cfg):
    """Everything the stock chart draws for one symbol (each study None when switched off)."""
    drows, live = daily_series(st, t)
    out = {"gas": None, "air": None, "uv": None, "t": t,
           "style": {k: cfg.get(k) for k in ("lbl_size", "lbl_gap_bars", "line_back_bars", "line_fwd_bars", "lbl_space_pct",
                                             "lbl_color_mode", "col_label")}}
    if not (cfg["gas"] or cfg["airspace"] or cfg["unvisited"]):
        return out
    g = gas(st, t, cfg, drows, live)
    if cfg["gas"]:
        out["gas"] = g
    if cfg["airspace"]:
        out["air"] = airspace(st, t, cfg, drows, live, g)
    if cfg["unvisited"] and len(drows) > int(cfg["uv_left"]) + int(cfg["uv_right"]):
        out["uv"] = unvisited(drows, live, cfg)
    return out
