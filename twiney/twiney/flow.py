"""Options flow: the tape of option prints for your watchlist, shaped like FlowAlgo's feed, with the one
thing a PS60 desk wants from it: **somebody knows something?** — size coming for out-of-the-money calls
or puts while price is still a ways away.

* ``normalize``      turns a vendor record (Quant Data, or anything with similar fields) into one print
* ``FlowBook``       engine-side state: per-symbol history, premium totals, the unusual detector
* ``QuantDataFeed``  polls the Quant Data REST API (Bearer key from config.json, never anywhere else)
* ``SimFlow``        the practice feed: mostly noise, now and then a cluster that means something

Every print reaches the engine through ``Engine.on_flow`` so it is recorded and replays like everything else.
"""

import json
import math
import random
import threading
import time
from collections import deque

FLOW_LABELS = ("UNUSUAL CALLS", "UNUSUAL PUTS")

_ALIASES = {
    "ticker": ("ticker", "symbol", "underlying", "underlying_symbol", "sym", "root"),
    "strike": ("strike", "strike_price", "k"),
    "expiry": ("expiry", "expiration", "expiration_date", "exp", "exp_date", "expires"),
    "cp": ("put_call", "option_type", "type", "cp", "right", "side_cp", "call_put"),
    "premium": ("premium", "prem", "total_premium", "notional", "value", "dollars"),
    "size": ("size", "contracts", "volume", "qty", "quantity"),
    "price": ("price", "option_price", "fill_price", "trade_price", "px"),
    "spot": ("spot", "underlying_price", "stock_price", "ref_price", "underlying_last", "spot_price"),
    "side": ("side", "aggressor", "at", "execution_side", "trade_side", "bid_ask"),
    "kind": ("kind", "order_type", "flow_type", "trade_type", "alert_type", "tag", "sweep_type", "type"),
    "t": ("t", "time", "timestamp", "executed_at", "ts", "datetime", "created_at", "trade_time", "date_time"),
    "id": ("id", "trade_id", "tradeId", "uuid", "print_id", "flow_id"),
    "oi": ("oi", "open_interest", "openInterest"),
    "iv": ("iv", "implied_volatility", "impliedVolatility"),
}


def _flat(rec):
    """The record's fields by a loose name: case and underscores ignored (strikePrice = strike_price = STRIKE),
    one level of nesting opened up (option: {strike: ..}, underlying: {symbol: ..}). Cached on the record."""
    m = rec.get("__flat__") if isinstance(rec, dict) else None
    if m is not None:
        return m
    m = {}
    norm = lambda k: str(k).lower().replace("_", "").replace("-", "")
    for k, v in rec.items():                    # the record's own fields first: they win over a nested object's
        if not isinstance(v, dict):
            m.setdefault(norm(k), v)
    for k, v in rec.items():
        if isinstance(v, dict):
            for k2, v2 in v.items():
                m.setdefault(norm(k2), v2)
                m.setdefault(norm(k) + "." + norm(k2), v2)
    try:
        rec["__flat__"] = m
    except Exception:
        pass
    return m


_ALIASES = {k: tuple(a.lower().replace("_", "") for a in v) for k, v in _ALIASES.items()}
_ALIASES["ticker"] += ("underlyingsymbol", "underlyingticker", "stock", "tickersymbol", "underlying.symbol", "underlying.ticker")
_ALIASES["strike"] += ("strikeprice", "option.strike", "contract.strike")
_ALIASES["cp"] += ("optiontype", "putcall", "callput", "contracttype", "option.type", "contract.type", "option.putcall")
_ALIASES["premium"] += ("totalpremium", "premiumtotal", "dollarvalue", "cost")
_ALIASES["size"] += ("contracts", "tradesize", "totalsize", "quantity", "vol")
_ALIASES["price"] += ("optionprice", "tradeprice", "fillprice", "avgprice", "averageprice")
_ALIASES["spot"] += ("underlyingprice", "stockprice", "spotprice", "underlyinglast", "underlying.price", "underlying.last")
_ALIASES["side"] += ("aggressorside", "tradeside", "sideofmarket", "bidask", "sentiment", "execution")
_ALIASES["expiry"] += ("expirationdate", "expirydate", "option.expiry", "option.expiration", "contract.expiry")
_ALIASES["t"] += ("executedat", "tradetime", "datetime", "createdat", "time", "timestamp", "tradedate", "printtime", "executiontime")
_ALIASES["id"] += ("tradeid", "printid", "flowid", "uid")


def _pick(rec, key):
    m = _flat(rec)
    for k in _ALIASES[key]:
        if k in m and m[k] not in (None, ""):
            return m[k]
    return None


def _num(v):
    try:
        if isinstance(v, str):
            v = v.replace("$", "").replace(",", "").strip()
            if v.upper().endswith("K"):
                return float(v[:-1]) * 1e3
            if v.upper().endswith("M"):
                return float(v[:-1]) * 1e6
        return float(v)
    except (TypeError, ValueError):
        return None


NY = "America/New_York"


def _scale_epoch(x):
    """seconds / milliseconds / microseconds / nanoseconds since 1970 -> seconds."""
    x = float(x)
    if x > 1e17:
        return x / 1e9
    if x > 1e14:
        return x / 1e6
    if x > 1e11:
        return x / 1e3
    return x


def _epoch(v, now):
    """The print's time, or None when it can't be read (never 'now': a re-sent print must look the same)."""
    import datetime as _dt
    from zoneinfo import ZoneInfo
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return _scale_epoch(v)
    s = str(v).strip()
    try:
        return _scale_epoch(float(s))
    except ValueError:
        pass
    # ISO with more than 6 fractional digits (nanoseconds): keep 6
    import re
    s = re.sub(r"(\.\d{6})\d+", r"\1", s)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        d = _dt.datetime.fromisoformat(s.replace(" ", "T", 1) if len(s) > 10 and s[10] == " " else s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=ZoneInfo(NY))     # a US vendor's clock time with no zone is New York time
        return d.timestamp()
    except ValueError:
        pass
    m = re.fullmatch(r"(\d{1,2}):(\d{2})(?::(\d{2})(?:\.(\d+))?)?", s)
    if m:                                          # a bare time of day: today, New York
        today = _dt.datetime.fromtimestamp(now, ZoneInfo(NY))
        d = today.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=int(m.group(3) or 0), microsecond=0)
        return d.timestamp()
    return None


def _expiry_days(v, now):
    """Days to expiry from a date string (YYYY-MM-DD, MM/DD/YY...) or epoch."""
    if v is None:
        return None
    import datetime as _dt
    from zoneinfo import ZoneInfo
    if isinstance(v, (int, float)):
        return max(0.0, (_scale_epoch(v) - now) / 86400.0)
    s = str(v).strip()[:10]
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y%m%d"):
        try:
            d = _dt.datetime.strptime(s, fmt)
            close = _dt.datetime(d.year, d.month, d.day, 16, 0, tzinfo=ZoneInfo(NY))   # options stop trading 4:00 pm ET
            return max(0.0, (close.timestamp() - now) / 86400.0)
        except ValueError:
            continue
    return None


def normalize(rec, now=None):
    """One vendor record -> one print dict, or None when it is not an option trade we can read."""
    now = now or time.time()
    if not isinstance(rec, dict):
        return None
    ticker = _pick(rec, "ticker")
    strike = _num(_pick(rec, "strike"))
    cp = ""
    m = _flat(rec)
    for k in _ALIASES["cp"]:              # "type" can mean SWEEP / BLOCK: take the first field that says call or put
        v = str(m.get(k) or "").strip().upper()
        if v in ("C", "P", "CALL", "PUT", "CALLS", "PUTS"):
            cp = v[0]
            break
    if not ticker or not strike or cp not in ("C", "P"):
        return None
    size = _num(_pick(rec, "size")) or 0.0
    price = _num(_pick(rec, "price"))
    premium = _num(_pick(rec, "premium"))
    if premium is None and price is not None:
        premium = price * 100.0 * size
    spot = _num(_pick(rec, "spot"))
    side = str(_pick(rec, "side") or "").strip().upper()
    if "BID" in side:                      # "AT BID", "AT_BID", "BELOW BID"
        side = "bid"
    elif "ASK" in side or "OFFER" in side:  # "AT ASK", "ABOVE ASK"
        side = "ask"
    else:
        side = ("ask" if side.startswith("A") or side in ("BUY", "BOUGHT", "ABOVE", "BULLISH") else
                "bid" if side.startswith("B") or side in ("SELL", "SOLD", "BELOW", "BEARISH") else "mid")
    kind = str(_pick(rec, "kind") or "").strip().lower()
    kind = "sweep" if "sweep" in kind else "block" if "block" in kind else "split" if "split" in kind else "trade"
    t0 = _epoch(_pick(rec, "t"), now)
    t = t0 if t0 is not None else now
    exp_raw = _pick(rec, "expiry")
    dte = _expiry_days(exp_raw, now)
    otm = None
    if spot:
        otm = (strike - spot) / spot * 100.0 if cp == "C" else (spot - strike) / spot * 100.0
    return {"t": t, "symbol": str(ticker).upper(), "strike": strike, "cp": cp, "expiry": str(exp_raw or "")[:10],
            "dte": None if dte is None else round(dte, 1), "size": int(size), "price": price,
            "premium": round(premium or 0.0, 2), "spot": spot, "side": side, "kind": kind,
            "otm_pct": None if otm is None else round(otm, 2),
            "oi": _num(_pick(rec, "oi")), "iv": _num(_pick(rec, "iv")),
            "t_ok": t0 is not None, "vid": None if _pick(rec, "id") is None else str(_pick(rec, "id"))}


class FlowBook:
    """Per-symbol flow history plus the unusual detector.

    UNUSUAL CALLS / UNUSUAL PUTS: inside ``window_minutes`` a watchlist symbol takes ``min_prints`` or more
    prints of the same side, bought at the ask, at least ``otm_pct`` out of the money, ``max_dte`` days or
    less to expiry, adding up to ``min_premium`` in premium. That is someone paying up for a move that
    has not started. One call per symbol per side per ``repeat_minutes``.
    """

    def __init__(self, cfg):
        self.cfg = cfg
        self.recent = deque(maxlen=400)          # every print, newest first (the feed)
        self.by_symbol = {}                      # symbol -> deque of prints (oldest first)
        self.max_symbols = 400                   # the whole market flows through; keep the busiest
        self.last_call = {}                      # (symbol, cp) -> t of the last unusual call
        self.unusual = {}                        # (symbol, cp) -> last unusual dict

    def add(self, p):
        self.recent.appendleft(p)
        d = self.by_symbol.get(p["symbol"])
        if d is None:
            if len(self.by_symbol) >= self.max_symbols:
                oldest = min(self.by_symbol, key=lambda s: self.by_symbol[s][-1]["t"] if self.by_symbol[s] else 0)
                del self.by_symbol[oldest]
            d = self.by_symbol[p["symbol"]] = deque(maxlen=600)
        d.append(p)

    def _window(self, symbol, now, minutes):
        d = self.by_symbol.get(symbol, ())
        cut = now - minutes * 60
        return [p for p in d if p["t"] >= cut]

    def check(self, symbol, now):
        """Return an unusual dict when the detector fires for ``symbol`` right now, else None."""
        c = self.cfg
        index = symbol in set(c.get("index_symbols", ()))
        min_premium = c.get("index_min_premium", 5e6) if index else c["min_premium"]
        min_prints = c.get("index_min_prints", 3) if index else c["min_prints"]
        prints = self._window(symbol, now, c["window_minutes"])
        for cp in ("C", "P"):
            hits = [p for p in prints if p["cp"] == cp and p["side"] == "ask"
                    and p["otm_pct"] is not None and p["otm_pct"] >= c["otm_pct"]
                    and (p["dte"] is None or p["dte"] <= c["max_dte"])]
            prem = sum(p["premium"] for p in hits)
            if len(hits) >= min_prints and prem >= min_premium:
                key = (symbol, cp)
                if now - self.last_call.get(key, -1e9) < c["repeat_minutes"] * 60:
                    continue
                self.last_call[key] = now
                otm = [p["otm_pct"] for p in hits if p["otm_pct"] is not None]
                dtes = [p["dte"] for p in hits if p["dte"] is not None]
                u = {"symbol": symbol, "cp": cp, "premium": round(prem), "prints": len(hits),
                     "otm_pct": round(sum(otm) / len(otm), 1) if otm else None,
                     "dte": round(min(dtes)) if dtes else None, "spot": hits[-1].get("spot"),
                     "strikes": sorted({p["strike"] for p in hits})[:4], "t": now}
                self.unusual[key] = u
                return u
        return None

    def summary(self, symbol, now, minutes=30):
        """Calls vs puts premium (bought at the ask) over the last ``minutes``, plus the unusual flags."""
        prints = self._window(symbol, now, minutes)
        calls = sum(p["premium"] for p in prints if p["cp"] == "C" and p["side"] == "ask")
        puts = sum(p["premium"] for p in prints if p["cp"] == "P" and p["side"] == "ask")
        tot = calls + puts
        bias = None if tot < 1 else round((calls - puts) / tot, 2)     # +1 all calls, -1 all puts
        flags = [u for (s, cp), u in self.unusual.items() if s == symbol and now - u["t"] < 3600]
        return {"calls": round(calls), "puts": round(puts), "bias": bias, "prints": len(prints),
                "unusual": sorted(flags, key=lambda u: -u["t"])[:2], "minutes": minutes}

    def context_text(self, symbol, now):
        s = self.summary(symbol, now)
        if not s["prints"]:
            return "no option flow seen"
        k = lambda v: f"${v / 1e6:.1f}M" if v >= 1e6 else f"${v / 1e3:.0f}K"
        txt = f"calls {k(s['calls'])} / puts {k(s['puts'])} last {s['minutes']}m"
        if s["bias"] is not None:
            txt += f" · {'call' if s['bias'] > 0 else 'put'} heavy {abs(s['bias']) * 100:.0f}%"
        for u in s["unusual"]:
            txt += f" · UNUSUAL {'CALLS' if u['cp'] == 'C' else 'PUTS'} {k(u['premium'])}"
        return txt


class QuantDataFeed:
    """Polls Quant Data for option prints on your watchlist and hands them to the engine.

    The endpoint and request shape are configurable (config.json ``quantdata``): the vendor's docs were
    not reachable from the build machine, so on the first successful call a sample of the raw response is
    written to ``recordings/quantdata_sample.json``. If prints do not show up, that file is what to look at:
    the field names it uses can be added to ``_ALIASES`` above.
    """

    def __init__(self, engine, cfg, symbols):
        self.engine = engine
        self.cfg = cfg["quantdata"]
        self.symbols = list(symbols)
        self.stop_evt = threading.Event()
        self.seen = deque(maxlen=5000)
        self.seen_set = set()
        self.sample_written = False
        self.errors = 0

    def start(self):
        self.engine.flow_status.update(source="quantdata", state="connecting", detail="")
        threading.Thread(target=self._loop, name="quantdata", daemon=True).start()
        return self

    def stop(self):
        self.stop_evt.set()

    def _loop(self):
        while not self.stop_evt.is_set():
            try:
                self.poll()
            except Exception as exc:      # the desk keeps running without flow
                self.engine.flow_status.update(state="error", detail=str(exc)[:160])
                self.errors += 1
                if self.errors in (1, 10, 100):
                    self.engine._message("warn", f"Quant Data: {exc}", time.time())
            self.stop_evt.wait(max(2.0, float(self.cfg.get("poll_seconds", 5))))

    def _body(self, now=None):
        """Quant Data's documented request: a POST with the session date (New York) and an optional filter.
        One request per poll for the whole market; the watchlist-only view is filtered here, so a long
        watchlist never costs more requests (the plan allows 240 a minute; this uses 12)."""
        from datetime import datetime
        from zoneinfo import ZoneInfo
        day = datetime.fromtimestamp(now or time.time(), ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
        body = {"sessionDate": day}
        body.update(self.cfg.get("extra_params") or {})
        return body

    def _request(self):
        import urllib.error
        import urllib.request
        url = self.cfg["base_url"].rstrip("/") + "/" + self.cfg["flow_path"].lstrip("/")
        req = urllib.request.Request(url, data=json.dumps(self._body()).encode("utf-8"), method=self.cfg.get("method", "POST"),
                                     headers={"Authorization": f"Bearer {self.cfg['api_key']}",
                                              "Content-Type": "application/json", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # say what Quant Data said (never the key): 401 = the key, 403 = the plan, 400 = the request
            why = {401: "key not accepted - check it in SETTINGS", 403: "this key's plan does not include this data",
                   429: "too many requests"}.get(exc.code, "")
            try:
                said = exc.read().decode("utf-8", "replace")[:200]
            except Exception:
                said = ""
            raise RuntimeError(f"HTTP {exc.code}{' (' + why + ')' if why else ''}{': ' + said if said else ''}") from None

    @staticmethod
    def _records(payload, depth=0):
        """The list of prints inside the answer, wherever the vendor put it: the biggest list of records
        found within a few levels (data / results / result.trades / ...)."""
        if isinstance(payload, list):
            return payload if all(isinstance(x, dict) for x in payload[:5]) else []
        best = []
        if isinstance(payload, dict) and depth < 4:
            for v in payload.values():
                if isinstance(v, (list, dict)):
                    inner = QuantDataFeed._records(v, depth + 1)
                    if len(inner) > len(best):
                        best = inner
        return best

    def _write_sample(self, payload):
        """What Quant Data actually sends, for reading their field names: recordings/quantdata_sample.json
        (the answer only, never the key). Kept fresh until a print has been read."""
        try:
            import os
            path = os.path.join(self.engine.cfg["recording"]["dir"], "quantdata_sample.json")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"request": self._body(), "response": payload}, fh, indent=1, default=str)
        except Exception:
            pass

    def poll(self):
        payload = self._request()
        self.engine.flow_status.update(state="ok", detail="", last_ok=time.time())
        recs = self._records(payload)
        if not self.sample_written or (self.engine.flow_status.get("last_print") is None):
            self.sample_written = True
            self._write_sample(payload)
        now = time.time()
        n = 0
        for rec in reversed(recs):          # oldest first
            p = normalize(rec, now)
            if p is None:
                continue
            if getattr(self.engine, "flow_scope", self.cfg.get("scope", "all")) == "watchlist" and p["symbol"] not in self.symbols:
                continue
            # the same print polled twice is one print: the vendor's id, else its time, else the whole record
            if p.get("vid"):
                key = ("id", p["vid"])
            elif p.get("t_ok"):
                key = (p["symbol"], p["t"], p["strike"], p["cp"], p["size"], p["premium"])
            else:
                key = ("rec", json.dumps(rec, sort_keys=True, default=str))
            if key in self.seen_set:
                continue
            if len(self.seen) == self.seen.maxlen:
                self.seen_set.discard(self.seen[0])
            self.seen.append(key); self.seen_set.add(key)
            self.engine.on_flow(p, now)
            n += 1
        if n == 0 and self.engine.flow_status.get("last_print") is None:
            # answered, but nothing readable: say what came back so the field names can be matched
            if recs:
                keys = ", ".join(str(k) for k in list(recs[0])[:10] if not str(k).startswith("__"))
                why = f"{len(recs)} records, none readable as an option print - fields: {keys}"
            else:
                keys = ", ".join(str(k) for k in list(payload)[:8]) if isinstance(payload, dict) else type(payload).__name__
                why = f"no print list in the answer - top-level: {keys}"
            self.engine.flow_status.update(detail=why + " (see recordings/quantdata_sample.json)")
            if not getattr(self, "_said_unreadable", False):
                self._said_unreadable = True
                self.engine._message("warn", "Quant Data answered but TED could not read any print: " + why, now)
        return n


class SimFlow:
    """Practice option flow for the demo: a steady trickle of ordinary prints for every watchlist symbol,
    and every so often a quiet cluster of out-of-the-money buying with size while price is still away.
    Not announced anywhere: you have to see it in the feed, or let the detector call it."""

    # the rest of the market for practice: ticker, rough price, how busy its options are
    MARKET = [("SPY", 572, 5.0), ("QQQ", 488, 4.0), ("SPX", 5725, 3.0), ("IWM", 221, 1.5), ("META", 562, 1.6), ("AMZN", 186, 1.8),
              ("MSFT", 431, 1.4), ("GOOGL", 163, 1.3), ("NFLX", 701, 0.8), ("COIN", 176, 1.0), ("MSTR", 158, 1.1), ("HOOD", 23, 0.9),
              ("BA", 154, 0.7), ("UBER", 74, 0.7), ("AVGO", 172, 1.0), ("MU", 101, 0.9), ("SMCI", 43, 0.8), ("INTC", 22, 0.7),
              ("RIVN", 11, 0.6), ("NIO", 6, 0.5), ("BABA", 106, 0.8), ("DIS", 94, 0.5), ("JPM", 211, 0.5), ("XOM", 118, 0.4),
              ("TLT", 98, 0.6), ("GLD", 245, 0.5), ("ARM", 145, 0.6), ("SNOW", 115, 0.4), ("SHOP", 79, 0.5), ("CVNA", 171, 0.4)]

    def __init__(self, engine, symbols, seed=None, market=None):
        self.engine = engine
        engine.flow_status.update(source="practice", state="ok")
        self.symbols = list(symbols)
        self.market = market   # the practice feed: its market factor moves the rest of the market too
        self.others = {}   # ticker -> [spot, busy], its own walk plus beta x the market
        self.rng = random.Random(seed if seed is not None else int(time.time()) % 99991)
        self.next_t = {}
        self.cluster = {}      # symbol -> {"cp", "until", "next", "strike", "dte"}
        self.next_cluster = 0.0

    def _spot(self, sym):
        st = self.engine.syms.get(sym)
        if st is not None:
            return st.price()
        o = self.others.get(sym)
        return o[0] if o else None

    def _print(self, sym, spot, cp, strike, dte, size, at_ask, kind, t):
        intrinsic = max(0.0, spot - strike) if cp == "C" else max(0.0, strike - spot)
        otm = max(0.0, ((strike - spot) if cp == "C" else (spot - strike)) / spot * 100.0)
        tv = spot * 0.008 * math.sqrt(max(dte, 0.5) / 7.0) * math.exp(-otm / (1.5 + 0.35 * math.sqrt(max(dte, 0.5)))) * self.rng.uniform(0.8, 1.25)
        price = max(0.05, round(intrinsic + tv, 2))
        return {"t": t, "symbol": sym, "strike": strike, "cp": cp, "expiry": time.strftime("%Y-%m-%d", time.localtime(t + dte * 86400)),
                "dte": float(dte), "size": int(size), "price": price, "premium": round(price * 100 * size, 2), "spot": round(spot, 2),
                "side": "ask" if at_ask else self.rng.choice(("bid", "mid")), "kind": kind,
                "otm_pct": round(((strike - spot) if cp == "C" else (spot - strike)) / spot * 100.0, 2), "oi": None, "iv": None}

    def step(self, t):
        rng = self.rng
        if not self.others:
            for sym, spot, busy in self.MARKET:
                if sym not in self.symbols:
                    self.others[sym] = [spot * rng.uniform(0.97, 1.03), busy]
        mk = getattr(self.market, "mkt", None)
        mret = math.log(mk.level / mk.prev_level) if mk and mk.prev_level else 0.0
        from .sim import beta_of
        for sym, o in self.others.items():                     # the rest of the market: beta x the market, plus its own noise
            o[0] *= math.exp(beta_of(sym) * mret + rng.gauss(0, 0.00012))
        lean = (mk.bias - 0.5) if mk else 0.0                  # a rallying tape buys calls, a falling one buys puts
        if t >= self.next_cluster:
            self.next_cluster = t + rng.uniform(300, 900)
            pool = self.symbols + (list(self.others) if getattr(self.engine, "flow_scope", "all") != "watchlist" else [])
            sym = rng.choice(pool) if rng.random() < 0.6 else rng.choice(self.symbols or pool)
            if sym not in self.cluster:
                cp = rng.choice(("C", "P"))
                self.cluster[sym] = {"cp": cp, "until": t + rng.uniform(120, 420), "next": t,
                                     "otm": rng.uniform(3.5, 9.0), "dte": rng.choice((2, 5, 9, 16, 23))}
                # about half the time the flow was early: the stock moves their way some minutes later
                pushes = getattr(self.market, "pushes", None)
                if pushes is not None and sym in getattr(self.market, "state", {}) and rng.random() < 0.5:
                    pushes[sym] = (t + rng.uniform(300, 1200), 1 if cp == "C" else -1)
        whole = getattr(self.engine, "flow_scope", "all") != "watchlist"
        for sym in self.symbols + (list(self.others) if whole else []):
            spot = self._spot(sym)
            if not spot:
                continue
            busy = self.others[sym][1] if sym in self.others else 1.0
            # ordinary flow: near the money, mixed sides, mixed expiries; index products trade far more
            if t >= self.next_t.get(sym, 0):
                self.next_t[sym] = t + rng.expovariate(busy / 25.0)
                cp = "C" if rng.random() < 0.5 + 1.2 * lean else "P"
                step = 5.0 if spot > 1000 else 1.0 if spot > 50 else 0.5 if spot > 10 else 0.25
                strike = round(round((spot * (1 + rng.gauss(0, 0.02) * (1 if cp == "C" else -1))) / step) * step, 2)
                size = int(rng.choice((5, 10, 20, 25, 50, 75, 100, 150, 250, 400, 600, 1000, 2500)))
                self.engine.on_flow(self._print(sym, spot, cp, strike, rng.choice((1, 2, 4, 9, 16, 30, 45)), size,
                                                rng.random() < 0.5, rng.choice(("trade", "trade", "sweep", "block")), t), t)
            cl = self.cluster.get(sym)
            if cl and t >= cl["next"]:
                if t > cl["until"]:
                    del self.cluster[sym]
                    continue
                cl["next"] = t + rng.uniform(15, 60)
                step = 5.0 if spot > 1000 else 1.0 if spot > 50 else 0.5 if spot > 10 else 0.25
                strike = round(round(spot * (1 + cl["otm"] / 100.0 * (1 if cl["cp"] == "C" else -1)) / step) * step, 2)
                size = int(rng.choice((300, 500, 800, 1200, 2000)))
                self.engine.on_flow(self._print(sym, spot, cl["cp"], strike, cl["dte"], size, True, rng.choice(("sweep", "sweep", "block")), t), t)
