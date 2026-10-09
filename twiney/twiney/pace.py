"""PACE OF TAPE: how fast this stock is trading RIGHT NOW against its own normal, who is pushing, and what that
means at your levels.

Every print lands in a 5-second bucket (buy / sell / other shares, prints, first and last price). From those:
- RATE: shares a second over the last 15 s, against the MEDIAN 15 s of the last 20 minutes (this stock against
  itself: 3,000 shares a second is a crawl on NVDA and a stampede on a small cap). ×1.0 = its normal pace.
- PERCENTILE: where this 15 s ranks among the last 20 minutes' (95 = faster than 95% of them).
- ACCELERATION: the last 5 s against the last 15 s, and the last 15 s against a minute ago (speeding up / slowing).
- AGGRESSION: of the shares that crossed the spread in the last 15 s, how much was buyers paying up.
- STATE: SURGE / FAST / NORMAL / SLOW / DRYING UP.

At a level (your lines, the chart studies' levels):
- PRESSING <level>: price within reach of it and the tape speeding up into it.
- STALLING INTO <level>: price within reach of it and the tape slowing / drying up: the move is running out of gas.
- BREAKOUT / BREAKDOWN WITH SPEED: the level broke in the last 30 s with the tape well above its normal and the
  aggression on the break's side. With option flow on the same side (calls bought at the ask on a breakout, puts
  on a breakdown) it carries the dollars: + FLOW $640K calls.
- BREAK WITHOUT SPEED: the level broke on a normal / slow tape: suspect, the kind that comes back.
"""

import statistics
from collections import deque

BUCKET = 5.0
WINDOW = 1200.0                 # the stock's normal: the last 20 minutes


class PaceBook:
    """The 5-second buckets of one stock's tape (kept as prints arrive)."""

    def __init__(self):
        self.b = deque(maxlen=int(WINDOW // BUCKET) + 8)    # [t0, buy, sell, other, prints, first px, last px]
        self.first_t = None                                   # the first bucket this book ever saw (warm-up)

    def add(self, t, price, size, side):
        t0 = (t // BUCKET) * BUCKET
        if self.b and self.b[-1][0] == t0:
            r = self.b[-1]
        elif self.b and t0 < self.b[-1][0]:
            r = next((x for x in reversed(self.b) if x[0] == t0), None)
            if r is None:
                return                                        # older than what we keep: a late print, ignored
        else:
            r = [t0, 0.0, 0.0, 0.0, 0, price, price]
            self.b.append(r)
            if self.first_t is None:
                self.first_t = t0
        r[1 if side == "buy" else 2 if side == "sell" else 3] += size
        r[4] += 1
        r[6] = price


def _win(rows, start, end):
    """Shares, prints, buy, sell in the buckets that started in [start, end)."""
    sh = n = buy = sell = 0.0
    for r in rows:
        if start <= r[0] < end:
            sh += r[1] + r[2] + r[3]; n += r[4]; buy += r[1]; sell += r[2]
    return sh, n, buy, sell


def knows_txt(k):
    """SOMEBODY KNOWS SOMETHING in one line: $640K calls · 6 prints · 2 sweeps · 160 strike, 3d."""
    if not k or not k.get("dollars"):
        return None
    top = k.get("top") or {}
    what = "calls" if k.get("cp") == "C" else "puts"
    return (f"{_k(k['dollars'])} {what} · {k.get('prints', 0)} prints" + (f" · {k['sweeps']} sweeps" if k.get("sweeps") else "")
            + (f" · {top['strike']:g} strike" if top.get("strike") is not None else "") + (f", {round(top['dte'])}d" if top.get("dte") is not None else ""))


def read(book, now, last, levels, tick, cfg, flow=None, knows=None):
    """The pace right now. levels = [(price, name)], flow = recent option prints [(t, cp, side, premium)],
    knows = {"C": ..., "P": ...}: the SOMEBODY KNOWS SOMETHING read for calls and puts (short-dated, out of the money, bought at
    the ask, again and again)."""
    rows = [r for r in book.b if now - r[0] < WINDOW + 2 * BUCKET]
    out = {"state": "QUIET", "ratio": None, "pct": None, "heat": 0.0, "buy_pct": None, "accel": "", "sps": 0, "pps": 0.0,
           "call": None, "level": None, "flow": None, "words": None, "knows": None}
    knows = knows or {}
    for cp in ("C", "P"):                    # the flow tag on the ladder / T&S: who is hammering short-dated options now
        k = knows.get(cp)
        if k and k.get("knows"):
            out["knows"] = {"cp": cp, "text": knows_txt(k), "score": k.get("score"), "ids": list(k.get("ids") or [])}
            break
    if not rows:
        return out
    cur0 = (now // BUCKET) * BUCKET                    # the bucket being filled right now
    w0 = cur0 - 2 * BUCKET                             # the last 15 s = this bucket and the two before it
    span = max(BUCKET, now - w0)
    cur_sh, cur_n, cur_b, cur_s = _win(rows, w0, cur0 + BUCKET)
    sps = cur_sh / span
    # the stock's normal: every full 15-second slice of the last 20 minutes before that
    slices = []
    t = w0
    # only time the book has actually watched counts: before the first print it saw is not "zero volume"
    # (otherwise the first minutes after a start read every tape as FAST)
    start = max(now - WINDOW, book.first_t if book.first_t is not None else now - WINDOW)
    while t - 15.0 >= start:
        slices.append(_win(rows, t - 15.0, t)[0] / 15.0)
        t -= 15.0
    active = [x for x in slices if x > 0]
    if len(active) < 8:
        out.update(state="WARMING UP", sps=round(sps), pps=round(cur_n / span, 1))
        return out
    norm = statistics.median(slices) or (statistics.median(active) * 0.5)
    ratio = sps / norm if norm > 0 else 0.0
    pct = 100.0 * sum(1 for x in slices if x <= sps) / len(slices)
    fast5 = _win(rows, cur0 - BUCKET, cur0 + BUCKET)[0] / max(BUCKET, now - (cur0 - BUCKET))   # the last 5-10 s
    min_ago = _win(rows, w0 - 60.0, w0 - 45.0)[0]                                                # the same 15 s a minute ago
    rate5, rate_1m = fast5, min_ago / 15.0
    accel = ("SPEEDING UP" if rate5 > 1.3 * max(sps, 1e-9) or (sps > 1.4 * max(rate_1m, 1e-9) and sps > norm)
             else "SLOWING" if rate5 < 0.6 * sps or sps < 0.6 * rate_1m else "")
    directional = cur_b + cur_s
    buy_pct = 100.0 * cur_b / directional if directional else None
    # the PRICE PATH over the same 15 s: who is really in control. Buyers lifting offers that keep stepping lower are
    # getting run over, not stepping up; the voice never calls buyers while the tape prints lower and lower
    win_rows = [r for r in rows if w0 <= r[0] < cur0 + BUCKET]
    drift = round(win_rows[-1][6] - win_rows[0][5], 4) if win_rows else 0.0
    step = max(3 * float(tick or 0.01), (last or win_rows[-1][6] if win_rows else 0.0) * 0.001)
    control = "sellers" if drift <= -step else "buyers" if drift >= step else None
    c = cfg
    state = ("SURGE" if ratio >= c["surge_ratio"] and pct >= 90 else "FAST" if ratio >= c["fast_ratio"]
             else "DRYING UP" if ratio <= c["dry_ratio"] else "SLOW" if ratio <= c["slow_ratio"] else "NORMAL")
    out.update(state=state, ratio=round(ratio, 2), pct=round(pct), heat=round(min(1.0, ratio / 3.0), 2), buy_pct=None if buy_pct is None else round(buy_pct),
               accel=accel, sps=round(sps), pps=round(cur_n / span, 1), norm_sps=round(norm), drift=drift, control=control)
    if last is None:
        return out
    levels = levels or []
    # where price is against the levels
    near = max(c["near_ticks"] * tick, last * c["near_pct"] / 100.0)
    # the price ~30 s ago: the last print of the bucket ending 25-30 s ago (or the nearest one before it, up to 45 s)
    past = [r for r in rows if cur0 - 45.0 <= r[0] <= cur0 - 30.0]
    then = max(past, key=lambda r: r[0])[6] if past else None
    broke = None
    through = float(c.get("break_ticks", 3)) * tick      # a break is a few ticks through the level, not a one-tick poke
    if then is not None:
        for p, nm in levels:
            if then < p <= last and last - p >= through:
                broke = ("up", p, nm) if broke is None or p > broke[1] else broke
            elif then > p >= last and p - last >= through:
                broke = ("down", p, nm) if broke is None or p < broke[1] else broke
    flow_txt, flow_usd, against_usd = None, 0.0, 0.0
    flow_ids, against_ids = [], []
    if broke:
        up = broke[0] == "up"
        same = (buy_pct or 0) >= c["aggress_pct"] if up else (buy_pct is not None and 100 - buy_pct >= c["aggress_pct"])
        if flow:
            for row in flow:
                ft, cp, side, prem = row[:4]
                pid = row[4] if len(row) > 4 else None
                if now - ft <= c["flow_minutes"] * 60 and side == "ask":
                    if (cp == "C") == up:
                        flow_usd += prem; flow_ids.append(pid)
                    else:
                        against_usd += prem; against_ids.append(pid)
        kn = knows.get("C" if up else "P")
        if kn and kn.get("knows"):
            flow_txt = "+ SOMEBODY KNOWS SOMETHING " + knows_txt(kn)
            if (kn.get("dollars") or 0) >= flow_usd:          # the number said is the knows read's: its prints are the receipt
                flow_usd, flow_ids = kn.get("dollars") or 0, list(kn.get("ids") or [])
        elif flow_usd >= c["flow_min_premium"]:
            flow_txt = f"+ FLOW {_k(flow_usd)} {'calls' if up else 'puts'}"
        elif against_usd >= c["flow_min_premium"]:
            flow_txt = f"flow against: {_k(against_usd)} {'puts' if up else 'calls'}"
        fast = ratio >= c["break_ratio"] and same
        what = ("BREAKOUT" if up else "BREAKDOWN") + (" WITH SPEED" if fast else " WITHOUT SPEED")
        if flow_txt and flow_txt.startswith("+"):
            out["flow_ref"] = {"cp": "C" if up else "P", "ids": [i for i in flow_ids if i is not None]}
        elif flow_txt:
            out["flow_ref"] = {"cp": "P" if up else "C", "ids": [i for i in against_ids if i is not None]}
        out.update(call=what, level=[broke[1], broke[2]], flow=flow_txt,
                   words=(f"{'Breakout' if up else 'Breakdown'} through {broke[2]} with speed, {ratio:.1f} times its normal pace"
                          + (f", and somebody knows something: {_k(flow_usd)} of short dated {'calls' if up else 'puts'} hammered" if flow_txt and "KNOWS" in flow_txt
                             else f", and {_k(flow_usd)} of {'calls' if up else 'puts'} behind it" if flow_txt and flow_txt.startswith("+") else "")
                          if fast else f"{broke[2]} broke without speed. Careful, that one can come back")
                   + f". Not confirmed until a candle closes {'over' if up else 'under'} it")
        out["needs_close"] = "over" if up else "under"
        return out
    # SPEED + FLOW: the tape speeding up on one side while short-dated out-of-the-money options on that side are
    # being hammered — wherever price is
    if out["knows"] and buy_pct is not None and (state in ("FAST", "SURGE") or (accel == "SPEEDING UP" and ratio >= 1.2)):
        cp = out["knows"]["cp"]
        if (cp == "C" and buy_pct >= c["aggress_pct"]) or (cp == "P" and 100 - buy_pct >= c["aggress_pct"]):
            what = "calls" if cp == "C" else "puts"
            out["flow_ref"] = {"cp": cp, "ids": list(out["knows"].get("ids") or [])}
            out.update(call="SPEED + FLOW", level=[last, "calls hammered" if cp == "C" else "puts hammered"],
                       flow="+ SOMEBODY KNOWS SOMETHING " + out["knows"]["text"],
                       words=(f"Tape speeding up, {ratio:.1f} times normal" if accel == "SPEEDING UP" else f"Tape running {ratio:.1f} times normal")
                             + f", {'buyers' if cp == 'C' else 'sellers'} in control, and short dated {what} are being hammered")
            # a level close ahead still gets its own read below only when this did not fire
            return out
    # approaching a level: the nearest one in the direction price is travelling
    # with no price 30 s back (a quiet tape), a level within reach on EITHER side counts (never assume up)
    going_up = None if then is None else last >= then
    ahead = [(p, nm) for p, nm in levels if abs(p - last) <= near and (going_up is None or (p >= last if going_up else p <= last))]
    if ahead:
        p, nm = min(ahead, key=lambda x: abs(x[0] - last))
        pressing = state != "DRYING UP" and buy_pct is not None and ((buy_pct >= c["aggress_pct"]) if p >= last else (100 - buy_pct >= c["aggress_pct"]))
        if ratio <= c["stall_ratio"] and accel != "SPEEDING UP" and not pressing:
            out.update(call="STALLING INTO", level=[p, nm],
                       words=f"Stalling into {nm}. " + ("The tape is drying up" if state == "DRYING UP" else "The tape is slowing"))
        elif ratio >= 1.3 and accel == "SPEEDING UP":
            out.update(call="PRESSING", level=[p, nm], words=f"Pushing into {nm}. The tape is speeding up into it")
    return out


def _k(v):
    v = float(v or 0)
    return f"${v / 1e6:.1f}M" if v >= 1e6 else f"${v / 1e3:.0f}K"
