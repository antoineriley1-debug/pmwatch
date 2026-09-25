"""IBKR market-data adapter (TWS API ``ibapi``).

Only these requests are ever sent: reqMarketDataType, reqMktData / cancelMktData,
reqMktDepth / cancelMktDepth, reqTickByTickData / cancelTickByTickData.
The client class puts ``ReadOnlyGuard`` ahead of EClient so order/execution
calls raise instead of reaching TWS.

Callback signatures follow TWS API 10.x; ``error`` accepts both the pre-10.35
form (reqId, code, msg[, json]) and the newer one (reqId, errorTime, code, msg[, json]).
"""

import logging
import threading
import time

from .safety import ReadOnlyGuard

log = logging.getLogger("twiney.ibkr")

# tickPrice / tickSize types -> engine L1 field (live and delayed variants)
PRICE_TICKS = {1: "bid", 2: "ask", 4: "last", 6: "high", 7: "low", 9: "close", 14: "open",
               66: "bid", 67: "ask", 68: "last", 72: "high", 73: "low", 75: "close", 76: "open"}
SIZE_TICKS = {0: "bid_size", 3: "ask_size", 5: "last_size", 8: "volume",
              69: "bid_size", 70: "ask_size", 71: "last_size", 74: "volume"}

INFO_CODES = {2104, 2106, 2107, 2108, 2119, 2158, 2150, 10167}
FARM_WARN_CODES = {2103, 2105, 2157, 2152}
DEPTH_REJECT_CODES = {309, 10092}
SUBSCRIPTION_CODES = {354, 10089, 10090, 10168, 10186, 10197, 322, 10190, 200}


def num(x):
    """IBKR Decimal / float -> float, mapping UNSET sentinels to None."""
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if v != v or abs(v) >= 1e30:
        return None
    return v


def parse_error_args(args):
    """Normalise ``error`` callback args -> (req_id, code, message)."""
    args = list(args)
    req_id = args[0] if args else -1
    if len(args) >= 4 and isinstance(args[2], int) and isinstance(args[3], str):
        return req_id, args[2], args[3]  # (reqId, errorTime, code, msg, ...)
    code = args[1] if len(args) > 1 else 0
    msg = args[2] if len(args) > 2 else ""
    return req_id, code, str(msg)


class TwineyWrapper:
    """EWrapper callbacks translated into engine events. Pure Python; testable."""

    def __init__(self, engine, session, clock=time.time):
        self.engine = engine
        self.session = session
        self.clock = clock
        self.req = {}  # reqId -> (kind, symbol)

    # connection -----------------------------------------------------------
    def nextValidId(self, orderId):
        # used only as the "API is ready" signal; the order id is discarded
        self.session.handle_ready()

    def connectionClosed(self):
        self.session.handle_closed("connection closed by TWS / Gateway")

    def marketDataType(self, reqId, marketDataType):
        self.engine.on_market_data_type(marketDataType, self.clock())

    def error(self, *args):
        req_id, code, msg = parse_error_args(args)
        t = self.clock()
        kind, sym = self.req.get(req_id, (None, None))
        if code == 317 and kind == "depth":
            self.engine.on_depth_reset(sym, t, "317")
        elif code in DEPTH_REJECT_CODES and kind == "depth":
            self.session.mark_dead(req_id)
            self.engine.on_depth_rejected(sym, code, msg, t)
        elif code == 1100:
            self.engine.on_connection("FEED_DOWN", f"[1100] {msg}", t)
        elif code == 2110:
            self.engine.on_connection("FEED_DOWN", f"[2110] {msg}", t)
        elif code == 1101:
            self.session.handle_data_lost(msg)
        elif code == 1102:
            self.engine.on_connection("CONNECTED", "[1102] restored, data maintained", t)
        elif code in (502, 504, 326):
            self.session.handle_closed(f"[{code}] {msg}")
        elif code in INFO_CODES:
            self.engine.on_error(sym, code, msg, t, level="info")
        elif code in FARM_WARN_CODES:
            self.engine.on_error(sym, code, msg, t, level="warn")
        elif code in SUBSCRIPTION_CODES:
            self.engine.on_error(sym, code, msg, t, level="error")
        else:
            self.engine.on_error(sym, code, msg, t, level="warn" if code >= 2000 else "error")

    # L1 -------------------------------------------------------------------
    def tickPrice(self, reqId, tickType, price, attrib):
        field = PRICE_TICKS.get(tickType)
        kind, sym = self.req.get(reqId, (None, None))
        if field is None or kind != "l1":
            return
        v = num(price)
        if v is None or v <= 0:
            return
        self.engine.on_l1(sym, field, v, self.clock())

    def tickSize(self, reqId, tickType, size):
        field = SIZE_TICKS.get(tickType)
        kind, sym = self.req.get(reqId, (None, None))
        if field is None or kind != "l1":
            return
        v = num(size)
        if v is not None:
            self.engine.on_l1(sym, field, v, self.clock())

    # depth ----------------------------------------------------------------
    def updateMktDepth(self, reqId, position, operation, side, price, size):
        self.updateMktDepthL2(reqId, position, "", operation, side, price, size, False)

    def updateMktDepthL2(self, reqId, position, marketMaker, operation, side, price, size, isSmartDepth=True):
        kind, sym = self.req.get(reqId, (None, None))
        if kind != "depth":
            return
        self.engine.on_depth(sym, int(position), int(operation), int(side),
                             num(price) or 0.0, num(size) or 0.0, marketMaker or "", self.clock())

    # tape -----------------------------------------------------------------
    def tickByTickAllLast(self, reqId, tickType, time_, price, size, tickAttribLast, exchange, specialConditions):
        kind, sym = self.req.get(reqId, (None, None))
        if kind != "tape":
            return
        self.engine.on_print(sym, num(price), num(size), exchange or "", self.clock(), specialConditions or "")


def make_contract(play):
    from ibapi.contract import Contract
    c = Contract()
    c.symbol = play["symbol"]
    c.secType = "STK"
    c.exchange = play.get("exchange") or "SMART"
    c.currency = play.get("currency") or "USD"
    if play.get("primary_exchange"):
        c.primaryExchange = play["primary_exchange"]
    return c


def ibapi_app_factory():
    """Return a factory building the real read-only TWS API client."""
    from ibapi.client import EClient
    from ibapi.wrapper import EWrapper

    class TwineyApp(TwineyWrapper, ReadOnlyGuard, EWrapper, EClient):
        def __init__(self, engine, session):
            EWrapper.__init__(self)
            EClient.__init__(self, wrapper=self)
            TwineyWrapper.__init__(self, engine, session)

    return TwineyApp


class MarketDataSession:
    """Owns the connection, reconnect backoff and all subscriptions."""

    def __init__(self, engine, cfg, plays, app_factory, contract_factory=make_contract, clock=time.time):
        self.engine = engine
        self.cfg = cfg
        self.plays = {p["symbol"]: p for p in plays if p["active"]}
        self.app_factory = app_factory
        self.contract_factory = contract_factory
        self.clock = clock
        self.app = None
        self.ready = False
        self.connecting_since = None
        self.backoff = cfg["ibkr"]["reconnect_initial_seconds"]
        self.next_attempt = 0.0
        self._next_id = 1000
        self.l1_ids = {}      # symbol -> reqId
        self.depth_ids = {}   # symbol -> (depth reqId, tape reqId)
        self.dead = set()
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self.thread = None

    def _rid(self):
        self._next_id += 1
        return self._next_id

    # lifecycle -------------------------------------------------------------
    def start(self):
        self.thread = threading.Thread(target=self._loop, name="twiney-session", daemon=True)
        self.thread.start()

    def stop(self):
        self._stop.set()
        with self._lock:
            app = self.app
        if app is not None:
            try:
                app.disconnect()
            except Exception:
                pass

    def _loop(self):
        while not self._stop.is_set():
            try:
                self.step(self.clock())
            except Exception:
                log.exception("session step failed")
            self._stop.wait(0.25)

    def step(self, now):
        with self._lock:
            if self.app is None and now >= self.next_attempt:
                self._connect(now)
            elif self.app is not None and not self.ready and self.connecting_since is not None \
                    and now - self.connecting_since > 15.0:
                self.handle_closed("no nextValidId within 15s (check API settings / client id)")
            if self.ready:
                self.engine.tick(now)
                self.reconcile_depth()
            else:
                self.engine.tick(now, allocate_slots=False)

    def _connect(self, now):
        ib = self.cfg["ibkr"]
        self.engine.on_connection("CONNECTING", f"{ib['host']}:{ib['port']} client {ib['client_id']}", now)
        app = self.app_factory(self.engine, self)
        self.app = app
        self.connecting_since = now
        try:
            app.connect(ib["host"], ib["port"], ib["client_id"])
        except Exception as exc:  # socket refused etc.
            self.handle_closed(f"connect failed: {exc}")
            return
        if hasattr(app, "isConnected") and not app.isConnected():
            self.handle_closed("connect failed: TWS / Gateway not reachable")
            return
        if hasattr(app, "run"):
            threading.Thread(target=app.run, name="twiney-ibapi-reader", daemon=True).start()

    # callbacks from the wrapper ---------------------------------------------
    def handle_ready(self):
        with self._lock:
            if self.app is None:
                return
            self.ready = True
            self.connecting_since = None
            self.backoff = self.cfg["ibkr"]["reconnect_initial_seconds"]
            mdt = self.cfg["ibkr"]["market_data_type"]
            self.app.reqMarketDataType(mdt)
            self.engine.on_connection("CONNECTED", "", self.clock(), market_data_type=mdt)
            self.subscribe_l1()

    def handle_data_lost(self, msg):
        with self._lock:
            t = self.clock()
            self.engine.on_connection("DATA_LOST", f"[1101] {msg}", t)
            self.depth_ids.clear()
            self.l1_ids.clear()
            self._forget_ids()
            if self.app is not None:
                self.subscribe_l1()
            self.engine.on_connection("CONNECTED", "[1101] restored, resubscribed", t)

    def handle_closed(self, reason):
        with self._lock:
            app = self.app
            if app is None:
                return  # already closed (disconnect() re-enters via connectionClosed)
            self.app = None
            self.ready = False
            self.connecting_since = None
            self.depth_ids.clear()
            self.l1_ids.clear()
            now = self.clock()
            self.next_attempt = now + self.backoff
            detail = f"{reason}; retry in {self.backoff:.0f}s"
            self.backoff = min(self.backoff * 2, self.cfg["ibkr"]["reconnect_max_seconds"])
            self.engine.on_connection("DISCONNECTED", detail, now)
        if app is not None:
            try:
                app.disconnect()
            except Exception:
                pass

    def mark_dead(self, req_id):
        self.dead.add(req_id)

    def _forget_ids(self):
        if self.app is not None and hasattr(self.app, "req"):
            self.app.req.clear()

    # subscriptions -----------------------------------------------------------
    def subscribe_l1(self):
        for sym, play in self.plays.items():
            if sym in self.l1_ids:
                continue
            rid = self._rid()
            self.app.req[rid] = ("l1", sym)
            self.l1_ids[sym] = rid
            self.app.reqMktData(rid, self.contract_factory(play), "", False, False, [])

    def reconcile_depth(self):
        """Make IBKR depth + tape subscriptions match the engine's slots."""
        if self.app is None or not self.ready:
            return
        dc = self.cfg["depth"]
        wanted = set(self.engine.slots)
        for sym in [s for s in self.depth_ids if s not in wanted]:
            d_id, t_id = self.depth_ids.pop(sym)
            if d_id not in self.dead:
                self.app.cancelMktDepth(d_id, dc["smart_depth"])
            self.app.cancelTickByTickData(t_id)
            self.app.req.pop(d_id, None)
            self.app.req.pop(t_id, None)
            self.dead.discard(d_id)
        for sym in sorted(wanted - set(self.depth_ids)):
            c = self.contract_factory(self.plays[sym])
            d_id, t_id = self._rid(), self._rid()
            self.app.req[d_id] = ("depth", sym)
            self.app.req[t_id] = ("tape", sym)
            self.depth_ids[sym] = (d_id, t_id)
            self.app.reqMktDepth(d_id, c, dc["rows_requested"], dc["smart_depth"], [])
            self.app.reqTickByTickData(t_id, c, "AllLast", 0, False)
