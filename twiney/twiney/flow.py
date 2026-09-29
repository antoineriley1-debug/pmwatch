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
    "kind": ("kind", "order_type", "flow_type", "trade_type", "alert_type", "tag", "sweep_type"),
    "t": ("t", "time", "timestamp", "executed_at", "ts", "datetime", "created_at"),
    "oi": ("oi", "open_interest", "openInterest"),
    "iv": ("iv", "implied_volatility", "impliedVolatility"),
}


def _pick(rec, key):
    for k in _ALIASES[key]:
        if k in rec and rec[k] not in (None, ""):
            return rec[k]
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


def _epoch(v, now):
    if v is None:
        return now
    if isinstance(v, (int, float)):
        return float(v) / 1000.0 if v > 1e11 else float(v)
    s = str(v).strip()
    try:
        return float(s) / 1000.0 if float(s) > 1e11 else float(s)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            import datetime as _dt
            d = _dt.datetime.strptime(s, fmt)
            if d.tzinfo is None:
                d = d.replace(tzinfo=_dt.timezone.utc)
            return d.timestamp()
        except ValueError:
            continue
    return now


def _expiry_days(v, now):
    """Days to expiry from a date string (YYYY-MM-DD, MM/DD/YY...) or epoch."""
    if v is None:
        return None
    import datetime as _dt
    if isinstance(v, (int, float)):
        return max(0.0, (float(v) - now) / 86400.0)
    s = str(v).strip()[:10]
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y%m%d"):
        try:
            d = _dt.datetime.strptime(s, fmt).replace(tzinfo=_dt.timezone.utc)
            return max(0.0, (d.timestamp() + 16 * 3600 - now) / 86400.0)
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
    cp = str(_pick(rec, "cp") or "").strip().upper()[:1]
    if not ticker or not strike or cp not in ("C", "P"):
        return None
    size = _num(_pick(rec, "size")) or 0.0
    price = _num(_pick(rec, "price"))
    premium = _num(_pick(rec, "premium"))
    if premium is None and price is not None:
        premium = price * 100.0 * size
    spot = _num(_pick(rec, "spot"))
    side = str(_pick(rec, "side") or "").strip().upper()
    side = "ask" if side.startswith("A") or side in ("BUY", "ABOVE") else "bid" if side.startswith("B") and side != "BUY" else "mid"
    kind = str(_pick(rec, "kind") or "").strip().lower()
    kind = "sweep" if "sweep" in kind else "block" if "block" in kind else "split" if "split" in kind else "trade"
    t = _epoch(_pick(rec, "t"), now)
    exp_raw = _pick(rec, "expiry")
    dte = _expiry_days(exp_raw, now)
    otm = None
    if spot:
        otm = (strike - spot) / spot * 100.0 if cp == "C" else (spot - strike) / spot * 100.0
    return {"t": t, "symbol": str(ticker).upper(), "strike": strike, "cp": cp, "expiry": str(exp_raw or "")[:10],
            "dte": None if dte is None else round(dte, 1), "size": int(size), "price": price,
            "premium": round(premium or 0.0, 2), "spot": spot, "side": side, "kind": kind,
            "otm_pct": None if otm is None else round(otm, 2),
            "oi": _num(_pick(rec, "oi")), "iv": _num(_pick(rec, "iv"))}


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
        self.last_call = {}                      # (symbol, cp) -> t of the last unusual call
        self.unusual = {}                        # (symbol, cp) -> last unusual dict

    def add(self, p):
        self.recent.appendleft(p)
        d = self.by_symbol.setdefault(p["symbol"], deque(maxlen=600))
        d.append(p)

    def _window(self, symbol, now, minutes):
        d = self.by_symbol.get(symbol, ())
        cut = now - minutes * 60
        return [p for p in d if p["t"] >= cut]

    def check(self, symbol, now):
        """Return an unusual dict when the detector fires for ``symbol`` right now, else None."""
        c = self.cfg
        prints = self._window(symbol, now, c["window_minutes"])
        for cp in ("C", "P"):
            hits = [p for p in prints if p["cp"] == cp and p["side"] == "ask"
                    and (p["otm_pct"] is None or p["otm_pct"] >= c["otm_pct"])
                    and (p["dte"] is None or p["dte"] <= c["max_dte"])]
            prem = sum(p["premium"] for p in hits)
            if len(hits) >= c["min_prints"] and prem >= c["min_premium"]:
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
        calls = sum(p["premium"] for p in prints if p["cp"] == "C" and p["side"] != "bid")
        puts = sum(p["premium"] for p in prints if p["cp"] == "P" and p["side"] != "bid")
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
        threading.Thread(target=self._loop, name="quantdata", daemon=True).start()
        return self

    def stop(self):
        self.stop_evt.set()

    def _loop(self):
        while not self.stop_evt.is_set():
            try:
                self.poll()
            except Exception as exc:      # the desk keeps running without flow
                self.errors += 1
                if self.errors in (1, 10, 100):
                    self.engine._message("warn", f"Quant Data: {exc}", time.time())
            self.stop_evt.wait(max(2.0, float(self.cfg.get("poll_seconds", 5))))

    def _request(self):
        import urllib.request
        url = self.cfg["base_url"].rstrip("/") + "/" + self.cfg["flow_path"].lstrip("/")
        body = {"tickers": self.symbols, "limit": int(self.cfg.get("limit", 200))}
        body.update(self.cfg.get("extra_params") or {})
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method=self.cfg.get("method", "POST"),
                                     headers={"Authorization": f"Bearer {self.cfg['api_key']}",
                                              "Content-Type": "application/json", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))

    @staticmethod
    def _records(payload):
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for k in ("data", "results", "items", "flow", "trades", "alerts", "records"):
                v = payload.get(k)
                if isinstance(v, list):
                    return v
                if isinstance(v, dict):
                    inner = QuantDataFeed._records(v)
                    if inner:
                        return inner
        return []

    def poll(self):
        payload = self._request()
        if not self.sample_written:
            self.sample_written = True
            try:
                import os
                path = os.path.join(self.engine.cfg["recording"]["dir"], "quantdata_sample.json")
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump(payload, fh, indent=1)
            except Exception:
                pass
        now = time.time()
        n = 0
        for rec in reversed(self._records(payload)):          # oldest first
            p = normalize(rec, now)
            if p is None:
                continue
            key = (p["symbol"], p["t"], p["strike"], p["cp"], p["size"], p["premium"])
            if key in self.seen_set:
                continue
            if len(self.seen) == self.seen.maxlen:
                self.seen_set.discard(self.seen[0])
            self.seen.append(key); self.seen_set.add(key)
            self.engine.on_flow(p, now)
            n += 1
        return n


class SimFlow:
    """Practice option flow for the demo: a steady trickle of ordinary prints for every watchlist symbol,
    and every so often a quiet cluster of out-of-the-money buying with size while price is still away.
    Not announced anywhere: you have to see it in the feed, or let the detector call it."""

    def __init__(self, engine, symbols, seed=None):
        self.engine = engine
        self.symbols = list(symbols)
        self.rng = random.Random(seed if seed is not None else int(time.time()) % 99991)
        self.next_t = {}
        self.cluster = {}      # symbol -> {"cp", "until", "next", "strike", "dte"}
        self.next_cluster = 0.0

    def _spot(self, sym):
        st = self.engine.syms.get(sym)
        return st.price() if st is not None else None

    def _print(self, sym, spot, cp, strike, dte, size, at_ask, kind, t):
        price = max(0.05, round(abs(spot - strike) * 0.25 + spot * 0.004 * math.sqrt(max(dte, 1) / 10.0) * self.rng.uniform(0.7, 1.4), 2))
        return {"t": t, "symbol": sym, "strike": strike, "cp": cp, "expiry": time.strftime("%Y-%m-%d", time.localtime(t + dte * 86400)),
                "dte": float(dte), "size": int(size), "price": price, "premium": round(price * 100 * size, 2), "spot": round(spot, 2),
                "side": "ask" if at_ask else self.rng.choice(("bid", "mid")), "kind": kind,
                "otm_pct": round(((strike - spot) if cp == "C" else (spot - strike)) / spot * 100.0, 2), "oi": None, "iv": None}

    def step(self, t):
        rng = self.rng
        if t >= self.next_cluster:
            self.next_cluster = t + rng.uniform(600, 1800)
            sym = rng.choice(self.symbols)
            if sym not in self.cluster:
                self.cluster[sym] = {"cp": rng.choice(("C", "P")), "until": t + rng.uniform(120, 420), "next": t,
                                     "otm": rng.uniform(3.5, 9.0), "dte": rng.choice((2, 5, 9, 16, 23))}
        for sym in self.symbols:
            spot = self._spot(sym)
            if not spot:
                continue
            # ordinary flow: near the money, mixed sides, mixed expiries
            if t >= self.next_t.get(sym, 0):
                self.next_t[sym] = t + rng.expovariate(1 / 25.0)
                cp = rng.choice(("C", "P"))
                step = 1.0 if spot > 50 else 0.5 if spot > 10 else 0.25
                strike = round(round((spot * (1 + rng.gauss(0, 0.02) * (1 if cp == "C" else -1))) / step) * step, 2)
                size = int(rng.choice((5, 10, 20, 25, 50, 75, 100, 150, 250, 400)))
                self.engine.on_flow(self._print(sym, spot, cp, strike, rng.choice((1, 2, 4, 9, 16, 30, 45)), size,
                                                rng.random() < 0.5, rng.choice(("trade", "trade", "sweep", "block")), t), t)
            cl = self.cluster.get(sym)
            if cl and t >= cl["next"]:
                if t > cl["until"]:
                    del self.cluster[sym]
                    continue
                cl["next"] = t + rng.uniform(15, 60)
                step = 1.0 if spot > 50 else 0.5 if spot > 10 else 0.25
                strike = round(round(spot * (1 + cl["otm"] / 100.0 * (1 if cl["cp"] == "C" else -1)) / step) * step, 2)
                size = int(rng.choice((300, 500, 800, 1200, 2000)))
                self.engine.on_flow(self._print(sym, spot, cl["cp"], strike, cl["dte"], size, True, rng.choice(("sweep", "sweep", "block")), t), t)
