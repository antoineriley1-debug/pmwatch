"""MARKET ANALYSIS DETAILED REPORT: Twiney's TradingView boards, rebuilt inside TED on daily closes.

Every test below is the same test his Pine boards run, bar for bar, so the page and the boards agree:
    Twiney's Recession Steps v1.2   the five steps, their day counts, the history from 2007
    Twiney's Market State v1.1      the four states (CLEAR / CAUTION / CONFIRMED / LATE) with the action for each
    Twiney's Relationships Board v1.5  the sixteen relationships, each with its line, cushion and direction
    Twiney's Rate Baskets Board v1.3.0  thirteen sector funds in three rate baskets against the S&P
    Twiney's Macro Vision (who is carrying it)  sector leaders, chips and big names, the average stock vs the S&P
plus what TED can see that a Pine board cannot: all 500 S&P members, so the leaders and the stocks lagging by
name, and how many stocks in each sector are taking part.

This is the backdrop, never a call. It decides how much and which way Twiney leans; PS60 decides when.

The numbers come in as plain daily closes ({key: [(yyyymmdd, close), ...]}); ``build_report`` is pure (no network,
no clock) so it is tested bar for bar. Loading the closes (IBKR, FRED, the cache) lives in ``macrofeed``.

Breadth: TradingView's S5FI / S5TH are not on IBKR, so TED counts the 500 members itself (share above their own
50-day / 200-day). It counts today's members over the whole history, so the early years read a little stronger
than the official index did; the page says so.
"""

import math
import random

VERSION = "1.0"

# ---- the thirteen sector funds of the Rate Baskets Board (name, fund, basket, what it is) ------------------------
SECTORS = [
    ("ENERGY", "XLE", 0, "Oil and gas. Earns cash today and rides inflation, which is what pushes rates up."),
    ("BIG BANKS", "XLF", 0, "The giant banks. They earn more when rates rise, as long as people keep paying their loans."),
    ("TECHNOLOGY", "XLK", 1, "Profits that arrive years from now. Higher rates make far-off profits worth less today."),
    ("COMMUNICATION", "XLC", 1, "Ads, phones, streaming. Ad budgets are the first thing cut when business slows."),
    ("DISCRETIONARY", "XLY", 1, "Cars, homes, big-ticket things people buy on credit. Cheaper credit means more buying."),
    ("UTILITIES", "XLU", 1, "Power companies. Built on borrowed money, and their dividend competes with Treasuries."),
    ("REAL ESTATE", "XLRE", 1, "Landlords. Their debt rolls over at whatever the new rate is."),
    ("HOMEBUILDERS", "XHB", 1, "Mortgage rates are the whole story. Buyers show up before the rate cut arrives."),
    ("REGIONAL BANKS", "KRE", 1, "Small banks. They carry the loans the giants do not want. First to crack when credit tightens."),
    ("STAPLES", "XLP", 2, "Food, soap, toothpaste. Bought no matter what the economy does."),
    ("HEALTHCARE", "XLV", 2, "Doctors and drugs. Demand does not follow the economy."),
    ("INDUSTRIALS", "XLI", 3, "Machines, freight, construction. Follows real growth, not rates."),
    ("MATERIALS", "XLB", 3, "Copper, steel, chemicals. Follows real growth."),
]
BASKETS = [
    ("MONEY COSTS MORE", "Wins when money costs more: rates up, oil up, banks earning the gap between what they pay and what they charge."),
    ("MONEY GETS CHEAPER", "Usually benefits when borrowing costs fall, but this basket can lead while rates rise. The board reads the actual 10-year separately; the basket name is not a statement about today's rate direction."),
    ("WHERE MONEY HIDES", "Wins when nobody wants to bet on rates at all. Bought for safety, not for growth."),
    ("FOLLOWS THE ECONOMY", "No rate bet. These follow the real economy. Green here means real growth. Red here while everything else is green means the rally is thin."),
]
# the 11 GICS sector funds Macro Vision ranks for its sector leaders row
GICS_FUND = {"Energy": "XLE", "Financials": "XLF", "Information Technology": "XLK", "Communication Services": "XLC",
             "Consumer Discretionary": "XLY", "Utilities": "XLU", "Real Estate": "XLRE", "Consumer Staples": "XLP",
             "Health Care": "XLV", "Industrials": "XLI", "Materials": "XLB"}
GICS_SHORT = {"Information Technology": "Technology", "Communication Services": "Communication", "Consumer Discretionary": "Discretionary",
              "Consumer Staples": "Staples", "Health Care": "Healthcare"}

# FRED series (free, no key) for what IBKR does not carry
FRED = {"Y10": "DGS10", "Y02": "DGS2", "UR": "UNRATE", "CLM": "ICSA", "WTI": "DCOILWTICO", "BRENT": "DCOILBRENTEU",
        "OAS": "BAMLH0A0HYM2"}

MS_STATES = {
    1: ("CLEAR", "No steps on. Lenders are calm, so nothing in the economy plumbing is flagging.",
        "Normal size on your usual setups. No defensive overlay. The panel is background. Both directions traded normally."),
    2: ("CAUTION", "Step 1 on, steps 2 and 3 not confirmed. Credit is nervous but stocks have not agreed yet; one of them is wrong.",
        "Cut swing and position size by a quarter to a third. Tighten stops on anything held overnight. Stop adding to small caps and cyclicals. Take profits earlier than usual. Day trades barely affected. This state says smaller, not short."),
    3: ("CONFIRMED", "Step 2 on and held {hold} extra days, or steps 1, 2 and 3 all on together. Credit, breadth and banks agree: the regime changed.",
        "The regime has changed. Cut size again. Rotate holdings toward staples, utilities, healthcare. Long bonds start working. Downside exposure earns its keep here, and only with defined risk so the loss is capped at what you paid. Favor the short side on intraday setups, since the tape now leans the same way as the backdrop."),
    4: ("LATE", "Step 4 or step 5 on. The economy is confirming what the market already priced; most of the move has usually happened.",
        "The move has mostly happened. Flip from defense to preparation. Build a shopping list. Scale in gradually. Stop pressing shorts. This is where people who read the whole sequence correctly still lose money by staying short too long."),
}
MS_RULES = ("1. Act on the state, not on a flip: one day of a step turning on changes nothing. 2. States move one at a time. "
            "3. Write your size for each state down in advance, while calm. 4. This sets how much and which way you lean; PS60 "
            "sets when. Never ask it to time an entry. 5. Downside exposure uses defined risk: a short can lose more than you put "
            "up, and the sharpest rallies happen in bear markets.")
MS_STATE3 = ("Hit hardest, roughly in order: small caps, regional banks, high-yield credit, consumer discretionary, cyclical "
             "industrials, semiconductors. Holds up: staples, utilities, healthcare, long Treasuries, the dollar. Safer expression "
             "is relative value: long staples against short discretionary, or long large caps against short small caps. Banks: "
             "shorting a group that lags but still trends above its 200-day is how people get run over; the setup most wait for "
             "is the 200-day breaking with the other two clues on.")
STEP_NAMES = {1: "LENDERS NERVOUS", 2: "FEWER STOCKS", 3: "BANKS LAG", 4: "RECESSION WARNING", 5: "JOBS"}


# =====================================================================================================================
# small series tools (None = Pine's na)
# =====================================================================================================================
def sma(vals, n):
    out, s, q = [None] * len(vals), 0.0, []
    for i, v in enumerate(vals):
        q.append(v)
        if v is not None:
            s += v
        if len(q) > n:
            old = q.pop(0)
            if old is not None:
                s -= old
        if len(q) == n and all(x is not None for x in q):
            out[i] = s / n
    return out


def sma_fast(vals, n):
    """sma for a series with no gaps once it starts (closes): O(n)."""
    out, s, cnt = [None] * len(vals), 0.0, 0
    for i, v in enumerate(vals):
        if v is None:
            s, cnt = 0.0, 0
            continue
        s += v
        cnt += 1
        if cnt > n:
            s -= vals[i - n]
            cnt = n
        if cnt == n:
            out[i] = s / n
    return out


def shift(vals, k):
    return [vals[i - k] if i >= k else None for i in range(len(vals))]


def lowest(vals, n):
    out = [None] * len(vals)
    for i in range(len(vals)):
        if i + 1 >= n:
            w = vals[i - n + 1:i + 1]
            if all(x is not None for x in w):
                out[i] = min(w)
    return out


def chg(a, b):
    if a is None or b is None or b == 0:
        return None
    return (a / b - 1.0) * 100.0


def align(axis, days, vals):
    """The value of a series on each chart day: its own bar that day, else its last bar before (request.security)."""
    out, j, last, n = [None] * len(axis), 0, None, len(days)
    for i, d in enumerate(axis):
        while j < n and days[j] <= d:
            last = vals[j]
            j += 1
        out[i] = last
    return out


def last_day_index(axis, days):
    """For each chart day, how many chart days since this series last printed (data check: an old feed)."""
    out, j, lastd, n = [None] * len(axis), 0, None, len(days)
    pos = {d: i for i, d in enumerate(axis)}
    for i, d in enumerate(axis):
        while j < n and days[j] <= d:
            lastd = days[j]
            j += 1
        out[i] = None if lastd is None else i - pos.get(lastd, i)
    return out


def runs(flags):
    out, n = [], 0
    for f in flags:
        n = n + 1 if f else 0
        out.append(n)
    return out


def fmt_day(d):
    if not d:
        return "n/a"
    m = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][(d // 100) % 100 - 1]
    return f"{m} {d % 100}, {d // 10000}"


def n2(v, f="0.00"):
    if v is None:
        return "n/a"
    places = len(f.split(".")[1]) if "." in f else 0
    return f"{v:.{places}f}"


def sg(v, places=2):
    if v is None:
        return "n/a"
    return ("+" if v > 0 else "") + f"{v:.{places}f}"


def pct(v):
    return "n/a" if v is None else sg(v) + "%"


def days_word(n):
    return f"{n} trading day" + ("" if n == 1 else "s")


def cos(p):
    return "?" if p is None else str(int(round(p * 5.0)))


# =====================================================================================================================
# the report
# =====================================================================================================================
def _native(S, key, smas=(), shifts=()):
    """Closes of one series plus the moving averages / lookbacks computed on ITS OWN bars (like request.security)."""
    rows = S.get(key) or []
    days = [d for d, _ in rows]
    c = [v for _, v in rows]
    out = {"c": c}
    for n in smas:
        out[f"sma{n}"] = sma_fast(c, n)
    for k in shifts:
        out[f"b{k}"] = shift(c, k)
    return days, out


def _aligned(S, axis, key, smas=(), shifts=()):
    days, f = _native(S, key, smas, shifts)
    if not days:
        return {k: [None] * len(axis) for k in ["c"] + [f"sma{n}" for n in smas] + [f"b{k}" for k in shifts]}, None
    return {k: align(axis, days, v) for k, v in f.items()}, last_day_index(axis, days)


def breadth_series(S, axis, members):
    """Share of the members above their own 50-day and 200-day on each chart day (S5FI / S5TH, counted by TED), plus
    per member the last values the page uses (sector breadth, leaders and laggards)."""
    pos = {d: i for i, d in enumerate(axis)}
    n = len(axis)
    up50, cnt50, up200, cnt200 = [0] * n, [0] * n, [0] * n, [0] * n
    per = {}
    for sym in members:
        rows = S.get("M:" + sym) or []
        if len(rows) < 2:
            continue
        c = [v for _, v in rows]
        a50, a200 = sma_fast(c, 50), sma_fast(c, 200)
        for j, (d, v) in enumerate(rows):
            i = pos.get(d)
            if i is None:
                continue
            if a50[j] is not None:
                cnt50[i] += 1
                if v > a50[j]:
                    up50[i] += 1
            if a200[j] is not None:
                cnt200[i] += 1
                if v > a200[j]:
                    up200[i] += 1
        k = len(c) - 1
        hi = max(c[-252:]) if len(c) >= 2 else None
        lo = min(c[-252:]) if len(c) >= 2 else None
        per[sym] = {"last_day": rows[-1][0], "c": c[-1], "d1": chg(c[-1], c[-2]) if k >= 1 else None,
                    "w": chg(c[-1], c[-6]) if k >= 5 else None, "m": chg(c[-1], c[-21]) if k >= 20 else None,
                    "y": chg(c[-1], c[-253]) if k >= 252 else None,
                    "a50": None if a50[-1] is None else c[-1] > a50[-1], "a200": None if a200[-1] is None else c[-1] > a200[-1],
                    "hi52": len(c) >= 252 and c[-1] >= hi, "lo52": len(c) >= 252 and c[-1] <= lo}
    # a day only counts when enough members printed that day (a holiday mismatch or a missing pull is not a reading)
    need = max(10, int(len(members) * 0.30)) if members else 10
    s5fi = [100.0 * up50[i] / cnt50[i] if cnt50[i] >= need else None for i in range(n)]
    s5th = [100.0 * up200[i] / cnt200[i] if cnt200[i] >= need else None for i in range(n)]
    return s5fi, s5th, per, (cnt50[-1] if n else 0)


def build_report(S, members=None, mc=None, source="IBKR + FRED", breadth=None):
    """S: {key: [(yyyymmdd, close)]}. Keys: SPY, SPY.A (dividend-adjusted), HYG.A, XLF.A, the 13 sector funds, RSP,
    SMH, COPPER, M:<member>, F:<FRED key>. members: {symbol: (name, gics sector)}. mc: SETTINGS > Market report."""
    mc = dict(mc or {})
    members = members or {}
    confirm_days = int(mc.get("confirm_days", 2) or 2)
    hold_days = int(mc.get("hold_days", 5))
    follow_win = int(mc.get("follow_window", 40) or 40)
    bank_key = (mc.get("bank_fund") or "XLF").upper()

    spy_key = "SPY.A" if S.get("SPY.A") else "SPY"
    axis = [d for d, _ in (S.get(spy_key) or [])]
    if len(axis) < 30:
        return {"ok": False, "reason": "not enough S&P history yet", "version": VERSION, "source": source}
    n = len(axis)
    L = n - 1

    def adj(k):
        return k + ".A" if S.get(k + ".A") else k

    spy, spy_age = _aligned(S, axis, spy_key, smas=(50, 200), shifts=(5, 20))
    hyg, hyg_age = _aligned(S, axis, adj("HYG"), smas=(50,), shifts=(5, 10, 20, 25))
    xlf, xlf_age = _aligned(S, axis, adj(bank_key), smas=(200,), shifts=(5, 20, 25))
    cop, cop_age = _aligned(S, axis, "COPPER", smas=(200,), shifts=(5,))
    y10, y10_age = _aligned(S, axis, "F:Y10", shifts=(5,))
    y02, y02_age = _aligned(S, axis, "F:Y02", shifts=(5,))
    ur, ur_age = _aligned(S, axis, "F:UR")
    clm, clm_age = _aligned(S, axis, "F:CLM")
    wti, wti_age = _aligned(S, axis, "F:WTI", shifts=(5,))
    brt, brt_age = _aligned(S, axis, "F:BRENT", shifts=(5,))
    oas, oas_age = _aligned(S, axis, "F:OAS", shifts=(5,))
    s5fi, s5th, per, nmem = breadth_series(S, axis, list(members))
    if breadth is not None:            # tests: the two breadth lines given directly, one value per chart day
        s5fi, s5th = list(breadth[0]), list(breadth[1])
        nmem = nmem or 500

    # ---------------- per chart day: the five steps (Recession Steps v1.2) ----------------
    hygC, hyg50, hygMo, hygWkAgo = hyg["c"], hyg["sma50"], hyg["b20"], hyg["b5"]
    hygOk = [hygC[i] is not None and hyg50[i] is not None and hygMo[i] is not None for i in range(n)]
    credWeakDay = [hygOk[i] and hygC[i] < hyg50[i] and hygC[i] < hygMo[i] for i in range(n)]
    credRun = runs(credWeakDay)
    s1 = [r >= 5 for r in credRun]
    hygWk = [chg(hygC[i], hygWkAgo[i]) for i in range(n)]
    thinRun = runs([v is not None and v < 30.0 for v in s5fi])
    s2 = [r >= 5 for r in thinRun]
    spyMo = [chg(spy["c"][i], spy["b20"][i]) for i in range(n)]
    xlfMo = [chg(xlf["c"][i], xlf["b20"][i]) for i in range(n)]
    bankVs = [None if spyMo[i] is None or xlfMo[i] is None else xlfMo[i] - spyMo[i] for i in range(n)]
    bankLag = [v is not None and v <= -3.0 for v in bankVs]
    bankBelow = [xlf["c"][i] is not None and xlf["sma200"][i] is not None and xlf["c"][i] < xlf["sma200"][i] for i in range(n)]
    credWeakWk = [v is not None and v <= -1.0 for v in hygWk]
    bankN = [int(bankLag[i]) + int(bankBelow[i]) + int(credWeakWk[i]) for i in range(n)]
    s3 = [b >= 2 for b in bankN]
    urAvg3 = sma(ur["c"], 63)
    urLow12 = lowest(urAvg3, 252)
    sahm = [None if urAvg3[i] is None or urLow12[i] is None else urAvg3[i] - urLow12[i] for i in range(n)]
    laborWarn = [v is not None and v >= 0.50 for v in sahm]
    laborClose = [v is not None and 0.30 <= v < 0.50 for v in sahm]
    clmK = [None if v is None else (v / 1000.0 if v > 5000.0 else v) for v in clm["c"]]
    clmAvg4 = sma(clmK, 20)
    clmLow6 = lowest(clmAvg4, 130)
    curve = [None if y10["c"][i] is None or y02["c"][i] is None else y10["c"][i] - y02["c"][i] for i in range(n)]
    curveWarn = [v is not None and v < 0 for v in curve]
    stockWeak = [spy["c"][i] is not None and spy["sma200"][i] is not None and spy["c"][i] < spy["sma200"][i] for i in range(n)]
    longWeak = [v is not None and v < 45 for v in s5th]
    copWeak = [cop["c"][i] is not None and cop["sma200"][i] is not None and cop["c"][i] < cop["sma200"][i] for i in range(n)]
    econN = [(2 if laborWarn[i] else 1 if laborClose[i] else 0) + int(curveWarn[i]) + int(credWeakWk[i]) + int(stockWeak[i])
             + int(longWeak[i]) + int(copWeak[i]) for i in range(n)]
    s4 = [econN[i] >= 3 or laborClose[i] or laborWarn[i] for i in range(n)]
    s5 = laborWarn
    steps = {1: s1, 2: s2, 3: s3, 4: s4, 5: s5}
    drun = {k: runs(v) for k, v in steps.items()}

    def since(k):
        if not steps[k][L]:
            return None
        return axis[L - drun[k][L] + 1]

    step_now = 0 if not s1[L] else 1 if not s2[L] else 2 if not s3[L] else 3 if not s4[L] else 4 if not s5[L] else 5

    # ---------------- Market State v1.1: the state machine ----------------
    st, cand, candRun = 1, 1, 0
    st_series, raw_series = [], []
    for i in range(n):
        raw = 4 if (s4[i] or s5[i]) else 3 if ((s2[i] and drun[2][i] >= hold_days) or (s1[i] and s2[i] and s3[i])) else 2 if s1[i] else 1
        want = st + 1 if raw > st else raw
        if want == st:
            candRun = 0
        elif want == cand:
            candRun += 1
        else:
            cand, candRun = want, 1
        if want != st and candRun >= confirm_days:
            st, candRun = want, 0
        st_series.append(st)
        raw_series.append(raw)
    st_run = 1
    for i in range(L, 0, -1):
        if st_series[i - 1] != st_series[L]:
            break
        st_run += 1
    st_since = axis[L - st_run + 1]
    want_now = st_series[L] + 1 if raw_series[L] > st_series[L] else raw_series[L]

    # ---------------- history from when the junk bond and breadth data both start ----------------
    h0 = next((i for i in range(n) if hygOk[i] and s5fi[i] is not None), None)
    hist = {"start": axis[h0] if h0 is not None else None, "years": round((n - (h0 or n)) / 252.0, 1) if h0 is not None else 0}
    ep = {k: 0 for k in range(1, 6)}
    lenSum = {k: 0 for k in range(1, 6)}
    lenMax = {k: 0 for k in range(1, 6)}
    lastOn = {k: None for k in range(1, 6)}
    fol = {k: 0 for k in range(1, 6)}
    win = {k: 0 for k in range(1, 6)}
    cur = {k: 0 for k in range(1, 6)}
    turned_on = {k: 0 for k in range(1, 6)}
    ep1, fol1, s2InEp, len1Sum, len1Max = 0, 0, False, 0, 0
    brEp, brLast, thinMax = 0, None, 0
    st_days = {k: 0 for k in range(1, 5)}
    st_entries = {k: 0 for k in range(1, 5)}
    st_last = {k: None for k in range(1, 5)}
    hist_bars = 0
    s2_heal = 0        # step 2 runs that ended with no step 3 inside the window
    if h0 is not None:
        for i in range(h0, n):
            hist_bars += 1
            for k in range(1, 6):
                o, p = steps[k][i], steps[k][i - 1] if i > 0 else False
                if o:
                    lastOn[k] = axis[i]
                    cur[k] += 1
                else:
                    if p:
                        ep[k] += 1
                        lenSum[k] += cur[k]
                        lenMax[k] = max(lenMax[k], cur[k])
                    cur[k] = 0
                if o and not p:
                    turned_on[k] += 1
                    win[k] = follow_win
                    if k > 1 and win[k - 1] > 0:
                        fol[k - 1] += 1
                        win[k - 1] = 0
                elif win[k] > 0:
                    win[k] -= 1
            # Recession Steps' own count: step 2 confirmed WHILE step 1 was on
            if s1[i] and s2[i]:
                s2InEp = True
            if i > 0 and not s1[i] and s1[i - 1]:
                ep1 += 1
                len1Sum += drun[1][i - 1]
                len1Max = max(len1Max, drun[1][i - 1])
                if s2InEp:
                    fol1 += 1
                s2InEp = False
            if thinRun[i] == 5:
                brEp += 1
                brLast = axis[i]
            thinMax = max(thinMax, thinRun[i])
            sk = st_series[i]
            st_days[sk] += 1
            if i == h0 or st_series[i - 1] != sk:
                st_entries[sk] += 1
                st_last[sk] = axis[i]
    step_hist = {}
    for k in range(1, 6):
        avg = round(lenSum[k] / ep[k]) if ep[k] else None
        since_last = None
        if lastOn[k] is not None and not steps[k][L]:
            since_last = L - axis.index(lastOn[k])
        step_hist[k] = {"episodes": ep[k], "turned_on": turned_on[k], "avg_days": avg, "longest": lenMax[k],
                        "last_on": lastOn[k], "days_since": since_last, "next_followed": fol[k] if k < 5 else None,
                        "on_now": steps[k][L], "run_now": drun[k][L]}
    hist.update(steps=step_hist, follow_window=follow_win, ep1=ep1, fol1=fol1, heal1=ep1 - fol1,
                len1_avg=round(len1Sum / ep1) if ep1 else None, len1_max=len1Max, breadth_thin_runs=brEp,
                breadth_thin_last=brLast, breadth_thin_longest=thinMax,
                states={k: {"pct_days": round(100.0 * st_days[k] / hist_bars, 1) if hist_bars else None, "entered": st_entries[k],
                            "last_entered": st_last[k]} for k in range(1, 5)}, bars=hist_bars)

    # ---------------- the numbers on the last day ----------------
    g = {}
    g["spyC"], g["spy50"], g["spy200"] = spy["c"][L], spy["sma50"][L], spy["sma200"][L]
    g["spyGap50"] = None if g["spyC"] is None or g["spy50"] is None else g["spyC"] - g["spy50"]
    g["hygC"], g["hyg50"], g["hygMo"] = hygC[L], hyg50[L], hygMo[L]
    g["hygVs50"], g["hygVsMo"], g["hygWk"] = chg(hygC[L], hyg50[L]), chg(hygC[L], hygMo[L]), hygWk[L]
    g["s5fi"], g["s5th"] = s5fi[L], s5th[L]
    g["s5fiWk"] = s5fi[L - 5] if L >= 5 else None
    g["s5fiMo"] = s5fi[L - 20] if L >= 20 else None
    g["s5thWk"] = s5th[L - 5] if L >= 5 else None
    g["s5thMo"] = s5th[L - 20] if L >= 20 else None
    g["xlfC"], g["xlf200"], g["bankVs"] = xlf["c"][L], xlf["sma200"][L], bankVs[L]
    g["xlfVs200"] = chg(xlf["c"][L], xlf["sma200"][L])
    g["curve"], g["y10"], g["y02"] = curve[L], y10["c"][L], y02["c"][L]
    g["spyVs200"] = chg(spy["c"][L], spy["sma200"][L])
    g["copC"], g["cop200"], g["copVs200"] = cop["c"][L], cop["sma200"][L], chg(cop["c"][L], cop["sma200"][L])
    g["ur"], g["urAvg3"], g["urLow12"], g["sahm"] = ur["c"][L], urAvg3[L], urLow12[L], sahm[L]
    g["clm"], g["clmAvg4"], g["clmLow6"] = clmK[L], clmAvg4[L], clmLow6[L]
    g.update(credRun=credRun[L], thinRun=thinRun[L], bankN=bankN[L], econN=econN[L], laborWarn=laborWarn[L],
             laborClose=laborClose[L], curveWarn=curveWarn[L], stockWeak=stockWeak[L], longWeak=longWeak[L],
             copWeak=copWeak[L], bankLag=bankLag[L], bankBelow=bankBelow[L], credWeakWk=credWeakWk[L], hygOk=hygOk[L])

    ctx = dict(g=g, step=step_now, steps={k: steps[k][L] for k in steps}, drun={k: drun[k][L] for k in drun},
               since={k: since(k) for k in steps}, hist=hist, hold=hold_days)
    rec = _recession_words(ctx)

    # ---------------- feeds: what loaded, what is old ----------------
    feeds = _feed_check(S, axis, dict(SPY=spy_age, HYG=hyg_age, BANK=xlf_age, COPPER=cop_age, Y10=y10_age, Y02=y02_age,
                                      UR=ur_age, CLM=clm_age, WTI=wti_age, BRENT=brt_age, OAS=oas_age), s5fi, nmem, bank_key)

    # ---------------- Relationships Board v1.5 ----------------
    rel = _relationships(L, dict(spy=spy, hyg=hyg, xlf=xlf, cop=cop, y10=y10, y02=y02, wti=wti, brt=brt, oas=oas),
                         dict(s5fi=s5fi, s5th=s5th, sahm=sahm, urAvg3=urAvg3, urLow12=urLow12, ur=ur["c"], clmK=clmK,
                              clmAvg4=clmAvg4, clmLow6=clmLow6), g, feeds)

    # ---------------- Market State words ----------------
    ms = _state_words(st_series[L], st_run, st_since, want_now, raw_series[L], ctx, hist, mc)

    # ---------------- Rate Baskets v1.3.0 ----------------
    baskets = _baskets(S, axis, mc)

    # ---------------- who is carrying it / leaders and laggards ----------------
    leaders = _leaders(S, axis, per, members, mc, spy)

    # ---------------- history of the two breadth lines for the page's chart ----------------
    keep = min(n, 260)
    chart = {"days": axis[-keep:], "s5fi": [None if v is None else round(v, 2) for v in s5fi[-keep:]],
             "s5th": [None if v is None else round(v, 2) for v in s5th[-keep:]],
             "spy": [None if v is None else round(v, 2) for v in spy["c"][-keep:]],
             "spy50": [None if v is None else round(v, 2) for v in spy["sma50"][-keep:]],
             "spy200": [None if v is None else round(v, 2) for v in spy["sma200"][-keep:]],
             "state": st_series[-keep:], "step": [0 if not s1[i] else 1 if not s2[i] else 2 if not s3[i] else 3 if not s4[i] else 4 if not s5[i] else 5
                                                   for i in range(n - keep, n)]}

    scen = _scenarios(ctx, hist, st_series[L], baskets)

    return {"ok": True, "version": VERSION, "source": source, "as_of": axis[L], "as_of_text": fmt_day(axis[L]),
            "state": ms, "recession": rec, "numbers": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in g.items()},
            "relationships": rel, "baskets": baskets, "leaders": leaders, "history": hist, "scenarios": scen,
            "feeds": feeds, "chart": chart, "members_counted": nmem,
            "note": ("Breadth is counted by TED from today's S&P 500 members (" + str(nmem) + " with a 50-day today). "
                     "Older years count companies that joined the index later, so they read a little stronger than the "
                     "official numbers did. Counts are counts, not promises."),
            "footer": "This is a backdrop, not a call and not advice. It decides how much and which way you lean; your PS60 setup decides when."}


# =====================================================================================================================
# Recession Steps v1.2 words (the same sentences as the board, in PS60-safe words)
# =====================================================================================================================
def _dir_txt(now, wk, mo):
    if now is None or wk is None or mo is None:
        return ""
    dW, dM = now - wk, now - mo
    trend = ("falling fast" if dW <= -5 else "falling" if dW <= -1.5 else "climbing fast" if dW >= 5
             else "climbing" if dW >= 1.5 else "flat this week")
    tail = ", and well below a month ago." if dM <= -10 else ", and well above a month ago." if dM >= 10 else "."
    return f" A week ago it was {wk:.1f}%, a month ago {mo:.1f}%: {trend}{tail}"


def _recession_words(c):
    g, step, on, d, t, hist = c["g"], c["step"], c["steps"], c["drun"], c["since"], c["hist"]
    ep1, fol1 = hist["ep1"], hist["fol1"]
    rows = {}

    # breadth
    s5fi, s5th = g["s5fi"], g["s5th"]
    if s5fi is None and s5th is None:
        b, bc = "UNKNOWN — neither breadth number is loading (the S&P members have not come in yet).", "warn"
    else:
        shortT = "SHORT-TERM: not loading." if s5fi is None else (
            f"SHORT-TERM: {s5fi:.2f}% of the 500 S&P stocks are above their own 50-day average, about {cos(s5fi)} companies. "
            f"The other {cos(100 - s5fi)}, roughly {round((100 - s5fi) / 10)} in 10, are below it."
            + _dir_txt(s5fi, g["s5fiWk"], g["s5fiMo"])
            + " The line is 30: under 30 for 5 straight days is step 2"
            + (f" ({g['thinRun']} of 5 so far)." if g["thinRun"] > 0 else " (count at zero)."))
        longT = " LONG-TERM: not loading." if s5th is None else (
            f" LONG-TERM: {s5th:.2f}% are above their 200-day average, about {cos(s5th)} companies."
            + _dir_txt(s5th, g["s5thWk"], g["s5thMo"])
            + (" The line is 45, and it is BELOW the line: that warning point is on in step 4." if g["longWeak"] else
               f" The line is 45, a {s5th - 45.0:.2f}-point cushion. Under 45 adds a warning point to step 4 and means the damage has spread from short-term to long-term."))
        gap, bc = "", "ok"
        if s5fi is not None and s5th is not None:
            diff = s5th - s5fi
            if s5fi < 35 and s5th < 45:
                gap, bc = " WHAT THE GAP SAYS: both numbers are weak. Most stocks have broken their short-term AND their long-term trend. That is a broad decline, not a narrow one.", "bad"
            elif diff >= 12 and s5fi < 35:
                gap, bc = " WHAT THE GAP SAYS: short-term is far weaker than long-term. Many stocks have broken their recent trend but not their long-term one: damaged, not dead. The index is being held up by its biggest names. If the long-term number slides toward 45 while the short-term stays under 30, that is the damage spreading.", "warn"
            elif s5fi > s5th + 5:
                gap, bc = " WHAT THE GAP SAYS: more stocks are above their 50-day than their 200-day. Short-term is healing ahead of long-term, which is how recoveries usually start.", "ok"
            elif s5fi >= 50 and s5th >= 50:
                gap, bc = " WHAT THE GAP SAYS: most stocks are above both trend lines. The market is broad and healthy, the index is not being carried by a few names.", "ok"
            else:
                gap, bc = " WHAT THE GAP SAYS: middle ground. Neither number is at a line, watch the direction more than the level.", "warn" if s5fi < 40 else "ok"
        b = shortT + longT + gap
    rows["breadth"] = {"label": "BREADTH · HOW MANY STOCKS ARE TAKING PART", "text": b, "tone": bc}

    # step 1
    spyLine = ""
    if g["spyGap50"] is not None:
        spyLine = (" Meanwhile the S&P is " + (f"still ABOVE its own 50-day by ${g['spyGap50']:.2f}. That gap is the room left before one of two things happens: credit heals and stocks were right, or stocks come down to meet credit. There is no third option where they stay apart."
                                                if g["spyGap50"] >= 0 else f"BELOW its own 50-day by ${-g['spyGap50']:.2f}. Stocks have joined credit on the weak side, so the split has resolved downward."))
    heal = f" Since the data began this step healed on its own {ep1 - fol1} of {ep1} times, and step 2 confirmed in the other {fol1}." if ep1 > 0 else ""
    if not g["hygOk"]:
        s, tone = "UNKNOWN — the junk bond fund is not loading, so this step cannot be checked.", "warn"
    elif on[1]:
        s = (f"ON since {fmt_day(t[1])}, {days_word(d[1])} — junk bonds, which are loans to shaky companies, have closed below their 50-day average and below a month ago for {days_word(g['credRun'])} straight. "
             f"Now {pct(g['hygVs50'])} against the 50-day and {pct(g['hygVsMo'])} against a month ago. That is small for a bond fund but it is persistent, and lenders get nervous before stock holders do, which is why this step comes first."
             + spyLine + heal + " It turns OFF the first day junk bonds close back above either line. WHAT CHANGES: the S&P losing its 50-day does not move a step by itself, but it usually drags the breadth number lower, and breadth is what step 2 counts.")
        tone = "warn"
    else:
        s = (f"OFF — junk bonds have been weak {g['credRun']} of the 5 straight days needed (below their 50-day average AND below a month ago). Now {pct(g['hygVs50'])} against the 50-day. Lenders are not nervous yet, so the sequence has not started."
             + (f" WHAT CHANGES: {5 - g['credRun']} more weak days turns this ON and starts the sequence." if g["credRun"] >= 3 else ""))
        tone = "warn" if g["credRun"] >= 3 else "ok"
    rows[1] = {"label": "STEP 1 · LENDERS NERVOUS", "text": s, "tone": tone}

    # step 2
    order = " This is showing out of order: step 1 is off." if on[2] and not on[1] else ""
    meaning = "" if s5fi is None else (f" Only {s5fi:.2f}% of S&P stocks are above their 50-day, about {cos(s5fi)} of 500, so roughly {round((100 - s5fi) / 10)} in 10 are already broken while the index is held up by its biggest names."
                                       + _dir_txt(s5fi, g["s5fiWk"], g["s5fiMo"]))
    if s5fi is None:
        s, tone = "UNKNOWN — the share of S&P stocks above their 50-day is not loading.", "warn"
    elif on[2]:
        fresh = d[2] <= 5
        s = (("JUST TURNED ON — " if fresh else "ON — ") + f"since {fmt_day(t[2])}, under 30 for {days_word(g['thinRun'])} straight." + meaning
             + " The market is officially thin: the index can hold up on a few names for a while, but there is nothing underneath if they roll." + order
             + f" It turns OFF the first day the number closes at 30 or higher. WHAT CHANGES: with steps 1 and 2 both on, the next question is whether banks confirm (step 3, {g['bankN']} of 3 bank warnings on now).")
        tone = "loud" if fresh else "bad"
    elif g["thinRun"] > 0:
        s = (f"NOT YET — under 30 for {days_word(g['thinRun'])} straight, needs 5: {5 - g['thinRun']} more. One day at 30 or higher resets the count to zero." + meaning
             + " Narrow leadership is fragile, not fatal: it can run for months. It becomes a step only when it persists. WHAT CHANGES: if it confirms while step 1 is on, that is the pattern that has come before past sell cycles"
             + (f" (it followed step 1 in {fol1} of {ep1} runs)." if ep1 > 0 else "."))
        tone = "warn"
    else:
        s = (f"NOT YET — {s5fi:.2f}% of S&P stocks are above their 50-day, about {cos(s5fi)} of 500. It has to drop under 30 and stay there 5 straight days. The count is at zero."
             + _dir_txt(s5fi, g["s5fiWk"], g["s5fiMo"])
             + (" WHAT CHANGES: it is within 5 points of the line, so one bad week could start the count." if s5fi < 35 else " Breadth is not thin. Whatever the index does, most stocks are still participating."))
        tone = "warn" if s5fi < 35 else "ok"
    rows[2] = {"label": "STEP 2 · FEWER STOCKS", "text": s, "tone": tone}

    # step 3
    bv = g["bankVs"]
    c1 = " Clue 1, banks against the market this month: " + ("n/a." if bv is None else f"{bv:.2f} points, " + (
        "ON (line is -3). Banks are losing money faster than the market, which usually means lending is getting harder." if g["bankLag"] else
        "OFF (line is -3). Banks are keeping pace with the market."))
    c2 = " Clue 2, bank fund against its 200-day: " + ("n/a." if g["xlf200"] is None else (
        f"BELOW by {pct(g['xlfVs200'])}, ON. Bank weakness has stopped being relative and become a trend break." if g["bankBelow"] else
        f"above by {pct(g['xlfVs200'])}, OFF. Banks are lagging but still in an uptrend. Betting against a group that is still above its 200-day is the classic way to get run over; the trend break is the setup most wait for."))
    c3 = f" Clue 3, junk bonds this week: {pct(g['hygWk'])}, " + ("ON (line is -1%). Lenders are pulling back right now, not just over the month." if g["credWeakWk"] else "OFF (line is -1%). No new credit stress this week.")
    offOne = ""
    if g["bankN"] == 2:
        offOne = (" THE ONE STILL OFF: banks against the market. WHAT CHANGES: if banks fall 3+ points behind this month, all three are on." if not g["bankLag"] else
                  " THE ONE STILL OFF: the bank fund against its 200-day. WHAT CHANGES: if the bank fund closes under its 200-day, all three are on and bank weakness is a confirmed trend break." if not g["bankBelow"] else
                  " THE ONE STILL OFF: junk bonds this week. WHAT CHANGES: a 1% weekly drop in junk bonds turns all three on.")
    order3 = " This is showing out of order: the steps before it are not all on, so it is a warning without the setup, which weakens it." if on[3] and step < 2 else ""
    known = bv is not None and g["xlf200"] is not None and g["hygWk"] is not None
    if not known:
        s, tone = "UNKNOWN — part of the bank data is not loading." + c1 + c2 + c3, "warn"
    elif on[3]:
        s = (f"ON since {fmt_day(t[3])}, {days_word(d[3])} — {g['bankN']} of 3 bank warnings are on. Banks are the plumbing: when they lag while credit weakens, lending tightens and that is what slows an economy."
             + c1 + c2 + c3 + offOne + order3 + " It turns OFF when fewer than 2 clues are on.")
        tone = "bad"
    else:
        s = (f"NOT YET — {g['bankN']} of 3 bank warnings are on. It needs 2." + c1 + c2 + c3
             + (" WHAT CHANGES: one more clue turns this ON." if g["bankN"] == 1 else " Banks are not confirming anything yet."))
        tone = "warn" if g["bankN"] == 1 else "ok"
    rows[3] = {"label": "STEP 3 · BANKS LAG", "text": s, "tone": tone}

    # step 4
    sahm = g["sahm"]
    jobsW = "UNKNOWN (no jobs data)" if sahm is None else "CROSSED, 2 points" if g["laborWarn"] else "getting close, 1 point" if g["laborClose"] else f"not close, 0 points ({sahm:.2f} of 0.30)"
    p = [f" Jobs: {jobsW}.",
         " 10-year against 2-year: " + ("n/a." if g["curve"] is None else f"{g['curve']:.2f} points, " + (
             "ON. Short rates above long rates means lenders expect trouble ahead." if g["curveWarn"] else
             "OFF, turns on below zero. Lenders still get paid more to lend long, which is normal.")),
         f" Junk bonds this week: {pct(g['hygWk'])}, " + ("ON." if g["credWeakWk"] else "OFF, turns on at -1%."),
         " S&P against its 200-day: " + ("n/a." if g["spy200"] is None else (
             f"BELOW by {pct(g['spyVs200'])}, ON. The long-term stock trend is broken." if g["stockWeak"] else
             f"above by {pct(g['spyVs200'])}, OFF. The long-term stock trend is intact.")),
         f" S&P stocks above their 200-day: {n2(s5th)}%, " + ("ON (under 45). Most stocks have broken their long-term trend." if g["longWeak"] else
                                                             f"OFF, {n2(None if s5th is None else s5th - 45.0)} points above the 45 line. If this slides under 45 the damage has spread from short-term to long-term."),
         " Copper against its 200-day: " + ("n/a." if g["cop200"] is None else (
             f"BELOW by {pct(g['copVs200'])}, ON. Copper falls when factories expect less work." if g["copWeak"] else
             f"above by {pct(g['copVs200'])}, OFF. Factories are not signaling a slowdown."))]
    order4 = " This is showing out of order: the steps before it are not all on." if on[4] and step < 3 else ""
    if on[4]:
        s = (f"ON since {fmt_day(t[4])}, {days_word(d[4])} — {g['econN']} warning points. Several unrelated parts of the economy are breaking at once, which is what single readings cannot fake."
             + "".join(p) + order4 + " It turns OFF when the points drop under 3 and jobs are not close.")
        tone = "bad"
    else:
        s = (f"NOT YET — {g['econN']} of the 3 warning points it takes. Each point is a different part of the economy; the warning only turns on when several break together."
             + "".join(p) + (" WHAT CHANGES: one more point turns the recession warning ON." if g["econN"] == 2 else ""))
        tone = "warn" if g["econN"] >= 2 else "ok"
    rows[4] = {"label": "STEP 4 · RECESSION WARNING", "text": s, "tone": tone}

    # step 5
    clmTxt = " Weekly jobless claims: not loading." if g["clm"] is None else (
        f" Weekly jobless claims: latest {g['clm']:.0f} thousand, 4-week average {n2(g['clmAvg4'], '0')} thousand. "
        + ("Above 300 means layoffs are spreading." if (g["clmAvg4"] or 0) >= 300 else
           "Between 250 and 300 is rising, worth watching." if (g["clmAvg4"] or 0) >= 250 else "Under 250 is calm, layoffs are not spreading."))
    if sahm is None:
        s, tone = "UNKNOWN — the unemployment rate is not loading, so the jobs step cannot be checked. Unknown is not the same as clear." + clmTxt, "warn"
    elif on[5]:
        s = (f"ON since {fmt_day(t[5])}, {days_word(d[5])} — the unemployment rate's 3-month average ({n2(g['urAvg3'])}%) is {sahm:.2f} points above its lowest 3-month average of the past year. This is the Sahm rule: by the time this crosses, a recession has usually already started. People are losing jobs." + clmTxt)
        tone = "bad"
    else:
        s = (f"NOT YET — unemployment is {n2(g['ur'], '0.0')}%. The 3-month average ({n2(g['urAvg3'])}%) is {sahm:.2f} points above its lowest of the past year ({n2(g['urLow12'])}%). The line is 0.50, and 0.30 counts as getting close."
             + clmTxt + " Jobs are the LAST thing to break, not the first: by the time this turns on the market has usually already moved. Do not wait for this step to act; it confirms, it does not warn.")
        tone = "warn" if g["laborClose"] else "ok"
    rows[5] = {"label": "STEP 5 · JOBS", "text": s, "tone": tone}

    where = {
        0: ("NO STEPS ON — lenders are not nervous, so the recession sequence has not started. Whatever the index does day to day, the economy plumbing is not flagging anything.", "ok"),
        1: ("STEP 1 OF 5 IS ON — lenders got nervous first: junk bonds are sagging while the S&P holds up. Credit and stocks are saying different things, and one of them is wrong. Step 1 heals on its own more often than not"
            + (f" ({ep1 - fol1} of {ep1} times)" if ep1 > 0 else "") + ". This is a reason to be smaller, not a reason to be short. The sequence only moves forward if step 2 confirms.", "warn"),
        2: ("STEP 2 OF 5 IS ON — lenders got nervous, and now fewer and fewer stocks are holding the market up. The regime has changed: the index can look fine while most of it is already down. The short side is now in line with the backdrop, and size should already be cut.", "bad"),
        3: ("STEP 3 OF 5 IS ON — lenders got nervous, fewer stocks held the market up, and now banks are falling behind. The plumbing is confirming what credit said first. This is the point where past sell cycles stopped being pullbacks.", "bad"),
        4: ("STEP 4 OF 5 IS ON — the recession warning is up: several unrelated parts of the economy are breaking together. This is late in the sequence; a lot of the market move has usually already happened by here.", "bad"),
        5: ("ALL 5 STEPS ARE ON — jobs have confirmed. This is the full pattern that has come before past recessions. By this point the question is usually when the recovery starts, not whether the slowdown is real.", "loud"),
    }[step]

    if step == 0:
        nxt = f"WATCH STEP 1 — junk bonds need 5 straight days below their 50-day average AND below a month ago. {g['credRun']} of 5 so far. If it turns on, be smaller, not short."
    elif step == 1:
        nxt = (f"WATCH STEP 2 — the share of S&P stocks above their 50-day (now {n2(s5fi)}%) has to stay under 30 for 5 straight days. {g['thinRun']} of 5 so far."
               + ("" if g["spyGap50"] is None else (f" The S&P is ${g['spyGap50']:.2f} above its 50-day: if it loses that line, expect breadth to fall further and step 2 to confirm soon after."
                                                    if g["spyGap50"] >= 0 else " The S&P is already under its 50-day, so breadth is likely to keep falling."))
               + " If junk bonds close back above their 50-day first, step 1 turns off and the sequence resets.")
    elif step == 2:
        nxt = f"WATCH STEP 3 — banks. It needs 2 of the 3 bank warnings; {g['bankN']} of 3 are on now. If banks confirm, this is no longer a pullback."
    elif step == 3:
        nxt = f"WATCH STEP 4 — the recession warning needs 3 warning points; it has {g['econN']} now. The closest one to turning on is worth checking in the step 4 row."
    elif step == 4:
        nxt = f"WATCH STEP 5 — jobs. The unemployment 3-month average has to climb 0.50 above its 12-month low; it is {n2(sahm)} now. Remember jobs confirm late, do not wait for this to act."
    else:
        nxt = "WATCH FOR RECOVERY — junk bonds climbing back above their 50-day, more stocks rejoining the rally (short-term breadth rising above long-term), banks steadying, and job losses leveling off. Recovery signs do not all turn at once, and markets usually turn up before the economy feels better."

    avg1 = hist.get("len1_avg")
    d1 = d[1]
    histTxt = (f"SINCE {fmt_day(hist['start'])}, WHEN THE JUNK BOND AND BREADTH DATA START — step 1 switched on and then ended {ep1} times. "
               f"It lasted about {avg1 if avg1 is not None else 'n/a'} trading days on average, the longest {hist['len1_max']}"
               + ((f"; the current run is {d1} days, " + ("already the longest on record." if d1 > hist["len1_max"] else "longer than average." if avg1 is not None and d1 > avg1 else "shorter than average.")) if on[1] else ".")
               + f" Step 2 confirmed while step 1 was on in {fol1} of those {ep1}, so about {round(10.0 * fol1 / ep1) if ep1 else '?'} in 10."
               f" The share of S&P stocks above their 50-day has stayed under 30 for 5+ straight days {hist['breadth_thin_runs']} times, most recently "
               + (fmt_day(hist["breadth_thin_last"]) if hist["breadth_thin_last"] else "never")
               + f", and the longest stretch ran {hist['breadth_thin_longest']} straight days. This counts about {hist['years']} years and only a couple of recessions. Counts are counts, not promises.")
    return {"step": step, "where": {"text": where[0], "tone": where[1]}, "rows": rows, "next": nxt, "history_text": histTxt,
            "on": {k: on[k] for k in on}, "days": {k: d[k] for k in d}, "since": {k: t[k] for k in t},
            "since_text": {k: fmt_day(t[k]) if t[k] else None for k in t}}


# =====================================================================================================================
# Market State v1.1 words
# =====================================================================================================================
def _state_words(st, st_run, st_since, want, raw, c, hist, mc):
    g, step = c["g"], c["step"]
    name = MS_STATES[st][0]
    if st == 1:
        flips = (f"State 2 starts when step 1 turns on: junk bonds weak 5 straight days ({g['credRun']} of 5 so far) below their 50-day and below a month ago.")
    elif st == 2:
        flips = (f"State 3 starts when step 2 turns on (breadth now {n2(g['s5fi'])}%, under 30 for {g['thinRun']} of 5 days) and then holds {c['hold']} more days, "
                 f"OR when steps 1, 2 and 3 are all on (banks {g['bankN']} of 3)."
                 + ("" if g["spyGap50"] is None else (f" The S&P is ${g['spyGap50']:.2f} above its 50-day; losing it would likely pull breadth down and speed this up." if g["spyGap50"] >= 0
                                                      else f" The S&P is ${-g['spyGap50']:.2f} under its 50-day already, which usually drags breadth lower."))
                 + " Back to State 1 if junk bonds close above their 50-day and step 1 turns off. If State 3 comes: the short side is in line with the backdrop, defined risk only.")
    elif st == 3:
        flips = (f"State 4 starts when step 4 turns on: 3 warning points ({g['econN']} now) or jobs getting close ({n2(g['sahm'])} of 0.30). "
                 "Back to State 2 if step 2 turns off and banks are not lagging. If State 4 comes: the move is mostly done, stop pressing shorts.")
    else:
        flips = ("Back to State 3 when steps 4 and 5 both turn off. Recovery shows first in junk bonds back over their 50-day and short-term breadth climbing over long-term.")
    pending = ""
    if want != st:
        pending = f" The steps already point to State {want} ({MS_STATES[want][0]}); it switches after {int(mc.get('confirm_days', 2) or 2)} days in a row, one state at a time."
    ladder = []
    for k in range(1, 5):
        nm, when, do = MS_STATES[k]
        ladder.append({"n": k, "name": nm, "when": when.format(hold=c["hold"]), "do": do, "now": k == st,
                       "pct_days": hist["states"][k]["pct_days"], "entered": hist["states"][k]["entered"],
                       "last_entered": hist["states"][k]["last_entered"], "last_text": fmt_day(hist["states"][k]["last_entered"]) if hist["states"][k]["last_entered"] else None})
    return {"n": st, "name": name, "days": st_run, "since": st_since, "since_text": fmt_day(st_since),
            "now": f"STATE {st} · {name} for {days_word(st_run)} (since {fmt_day(st_since)}). " + MS_STATES[st][1].format(hold=c["hold"]) + pending,
            "do": MS_STATES[st][2], "flips": flips, "ladder": ladder, "rules": MS_RULES, "state3": MS_STATE3, "want": want, "raw": raw}


# =====================================================================================================================
# feeds
# =====================================================================================================================
def _feed_check(S, axis, ages, s5fi, nmem, bank_key):
    names = {"SPY": "S&P 500 fund (SPY)", "HYG": "Junk bond fund (HYG)", "BANK": f"Bank fund ({bank_key})", "COPPER": "Copper",
             "Y10": "10-year rate", "Y02": "2-year rate", "UR": "Unemployment rate", "CLM": "Weekly jobless claims",
             "WTI": "Oil, US (WTI)", "BRENT": "Oil, world (Brent)", "OAS": "High-yield credit spread"}
    limit = {"UR": 75, "CLM": 15, "Y10": 6, "Y02": 6, "WTI": 9, "BRENT": 12, "OAS": 9}
    out, bad = [], []
    for k, nm in names.items():
        a = ages.get(k)
        age = a[-1] if a else None
        if age is None:
            state, why = "MISSING", "not loading"
            bad.append(nm)
        elif age > limit.get(k, 6):
            state, why = "OLD", f"last print {age} trading days ago"
            bad.append(nm)
        else:
            state, why = "OK", "loading"
        out.append({"key": k, "name": nm, "state": state, "why": why})
    br = s5fi[-1] if s5fi else None
    out.append({"key": "BREADTH", "name": "S&P members (breadth, leaders, laggards)", "state": "OK" if br is not None else "MISSING",
                "why": f"{nmem} members counted" if br is not None else "the members have not come in yet"})
    if br is None:
        bad.append("S&P members")
    return {"rows": out, "bad": bad, "text": "All feeds are loading." if not bad else "NOT LOADING OR OLD: " + ", ".join(bad) + "."}


# =====================================================================================================================
# Relationships Board v1.5: sixteen relationships, each with its line, cushion and direction
# =====================================================================================================================
def _relationships(L, M, D, g, feeds):
    spy, hyg, xlf, cop, y10, y02, wti, brt, oas = (M[k] for k in ("spy", "hyg", "xlf", "cop", "y10", "y02", "wti", "brt", "oas"))
    s5fi, s5th = D["s5fi"], D["s5th"]
    W = L - 5 if L >= 5 else None

    def at(arr, i):
        return None if i is None or i < 0 else arr[i]
    bad = {r["key"]: r["state"] != "OK" for r in feeds["rows"]}

    def chk(*keys):
        miss = [k for k in keys if bad.get(k)]
        return ("the " + ", ".join(miss).lower().replace("hyg", "junk bond fund").replace("bank", "bank fund") + " feed failed its check") if miss else ""

    sahm, clmAvg4, clmLow6 = D["sahm"], D["clmAvg4"], D["clmLow6"]
    g13 = sahm[L]
    g13w = at(sahm, W)
    g14 = chg(clmAvg4[L], clmLow6[L])
    g14w = chg(at(clmAvg4, W), at(clmLow6, W))
    defs = [
        # n, label, gap, gap a week ago, line, higher is safer, watch band, unit, feeds, what, rises, falls
        (1, "JUNK BONDS vs 50-DAY", chg(hyg["c"][L], hyg["sma50"][L]), chg(at(hyg["c"], W), at(hyg["sma50"], W)), 0.0, True, 0.75, "%", ("HYG",),
         "The junk bond fund (loans to shaky companies) vs its 50-day average. Lenders to weak companies get scared first.",
         "Back over the average means lenders calming. Held a few days, step 1 turns off.",
         "5 straight days under it (and under a month ago) is step 1. Stocks tend to follow credit within weeks. Check row 16: if the spread is calm, this may be rates moving, not credit risk."),
        (2, "JUNK BONDS vs MONTH AGO", chg(hyg["c"][L], hyg["b20"][L]), chg(at(hyg["b5"], L), at(hyg["b25"], L)), 0.0, True, 0.75, "%", ("HYG",),
         "The same fund vs where it was a month ago. Is credit weaker than it was, not just weaker than average?",
         "Positive and growing means credit healing month over month. With row 1 positive, step 1 is clear.",
         "Negative and widening means damage getting worse. Rows 1 and 2 both negative is what step 1 requires."),
        (3, "JUNK BONDS THIS WEEK", chg(hyg["c"][L], hyg["b5"][L]), chg(at(hyg["b5"], L), at(hyg["b10"], L)), -1.0, True, 0.5, "%", ("HYG",),
         "The fund's move over the last 5 trading days. Speed matters: a fast drop means forced selling, a slow slide is less urgent.",
         "A positive week means buyers returned to risky debt. Small caps and banks usually follow within days.",
         "Past -1% in a week is a real move for a bond fund. It advances steps 3 and 4 at once."),
        (4, "BANKS vs MARKET, 1 MONTH", g["bankVs"],
         (lambda a, b: None if a is None or b is None else a - b)(chg(at(xlf["b5"], L), at(xlf["b25"], L)), chg(at(spy["b5"], L), at(spy["c"], L - 25 if L >= 25 else None))),
         -3.0, True, 1.5, " pts", ("BANK", "SPY"),
         "Bank fund's one-month return minus the S&P's. Banks are the plumbing; trailing means money leaving the part of the economy that lends.",
         "Banks catching up removes a step 3 clue. One of the better signs a scare is passing.",
         "Trailing by 3+ pts is a step 3 clue. Trailing by 6+ near market highs means the rally stands on fewer legs. THE TELL: banks losing while rates rise is credit stress, not rotation."),
        (5, "BANK FUND vs 200-DAY", chg(xlf["c"][L], xlf["sma200"][L]), chg(at(xlf["c"], W), at(xlf["sma200"], W)), 0.0, True, 2.0, "%", ("BANK",),
         "Bank fund vs its 200-day, its long-term trend. Above it banks lag but still trend up. Below it the trend broke.",
         "Room above the line means bank shorts fight the trend. Rows 4 and 5 disagreeing is damaged, not broken.",
         "A close under the 200-day turns bank lag into bank breakdown. With rows 3 and 4 on, this fully confirms step 3, and it is the setup most wait for before shorting banks."),
        (6, "SHORT-TERM BREADTH", s5fi[L], at(s5fi, W), 30.0, True, 5.0, "%", ("BREADTH",),
         "Share of the 500 S&P stocks above their own 50-day. How many are actually participating. The index can sit near highs while most members fall.",
         "More stocks joining means the rally is broadening. Back above 50 and the market stands on its own feet.",
         "Under 30 for 5 straight days is step 2. A narrow rally becomes officially thin, and State 3 gets closer."),
        (7, "LONG-TERM BREADTH", s5th[L], at(s5th, W), 45.0, True, 5.0, "%", ("BREADTH",),
         "Share of S&P stocks above their 200-day. Row 6 counts stocks wobbling this month; this counts stocks that lost the whole year's trend.",
         "Above 60 with row 6 rising is a broad, durable bull. Long-term breadth recovers last in a real bottom.",
         "Under 45 means damage went long-term: half the market lost its yearly trend. Adds a step 4 point; bounces stop being buyable."),
        (8, "THE BREADTH GAP", None if s5th[L] is None or s5fi[L] is None else s5th[L] - s5fi[L],
         None if at(s5th, W) is None or at(s5fi, W) is None else at(s5th, W) - at(s5fi, W), 12.0, False, 3.0, " pts", ("BREADTH",),
         "Row 7 minus row 6. A wide gap means many stocks broke their recent trend but not their long-term one: damaged, not dead, and the index is carried by its biggest names.",
         "Gap widening means short-term damage spreading faster than long-term: a scare that usually resolves fast. Watch which row moves.",
         "Gap closing because row 6 rises = recovery. Closing because row 7 falls = damage went long-term. Never read this row alone."),
        (9, "THE YIELD CURVE", g["curve"], None if at(y10["b5"], L) is None or at(y02["b5"], L) is None else y10["b5"][L] - y02["b5"][L], 0.0, True, 0.25, " pts", ("Y10", "Y02"),
         "10-year Treasury rate minus 2-year. Lending 10 years should pay more than 2. When it pays less, bond buyers expect cuts because they expect weakness. One piece of evidence, not a timer.",
         "A widening positive gap means the bond market sees growth and inflation ahead, not recession. Long bonds bleed.",
         "Below zero is an inverted curve, a step 4 point. The trap: recessions usually arrive after the curve un-inverts, so a curve climbing back from negative is later in the sequence, not earlier."),
        (10, "S&P vs 50-DAY", chg(spy["c"][L], spy["sma50"][L]), chg(at(spy["c"], W), at(spy["sma50"], W)), 0.0, True, 1.0, "%", ("SPY",),
         "The S&P fund vs its 50-day, the medium-term trend and the line most funds use to decide whether to hold.",
         "Room above the 50-day means dips are bought. A market above its 50-day with credit weak is a split that has to resolve.",
         "A close under the 50-day is where systematic sellers step in and breadth follows. Expect row 6 toward 30 within days. The practical alert level for the whole board."),
        (11, "S&P vs 200-DAY", chg(spy["c"][L], spy["sma200"][L]), chg(at(spy["c"], W), at(spy["sma200"], W)), 0.0, True, 2.0, "%", ("SPY",),
         "The S&P fund vs its 200-day, the long-term trend line. Above it is a bull market by most definitions.",
         "A wide cushion lets the market correct without changing regime. A scary pullback that holds this line is still a dip in a bull.",
         "A close under the 200-day is a step 4 point and flips how large funds may position. The worst stretches and the sharpest rallies both happen below it, so shorts need defined risk."),
        (12, "COPPER vs 200-DAY", chg(cop["c"][L], cop["sma200"][L]), chg(at(cop["c"], W), at(cop["sma200"], W)), 0.0, True, 2.0, "%", ("COPPER",),
         "Copper vs its 200-day. Copper goes into wiring, building, cars and factories, so its price is a vote on real demand.",
         "Copper above trend means builders and factories still buying. Argues against recession even with credit nervous.",
         "Under the 200-day is a step 4 point: real demand slipping. Copper and junk bonds weak together is stronger than either alone: one is Wall Street, one is the real world."),
        (13, "UNEMPLOYMENT vs 12-MO LOW", g13, g13w, 0.50, False, 0.20, " pts", ("UR",),
         "Unemployment averaged over 3 months, minus that average's 12-month low. The Sahm rule. It catches unemployment lifting off its floor.",
         "0.30 is WATCH and a step 4 point. 0.50 is step 5. This confirms; it arrives last.",
         "Back to zero means unemployment on its lows. Jobs break last, so this row calm while rows 1 to 8 are on is normal early in the sequence. Do not wait for it."),
        (14, "JOBLESS CLAIMS vs 6-MO LOW", g14, g14w, 10.0, False, 4.0, "%", ("CLM",),
         "Weekly jobless claims, 4-week average, vs that average's 6-month low. Claims move before the unemployment rate does.",
         "10% off the low means layoffs picking up, usually 2 to 4 months before row 13 moves. The early read on step 5.",
         "Near the low means companies holding workers. With row 13 calm, any recession call is still a market call, not an economy call."),
        (15, "OIL: BRENT minus WTI", None if brt["c"][L] is None or wti["c"][L] is None else brt["c"][L] - wti["c"][L],
         None if brt["b5"][L] is None or wti["b5"][L] is None else brt["b5"][L] - wti["b5"][L], 8.0, False, 2.0, "$", ("BRENT", "WTI"),
         "World oil (Brent) minus US oil (WTI), dollars a barrel. A wide gap means the world is paying up for oil, a supply scare or shipping trouble, and a tax on consumers outside the US.",
         "Past $8 is a stress reading. Energy and the dollar benefit; airlines, chemicals and consumers get squeezed; it keeps the Fed from cutting.",
         "Back under $5 means the supply scare easing. Oil calming is one of the few things that lets bonds and stocks rally together."),
        (16, "CREDIT SPREAD (OAS)", oas["c"][L], oas["b5"][L], 5.0, False, 0.75, " pts", ("OAS",),
         "The high-yield credit spread: the extra yield investors demand to hold junk bonds over Treasuries. Rows 1 to 3 watch the junk bond PRICE, which can fall just because Treasury yields rose. This isolates the credit-risk part.",
         "Past 5.00 means lenders demanding real compensation for default risk. With row 1 also on, the credit signal is confirmed, not just suggested.",
         "Back toward 3.00 to 4.00 is a calm credit market. Junk price weakness with a calm spread is a rates story, and rates stories resolve faster."),
    ]
    rows = []
    for (num, label, gap, gapw, line, higher, band, unit, fkeys, what, rises, falls) in defs:
        cush = None if gap is None else (gap - line if higher else line - gap)
        cushw = None if gapw is None else (gapw - line if higher else line - gapw)
        why = chk(*fkeys)
        state = "DATA CHECK" if why or cush is None else "PAST THE LINE" if cush < 0 else "WATCH" if cush <= band else "CLEAR"
        crossed = ""
        if cush is not None and cushw is not None:
            if cush < 0 <= cushw:
                crossed = "Crossed the line this week."
            elif cush >= 0 > cushw:
                crossed = "Came back over the line this week."
        direction = None
        if cush is not None and cushw is not None:
            dd = cush - cushw
            direction = "toward" if dd < 0 else "away" if dd > 0 else "flat"
        rows.append({"n": num, "label": label, "gap": None if gap is None else round(gap, 4), "gap_week_ago": None if gapw is None else round(gapw, 4),
                     "line": line, "unit": unit.strip() or "", "cushion": None if cush is None else round(cush, 4),
                     "cushion_week_ago": None if cushw is None else round(cushw, 4), "band": band, "state": state, "why": why,
                     "direction": direction, "crossed": crossed, "what": what, "rises": rises, "falls": falls,
                     "higher_safer": higher})
    # row 16 agrees with row 1?
    r1, r16 = rows[0], rows[15]
    if r16["state"] != "DATA CHECK":
        p1, p16 = r1["state"] == "PAST THE LINE", r16["state"] == "PAST THE LINE"
        r16["agree"] = ("AGREES with row 1: price down AND spread wide. This is real credit risk." if p1 and p16 else
                        "Does NOT agree with row 1 yet: price down but spread still calm. That drop may be rates, not credit risk. WATCH, not confirmed." if p1 else
                        "Spread wide while the fund still holds its average. Unusual; watch row 1." if p16 else
                        "Calm, and row 1 is clear. No credit stress signal.")
    counts = {s: sum(1 for r in rows if r["state"] == s) for s in ("PAST THE LINE", "WATCH", "CLEAR", "DATA CHECK")}
    order = {"PAST THE LINE": 0, "WATCH": 1, "DATA CHECK": 3, "CLEAR": 2}
    rows.sort(key=lambda r: (order[r["state"]], r["cushion"] if r["cushion"] is not None else 9e9))
    return {"rows": rows, "counts": counts, "key_rows": [16, 5, 7]}


# =====================================================================================================================
# Rate Baskets Board v1.3.0
# =====================================================================================================================
def _pattern(w, m, y):
    if w is None or m is None or y is None:
        return "Waiting on data for one of the columns."
    if w > 0 and m > 0 and y > 0:
        return "Beating the market at every distance. A leader."
    if w < 0 and m > 0 and y > 0:
        return "Long-time leader that took a breather this week. Fine unless it keeps up."
    if w < 0 and m < 0 and y > 0:
        return "Was a leader this year, losing ground now. Old leader losing its lead."
    if w > 0 and m > 0 and y < 0:
        return "Trailed all year, winning lately. New leader forming."
    if w > 0 and m < 0 and y < 0:
        return "Still behind, but this week it turned. Earliest possible sign. Not confirmed."
    if w < 0 and m > 0 and y < 0:
        return "Picked up last month, gave it back this week. Not confirmed."
    if w > 0 and m < 0 and y > 0:
        return "Mixed. A bounce inside a slide. Do not trust it yet."
    if w < 0 and m < 0 and y < 0:
        return "Trailing the market at every distance. Stay away."
    return "Flat against the market. No opinion."


def _baskets(S, axis, mc):
    tie_in = float(mc.get("tie_points", 0.25))
    rate_in = float(mc.get("rate_move", 0.05))
    n = len(axis)
    spy, _ = _aligned(S, axis, "SPY" if S.get("SPY") else "SPY.A", shifts=(5, 20, 252))
    y10, _ = _aligned(S, axis, "F:Y10", shifts=(5,))

    def rel(f, i, k):
        a = chg(f["c"][i], f[f"b{k}"][i])
        b = chg(spy["c"][i], spy[f"b{k}"][i])
        return None if a is None or b is None else a - b
    funds = []
    for nm, sym, grp, what in SECTORS:
        f, _ = _aligned(S, axis, sym, shifts=(5, 20, 252))
        funds.append((nm, sym, grp, what, f))

    def avg(vals):
        v = [x for x in vals if x is not None]
        return sum(v) / len(v) if v else None

    def leader(a):
        if any(x is None for x in a):
            return -1
        return 0 if a[0] >= a[1] and a[0] >= a[2] else 1 if a[1] >= a[2] else 2

    def loser(a):
        if any(x is None for x in a):
            return -1
        return 0 if a[0] <= a[1] and a[0] <= a[2] else 1 if a[1] <= a[2] else 2

    def at(i):
        relW = [rel(f, i, 5) for *_x, f in funds]
        relM = [rel(f, i, 20) for *_x, f in funds]
        relY = [rel(f, i, 252) for *_x, f in funds]
        bW = [avg([relW[j] for j in range(13) if SECTORS[j][2] == gi]) for gi in range(4)]
        bM = [avg([relM[j] for j in range(13) if SECTORS[j][2] == gi]) for gi in range(4)]
        bY = [avg([relY[j] for j in range(13) if SECTORS[j][2] == gi]) for gi in range(4)]
        return relW, relM, relY, bW, bM, bY, leader(bW[:3]), leader(bM[:3]), leader(bY[:3])

    # the weekly leader over the last stretch: the streak, and yesterday's values for the rotation calls
    lead_hist = []
    start = max(0, n - 260)
    for i in range(start, n):
        lead_hist.append(at(i)[6:8])
    L = n - 1
    relW, relM, relY, bW, bM, bY, leadW, leadM, leadY = at(L)
    prevW, prevM = lead_hist[-2] if len(lead_hist) >= 2 else (-1, -1)
    streak = 0
    for lw, _lm in reversed(lead_hist):
        if lw == leadW:
            streak += 1
        else:
            break
    leadWavg = bW[leadW] if leadW >= 0 else None
    second = None
    if leadW >= 0:
        second = max(bW[j] for j in range(3) if j != leadW)
    gapW = None if leadWavg is None or second is None else leadWavg - second
    tieW = gapW is not None and gapW < tie_in
    y10chg = None if y10["c"][L] is None or y10["b5"][L] is None else y10["c"][L] - y10["b5"][L]
    up = y10chg is not None and y10chg > rate_in
    down = y10chg is not None and y10chg < -rate_in
    rateState = -1 if y10chg is None else 1 if up else 2 if down else 0
    members = [j for j in range(13) if leadW >= 0 and SECTORS[j][2] == leadW]
    usable = [relW[j] for j in members if relW[j] is not None]
    leadPos = sum(1 for v in usable if v > 0)
    broad = leadW >= 0 and len(usable) > 0 and leadPos >= math.ceil(len(usable) * 0.60)
    narrow = leadW >= 0 and len(usable) > 1 and leadPos <= 1
    hbW, rbW, bbW = relW[7], relW[8], relW[1]
    hbUpEarly = hbW is not None and hbW > 0 and (up or leadW == 0)
    hbDownLate = hbW is not None and hbW < 0 and down
    rbCrack = rbW is not None and bbW is not None and rbW < 0 and bbW >= 0
    rbLead = rbW is not None and bbW is not None and rbW > 0 and rbW > bbW
    B = [b[0] for b in BASKETS]

    def scen(Lx, R):
        if Lx < 0 or R < 0:
            return "Not enough data yet to name a winner. Check the DATA line."
        if Lx == 0:
            return {1: "Rates went up and Energy/Financials led. The rate move and the basket are pointing the same way.",
                    2: "Rates went down, but Energy/Financials still led. Those two signals do not agree. Read the sector rows before telling a bigger story.",
                    0: "Rates barely moved and Energy/Financials led. The rate move is not explaining the leadership this week."}[R]
        if Lx == 1:
            return {1: ("Rates went up, but the borrower/rate-sensitive basket still led with broad participation. That does NOT mean money is getting cheaper. The group is simply leading despite higher rates." if broad else
                        "Rates went up and the borrower/rate-sensitive basket has the best average, but the move is NOT broad. A few areas are carrying it. Do NOT call this cheaper money."),
                    2: ("Rates went down and most of the borrower/rate-sensitive basket is also beating the S&P. The rate move and the group are pointing the same way." if broad else
                        "Rates went down and the borrower/rate-sensitive basket has the best average, but only part of the group is joining. Do not call it a broad cheaper-money move yet."),
                    0: ("Rates barely moved and the borrower/rate-sensitive basket led broadly. The sectors are moving without much help from rates." if broad else
                        "Rates barely moved and only part of the borrower/rate-sensitive basket is leading. A few growth areas are carrying the move.")}[R]
        return {1: "Rates went up and Staples/Healthcare led. Defensive areas are winning while rates rise.",
                2: "Rates went down and Staples/Healthcare led. Defensive areas are still winning. Report that combination without guessing why rates fell.",
                0: "Rates barely moved and Staples/Healthcare led. Defensive areas are winning without a strong rate move."}[R]

    def scen_num(Lx, R):
        if Lx < 0 or R < 0:
            return 0
        return {0: {1: 1, 2: 2, 0: 3}, 1: {1: 4, 2: 5, 0: 6}, 2: {1: 7, 2: 8, 0: 9}}[Lx][R]
    active = 0 if tieW else scen_num(leadW, rateState)

    if leadW < 0 or leadM < 0:
        turn = ""
    elif tieW:
        turn = f"NO CLEAR WINNER THIS WEEK: the top two baskets are within {sg(gapW, 1)} points of each other. The market has not picked a side. Read the rows, not the header."
    elif leadW == leadM:
        turn = f"TREND, NOT A BLIP: {B[leadW]} leads on the week AND the month, and has led for {streak} day" + ("." if streak == 1 else "s.")
    else:
        turn = f"TURN IN PROGRESS: {B[leadM]} led for the month, but {B[leadW]} took over this week. Too early to call. If it holds a second week, the leader is changing."

    tells = []
    if hbUpEarly:
        tells.append("HOMEBUILDERS MOVING EARLY: they beat the market this week even while rates stayed high. Housing is stronger than the rate move alone would suggest.")
    if hbDownLate:
        tells.append("HOMEBUILDERS NOT BITING: rates fell and homebuilders still trailed the market. Cheaper money is not bringing buyers back. That is a demand problem, not a rate problem.")
    if rbCrack:
        tells.append("REGIONAL BANKS CRACKING: small banks trailed the market this week while the big banks held up. Credit is tightening somewhere real. The big-bank fund will not show this. Respect it.")
    if rbLead:
        tells.append("REGIONAL BANKS LEADING THE BIG BANKS: small lenders are being bought. Credit is easy and nobody is worried about the loans. Healthy.")
    tell_txt = " ".join(tells) if tells else "Tells: quiet. Homebuilders and regional banks are not flashing anything this week."

    loseW = loser(bW[:3])
    wl = None if leadWavg is None or loseW < 0 else leadWavg - bW[loseW]
    econW = bW[3]
    econWeak = econW is not None and econW < 0
    wmAgree = leadW >= 0 and leadW == leadM
    allAgree = wmAgree and leadW == leadY
    newWeekly = leadW >= 0 and leadM >= 0 and leadW != leadM
    failedTurn = leadW >= 0 and prevW >= 0 and leadW != prevW and prevW != prevM
    rateConflict = (leadW == 0 and down) or (leadW == 1 and up) or (leadW == 2 and down)
    oldW = bW[leadY] if leadY >= 0 else None
    oldM = bM[leadY] if leadY >= 0 else None
    oldLosing = leadY >= 0 and oldW is not None and oldM is not None and oldW < 0 and oldM < 0
    curBelow = leadWavg is not None and leadWavg <= 0
    vacuum = oldLosing and curBelow and not broad

    rot, why, tone = "NO CLEAR ROTATION", "The board does not have enough agreement to call a leadership change.", "hdr"
    if leadW < 0:
        rot, why, tone = "NO DATA", "The scored baskets are missing data, so the board will not classify the rotation.", "bad"
    elif tieW:
        rot, why, tone = "NO CLEAR ROTATION", "The top two rate baskets are too close. Read the individual rows instead of forcing a winner.", "hdr"
    elif vacuum:
        rot, why, tone = "LEADERSHIP VACUUM", "The old leader is losing ground, but no broad new leader has taken its place. The current winner is only losing less.", "warn"
    elif failedTurn:
        rot, why, tone = "ROTATION FAILURE", "A new weekly leader appeared and then lost the lead before the monthly trend confirmed it.", "bad"
    elif rateConflict:
        rot, why, tone = "THE PIECES DO NOT MATCH", "The winning basket and the 10-year rate are moving in opposite directions. Say that plainly and do not guess why.", "warn"
    elif allAgree and broad:
        rot, why, tone = "ESTABLISHED REGIME", f"{B[leadW]} leads the week, month and year, with broad participation inside the basket.", "ok"
    elif wmAgree and broad:
        rot, why, tone = "ROTATION CONFIRMED", f"{B[leadW]} leads the week and month, and most usable members of the basket are participating.", "ok"
    elif wmAgree:
        rot, why, tone = "ROTATION BUILDING", f"{B[leadW]} leads the week and month, but participation inside the basket is not broad enough for the strongest confirmation.", "hdr"
    elif newWeekly:
        rot, why, tone = "EARLY ROTATION", f"{B[leadW]} took the weekly lead while {B[leadM]} still owns the month. The turn is early, not confirmed.", "hdr"
    if not tieW and leadW == 2 and (econWeak or rbCrack):
        rot = "DEFENSIVE ROTATION" if wmAgree else "EARLY DEFENSIVE ROTATION"
        why, tone = "Staples and healthcare lead while cyclical or credit-sensitive evidence is weakening. Watch whether the month confirms.", "bad"
    elif not tieW and leadW == 1 and down and broad:
        rot = "BORROWER GROUP LEADING" if wmAgree else "BORROWER GROUP MOVING EARLY"
        why, tone = "The borrower/rate-sensitive basket leads while the 10-year rate falls, and most members are joining the move.", "ok"
    elif not tieW and leadW == 0 and up and broad:
        rot = "HIGHER-RATE ROTATION" if wmAgree else "EARLY HIGHER-RATE ROTATION"
        why, tone = "The costs-more basket leads while the 10-year rate rises, with broad participation inside the basket.", "ok"

    weakInd = relW[11] is not None and relW[11] < 0
    weakMat = relW[12] is not None and relW[12] < 0
    weakDisc = relW[4] is not None and relW[4] < 0
    defLead = leadW == 2 and not tieW
    rbFine = rbW is not None and rbW >= 0
    rbWeak = rbW is not None and rbW < 0
    econCount = int(weakInd) + int(weakMat) + int(weakDisc) + int(defLead) + int(rbWeak)
    bp, bpwhy, bptone = "MIXED MARKET", "The pieces do not agree enough to name one clean blueprint.", "hdr"
    if vacuum:
        bp, bpwhy, bptone = "LEADERSHIP VACUUM", "The old leader is losing ground, but nothing strong has replaced it. The current winner is only losing less, not showing broad leadership.", "warn"
    elif econCount >= 3:
        bp = f"ECONOMIC-WEAKNESS WATCH — {econCount} OF 5 PIECES AGREEING"
        bpwhy = (("Industrials and Materials are trailing. " if weakInd and weakMat else "") + ("Discretionary is trailing. " if weakDisc else "")
                 + ("Defensive sectors are leading. " if defLead else "") + ("Regional Banks are trailing." if rbWeak else "Regional Banks are still holding up." if rbFine else "")).strip()
        bptone = "warn"
    elif defLead:
        bp, bpwhy, bptone = "DEFENSIVE WATCH", "Staples and Healthcare are leading, but the rest of the weakness checklist is not strong enough yet.", "bad"
    elif leadW == 1 and broad:
        bp, bpwhy, bptone = "BROADER BORROWER / RATE-SENSITIVE MOVE", "Most members of the basket are beating the S&P, so the move is broader than just one or two growth sectors.", "ok"
    elif leadW == 1:
        bp, bpwhy, bptone = "NARROW GROWTH MOVE", "The basket average leads, but too few members are participating to call it broad.", "hdr"
    elif leadW == 0 and broad:
        bp, bpwhy, bptone = "HIGHER-RATE AREAS LEADING", "Energy and Financials are leading with broad participation.", "ok"

    rows = []
    for gi in range(4):
        isLead = gi == leadW and gi < 3 and not tieW
        tag = "" if gi >= 3 else ("WINNING THIS WEEK by " + sg(gapW, 1) + " pts" if isLead else "tied" if tieW else
                                  ("trailing the winner by " + sg(None if leadWavg is None or bW[gi] is None else leadWavg - bW[gi], 1) + " pts") if leadW >= 0 else "")
        sec = []
        for j in range(13):
            if SECTORS[j][2] == gi:
                sec.append({"name": SECTORS[j][0], "fund": SECTORS[j][1], "w": relW[j], "m": relM[j], "y": relY[j],
                            "read": SECTORS[j][3] + " " + _pattern(relW[j], relM[j], relY[j])})
        rows.append({"name": B[gi], "basket": gi, "tag": tag, "lead": isLead, "w": bW[gi], "m": bM[gi], "y": bY[gi],
                     "read": BASKETS[gi][1] + " " + _pattern(bW[gi], bM[gi], bY[gi]), "sectors": sec})
    dead = [SECTORS[j][0] for j in range(13) if funds[j][4]["c"][L] is None]
    if spy["c"][L] is None:
        dead.append("S&P")
    if y10["c"][L] is None:
        dead.append("10-YEAR")
    rate_txt = ("The 10-year rate: no data." if y10chg is None else
                f"The 10-year rate moved {sg(y10chg)} points this week ({'RISING' if up else 'FALLING' if down else 'flat'}), now {y10['c'][L]:.2f}%.")
    lead_name = "no data" if leadW < 0 else "no clear winner" if tieW else f"{B[leadW]} ({streak} day" + (")" if streak == 1 else "s)")
    return {"winner": lead_name, "lead_week": leadW, "lead_month": leadM, "lead_year": leadY, "tie": tieW, "gap": gapW,
            "rate_text": rate_txt, "rate_state": rateState, "y10_change": y10chg, "meaning": scen(-1 if tieW else leadW, rateState),
            "scenario": active, "rotation": {"state": rot, "why": why, "tone": tone},
            "blueprint": {"state": bp, "why": bpwhy, "tone": bptone},
            "winner_vs_loser": (f"WINNER VS LOSER: {B[leadW]} is {sg(wl, 1)} points ahead of {B[loseW]}." if leadW >= 0 and loseW >= 0 else "WINNER VS LOSER: waiting on data."),
            "strength": ("" if leadW < 0 else f"HOW STRONG IS IT: {leadPos} of {len(usable)} members in the winning basket are beating the S&P this week"
                         + (". Most of the group is joining." if broad else ". A few names are doing most of the work." if narrow else ". The group is mixed.")),
            "turn": turn, "tells": tell_txt, "tell_flags": {"homebuilders_early": hbUpEarly, "homebuilders_not_biting": hbDownLate,
                                                            "regional_cracking": rbCrack, "regional_leading": rbLead},
            "rows": rows, "data": "DATA: all 15 feeds loaded." if not dead else "DATA: no price for " + ", ".join(dead) + "."}


# =====================================================================================================================
# who is carrying it (Macro Vision) + what TED adds: the 500 members by name and by sector
# =====================================================================================================================
def _leaders(S, axis, per, members, mc, spy):
    L = len(axis) - 1

    def series_chg(key, k):
        f, _ = _aligned(S, axis, key, shifts=(k,))
        return chg(f["c"][L], f[f"b{k}"][L])
    out = {}
    secs = []
    for gics, fund in GICS_FUND.items():
        secs.append({"name": GICS_SHORT.get(gics, gics), "fund": fund, "d1": series_chg(fund, 1), "w": series_chg(fund, 5), "m": series_chg(fund, 20)})
    ok = [s for s in secs if s["d1"] is not None]
    by_d = sorted(ok, key=lambda s: s["d1"], reverse=True)
    out["sectors"] = secs
    out["sector_top"] = by_d[:3]
    out["sector_bottom"] = by_d[-3:][::-1] if len(by_d) >= 3 else []
    spy_d1, spy_w, spy_m = (series_chg("SPY" if S.get("SPY") else "SPY.A", k) for k in (1, 5, 20))
    out["spy"] = {"d1": spy_d1, "w": spy_w, "m": spy_m}
    rsp = {"d1": series_chg("RSP", 1), "w": series_chg("RSP", 5), "m": series_chg("RSP", 20)}
    out["equal_weight"] = rsp
    carry_pts = float(mc.get("carried_points", 1.5) or 1.5)
    gapW = None if rsp["w"] is None or spy_w is None else rsp["w"] - spy_w
    gapM = None if rsp["m"] is None or spy_m is None else rsp["m"] - spy_m
    carried = (gapM is not None and gapM <= -carry_pts) or (gapW is not None and gapW <= -carry_pts / 2)
    chip = (mc.get("chip_fund") or "SMH").upper()
    big = [s.strip().upper() for s in (mc.get("big_names") or []) if str(s).strip()]
    names = [{"sym": chip, "label": "chip fund", "d1": series_chg(chip, 1), "w": series_chg(chip, 5), "m": series_chg(chip, 20)}]
    for s in big:
        p = per.get(s)
        if p:
            names.append({"sym": s, "label": (members.get(s) or ("", ""))[0], "d1": p["d1"], "w": p["w"], "m": p["m"]})
        else:
            names.append({"sym": s, "label": "", "d1": series_chg("X:" + s, 1), "w": series_chg("X:" + s, 5), "m": series_chg("X:" + s, 20)})
    out["big_names"] = names
    chipM = names[0]["m"]
    chip_txt = ("Chip fund: no data." if chipM is None or spy_m is None else
                "Chipmakers are LEADING the market" + (" up" if chipM > 0 else "") + f": {sg(chipM, 1)}% this month against the S&P's {sg(spy_m, 1)}%." if chipM > spy_m + 1 else
                f"Chipmakers are TRAILING the market: {sg(chipM, 1)}% this month against the S&P's {sg(spy_m, 1)}%." if chipM < spy_m - 1 else
                f"Chipmakers are moving with the market: {sg(chipM, 1)}% this month against the S&P's {sg(spy_m, 1)}%.")
    out["chips_text"] = chip_txt
    top_sec = by_d[0]["name"] if by_d else None
    lifters = sorted([x for x in names if x["w"] is not None], key=lambda x: x["w"], reverse=True)[:4]
    if gapW is None and gapM is None:
        carry_txt = "WHO IS CARRYING IT: the average-stock fund (RSP) is not loading."
    elif carried:
        carry_txt = ("WHO IS CARRYING IT: a few huge stocks. The average S&P stock (equal weight) is "
                     + f"{sg(gapW, 1)} points against the S&P this week and {sg(gapM, 1)} this month. "
                     + (f"Top sector today: {top_sec}. " if top_sec else "")
                     + "Doing the lifting: " + ", ".join(f"{x['sym']} {sg(x['w'], 1)}%" for x in lifters) + " this week.")
    else:
        carry_txt = (f"WHO IS CARRYING IT: the market is not leaning on a few names. The average S&P stock is {sg(gapW, 1)} points against the S&P this week and {sg(gapM, 1)} this month.")
    out["carried"] = carried
    out["carry_text"] = carry_txt
    out["equal_weight_gap"] = {"w": gapW, "m": gapM}
    # the members by name
    rows = []
    for sym, p in per.items():
        if p.get("last_day") != axis[L]:
            continue
        nm, sec = members.get(sym, ("", ""))
        rows.append({"sym": sym, "name": nm, "sector": GICS_SHORT.get(sec, sec), "d1": p["d1"], "w": p["w"], "m": p["m"], "y": p["y"],
                     "a50": p["a50"], "a200": p["a200"], "hi52": p["hi52"], "lo52": p["lo52"]})

    def top(key, rev=True, k=12):
        r = [x for x in rows if x[key] is not None]
        return sorted(r, key=lambda x: x[key], reverse=rev)[:k]
    out["members_month_top"] = top("m")
    out["members_month_bottom"] = top("m", False)
    out["members_week_top"] = top("w")
    out["members_week_bottom"] = top("w", False)
    out["members_day_top"] = top("d1", k=8)
    out["members_day_bottom"] = top("d1", False, k=8)
    out["new_highs"] = sum(1 for x in rows if x["hi52"])
    out["new_lows"] = sum(1 for x in rows if x["lo52"])
    by = {}
    for x in rows:
        b = by.setdefault(x["sector"], {"sector": x["sector"], "n": 0, "a50": 0, "a200": 0, "m": []})
        b["n"] += 1
        b["a50"] += 1 if x["a50"] else 0
        b["a200"] += 1 if x["a200"] else 0
        if x["m"] is not None:
            b["m"].append(x["m"])
    sec_b = []
    for b in by.values():
        if b["n"]:
            sec_b.append({"sector": b["sector"], "members": b["n"], "pct50": round(100.0 * b["a50"] / b["n"], 1),
                          "pct200": round(100.0 * b["a200"] / b["n"], 1),
                          "median_m": round(sorted(b["m"])[len(b["m"]) // 2], 2) if b["m"] else None})
    out["sector_breadth"] = sorted(sec_b, key=lambda b: b["pct50"], reverse=True)
    return out


# =====================================================================================================================
# scenarios: what happens next, each with how often it has happened before
# =====================================================================================================================
def _scenarios(c, hist, st, baskets):
    g, step = c["g"], c["step"]
    H = hist["steps"]
    fw = hist["follow_window"]
    out = []

    def odds(a, b):
        return None if not b else round(100.0 * a / b)
    if step == 0:
        ep = H[1]["turned_on"]
        out.append({"name": "Lenders stay calm", "kind": "base", "needs": f"Junk bonds stay over their 50-day or over a month ago (weak {g['credRun']} of 5 days now).",
                    "history": f"Step 1 has turned on {ep} times in {hist['years']} years" + (f", last on {fmt_day(H[1]['last_on'])}." if H[1]["last_on"] else "."),
                    "means": MS_STATES[1][2]})
        out.append({"name": "Step 1 turns on", "kind": "risk", "needs": f"{5 - g['credRun']} more days with junk bonds under their 50-day AND under a month ago.",
                    "history": f"When it did, step 2 confirmed while it was on {hist['fol1']} of {hist['ep1']} times ({odds(hist['fol1'], hist['ep1'])}%).",
                    "means": MS_STATES[2][2]})
    elif step == 1:
        out.append({"name": "Step 1 heals on its own", "kind": "base", "needs": f"Junk bonds close back over their 50-day ({pct(g['hygVs50'])} now) or over a month ago ({pct(g['hygVsMo'])} now).",
                    "history": f"Happened {hist['heal1']} of {hist['ep1']} times ({odds(hist['heal1'], hist['ep1'])}%). Step 1 lasts about {hist['len1_avg']} days on average; this run is {c['drun'][1]}.",
                    "means": "Back to State 1: normal size on your usual setups."})
        out.append({"name": "Step 2 confirms: the market gets thin", "kind": "risk",
                    "needs": f"Share of S&P stocks above their 50-day ({n2(g['s5fi'])}% now) under 30 for 5 straight days ({g['thinRun']} of 5 now)."
                             + ("" if g["spyGap50"] is None else (f" The S&P is ${g['spyGap50']:.2f} above its 50-day; losing it usually speeds this up." if g["spyGap50"] >= 0
                                                                  else f" The S&P is already ${-g['spyGap50']:.2f} under its 50-day, which usually speeds this up.")),
                    "history": f"Happened {hist['fol1']} of {hist['ep1']} times ({odds(hist['fol1'], hist['ep1'])}%). Step 2 followed step 1 within {fw} days {H[1]['next_followed']} of {H[1]['episodes']} times.",
                    "means": MS_STATES[3][2]})
    elif step == 2:
        e2, f2 = H[2]["episodes"], H[2]["next_followed"]
        out.append({"name": "Breadth recovers, step 2 turns off", "kind": "base", "needs": f"The share above the 50-day closes at 30 or higher ({n2(g['s5fi'])}% now).",
                    "history": f"Step 2 has ended {e2} times; banks confirmed (step 3) within {fw} days in {f2} of them, so it ended without banks about {odds(e2 - f2, e2)}% of the time.",
                    "means": MS_STATES[2][2]})
        out.append({"name": "Banks confirm: step 3", "kind": "risk", "needs": f"2 of 3 bank warnings ({g['bankN']} on now). Watch the bank fund against its 200-day ({pct(g['xlfVs200'])}).",
                    "history": f"Step 3 followed step 2 within {fw} days {f2} of {e2} times ({odds(f2, e2)}%).", "means": MS_STATES[3][2]})
    elif step == 3:
        e3, f3 = H[3]["episodes"], H[3]["next_followed"]
        out.append({"name": "Banks steady, step 3 turns off", "kind": "base", "needs": "Fewer than 2 bank warnings.",
                    "history": f"Step 3 has ended {e3} times; the recession warning followed within {fw} days in {f3} of them.", "means": MS_STATES[3][2]})
        out.append({"name": "The recession warning: step 4", "kind": "risk", "needs": f"3 warning points ({g['econN']} now) or jobs getting close ({n2(g['sahm'])} of 0.30).",
                    "history": f"Step 4 followed step 3 within {fw} days {f3} of {e3} times ({odds(f3, e3)}%).", "means": MS_STATES[4][2]})
    elif step == 4:
        e4, f4 = H[4]["episodes"], H[4]["next_followed"]
        out.append({"name": "Jobs hold, the warning eases", "kind": "base", "needs": "Warning points under 3 and jobs not close.",
                    "history": f"Step 4 has ended {e4} times; jobs (step 5) followed within {fw} days in {f4} of them.", "means": MS_STATES[4][2]})
        out.append({"name": "Jobs confirm: step 5", "kind": "risk", "needs": f"The unemployment 3-month average 0.50 over its 12-month low ({n2(g['sahm'])} now).",
                    "history": f"Followed {f4} of {e4} times. A tiny sample: read it as a count, not odds.", "means": MS_STATES[4][2]})
    else:
        out.append({"name": "Recovery starts", "kind": "base", "needs": "Junk bonds back over their 50-day, short-term breadth climbing over long-term, banks steadying.",
                    "history": f"Step 5 has turned on {H[5]['turned_on']} times in this history: too few to give odds.", "means": MS_STATES[4][2]})
    # the money picture as its own scenario line
    out.append({"name": "Where the money is going", "kind": "money", "needs": baskets["rotation"]["state"] + ": " + baskets["rotation"]["why"],
                "history": baskets["blueprint"]["state"] + ". " + baskets["blueprint"]["why"], "means": baskets["meaning"]})
    return out


# =====================================================================================================================
# the practice market: synthetic closes for every feed (the practice desk; NOT the market)
# =====================================================================================================================
def practice_series(members, years=19, seed=11, end_day=None):
    import datetime as _dt
    rnd = random.Random(seed)
    end = _dt.date.today() if end_day is None else _dt.date(end_day // 10000, (end_day // 100) % 100, end_day % 100)
    while end.weekday() >= 5:
        end -= _dt.timedelta(days=1)
    days = []
    d = end - _dt.timedelta(days=int(years * 365.25))
    while d <= end:
        if d.weekday() < 5:
            days.append(d.year * 10000 + d.month * 100 + d.day)
        d += _dt.timedelta(days=1)
    n = len(days)
    # one market factor with calm stretches and a few sell cycles, credit leading stocks into them
    mkt, cred, regime = [0.0] * n, [0.0] * n, 0
    for i in range(1, n):
        if rnd.random() < 0.004:
            regime = 0 if regime else 1
        drift = -0.0011 if regime else 0.00045
        vol = 0.018 if regime else 0.009
        mkt[i] = drift + rnd.gauss(0, vol)
        cred[i] = (-0.0005 if regime else 0.0002) + rnd.gauss(0, 0.003)
    # credit turns about 15 days before stocks
    cred = cred[15:] + [0.0] * 15

    def path(start, rets):
        out, p = [], start
        for r in rets:
            p *= math.exp(r)
            out.append(round(p, 4))
        return out
    S = {}

    def put(key, beta, idio, start, lead=None):
        base = lead or mkt
        S[key] = list(zip(days, path(start, [beta * base[i] + rnd.gauss(0, idio) for i in range(n)])))
    put("SPY", 1.0, 0.002, 140.0)
    S["SPY.A"] = S["SPY"]
    put("HYG", 0.4, 0.001, 70.0, lead=[cred[i] + 0.2 * mkt[i] for i in range(n)])
    S["HYG.A"] = S["HYG"]
    put("RSP", 1.05, 0.003, 40.0)
    put("SMH", 1.5, 0.008, 30.0)
    put("COPPER", 0.8, 0.012, 3.0)
    for i, (nm, sym, grp, _w) in enumerate(SECTORS):
        put(sym, [1.0, 1.25, 1.2, 1.0, 1.1, 0.5, 0.9, 1.4, 1.35, 0.55, 0.65, 1.1, 1.05][i], 0.006, 30.0 + 3 * i)
    S["XLF.A"] = S["XLF"]
    for j, sym in enumerate(members):
        put("M:" + sym, rnd.uniform(0.6, 1.6), rnd.uniform(0.008, 0.02), rnd.uniform(15, 300))
    # rates, jobs, claims, oil, the spread
    y10, y02, oasv, ur, clm, wti = 3.5, 2.6, 4.0, 4.6, 230.0, 70.0
    Y10, Y02, OAS, WTI, BRT = [], [], [], [], []
    for i in range(n):
        y10 += rnd.gauss(0, 0.04) - 0.004 * (y10 - 4.0)
        y02 += rnd.gauss(0, 0.045) - 0.01 * (y02 - y10 + 0.5)
        oasv = max(2.5, oasv - 25 * cred[i] + rnd.gauss(0, 0.03) - 0.01 * (oasv - 3.8))
        wti = max(20.0, wti * math.exp(rnd.gauss(0, 0.02)))
        Y10.append((days[i], round(max(0.3, y10), 2)))
        Y02.append((days[i], round(max(0.1, y02), 2)))
        OAS.append((days[i], round(oasv, 2)))
        WTI.append((days[i], round(wti, 2)))
        BRT.append((days[i], round(wti + 3 + rnd.gauss(0, 0.8), 2)))
    S["F:Y10"], S["F:Y02"], S["F:OAS"], S["F:WTI"], S["F:BRENT"] = Y10, Y02, OAS, WTI, BRT
    UR, CLM = [], []
    for i in range(0, n, 21):
        ur = min(11.0, max(3.4, ur + rnd.gauss(0, 0.06) + (0.08 if mkt[i] < -0.015 else 0.0) - 0.04 * (ur - 4.4)))
        UR.append((days[i], round(ur, 1)))
    for i in range(0, n, 5):
        clm = min(700.0, max(180.0, clm * math.exp(rnd.gauss(0, 0.03) - 0.03 * math.log(clm / 225.0))))
        CLM.append((days[i], round(clm * 1000)))
    S["F:UR"], S["F:CLM"] = UR, CLM
    return S
