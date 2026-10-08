"""INSTITUTIONAL FOOTPRINTS: the way a fund's order shows up on a public tape. No names (the tape has none): the
fingerprints of a large parent order sliced into small child orders by an execution algorithm.

- PROGRAM (VWAP / percentage-of-volume algos): the same side wins slot after slot (5-minute slots of today's regular
  session), at a steady share of the volume, more when the market is busy (open, close) and less at lunch. Read from
  the minute bars' buy / sell volume: net = bought at the ask - sold at the bid, as a share of the slot's volume.
  Where it fills against VWAP says how it is working the benchmark (a buyer under VWAP is buying the dips).
- TIME OF DAY: this slot's volume against the stock's own normal for that slot (the last two months of 5-minute bars):
  "x1.4 for 11:05" — busy for the time, not just busy.
- FUND-STYLE RELOAD: a reloader whose refills keep showing the SAME size (large size shown a little at a time: 200, 200, 200 ...),
  soaking up everything that hits it.
- WALKING: the same side's reloaders stepping up (a buyer accumulating behind price) or down (a seller distributing).
"""

import math
from collections import Counter

SLOT = 300                      # 5 minutes
OPEN_S, CLOSE_S = 34200, 57600  # 9:30, 16:00 New York (seconds of the day)


def _local(t, off):
    return t + off


def slot_of(t, off):
    return int((_local(t, off) % 86400) // SLOT)


def hm(slot):
    s = slot * SLOT
    return f"{s // 3600}:{(s % 3600) // 60:02d}"


def volume_curve(m5, t, off):
    """The stock's normal volume per 5-minute slot of the regular session, from the 5-minute history (today left
    out): {slot: average volume}."""
    today = int(_local(t, off) // 86400)
    per = {}
    for k, b in m5.items():
        loc = _local(k, off)
        day, sec = int(loc // 86400), loc % 86400
        if day == today or not (OPEN_S <= sec < CLOSE_S):
            continue
        per.setdefault((day, int(sec // SLOT)), 0.0)
        per[(day, int(sec // SLOT))] += float(b[4] or 0)
    sums, days = {}, {}
    for (day, sl), v in per.items():
        sums[sl] = sums.get(sl, 0.0) + v
        days[sl] = days.get(sl, 0) + 1
    return {sl: sums[sl] / days[sl] for sl in sums if days[sl] >= 3}


def today_slots(bars, t, off, any_time=False):
    """Today's 5-minute slots from the minute bars [o, h, l, c, v, buy_v, sell_v]: [slot, vol, buy, sell, pv], the
    slot still filling last."""
    today = int(_local(t, off) // 86400)
    out = {}
    for m in sorted(bars):
        loc = _local(m, off)
        if int(loc // 86400) != today or m > t:
            continue
        sec = loc % 86400
        if not any_time and not (OPEN_S <= sec < CLOSE_S):
            continue
        b = bars[m]
        sl = int(sec // SLOT)
        r = out.setdefault(sl, [sl, 0.0, 0.0, 0.0, 0.0])
        v = float(b[4] or 0)
        r[1] += v; r[2] += float(b[5] if len(b) > 5 else 0) or 0.0; r[3] += float(b[6] if len(b) > 6 else 0) or 0.0
        r[4] += (b[1] + b[2] + b[3]) / 3.0 * v
    return [out[k] for k in sorted(out)]


def market_shares(others):
    """The market's own one-sided share per slot: {slot: median (buy - sell) / volume} across the other stocks (or the
    index ETF's alone when it is on the desk). A stock that only moves with the market is not running a program."""
    per = {}
    for sl in others:
        for r in sl:
            if r[1] > 0:
                per.setdefault(r[0], []).append((r[2] - r[3]) / r[1])
    out = {}
    for k, v in per.items():
        v.sort()
        out[k] = v[len(v) // 2]
    return out


def program(slots, cur_slot, vwap, cfg, mkt=None):
    """A buy / sell PROGRAM on today's completed slots, or None. Rows [slot, vol, buy, sell, pv]. ``mkt`` = the
    market's one-sided share per slot (market_shares): taken out first, so only this stock's own flow counts."""
    mkt = mkt or {}
    slots = [[r[0], r[1], r[2] - max(0.0, mkt.get(r[0], 0.0)) * r[1] / 2 + max(0.0, -mkt.get(r[0], 0.0)) * r[1] / 2,
              r[3] + max(0.0, mkt.get(r[0], 0.0)) * r[1] / 2 - max(0.0, -mkt.get(r[0], 0.0)) * r[1] / 2, r[4]] for r in slots]
    done = [r for r in slots if r[0] < cur_slot and r[1] > 0]
    need = int(cfg.get("min_slots", 6))
    if len(done) < need:
        return None
    win = done[-int(cfg.get("window_slots", 18)):]
    vol = sum(r[1] for r in win)
    net = sum(r[2] - r[3] for r in win)
    if vol <= 0 or net == 0:
        return None
    side = 1 if net > 0 else -1
    part = net / vol                                           # the net imbalance as a share of all volume
    agree = sum(1 for r in win if (r[2] - r[3]) * side > 0.03 * r[1]) / len(win)
    steady = sum(1 for r in win if 0.25 * abs(part) <= (r[2] - r[3]) * side / r[1] <= 3.0 * abs(part)) / len(win)
    if not (agree >= float(cfg.get("agree", 0.65)) and abs(part) >= float(cfg.get("min_part", 0.06)) and steady >= float(cfg.get("steady", 0.45))):
        return None
    # since when: the earliest slot from which the run still agrees
    since = win[-1][0]
    run_ok = 0
    for i in range(len(done) - 1, -1, -1):
        r = done[i]
        if (r[2] - r[3]) * side > 0:
            run_ok += 1; since = r[0]
        elif run_ok and (len(done) - i) > 2 and run_ok / (len(done) - i) < float(cfg.get("agree", 0.65)):
            break
    run = [r for r in done if r[0] >= since]
    rnet = sum(r[2] - r[3] for r in run)
    avgp = sum(r[4] for r in run) / max(1.0, sum(r[1] for r in run))
    # where the program's own slots filled against VWAP (weighted by how much it did in each)
    wsum = sum(abs(r[2] - r[3]) for r in run if (r[2] - r[3]) * side > 0)
    fillp = (sum((r[4] / r[1]) * abs(r[2] - r[3]) for r in run if (r[2] - r[3]) * side > 0 and r[1]) / wsum) if wsum else None
    vs = None if (fillp is None or not vwap) else round(fillp - vwap, 4)
    return {"side": "BUY" if side > 0 else "SELL", "agree": round(agree * 100), "slots": len(win),
            "won": sum(1 for r in win if (r[2] - r[3]) * side > 0.03 * r[1]), "part": round(abs(part) * 100, 1),
            "since": hm(since), "usd": round(abs(rnet) * avgp), "shares": round(abs(rnet)), "vs_vwap": vs,
            "score": round(min(100, agree * 60 + min(abs(part) / 0.2, 1) * 25 + steady * 15))}


def fund_reloads(trackers, t, cfg):
    """Reloaders whose refills keep showing the same size (large size shown a little at a time)."""
    out = []
    for tr in trackers:
        rs = list(getattr(tr, "refill_sizes", ()) or ())
        if len(rs) < int(cfg.get("same_size_min_refills", 4)):
            continue
        size, n = Counter(rs).most_common(1)[0]
        share = n / len(rs)
        if share < float(cfg.get("same_size_share", 0.6)) or size <= 0:
            continue
        absorbed = float(tr.absorbed_all + tr.absorbed_total)
        out.append({"price": float(tr.price), "side": "bid" if str(tr.side).lower().startswith("b") else "ask", "size": int(size),
                    "refills": len(rs), "same": n, "absorbed": round(absorbed), "usd": round(absorbed * float(tr.price)),
                    "here": float(tr.displayed or 0) > 0})
    out.sort(key=lambda x: -x["usd"])
    return out


def walking(basket_rows, t, cfg):
    """The same side's reloaders stepping in one direction within the window: a buyer walking up (accumulating behind
    price) or a seller walking down (distributing)."""
    win = float(cfg.get("walk_minutes", 20)) * 60
    best = None
    for side, up in (("bid", True), ("ask", False)):
        rows = sorted([r for r in basket_rows if r["side"] == side and t - r.get("first", t) <= win], key=lambda r: r["first"])
        steps = []
        for r in rows:
            p = float(r["price"])
            if not steps or (p > steps[-1] if up else p < steps[-1]):
                steps.append(p)
        if len(steps) >= int(cfg.get("walk_steps", 3)):
            usd = sum(r["usd"] for r in rows if float(r["price"]) in steps)
            cand = {"side": "BUYER" if up else "SELLER", "dir": "up" if up else "down", "steps": steps[-5:], "usd": usd}
            if best is None or usd > best["usd"]:
                best = cand
    return best


def fund_levels(trackers, walk, dark_levels, prog, cfg):
    """ONE FUND SCORE PER LEVEL (0-100): how much a reload level looks like a fund working size there.
      same size  35  the refills keep showing the same size (large size shown a little at a time)
      large size 20  far more traded there than was ever shown at once
      walking    20  the level is a step of a side walking the price (up = accumulation, down = distribution)
      dark       15  off-exchange money printed at that price
      flow       10  steady one-sided flow on the same side (program-like)"""
    out = []
    darks = {round(float(d["price"]), 2): float(d["usd"]) for d in (dark_levels or [])}
    for tr in trackers:
        if not (getattr(tr, "proven", False) or str(getattr(tr, "state", "")) == "RELOAD"):
            continue
        side = "bid" if str(tr.side).lower().startswith("b") else "ask"
        p = float(tr.price)
        why, sc = [], 0.0
        rs = list(getattr(tr, "refill_sizes", ()) or ())
        if len(rs) >= 3:
            size, n = Counter(rs).most_common(1)[0]
            share = n / len(rs)
            if share >= 0.5:
                sc += 35 * min(1.0, (share - 0.5) / 0.4 + 0.25) * min(1.0, len(rs) / 6)
                why.append(f"same size {size:,} × {n}")
        absorbed = float(tr.absorbed_all + tr.absorbed_total)
        peak = float(getattr(tr, "peak_displayed", 0) or 0)
        if peak > 0 and absorbed >= 2 * peak:
            sc += 20 * min(1.0, (absorbed / peak - 1) / 5)
            why.append(f"large size: {absorbed:,.0f} traded, never over {peak:,.0f} shown")
        if walk and ((walk["side"] == "BUYER") == (side == "bid")) and any(abs(p - x) < 1e-6 for x in walk["steps"]):
            sc += 20
            why.append("walking " + walk["dir"] + (" (accumulation)" if walk["dir"] == "up" else " (distribution)"))
        du = sum(v for k, v in darks.items() if abs(k - p) <= 0.011)
        if du >= 100000:
            sc += 15 * min(1.0, du / 1000000)
            why.append(f"dark ${du / 1e6:.1f}M" if du >= 1e6 else f"dark ${du / 1e3:.0f}K")
        if prog and (prog["side"] == "BUY") == (side == "bid"):
            sc += 10
            why.append(f"steady {'buying' if side == 'bid' else 'selling'}")
        out.append({"price": p, "side": side, "score": round(sc), "why": why, "usd": round(absorbed * p), "here": float(tr.displayed or 0) > 0})
    out.sort(key=lambda x: -x["score"])
    return [x for x in out if x["score"] >= float(cfg.get("fund_show", 50))]


def guides(prog, last, vwap, ny_sec, cfg):
    """What a running program means for the trade (Dan's framework): which side the dips / pops get taken, and what
    the time of day does to the algo."""
    if not prog:
        return []
    out, buy = [], prog["side"] == "BUY"
    if last is not None and vwap:
        if buy and last >= vwap:
            out.append("Steady buying, price over VWAP: dips to VWAP are likely bought. Favours long 2nd entries near VWAP; pullbacks shallower")
        elif not buy and last <= vwap:
            out.append("Steady selling, price under VWAP: pops to VWAP are likely sold. Favours short 2nd entries near VWAP; bounces weaker")
        elif buy:
            out.append("Steady buying while under VWAP: the algo is buying the discount. Watch for a reclaim of VWAP")
        else:
            out.append("Steady selling while over VWAP: the algo is selling into strength. Watch for a loss of VWAP")
    if 41400 <= ny_sec < 50400:
        out.append("Midday: the algo slows down. Expect quiet, shallow pullbacks rather than reversals")
    elif 54000 <= ny_sec < 57600:
        out.append(f"Last hour: the algo speeds up to finish. Expect a push {'up' if buy else 'down'} into the close")
    return out
