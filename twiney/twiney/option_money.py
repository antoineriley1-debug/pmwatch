"""OPTION MONEY: what the option market says about the stock you are on, read for the PS60 trade.

Six reads, each one answering a question the trade already asks:

* OPTION MAX PAIN where this week's options pay out the least (the strike price tends to be pulled to on expiry
                 day). Not the PS60 max pain (where you are wrong, the stop): always called OPTION MAX PAIN
* BIG STRIKES    the strikes with the most option money on them, above and below price: hedging on those options
                 tends to slow price there or hold it (more supply / demand in the way of the move)
* CALL vs PUT $  the day's running total of call money minus put money: which side the option buyers lean, all day
* EXPECTED MOVE  how far the options say the stock moves by the expiry: is the measured potential inside it?
* OPENING MONEY  open interest that grew overnight: new positions opened and held
* AT THE ASK     on the contract you trade: how much traded at the ask against at the bid today

Each read comes from Quant Data's tools when the key opens them (one call per tool per symbol on its own timer, well
inside the plan's 240 a minute), else from what the desk already has (the flow it pulls, the IBKR option chain,
the option tape); on the practice market from the practice chain. Where a read comes from is always shown.

Quant Data's answers are read by field meaning, not by one fixed layout: their reference could not be reached from
the build machine, so the first answer of every tool is saved to recordings/quantdata_tools/<tool>.json and the
CHECK button reports which tools the key opens. Flow backs up the setup, never replaces it: none of this places an order.
"""

import json
import math
import os
import threading
import time
from datetime import datetime, timezone

TOOLS = {
    "net_drift": "/v1/options/tool/net-drift",
    "exposure": "/v1/options/tool/exposure-by-strike",
    "max_pain_by_exp": "/v1/options/tool/max-pain-over-time",
    "max_pain": "/v1/options/tool/max-pain",
    "oi_by_strike": "/v1/options/tool/open-interest-by-strike",
    "term_structure": "/v1/options/tool/term-structure",
    "trade_side": "/v1/options/tool/contract-trade-side-statistics",
}
TOOL_NAMES = {"net_drift": "CALL vs PUT MONEY (net drift)", "exposure": "BIG STRIKES (exposure by strike)",
              "max_pain_by_exp": "OPTION MAX PAIN by expiry", "max_pain": "OPTION MAX PAIN", "oi_by_strike": "OPEN INTEREST by strike",
              "term_structure": "EXPECTED MOVE (term structure)", "trade_side": "CALLS / PUTS BOUGHT vs SOLD"}


# ---- reading numbers and times wherever they are ------------------------------------------------------------------

def _num(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _secs(x):
    """A time as epoch seconds: epoch ms / s (number or string) or an ISO date / time."""
    v = _num(x)
    if v is not None:
        return v / 1000.0 if v > 1e11 else v
    if isinstance(x, str) and x:
        try:
            s = x.strip().replace("Z", "+00:00")
            d = datetime.fromisoformat(s if "T" in s or " " in s else s + "T00:00:00+00:00")
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            return d.timestamp()
        except ValueError:
            return None
    return None


def _ymd(x):
    """An expiry as YYYYMMDD from '2026-10-17', '20261017', epoch ms ..."""
    if x is None:
        return None
    s = str(x).strip()
    digits = s.replace("-", "")[:8]
    if len(digits) == 8 and digits.isdigit():
        return digits
    t = _secs(x)
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y%m%d") if t else None


def _data(payload):
    return payload.get("data", payload) if isinstance(payload, dict) else payload


def _lk(d):
    return {str(k).lower().replace("_", ""): v for k, v in d.items()} if isinstance(d, dict) else {}


def _pick(d, *names):
    lk = _lk(d)
    for n in names:
        v = lk.get(n.lower().replace("_", ""))
        if v is not None:
            return v
    return None


def _records(payload, depth=0):
    """The biggest list of dicts in an answer (data / results / rows ...), or a dict keyed by strike / time turned
    into rows with that key as "__key"."""
    d = _data(payload)
    if isinstance(d, list):
        return [x for x in d if isinstance(x, dict)]
    if isinstance(d, dict):
        keyed = [(k, v) for k, v in d.items()]
        if keyed and all(_num(k) is not None or _secs(k) is not None for k, _ in keyed[:5]):
            out = []
            for k, v in keyed:
                row = dict(v) if isinstance(v, dict) else {"value": v}
                row["__key"] = k
                out.append(row)
            return out
        best = []
        if depth < 3:
            for v in d.values():
                if isinstance(v, (list, dict)):
                    inner = _records(v, depth + 1)
                    if len(inner) > len(best):
                        best = inner
        return best
    return []


def _split_call_put(row, skip=("strike", "strikeprice", "price", "k", "__key", "expiration", "expirationdate", "expiry", "dte")):
    """(call, put, other) sums of the numeric fields whose name says call / put; other = the lone numeric field."""
    call = put = None
    other = []
    for k, v in row.items():
        lk = str(k).lower().replace("_", "")
        if lk in skip:
            continue
        n = _num(v)
        if n is None:
            continue
        if "call" in lk:
            call = (call or 0.0) + n
        elif "put" in lk:
            put = (put or 0.0) + n
        elif lk in ("value", "net", "netexposure", "exposure", "total", "gex", "dex", "amount"):
            other.append(n)
    return call, put, (other[0] if other else None)


# ---- Quant Data answers -------------------------------------------------------------------------------------------

def parse_net_drift(payload):
    """Net Drift: buckets keyed by start time (ms) with netCallPremium / netPutPremium (per bucket, not running).
    -> {"series": [[t, running call minus put $]], "calls": $, "puts": $, "net": $} or None."""
    rows = []
    for r in _records(payload):
        t = _secs(r.get("__key")) if "__key" in r else _secs(_pick(r, "t", "time", "timestamp", "bucket", "start", "startTime"))
        c = _num(_pick(r, "netCallPremium", "callPremium", "netCall", "calls"))
        p = _num(_pick(r, "netPutPremium", "putPremium", "netPut", "puts"))
        if t is None or (c is None and p is None):
            continue
        rows.append((t, c or 0.0, p or 0.0))
    if not rows:
        return None
    rows.sort()
    cum = cc = pp = 0.0
    series = []
    for t, c, p in rows:
        cc += c
        pp += p
        cum = cc - pp
        series.append([round(t), round(cum)])
    return {"series": series, "calls": round(cc), "puts": round(pp), "net": round(cum)}


def parse_max_pain_by_exp(payload):
    """Max Pain Over Time: {"YYYY-MM-DD": strike, ...} (or rows with an expiration and a strike) -> [(YYYYMMDD, strike)]."""
    d = _data(payload)
    out = []
    if isinstance(d, dict):
        for k, v in d.items():
            e, s = _ymd(k), _num(v if not isinstance(v, dict) else _pick(v, "maxPain", "strike", "maxPainStrike"))
            if e and s:
                out.append((e, s))
    if not out:
        for r in _records(payload):
            e = _ymd(_pick(r, "expiration", "expirationDate", "expiry", "__key"))
            s = _num(_pick(r, "maxPain", "maxPainStrike", "strike", "value"))
            if e and s:
                out.append((e, s))
    return sorted(out)


def parse_max_pain(payload):
    """Max Pain: the max-pain strike (wherever it sits in the answer) and the expiry when given."""
    def find(o, depth=0):
        if isinstance(o, dict):
            v = _num(_pick(o, "maxPain", "maxPainStrike", "maxPainPrice"))
            if v:
                return v, _ymd(_pick(o, "expiration", "expirationDate", "expiry"))
            if depth < 4:
                for x in o.values():
                    r = find(x, depth + 1)
                    if r:
                        return r
        elif isinstance(o, list) and depth < 4:
            for x in o[:3]:
                r = find(x, depth + 1)
                if r:
                    return r
        return None
    r = find(payload)
    return {"strike": r[0], "expiry": r[1]} if r else None


def parse_by_strike(payload):
    """Exposure By Strike / Open Interest By Strike: rows (or a dict keyed by strike) with call / put numbers.
    -> [(strike, call, put)] summed over expiries."""
    acc = {}
    for r in _records(payload):
        s = _num(_pick(r, "strike", "strikePrice", "k")) or _num(r.get("__key"))
        if not s:
            continue
        c, p, o = _split_call_put(r)
        if c is None and p is None:
            if o is None:
                continue
            c, p = (o, 0.0) if o >= 0 else (0.0, o)
        a = acc.setdefault(round(s, 2), [0.0, 0.0])
        a[0] += c or 0.0
        a[1] += p or 0.0
    return sorted((k, v[0], v[1]) for k, v in acc.items())


def parse_term(payload, spot=None, now=None):
    """Term Structure: per expiry the expected move ($) or the at-the-money implied volatility (turned into dollars
    with the price and the days left). -> [(YYYYMMDD, move $, iv)]"""
    out = []
    now = now or time.time()
    for r in _records(payload):
        e = _ymd(_pick(r, "expiration", "expirationDate", "expiry", "__key"))
        if not e:
            continue
        mv = _num(_pick(r, "expectedMove", "impliedMove", "expectedMoveDollars", "move", "em"))
        iv = _num(_pick(r, "atmIv", "atmImpliedVolatility", "impliedVolatility", "iv", "atmVol"))
        if iv and iv > 3:                         # 35 for 35%
            iv /= 100.0
        if mv and mv < 1 and spot and _pick(r, "expectedMovePct", "movePct") is not None:
            mv = mv * spot
        if not mv and iv and spot:
            days = max(0.5, (_secs(e[:4] + "-" + e[4:6] + "-" + e[6:]) + 72000 - now) / 86400.0)
            mv = spot * iv * math.sqrt(days / 365.0)
        if mv:
            out.append((e, round(mv, 2), iv))
    return sorted(out)


def parse_trade_side(payload):
    """Contract Trade Side Statistics: calls / puts bought (at or over the ask) against sold (at or under the bid).
    -> {"calls_bought", "calls_sold", "puts_bought", "puts_sold"} ($ or contracts, whichever the answer gives)."""
    out = {"calls_bought": 0.0, "calls_sold": 0.0, "puts_bought": 0.0, "puts_sold": 0.0}
    seen = False

    def walk(o, ctx="", depth=0):
        nonlocal seen
        if isinstance(o, dict):
            typ = str(_pick(o, "contractType", "type", "putCall", "callPut") or "").lower()
            for k, v in o.items():
                lk = (ctx + " " + typ + " " + str(k)).lower().replace("_", "")
                n = _num(v)
                if n is not None and ("premium" in lk or "volume" not in lk):
                    cp = "calls" if "call" in lk else "puts" if "put" in lk else None
                    bs = "bought" if any(w in lk for w in ("ask", "buy", "above")) else "sold" if any(w in lk for w in ("bid", "sell", "below")) else None
                    if cp and bs:
                        out[f"{cp}_{bs}"] += n
                        seen = True
                elif isinstance(v, (dict, list)) and depth < 4:
                    walk(v, ctx + " " + typ + " " + str(k), depth + 1)
        elif isinstance(o, list) and depth < 4:
            for x in o:
                walk(x, ctx, depth + 1)
    walk(_data(payload))
    return out if seen else None


# ---- the desk's own reads (no Quant Data needed) ------------------------------------------------------------------

def local_drift(prints, t, day_start):
    """CALL vs PUT money from the option flow the desk already pulls: calls bought at the ask add, sold at the bid
    take away; puts the other way round. -> same shape as parse_net_drift."""
    rows = sorted((p for p in prints if p.get("t", 0) >= day_start and p.get("premium")), key=lambda p: p["t"])
    if not rows:
        return None
    cc = pp = 0.0
    series = []
    for p in rows:
        s = 1.0 if p.get("side") == "ask" else -1.0 if p.get("side") == "bid" else 0.0
        if p.get("cp") == "C":
            cc += s * p["premium"]
        elif p.get("cp") == "P":
            pp += s * p["premium"]
        series.append([round(p["t"]), round(cc - pp)])
    return {"series": series[-400:], "calls": round(cc), "puts": round(pp), "net": round(cc - pp)}


def max_pain_from_oi(call_oi, put_oi):
    """The strike where the options in the money pay the least in total. call_oi / put_oi: {strike: contracts}."""
    strikes = sorted(set(call_oi) | set(put_oi))
    if len(strikes) < 3:
        return None
    best, best_s = None, None
    for s in strikes:
        pain = sum(oi * max(0.0, s - k) for k, oi in call_oi.items()) + sum(oi * max(0.0, k - s) for k, oi in put_oi.items())
        if best is None or pain < best:
            best, best_s = pain, s
    return best_s


def big_strikes(rows, spot, n_each=3, unit="$"):
    """rows [(strike, call, put)] -> the n biggest above and below price, biggest first, with which side carries it."""
    if not rows or not spot:
        return []
    out = []
    for s, c, p in rows:
        size = abs(c or 0.0) + abs(p or 0.0)
        if size <= 0:
            continue
        out.append({"strike": s, "size": round(size), "calls": round(abs(c or 0.0)), "puts": round(abs(p or 0.0)),
                    "side": "calls" if abs(c or 0) >= abs(p or 0) else "puts", "above": s > spot, "unit": unit})
    up = sorted((x for x in out if x["above"]), key=lambda x: -x["size"])[:n_each]
    dn = sorted((x for x in out if not x["above"]), key=lambda x: -x["size"])[:n_each]
    top = max([x["size"] for x in up + dn] or [1])
    for x in up + dn:
        x["rel"] = round(x["size"] / top, 2)
    return sorted(up + dn, key=lambda x: -x["strike"])


def expected_move(spot, iv, days):
    if not spot or not iv or days is None:
        return None
    return round(spot * iv * math.sqrt(max(0.5, days) / 365.0), 2)


def aggression(prints):
    """AT THE ASK on one contract: [t, price, contracts, "buy" / "sell" / None] prints -> % bought / sold."""
    b = sum(p[2] for p in prints if p[3] == "buy")
    s = sum(p[2] for p in prints if p[3] == "sell")
    n = sum(p[2] for p in prints)
    if not n:
        return None
    return {"ask_pct": round(100.0 * b / n), "bid_pct": round(100.0 * s / n), "contracts": int(n)}


def fmt_usd(v):
    a = abs(v or 0)
    s = f"${a / 1e9:.1f}B" if a >= 1e9 else f"${a / 1e6:.1f}M" if a >= 1e6 else f"${a / 1e3:.0f}K" if a >= 1e3 else f"${a:.0f}"
    return ("−" if (v or 0) < 0 else "+") + s if v else s


# ---- the reads, put together for one symbol -----------------------------------------------------------------------

class OptionMoney:
    def __init__(self, cfg):
        self.cfg = cfg
        self.qd = {}                 # symbol -> tool -> {"v": parsed, "t": when}
        self.status = {k: {"state": "untested", "detail": "", "t": None} for k in TOOLS}
        self.checked = None          # when the CHECK last ran
        self.lock = threading.Lock()

    def c(self):
        return self.cfg.get("optmoney") or {}

    def put(self, sym, tool, value, t):
        with self.lock:
            self.qd.setdefault(sym, {})[tool] = {"v": value, "t": t}

    def got(self, sym, tool, max_age):
        e = (self.qd.get(sym) or {}).get(tool)
        return e["v"] if e and e["v"] is not None and time.time() - e["t"] <= max_age else None

    def view(self, sym, spot, t, local=None, play=None, atr=None):
        """Everything the desk shows for one symbol. local: the desk's own data (see Engine._optmoney_local)."""
        c, local = self.c(), local or {}
        if not c.get("enabled", True) or not spot:
            return None
        out = {"symbol": sym, "spot": spot, "src": {}}
        # CALL vs PUT money
        d = self.got(sym, "net_drift", 600)
        if d:
            out["src"]["drift"] = "QUANT DATA"
        else:
            d = local.get("drift")
            if d:
                out["src"]["drift"] = local.get("drift_src", "FLOW")
        if d:
            ser = d["series"]
            back = [v for tt, v in ser if tt <= t - 900]
            d = dict(d, chg15=(d["net"] - back[-1]) if back else None)
            mag = max(float(c.get("lean_min_dollars", 250000)), 0.0)
            d["lean"] = "CALLS" if d["net"] >= mag else "PUTS" if d["net"] <= -mag else "EVEN"
            out["drift"] = d
        # MAX PAIN (this week's expiry first)
        mp = None
        rows = self.got(sym, "max_pain_by_exp", 3 * 3600)
        if rows:
            today = time.strftime("%Y%m%d", time.gmtime(t - 4 * 3600))
            ahead = [r for r in rows if r[0] >= today]
            if ahead:
                mp = {"strike": ahead[0][1], "expiry": ahead[0][0], "next": [{"expiry": e, "strike": s} for e, s in ahead[1:4]]}
                out["src"]["max_pain"] = "QUANT DATA"
        if not mp:
            one = self.got(sym, "max_pain", 3 * 3600)
            if one:
                mp = dict(one)
                out["src"]["max_pain"] = "QUANT DATA"
        if not mp and local.get("max_pain"):
            mp = dict(local["max_pain"])
            out["src"]["max_pain"] = local.get("max_pain_src", "CHAIN")
        if mp and mp.get("strike"):
            mp["dist"] = round(mp["strike"] - spot, 2)
            mp["expires_today"] = mp.get("expiry") == time.strftime("%Y%m%d", time.gmtime(t - 4 * 3600))
            out["max_pain"] = mp
        # BIG STRIKES
        n_each = int(c.get("strikes_each_side", 3))
        ex = self.got(sym, "exposure", 1800)
        if ex:
            out["strikes"] = big_strikes(ex, spot, n_each, "$")
            out["src"]["strikes"] = "QUANT DATA"
        else:
            oi = self.got(sym, "oi_by_strike", 6 * 3600) or local.get("oi_rows")
            if oi:
                out["strikes"] = big_strikes(oi, spot, n_each, "ct")
                out["src"]["strikes"] = "QUANT DATA OI" if self.got(sym, "oi_by_strike", 6 * 3600) else local.get("oi_src", "CHAIN")
        # EXPECTED MOVE
        em = None
        ts = self.got(sym, "term_structure", 3 * 3600)
        if ts:
            e, mv, iv = ts[0]
            em = {"expiry": e, "move": mv, "iv": iv}
            out["src"]["em"] = "QUANT DATA"
        elif local.get("em"):
            em = dict(local["em"])
            out["src"]["em"] = local.get("em_src", "CHAIN")
        if em:
            em["hi"] = round(spot + em["move"], 2)
            em["lo"] = round(spot - em["move"], 2)
            out["em"] = em
        # OPENING MONEY (overnight open interest change) and CALLS / PUTS BOUGHT vs SOLD
        if local.get("opening"):
            out["opening"] = local["opening"]
        tsd = self.got(sym, "trade_side", 900)
        if tsd:
            out["bought_sold"] = tsd
        if local.get("aggression"):
            out["aggression"] = local["aggression"]
        out["checks"] = self.checks(out, play, atr)
        return out

    def checks(self, v, play, atr):
        """The plain-English lines for PLAY SETUP: the play's MP against the expected move, a big strike between the
        pivot and the target, max pain's pull, the money's lean against the side."""
        lines = []
        if not play or not play.get("side"):
            return lines
        long_ = play["side"] == "long"
        piv = _num(play.get("trigger")) or v["spot"]
        tgt = _num(play.get("target"))
        em = v.get("em")
        if tgt and em:
            need = abs(tgt - piv)
            if need > em["move"] * 1.05:
                lines.append({"tone": "warn", "key": "em", "text": f"MP {need:.2f} · options expect {em['move']:.2f} by {em['expiry'][4:6]}/{em['expiry'][6:]}: the target is past what is priced in"})
            else:
                lines.append({"tone": "ok", "key": "em", "text": f"MP {need:.2f} inside the expected move {em['move']:.2f} ({em['expiry'][4:6]}/{em['expiry'][6:]})"})
        if tgt:
            lo, hi = sorted((piv, tgt))
            way = [s for s in v.get("strikes") or [] if lo < s["strike"] < hi and s.get("rel", 0) >= 0.5]
            if way:
                s = max(way, key=lambda x: x["rel"])
                lines.append({"tone": "warn", "key": "strike", "text": f"big strike {s['strike']:g} between the pivot and the target: pay yourself into it"})
            else:
                lines.append({"tone": "ok", "key": "strike", "text": "no big strike between the pivot and the target"})
        mp = v.get("max_pain")
        if mp and mp.get("expires_today"):
            toward = (mp["strike"] > v["spot"]) == long_
            lines.append({"tone": "ok" if toward else "warn", "key": "mp",
                          "text": f"expiry today: option max pain {mp['strike']:g} is {'with' if toward else 'against'} the {play['side']}"})
        d = v.get("drift")
        if d and d["lean"] != "EVEN":
            with_ = (d["lean"] == "CALLS") == long_
            lines.append({"tone": "ok" if with_ else "warn", "key": "drift",
                          "text": f"option money leans {d['lean']} today ({fmt_usd(d['net'])}): {'with' if with_ else 'against'} the {play['side']}"})
        return lines

    def reads(self, v, direction, atr):
        """What the scoring log keeps with a call: each read in the call's direction (+1 up, -1 down)."""
        if not v or not direction:
            return {}
        up = direction > 0
        spot = v["spot"]
        r = {}
        d = v.get("drift")
        if d:
            r["money"] = "EVEN" if d["lean"] == "EVEN" else ("WITH" if (d["lean"] == "CALLS") == up else "AGAINST")
            if d.get("chg15") is not None:
                r["money15"] = "WITH" if (d["chg15"] > 0) == up else "AGAINST"
        span = (atr or spot * 0.018) * float(self.c().get("strike_near_atr", 0.5))
        ss = v.get("strikes")
        if ss:
            ahead = [s for s in ss if spot < s["strike"] <= spot + span] if up else [s for s in ss if spot - span <= s["strike"] < spot]
            r["strike"] = "IN THE WAY" if any(s.get("rel", 0) >= 0.5 for s in ahead) else "CLEAR"
        mp = v.get("max_pain")
        if mp:
            r["max_pain"] = "TOWARD" if (mp["strike"] > spot) == up else "AWAY"
        em = v.get("em")
        if em:
            room = (em["hi"] - spot) if up else (spot - em["lo"])
            r["em_room"] = "ROOM" if room >= (atr or spot * 0.018) * 0.5 else "STRETCHED"
        op = v.get("opening")
        if op and op.get("lean"):
            r["opening"] = "WITH" if (op["lean"] == "CALLS") == up else "AGAINST" if op["lean"] in ("CALLS", "PUTS") else "EVEN"
        return r


def practice_view(sym, spot, t, prints, atr=None):
    """The practice market's option money, made the same way the live desk reads it: the practice flow for CALL vs
    PUT money, a steady made-up open interest for max pain and the big strikes, a 35% option price for the move."""
    if not spot:
        return {}
    step = 0.5 if spot < 25 else 1.0 if spot < 200 else 2.5 if spot < 500 else 5.0
    base = round(spot / step) * step
    seed = sum(ord(ch) for ch in sym)
    call_oi, put_oi = {}, {}
    for i in range(-10, 11):
        k = round(base + i * step, 2)
        w = 1.0 / (1 + abs(i) * 0.35) * (1.0 + 0.9 * (((seed * 7 + i * 13) % 11) / 10.0))
        call_oi[k] = int(3000 * w * (1.6 if i > 0 else 0.7))
        put_oi[k] = int(3000 * w * (1.6 if i < 0 else 0.7))
    day_start = t - ((t - 4 * 3600) % 86400)      # New York's day (practice: EDT is close enough)
    days = 4 - (int((t - 4 * 3600) // 86400) + 3) % 7      # Friday this week (practice)
    exp = time.strftime("%Y%m%d", time.gmtime(t - 4 * 3600 + max(0, days) * 86400))
    rows = [(k, call_oi[k] * 100.0 * spot * 0.004, put_oi[k] * 100.0 * spot * 0.004) for k in sorted(call_oi)]
    return {"drift": local_drift(prints, t, day_start), "drift_src": "PRACTICE FLOW",
            "max_pain": {"strike": max_pain_from_oi(call_oi, put_oi), "expiry": exp}, "max_pain_src": "PRACTICE",
            "oi_rows": rows, "oi_src": "PRACTICE",
            "em": {"expiry": exp, "move": expected_move(spot, 0.35, max(1, days)), "iv": 0.35}, "em_src": "PRACTICE",
            "opening": opening_lean(int(sum(call_oi.values()) * (0.05 if seed % 2 else 0.02)),
                                    int(sum(put_oi.values()) * (0.02 if seed % 2 else 0.05)), "PRACTICE")}


def opening_lean(calls, puts, src):
    """OPENING MONEY: contracts added overnight on calls and on puts; it leans the side that grew 20% more."""
    lean = "CALLS" if calls > max(0, puts) * 1.2 else "PUTS" if puts > max(0, calls) * 1.2 else "EVEN"
    return {"calls": calls, "puts": puts, "lean": lean, "src": src}


# ---- Quant Data, polled ------------------------------------------------------------------------------------------

class OptionMoneyFeed:
    """Calls Quant Data's tools for the desk's symbols, each tool on its own timer, and keeps the answers in
    engine.optmoney. A tool the key does not open (403 / 404) is left alone for six hours, then tried again."""

    def __init__(self, engine, cfg, request):
        self.engine = engine
        self.cfg = cfg
        self.request = request                 # (path, body) -> parsed JSON (QuantDataFeed._request: the key, errors)
        self.stop_evt = threading.Event()
        self.next = {}                         # (sym, tool) -> when to call again
        self.off_until = {}                    # tool -> skip until
        self.sample_dir = os.path.join(engine.cfg["recording"]["dir"], "quantdata_tools")

    def c(self):
        return self.cfg.get("optmoney") or {}

    def paths(self):
        return dict(TOOLS, **(self.c().get("tools") or {}))

    def start(self):
        threading.Thread(target=self._loop, name="optmoney", daemon=True).start()
        return self

    def stop(self):
        self.stop_evt.set()

    def symbols(self):
        syms = list(getattr(self.engine, "syms", {}) or {})
        return syms[: int(self.c().get("max_symbols", 15))]

    def body(self, sym, tool, now=None):
        from zoneinfo import ZoneInfo
        day = datetime.fromtimestamp(now or time.time(), ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
        b = {"sessionDate": day, "filter": {"ticker": sym}}
        if tool == "exposure":
            b.update(greekMode="GAMMA", representationMode="PER_ONE_PERCENT_MOVE")
        return b

    def parse(self, tool, payload, sym):
        st = self.engine.syms.get(sym)
        spot = st.price() if st else None
        if tool == "net_drift":
            return parse_net_drift(payload)
        if tool == "max_pain_by_exp":
            return parse_max_pain_by_exp(payload) or None
        if tool == "max_pain":
            return parse_max_pain(payload)
        if tool in ("exposure", "oi_by_strike"):
            return parse_by_strike(payload) or None
        if tool == "term_structure":
            return parse_term(payload, spot) or None
        if tool == "trade_side":
            return parse_trade_side(payload)
        return None

    def every(self, tool):
        c = self.c()
        return float({"net_drift": c.get("drift_seconds", 60), "exposure": c.get("exposure_seconds", 300),
                      "max_pain_by_exp": c.get("maxpain_seconds", 900), "max_pain": c.get("maxpain_seconds", 900),
                      "oi_by_strike": c.get("oi_seconds", 1800), "term_structure": c.get("term_seconds", 900),
                      "trade_side": c.get("trade_side_seconds", 300)}.get(tool, 600))

    def call(self, sym, tool, save=False):
        om = self.engine.optmoney
        try:
            payload = self.request(self.paths()[tool], self.body(sym, tool))
        except Exception as exc:
            msg = str(exc)[:200]
            st = om.status[tool]
            st.update(state="no" if any(x in msg for x in ("HTTP 403", "HTTP 404", "HTTP 400")) else "error", detail=msg, t=time.time())
            if st["state"] == "no":
                self.off_until[tool] = time.time() + 6 * 3600
            return None
        if save or om.status[tool]["state"] != "ok":
            try:
                os.makedirs(self.sample_dir, exist_ok=True)
                with open(os.path.join(self.sample_dir, f"{tool}.json"), "w", encoding="utf-8") as fh:
                    json.dump({"path": self.paths()[tool], "request": self.body(sym, tool), "response": payload}, fh, indent=1, default=str)
            except OSError:
                pass
        v = self.parse(tool, payload, sym)
        om.status[tool].update(state="ok" if v is not None else "unread",
                               detail="" if v is not None else "answered, but not read: see recordings/quantdata_tools/" + tool + ".json",
                               t=time.time())
        om.put(sym, tool, v, time.time())
        return v

    def check(self):
        """CHECK: every tool once on one symbol, its answer saved; which ones this key opens."""
        syms = self.symbols()
        sym = "SPY" if "SPY" in syms else (syms[0] if syms else "SPY")
        self.off_until.clear()
        for tool in TOOLS:
            self.call(sym, tool, save=True)
        self.engine.optmoney.checked = time.time()
        return {k: dict(v) for k, v in self.engine.optmoney.status.items()}

    def _loop(self):
        try:
            self.check()
        except Exception:
            pass
        while not self.stop_evt.is_set():
            budget = max(1, int(self.c().get("max_per_minute", 60)) // 6)    # per 10 s
            now = time.time()
            for sym in self.symbols():
                for tool in TOOLS:
                    if budget <= 0:
                        break
                    if self.off_until.get(tool, 0) > now or self.next.get((sym, tool), 0) > now:
                        continue
                    if tool == "max_pain" and self.engine.optmoney.got(sym, "max_pain_by_exp", 3 * 3600):
                        continue
                    if tool == "oi_by_strike" and self.engine.optmoney.got(sym, "exposure", 1800):
                        continue
                    self.next[(sym, tool)] = now + self.every(tool)
                    budget -= 1
                    try:
                        self.call(sym, tool)
                    except Exception:
                        pass
            self.stop_evt.wait(10.0)
