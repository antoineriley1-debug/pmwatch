"""Loads the daily closes the MARKET ANALYSIS DETAILED REPORT reads, keeps them on disk, and builds the report.

Where each number comes from:
    IBKR (the desk's own TWS / Gateway login, historical daily bars, no extra market data):
        SPY, the junk bond fund HYG, the bank fund, the 13 sector funds, the equal-weight S&P (RSP), the chip fund,
        copper (the continuous COMEX future), and all ~500 S&P 500 members (breadth, leaders, the stocks lagging)
    FRED (the St. Louis Fed, free, no key): the 10-year and 2-year rates, unemployment, weekly jobless claims,
        WTI and Brent oil, the high-yield credit spread
Nothing else leaves the computer for this page. The first load asks IBKR for 20 years of daily bars per symbol
(a few minutes, a few at a time so the desk's own requests are never crowded); after that only the missing days.
Everything is kept under the data folder (history/macro), so the page opens with the last report at once, even
before IBKR connects. The practice desk builds its report from synthetic closes and says so.
"""

import csv
import io
import json
import logging
import os
import threading
import time
import urllib.request

from . import macro

log = logging.getLogger("twiney.macro")

MEMBERS_FILE = os.path.join(os.path.dirname(__file__), "knowledge", "sp500_members.csv")
MEMBERS_URL = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={}"
RETRY_CODES = {162, 165, 366, 420, 10197}


def ny_now(t):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime.fromtimestamp(t, ZoneInfo("America/New_York"))


def ny_day(t):
    d = ny_now(t)
    return d.year * 10000 + d.month * 100 + d.day


def last_closed_day(t):
    """The last New York trading day whose 4:00 PM close has happened (weekends skipped; holidays show up as a
    day IBKR simply has no bar for, which the loader treats as already current)."""
    import datetime as _dt
    d = ny_now(t)
    day = d.date()
    if d.hour * 60 + d.minute < 16 * 60 + 15:
        day -= _dt.timedelta(days=1)
    while day.weekday() >= 5:
        day -= _dt.timedelta(days=1)
    return day.year * 10000 + day.month * 100 + day.day


def load_members(data_dir=None):
    """{symbol: (name, sector)} from the saved list (data folder first: a refreshed list wins over the shipped one)."""
    paths = []
    if data_dir:
        paths.append(os.path.join(data_dir, "members.csv"))
    paths.append(MEMBERS_FILE)
    for p in paths:
        try:
            with open(p, encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            out = {}
            for r in rows:
                sym = (r.get("symbol") or r.get("Symbol") or "").strip().upper()
                if sym:
                    out[sym] = ((r.get("name") or r.get("Security") or "").strip(), (r.get("sector") or r.get("GICS Sector") or "").strip())
            if len(out) > 100:
                return out
        except OSError:
            continue
    return {}


def ib_symbol(sym):
    """BRK.B on the S&P list is 'BRK B' at IBKR."""
    return sym.replace(".", " ")


class MacroFeed:
    """mode: 'live' (IBKR + FRED), 'practice' (synthetic closes), 'cache' (replay: what is on disk, nothing asked)."""

    def __init__(self, cfg, mode="live", cache_dir=None, clock=time.time, fetch=None, contract_factory=None):
        self.cfg = cfg
        self.mode = mode
        self.clock = clock
        self.dir = cache_dir
        if self.dir:
            os.makedirs(self.dir, exist_ok=True)
        self.fetch = fetch or self._http_get
        self.contract_factory = contract_factory
        self.lock = threading.RLock()
        self.series = {}                 # key -> [(yyyymmdd, close)]
        self.members = load_members(self.dir)
        self.report = None
        self.computed_at = None
        self.building = False
        self.error = None
        self.queue = []                  # (key, spec) waiting for IBKR
        self.inflight = {}               # reqId -> {"key", "spec", "t", "bars"}
        self.failed = {}                 # key -> reason
        self.total = 0
        self.done = 0
        self.loading = False
        self.load_started = None
        self.due = 0.0                   # when the next IBKR load may start
        self.last_load_day = None
        self.fred_state = {"state": "idle", "t": None, "failed": {}}
        self._last_send = 0.0
        self._refresh_asked = False
        self.changed = 0

    # ---- settings -----------------------------------------------------------------------------------------
    def mc(self):
        return self.cfg.get("market") or {}

    def enabled(self):
        return bool(self.mc().get("enabled", True))

    # ---- what the report needs ----------------------------------------------------------------------------
    def wanted(self):
        """[(key, spec)] spec = {symbol, sec, exchange, what, adjusted}."""
        mc = self.mc()
        out = []

        def stk(key, sym, adjusted=False):
            out.append((key, {"symbol": ib_symbol(sym), "sec": "STK", "exchange": "SMART", "what": "ADJUSTED_LAST" if adjusted else "TRADES", "adjusted": adjusted}))
        bank = (mc.get("bank_fund") or "XLF").upper()
        stk("SPY.A", "SPY", True)
        stk("HYG.A", "HYG", True)
        stk(bank + ".A", bank, True)
        stk("SPY", "SPY")
        for _nm, sym, _g, _w in macro.SECTORS:
            stk(sym, sym)
        if bank not in [s for _n, s, _g, _w in macro.SECTORS]:
            stk(bank, bank)
        stk("RSP", "RSP")
        chip = (mc.get("chip_fund") or "SMH").upper()
        stk(chip, chip)
        cop = (mc.get("copper") or "HG").upper()
        if cop == "HG":
            out.append(("COPPER", {"symbol": "HG", "sec": "CONTFUT", "exchange": "COMEX", "what": "TRADES", "adjusted": False}))
        else:
            stk("COPPER", cop)
        if mc.get("members", True):
            for sym in self.members:
                stk("M:" + sym, sym)
        for s in mc.get("big_names") or []:
            s = str(s).strip().upper()
            if s and s not in self.members:
                stk("X:" + s, s)
        return out

    # ---- disk -----------------------------------------------------------------------------------------------
    def _path(self, key):
        return os.path.join(self.dir, key.replace(":", "_").replace(".", "-").replace(" ", "_") + ".json") if self.dir else None

    def load_cache(self):
        if not self.dir:
            return 0
        n = 0
        keys = [k for k, _s in self.wanted()] + ["F:" + k for k in macro.FRED]
        for key in keys:
            p = self._path(key)
            try:
                with open(p, encoding="utf-8") as f:
                    rows = json.load(f)
                with self.lock:
                    self.series[key] = [(int(d), float(c)) for d, c in rows]
                n += 1
            except (OSError, ValueError, TypeError):
                continue
        return n

    def _save(self, key):
        p = self._path(key)
        if not p:
            return
        try:
            tmp = p + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.series.get(key) or [], f, separators=(",", ":"))
            os.replace(tmp, p)
        except OSError as exc:
            log.warning("market cache %s: %s", key, exc)

    def merge(self, key, rows, replace=False):
        """Fold new (day, close) rows into a series (newer wins on the same day)."""
        with self.lock:
            cur = {} if replace else dict(self.series.get(key) or [])
            for d, c in rows:
                if c is None or c != c:
                    continue                    # a blank or not-a-number close is skipped
                if c <= 0 and not key.startswith("F:"):
                    continue                    # a price is never zero or below; a FRED number can be
                cur[int(d)] = float(c)
            self.series[key] = sorted(cur.items())
            self.changed += 1

    # ---- FRED -----------------------------------------------------------------------------------------------
    @staticmethod
    def _http_get(url, timeout=25):
        req = urllib.request.Request(url, headers={"User-Agent": "TED-desk/1.0 (market report)"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace")

    @staticmethod
    def parse_fred(text):
        rows = []
        rd = csv.reader(io.StringIO(text))
        next(rd, None)
        for r in rd:
            if len(r) < 2 or not r[0] or r[1] in (".", ""):
                continue
            try:
                rows.append((int(r[0].replace("-", "")[:8]), float(r[1])))
            except ValueError:
                continue
        return rows

    def load_fred(self):
        if not self.mc().get("fred", True):
            self.fred_state.update(state="off", t=self.clock())
            return
        self.fred_state.update(state="loading", t=self.clock(), failed={})
        failed = {}
        for key, sid in macro.FRED.items():
            try:
                rows = self.parse_fred(self.fetch(FRED_URL.format(sid)))
                if not rows:
                    raise ValueError("no rows")
                self.merge("F:" + key, rows, replace=True)
                self._save("F:" + key)
            except Exception as exc:          # offline, blocked, FRED down: the cached copy stays
                failed[key] = str(exc)[:160]
        self.fred_state.update(state="ok" if not failed else "partial" if len(failed) < len(macro.FRED) else "failed",
                               t=self.clock(), failed=failed)

    def refresh_members(self):
        """A fresh S&P 500 list (from the public datasets list on GitHub) saved to the data folder."""
        text = self.fetch(MEMBERS_URL)
        rows = list(csv.DictReader(io.StringIO(text)))
        if len(rows) < 400:
            raise ValueError(f"the list came back with {len(rows)} names")
        p = os.path.join(self.dir, "members.csv")
        with open(p, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["symbol", "name", "sector"])
            for r in rows:
                w.writerow([r["Symbol"].strip(), r["Security"].strip(), r["GICS Sector"].strip()])
        self.members = load_members(self.dir)
        self.request_refresh()
        return len(self.members)

    # ---- the report ---------------------------------------------------------------------------------------------
    def build(self, source=None):
        with self.lock:
            if self.building:
                return False
            self.building = True
            S = {k: list(v) for k, v in self.series.items()}
            members = dict(self.members)
        try:
            src = source or ("PRACTICE · synthetic closes, not the market" if self.mode == "practice" else "IBKR daily closes + FRED")
            rep = macro.build_report(S, members, self.mc(), source=src)
            with self.lock:
                self.report = rep
                self.computed_at = self.clock()
                self.error = None if rep.get("ok") else rep.get("reason")
            return True
        except Exception as exc:
            log.exception("market report")
            with self.lock:
                self.error = f"the report failed to build: {exc}"
            return False
        finally:
            with self.lock:
                self.building = False

    def build_async(self):
        threading.Thread(target=self.build, name="twiney-market", daemon=True).start()

    # ---- start ----------------------------------------------------------------------------------------------------
    def start(self):
        """Practice: synthetic closes. Live / cache: last report from disk at once, then FRED in the background."""
        if not self.enabled():
            return self
        if self.mode == "practice":
            def run():
                syms = list(self.members)[: int(self.mc().get("practice_members", 200) or 200)]
                for s in self.mc().get("big_names") or []:          # the big names always count on the practice page
                    s = str(s).strip().upper()
                    if s in self.members and s not in syms:
                        syms.append(s)
                S = macro.practice_series(syms, seed=int(self.mc().get("practice_seed", 11) or 11))
                with self.lock:
                    self.series = S
                    self.members = {s: self.members[s] for s in syms}
                self.build()
            threading.Thread(target=run, name="twiney-market-practice", daemon=True).start()
            return self

        def run():
            if self.load_cache():
                self.build()
            if self.mode == "live":
                self.load_fred()
                self.build()
        threading.Thread(target=run, name="twiney-market-start", daemon=True).start()
        return self

    def request_refresh(self):
        with self.lock:
            self._refresh_asked = True
            self.due = 0.0

    # ---- IBKR loading (called from the session thread, once a step) ------------------------------------------------
    def _need(self, key, spec, today):
        rows = self.series.get(key)
        if not rows:
            return f"{int(self.mc().get('years', 20) or 20)} Y"
        last = rows[-1][0]
        if spec.get("adjusted"):
            # an adjusted history moves at every dividend: asked whole, or not at all when it is current
            return None if last >= today else f"{int(self.mc().get('years', 20) or 20)} Y"
        if last >= today:
            return None
        import datetime as _dt
        a = _dt.date(last // 10000, (last // 100) % 100, last % 100)
        b = _dt.date(today // 10000, (today // 100) % 100, today % 100)
        gap = (b - a).days + 7
        return f"{gap} D" if gap <= 360 else f"{min(20, gap // 365 + 1)} Y"

    def step(self, now, session):
        """Once a session step while connected: start a load when due, keep a few requests in flight."""
        if self.mode != "live" or not self.enabled() or session is None or getattr(session, "app", None) is None:
            return
        today = last_closed_day(now)
        with self.lock:
            if not self.loading:
                if now < self.due:
                    return
                if not self._refresh_asked and self.last_load_day == today:
                    return
                self._refresh_asked = False
                self.queue = []
                self.failed = {}
                for key, spec in self.wanted():
                    dur = self._need(key, spec, today)
                    if dur:
                        self.queue.append((key, dict(spec, dur=dur)))
                self.total = len(self.queue)
                self.done = 0
                self.loading = True
                self.load_started = now
                self.last_load_day = today
                if not self.queue:
                    self.loading = False
                    self.due = now + 600
                    if self.report is None:
                        self.build_async()
                    return
            # time out a request IBKR never answered
            tmo = float(self.mc().get("timeout_s", 40) or 40)
            for rid, r in list(self.inflight.items()):
                if now - r["t"] > tmo:
                    self.inflight.pop(rid, None)
                    session.app.req.pop(rid, None)
                    if r["tries"] < 2:                                   # asked again at the back of the line, twice
                        self.queue.append((r["key"], dict(r["spec"], tries=r["tries"] + 1)))
                        continue
                    self.failed[r["key"]] = f"IBKR did not answer in {tmo:.0f} s, three times"
                    self.done += 1
            limit = max(1, int(self.mc().get("in_flight", 6) or 6))
            gap = float(self.mc().get("send_gap_s", 0.2) or 0.2)
            while self.queue and len(self.inflight) < limit and now - self._last_send >= gap:
                key, spec = self.queue.pop(0)
                rid = session._rid()
                session.app.req[rid] = ("macro", key)
                self.inflight[rid] = {"key": key, "spec": spec, "t": now, "bars": [], "tries": spec.get("tries", 0)}
                self._last_send = now
                try:
                    contract = (self.contract_factory or make_contract)(spec)
                    session.app.reqHistoricalData(rid, contract, "", spec["dur"], "1 day", spec["what"], 1, 1, False, [])
                except Exception as exc:
                    self.inflight.pop(rid, None)
                    self.failed[key] = str(exc)[:160]
                    self.done += 1
            if not self.queue and not self.inflight:
                self.loading = False
                self.due = now + 600
                finished = True
            else:
                finished = False
        if finished:
            self.build_async()

    def on_bar(self, rid, bar):
        with self.lock:
            r = self.inflight.get(rid)
            if r is None:
                return
            d = str(getattr(bar, "date", "")).strip()[:8]
            if not d.isdigit():
                return
            day = int(d)
            if day >= ny_day(self.clock()) and ny_now(self.clock()).hour * 60 + ny_now(self.clock()).minute < 16 * 60 + 15:
                return                   # today's bar is still forming: the report reads closed days only
            try:
                c = float(bar.close)
            except (TypeError, ValueError):
                return
            r["bars"].append((day, c))

    def on_end(self, rid):
        with self.lock:
            r = self.inflight.pop(rid, None)
            if r is None:
                return
            self.done += 1
        if r["bars"]:
            self.merge(r["key"], r["bars"], replace=bool(r["spec"].get("adjusted")) or r["spec"]["dur"].endswith(" Y") and not self.series.get(r["key"]))
            self._save(r["key"])
        else:
            with self.lock:
                self.failed.setdefault(r["key"], "no bars came back")

    def on_error(self, rid, code, msg):
        with self.lock:
            r = self.inflight.pop(rid, None)
            if r is None:
                return
            if code in RETRY_CODES and r["tries"] < 2:
                spec = dict(r["spec"], tries=r["tries"] + 1)
                self.queue.append((r["key"], spec))     # asked again at the back of the line
                return
            self.done += 1
            self.failed[r["key"]] = f"{code}: {str(msg)[:140]}"

    # ---- the page ----------------------------------------------------------------------------------------------
    def snapshot(self, full=True):
        with self.lock:
            fails = dict(list(self.failed.items())[:40])
            return {"enabled": self.enabled(), "mode": self.mode, "computed_at": self.computed_at, "building": self.building,
                    "error": self.error, "loading": {"on": self.loading, "done": self.done, "total": self.total,
                                                     "inflight": len(self.inflight), "failed": len(self.failed),
                                                     "failed_list": fails, "started": self.load_started},
                    "fred": dict(self.fred_state), "members": len(self.members),
                    "series": len(self.series), "report": self.report if full else None}


def make_contract(spec):
    from ibapi.contract import Contract
    c = Contract()
    c.symbol = spec["symbol"]
    c.secType = spec.get("sec") or "STK"
    c.exchange = spec.get("exchange") or "SMART"
    c.currency = "USD"
    return c
