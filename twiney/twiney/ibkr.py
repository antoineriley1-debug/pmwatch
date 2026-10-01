"""IBKR adapter (TWS API ``ibapi``).

Market data: reqMarketDataType, reqMktData, reqMktDepth, reqTickByTickData,
reqHistoricalData. Account view: reqAllOpenOrders, reqPositions, reqExecutions.
Order entry: placeOrder / cancelOrder — ONLY via ``send_order`` / ``cancel_order``
below, which are only reachable through ``trading.TradingGate`` (paper-only
lock, size caps, armed switch). Nothing else in this package sends orders.

Callback signatures follow TWS API 10.x; ``error`` accepts both the pre-10.35
form (reqId, code, msg[, json]) and the newer one (reqId, errorTime, code, msg[, json]).
"""

import logging
import threading
import time

log = logging.getLogger("twiney.ibkr")

# tickPrice / tickSize types -> engine L1 field (live and delayed variants)
PRICE_TICKS = {1: "bid", 2: "ask", 4: "last", 6: "high", 7: "low", 9: "close", 14: "open",
               66: "bid", 67: "ask", 68: "last", 72: "high", 73: "low", 75: "close", 76: "open"}
SIZE_TICKS = {0: "bid_size", 3: "ask_size", 5: "last_size", 8: "volume",
              69: "bid_size", 70: "ask_size", 71: "last_size", 74: "volume"}

INFO_CODES = {2104, 2106, 2107, 2108, 2119, 2158, 2150, 2174, 2176}
# order-level errors: the order is not working (rejected / cancelled by IBKR)
ORDER_DEAD_CODES = {103, 104, 105, 106, 107, 109, 110, 111, 113, 116, 117, 118, 119, 120, 121, 122, 133, 135, 136,
                    137, 140, 141, 146, 147, 151, 153, 154, 155, 156, 157, 158, 159, 160, 161, 163, 164, 166, 167,
                    168, 200, 201, 202, 203, 10147, 10148, 10149, 10006, 10005, 10268, 10318}
# print conditions that are not a regular last sale (average price, derivatively priced, out of sequence, prior
# reference, next day, cash, contingent...): they never move the last price, bars, the retire check or the reload read
IRREGULAR_PRINT = set("BW4789CGHMNPQRUVZ")


def cancel_arg():
    """cancelOrder's second argument: an OrderCancel object on ibapi 10.2x+, an empty string before."""
    try:
        from ibapi.order_cancel import OrderCancel
        return OrderCancel()
    except ImportError:
        return ""


def ny_midnight(yyyymmdd):
    """'20260929' -> epoch seconds of that day's midnight in New York (daily bars are New York trading days)."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    d = datetime.strptime(str(yyyymmdd)[:8], "%Y%m%d")
    return datetime(d.year, d.month, d.day, tzinfo=ZoneInfo("America/New_York")).timestamp()


def ny_today(t):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime.fromtimestamp(t, ZoneInfo("America/New_York")).strftime("%Y%m%d")


def stock(contract):
    """Only the stock itself: an option / future on the same symbol must never land on the stock's position."""
    sec = getattr(contract, "secType", "STK") or "STK"
    return sec == "STK"


def option(contract):
    return (getattr(contract, "secType", "") or "") == "OPT"


def opt_key(contract):
    """One name for an option contract: 'TSLA 20261003 240C' (symbol, expiry, strike, right)."""
    strike = num(getattr(contract, "strike", 0)) or 0
    return f"{getattr(contract, 'symbol', '?')} {getattr(contract, 'lastTradeDateOrContractMonth', '')} {strike:g}{(getattr(contract, 'right', '') or '')[:1]}"


def opt_fields(contract):
    strike = num(getattr(contract, "strike", 0)) or 0
    mult = num(getattr(contract, "multiplier", 100)) or 100
    return {"symbol": getattr(contract, "symbol", "?"), "expiry": getattr(contract, "lastTradeDateOrContractMonth", ""),
            "strike": strike, "right": (getattr(contract, "right", "") or "")[:1], "mult": mult,
            "local": getattr(contract, "localSymbol", "") or ""}
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
        self.session.handle_ready(int(orderId))

    def managedAccounts(self, accountsList):
        self.session.handle_accounts([a.strip() for a in str(accountsList).split(",") if a.strip()])

    def connectionClosed(self):
        self.session.handle_closed("connection closed by TWS / Gateway")

    def marketDataType(self, reqId, marketDataType):
        kind, sym = self.req.get(reqId, (None, None))
        self.engine.on_market_data_type(marketDataType, self.clock(), sym)

    def error(self, *args):
        req_id, code, msg = parse_error_args(args)
        t = self.clock()
        kind, sym = self.req.get(req_id, (None, None))
        if kind is None and req_id in self.session.my_orders and code < 2000:
            # an order of ours was refused or cancelled by IBKR: say so on the order, never leave it "working"
            info = self.session.my_orders[req_id]
            if info.get("_mod_t") is not None and self.clock() - info["_mod_t"] < 10 and code != 202:
                # IBKR refused a MOVE: the order is still working where it was. Put our record back, say so
                prev = info.pop("_prev", None)
                info.pop("_mod_t", None)
                if prev:
                    info["aux"], info["price"], info["qty"] = prev
                    self.engine.on_order(self.session.perm_ids.get(req_id) or f"id{req_id}", t, order_id=req_id,
                                         lmt=prev[1] if info["type"] in ("LMT", "STP LMT") else None,
                                         aux=prev[0] if info["type"] in ("STP", "STP LMT") else None)
                self.engine.on_error(info["symbol"], code, f"move of order {req_id} refused, it is still working at its old price: {msg}", t, level="error")
                return
            if code in ORDER_DEAD_CODES:
                self.engine.on_order(self.session.perm_ids.get(req_id) or f"id{req_id}", t,
                                     status="Cancelled" if code == 202 else "Inactive", order_id=req_id,
                                     error=f"{code}: {msg}")
            self.engine.on_error(info["symbol"], code, f"order {req_id}: {msg}", t, level="info" if code == 202 else "error")
            return
        if code == 317 and kind == "depth":
            self.engine.on_depth_reset(sym, t, "317")
        elif code in DEPTH_REJECT_CODES and kind == "depth":
            self.session.mark_dead(req_id)
            self.engine.on_depth_rejected(sym, code, msg, t)
        elif code in (1100, 2110):
            # TWS itself lost its link to IBKR (every data farm drops with it): nothing on this side can fix it
            self.engine.on_connection("FEED_DOWN", f"[{code}] TWS lost its link to IBKR's servers — in TWS click the DATA box top right, "
                                                   f"then Reconnect All Farms; if it keeps dropping, your internet is dropping. {msg}", t)
        elif code == 1101:
            self.session.handle_data_lost(msg)
        elif code == 1102:
            self.engine.on_connection("CONNECTED", "[1102] restored, data maintained", t)
        elif code in (502, 504, 326):
            self.session.handle_closed(f"[{code}] {msg}")
        elif code in INFO_CODES:
            self.engine.on_error(sym, code, msg, t, level="info")
            if code in (2104, 2106, 2158) and self.engine.connection["state"] == "FEED_DOWN":
                # a data farm is back: TWS has its link again. Reconnect All Farms sends these, not a 1102, so
                # the light would otherwise stay FEED DOWN with data flowing
                self.engine.on_connection("CONNECTED", f"[{code}] a data farm is back: {msg}", t)
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
        if field is not None and kind == "opt":
            v = num(price)
            self.engine.on_opt_quote(sym, field, None if v is None or v <= 0 else v, self.clock())
            return
        if field is None or kind != "l1":
            return
        if self.engine.connection["state"] in ("FEED_DOWN", "DATA_LOST") and num(price) not in (None, -1):
            self.engine.on_connection("CONNECTED", "a live tick arrived: the feed is back", self.clock())   # data speaks louder than any message
        v = num(price)
        if v is not None and v == -1 and field in ("bid", "ask"):
            self.engine.on_l1(sym, field, None, self.clock())   # -1 = no bid / no offer (halt): clear it
            return
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

    # account view (read-only) ------------------------------------------------
    def openOrder(self, orderId, contract, order, orderState):
        if not stock(contract) and not option(contract):
            return
        client = getattr(order, "clientId", None)
        mine = self.session.is_mine(orderId, client)
        key = self.session.order_key(orderId, getattr(order, "permId", 0), mine)
        self.session.order_seen(key)
        if mine and int(orderId) in self.session.my_orders:
            info = self.session.my_orders[int(orderId)]
            info["qty"] = num(getattr(order, "totalQuantity", None)) or info["qty"]   # IBKR's current size (OCA reduce)
        self.engine.on_order(
            key, self.clock(), symbol=opt_key(contract) if option(contract) else getattr(contract, "symbol", "?"), action=getattr(order, "action", None),
            qty=num(getattr(order, "totalQuantity", None)), type=getattr(order, "orderType", None),
            lmt=num(getattr(order, "lmtPrice", None)) or None, aux=num(getattr(order, "auxPrice", None)) or None,
            tif=getattr(order, "tif", None), status=getattr(orderState, "status", None),
            order_id=int(orderId) if mine else None, mine=mine,
            role=self.session.order_roles.get(int(orderId)) if mine else "manual")

    def orderStatus(self, orderId, status, filled, remaining, avgFillPrice, permId, *rest):
        client = rest[2] if len(rest) > 2 else None     # rest = parentId, lastFillPrice, clientId, whyHeld, ...
        mine = self.session.is_mine(orderId, client)
        key = self.session.order_key(orderId, permId, mine)
        self.engine.on_order(key, self.clock(), status=status, filled=num(filled),
                             remaining=num(remaining), avg_fill=num(avgFillPrice) or None,
                             order_id=int(orderId) if mine else None)

    def openOrderEnd(self):
        self.session.orders_refreshed()

    def position(self, account, contract, position, avgCost):
        if option(contract):
            key = opt_key(contract)
            self.session.opt_contract(key, contract)
            self.engine.on_opt_position(account, key, opt_fields(contract), num(position) or 0.0,
                                        num(avgCost) or 0.0, self.clock())
            if num(position):
                self.session.subscribe_opt(key)
            return
        if not stock(contract):
            return
        self.engine.on_position(account, getattr(contract, "symbol", "?"), num(position) or 0.0,
                                num(avgCost) or 0.0, self.clock())

    def positionEnd(self):
        pass

    def execDetails(self, reqId, contract, execution):
        if option(contract):
            self.engine.on_opt_fill(getattr(execution, "execId", ""), opt_key(contract), getattr(execution, "side", ""),
                                    num(getattr(execution, "shares", 0)) or 0.0, num(getattr(execution, "price", 0)) or 0.0,
                                    self.clock())
            return
        if not stock(contract):
            return
        self.engine.on_fill(getattr(execution, "execId", ""), getattr(contract, "symbol", "?"),
                            getattr(execution, "side", ""), num(getattr(execution, "shares", 0)) or 0.0,
                            num(getattr(execution, "price", 0)) or 0.0, getattr(execution, "time", ""),
                            self.clock())

    def execDetailsEnd(self, reqId):
        pass

    def commissionReport(self, report):
        self.engine.on_commission(getattr(report, "execId", ""), num(getattr(report, "commission", None)))

    def commissionAndFeesReport(self, report):   # ibapi 10.3x+ name
        self.engine.on_commission(getattr(report, "execId", ""), num(getattr(report, "commissionAndFees", None)))

    # chart history ----------------------------------------------------------
    def historicalData(self, reqId, bar):
        kind, sym = self.req.get(reqId, (None, None))
        if kind == "daily":
            d = str(bar.date).strip()
            try:
                # daily bars come back as "yyyymmdd" (a New York trading day) even with formatDate=2
                t0 = ny_midnight(d) if len(d) >= 8 and d[:8].isdigit() else float(d)
            except (TypeError, ValueError):
                return
            if d[:8] == ny_today(self.clock()):
                return   # today's bar is still forming: the chart builds it live from the minute bars, ATR skips it
            self.engine.on_daily_bar(sym, t0, num(bar.open), num(bar.high), num(bar.low), num(bar.close), num(getattr(bar, "volume", None)))
            return
        if kind != "hist":
            return
        try:
            t0 = float(bar.date)  # formatDate=2 -> epoch seconds
        except (TypeError, ValueError):
            return
        o, h, l, c = num(bar.open), num(bar.high), num(bar.low), num(bar.close)
        if None in (o, h, l, c):
            return
        self.engine.on_hist_bar(sym, t0, o, h, l, c, num(bar.volume))

    def historicalDataEnd(self, reqId, start, end):
        self.req.pop(reqId, None)

    # tape -----------------------------------------------------------------
    def tickByTickAllLast(self, reqId, tickType, time_, price, size, tickAttribLast, exchange, specialConditions):
        kind, sym = self.req.get(reqId, (None, None))
        if kind != "tape":
            return
        if getattr(tickAttribLast, "unreported", False):
            return
        conds = specialConditions or ""
        if IRREGULAR_PRINT.intersection(conds.replace(" ", "")):
            return        # not a regular last sale: it never traded at the market you see
        self.engine.on_print(sym, num(price), num(size), exchange or "", self.clock(), conds)


def execution_filter():
    try:
        from ibapi.execution import ExecutionFilter
        return ExecutionFilter()
    except ImportError:  # tests run without ibapi
        return None


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


def make_order(action, qty, order_type, price, tif="DAY", parent_id=None, transmit=True, aux=None, oca=None):
    from ibapi.order import Order
    o = Order()
    o.action = action
    o.totalQuantity = qty
    o.orderType = order_type
    if order_type == "LMT":
        o.lmtPrice = price
    elif order_type == "STP":
        o.auxPrice = price
    elif order_type == "STP LMT":
        o.auxPrice = aux      # the stop trigger
        o.lmtPrice = price    # the limit once triggered (never a naked stop)
    if oca:
        o.ocaGroup = oca
        o.ocaType = 2         # reduce: a fill of one exit of the pair (target / its stop) reduces the other by the same shares
    o.tif = tif
    o.transmit = transmit
    if parent_id is not None:
        o.parentId = parent_id
    # IBKR 10.x rejects orders that still carry the legacy defaults for these
    for attr in ("eTradeOnly", "firmQuoteOnly"):
        if hasattr(o, attr):
            setattr(o, attr, False)
    return o


def ibapi_app_factory():
    """Return a factory building the real TWS API client."""
    from ibapi.client import EClient
    from ibapi.wrapper import EWrapper

    class TwineyApp(TwineyWrapper, EWrapper, EClient):
        def __init__(self, engine, session):
            EWrapper.__init__(self)
            EClient.__init__(self, wrapper=self)
            TwineyWrapper.__init__(self, engine, session)

    return TwineyApp


class MarketDataSession:
    """Owns the connection, reconnect backoff and all subscriptions."""

    def __init__(self, engine, cfg, plays, app_factory, contract_factory=make_contract, clock=time.time,
                 order_factory=make_order, gate=None):
        self.engine = engine
        self.order_factory = order_factory
        self.gate = gate
        self.next_order_id = None
        self.order_roles = {}   # orderId -> entry / stop / target
        self.perm_ids = {}      # orderId -> permId (stable key once TWS assigns it)
        self.my_orders = {}     # orderId -> (symbol, parent orderId)
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
        self._next_id = 90000000   # data request ids live far above order ids, so an error is never misread
        self.l1_ids = {}      # symbol -> reqId
        self.opt_contracts = {}   # option key -> the IBKR contract it came in as (positions): orders go out on it
        self.opt_ids = {}         # option key -> quote reqId
        self.depth_ids = {}   # symbol -> (depth reqId, tape reqId)
        self.dead = set()
        self._orders_seen = set()
        self._next_orders = 0.0
        self._next_fills = 0.0
        self.accounts = []
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
                self.refresh_account(now)
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
    def handle_accounts(self, accounts):
        with self._lock:
            self.accounts = accounts
            if self.gate is not None:
                self.gate.set_accounts(accounts)
            self.engine._message("info", f"account{'s' if len(accounts) != 1 else ''}: {', '.join(accounts)}"
                                 + ("  (PAPER)" if accounts and all(a.upper().startswith("DU") for a in accounts)
                                    else "  (LIVE)" if accounts else ""), self.clock())

    def handle_ready(self, order_id=None):
        with self._lock:
            if self.app is None:
                return
            if order_id is not None:
                self.next_order_id = max(order_id, self.next_order_id or 0)
            if self.ready:
                return  # a later nextValidId only refreshes the order id
            self.ready = True
            self.connecting_since = None
            self.backoff = self.cfg["ibkr"]["reconnect_initial_seconds"]
            mdt = self.cfg["ibkr"]["market_data_type"]
            self.app.reqMarketDataType(mdt)
            self.engine.on_connection("CONNECTED", "", self.clock(), market_data_type=mdt)
            self.subscribe_l1()
            if self.cfg["account"]["show"] or self.cfg["trading"]["enabled"]:
                self.engine.clear_positions()   # IBKR re-sends every open position right after this
                self.app.reqPositions()  # streams position updates
            self._next_orders = self._next_fills = 0.0

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
            if self.gate is not None:     # nothing trades until IBKR says again which account this is
                self.gate.arm(False)
                self.gate.set_accounts([])
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

    # order entry (only reachable through trading.TradingGate) -----------------
    def is_mine(self, order_id, client_id=None):
        """Orders this desk placed: same API client id and a real order id. Orders typed in TWS (order id 0) or
        placed by another API client are shown, never cancelled or modified from here."""
        order_id = int(order_id)
        if order_id <= 0:
            return False
        if client_id is not None:
            try:
                return int(client_id) == int(self.cfg["ibkr"]["client_id"])
            except (TypeError, ValueError):
                return False
        return order_id in self.my_orders

    def order_key(self, order_id, perm_id, mine=True):
        """permId is IBKR's unique id for an order; the order id is only unique per client."""
        order_id = int(order_id)
        if perm_id:
            if mine and order_id > 0 and order_id not in self.perm_ids:
                self.perm_ids[order_id] = perm_id
                self.engine.rename_order(f"id{order_id}", perm_id)
            return perm_id
        return (self.perm_ids.get(order_id) or f"id{order_id}") if mine else f"x{order_id}"

    def send_order(self, symbol, action, qty, price, order_type, parent, role, tif, now, aux=None, oca=None,
                   transmit=True, reducing=False):
        with self._lock:
            if self.app is None or not self.ready or self.next_order_id is None:
                raise RuntimeError("not connected to TWS")
            if self.gate is None or not (self.gate.can_trade() or (reducing and self.gate.can_reduce())):
                raise RuntimeError("trading gate closed")
            oid = self.next_order_id
            self.next_order_id += 1
            play = self.plays[symbol]
            # a bracket goes out as one family: the entry and every leg but the last are sent with transmit=False,
            # so TWS holds them and releases the whole family when the last leg arrives
            extra = {}
            if order_type == "STP LMT":
                extra["aux"] = aux
            if oca:
                extra["oca"] = f"twiney{parent}-{oca}"
            order = self.order_factory(action, qty, order_type, price, tif, parent, transmit=transmit, **extra)
            self.order_roles[oid] = role
            self.my_orders[oid] = {"symbol": symbol, "parent": parent, "action": action, "qty": qty,
                                   "type": order_type, "tif": tif, "aux": aux, "price": price,
                                   "oca": extra.get("oca")}
            self.app.placeOrder(oid, self.contract_factory(play), order)
            self.engine.on_order(f"id{oid}", now, symbol=symbol, action=action, qty=float(qty), remaining=float(qty),
                                 type=order_type, lmt=price if order_type in ("LMT", "STP LMT") else None,
                                 aux=price if order_type == "STP" else aux, tif=tif, status="PendingSubmit",
                                 order_id=oid, role=role, mine=True, parent=parent)
            self._orders_seen.add(f"id{oid}")
            self._next_orders = now + 1.0  # refresh the open-order list soon
            return oid

    def modify_order(self, oid, price, now, remaining=None):
        """IBKR modifies an order by re-sending placeOrder with the same id. It keeps the order's OCA group and
        sends its CURRENT size (filled so far + what is left), never the size it was first sent with.
        ``price`` None keeps the price (a resize); ``remaining`` None keeps the size."""
        with self._lock:
            info = self.my_orders.get(int(oid))
            if self.app is None or not self.ready or info is None:
                return False
            if self.gate is None or not (self.gate.can_trade() or self.gate.can_reduce()):
                raise RuntimeError("trading gate closed")
            live = self._live_order(int(oid))
            filled = float(live.get("filled") or 0) if live else 0.0
            left = live.get("remaining") if live else None
            if remaining is not None:
                left = remaining
            qty = filled + float(left) if left is not None else float(info["qty"])
            if qty <= filled:
                self.app.cancelOrder(int(oid), cancel_arg())
                return True
            extra = {"oca": info.get("oca")} if info.get("oca") else {}
            info["_prev"], info["_mod_t"] = (info.get("aux"), info["price"], info["qty"]), now
            if info["type"] == "STP LMT":
                if price is None:
                    price = info["aux"]
                # moving a stop-limit moves both the trigger and the limit by the same amount
                shift = price - (info.get("aux") or price)
                lmt = round(info["price"] + shift, 4)
                order = self.order_factory(info["action"], qty, info["type"], lmt, info["tif"],
                                           info["parent"], transmit=True, aux=price, **extra)
                info["aux"], info["price"] = price, lmt
            else:
                if price is None:
                    price = info["price"]
                order = self.order_factory(info["action"], qty, info["type"], price, info["tif"],
                                           info["parent"], transmit=True, **extra)
                info["price"] = price
            info["qty"] = qty
            contract = self.opt_contracts.get(info["symbol"]) if info.get("opt") else self.contract_factory(self.plays[info["symbol"]])
            self.app.placeOrder(int(oid), contract, order)
            key = self.perm_ids.get(int(oid)) or f"id{oid}"
            self.engine.on_order(key, now, lmt=info["price"] if info["type"] in ("LMT", "STP LMT") else None,
                                 aux=info.get("aux") if info["type"] in ("STP", "STP LMT") else None,
                                 qty=qty, remaining=qty - filled)
            self._next_orders = now + 1.0
            return True

    def _live_order(self, oid):
        with self.engine.lock:
            for o in self.engine.orders.values():
                if o.get("order_id") == oid:
                    return dict(o)
        return None

    def cancel_order(self, oid, now):
        with self._lock:
            if self.app is None or not self.ready or int(oid) not in self.my_orders and int(oid) <= 0:
                return False
            self.app.cancelOrder(int(oid), cancel_arg())
            self._next_orders = now + 1.0
            return True

    def cancel_all(self, now, symbol=None):
        """Cancel this desk's working orders (never an order typed in TWS or placed by another program)."""
        with self._lock:
            if self.app is None or not self.ready:
                return 0
            with self.engine.lock:
                mine = [o.get("order_id") for o in self.engine._pending(symbol) if o.get("mine") and o.get("order_id")]
            for oid in mine:
                self.app.cancelOrder(int(oid), cancel_arg())
            self._next_orders = now + 1.0
            return len(mine)

    def refresh_account(self, now):
        """Poll open orders and today's fills for the display (read-only requests)."""
        if not (self.cfg["account"]["show"] or self.cfg["trading"]["enabled"]) or self.app is None:
            return
        if now >= self._next_orders:
            self._next_orders = now + self.cfg["account"]["orders_refresh_seconds"]
            self._orders_seen = set()
            self.app.reqAllOpenOrders()
        if now >= self._next_fills:
            self._next_fills = now + self.cfg["account"]["fills_refresh_seconds"]
            self.app.reqExecutions(self._rid(), execution_filter())

    def order_seen(self, key):
        self._orders_seen.add(key)

    def orders_refreshed(self):
        self.engine.on_orders_snapshot_end(set(self._orders_seen), self.clock())

    def mark_dead(self, req_id):
        self.dead.add(req_id)

    def _forget_ids(self):
        if self.app is not None and hasattr(self.app, "req"):
            self.app.req.clear()

    # subscriptions -----------------------------------------------------------
    def add_play(self, play):
        with self._lock:
            self.plays[play["symbol"]] = play
            if self.app is not None and self.ready:
                self.subscribe_l1()

    def remove_play(self, symbol):
        """The ticker left the desk: its quotes go, its depth is released by the engine's slot command."""
        with self._lock:
            self.plays.pop(symbol, None)
            rid = self.l1_ids.pop(symbol, None)
            if rid is not None and self.app is not None:
                try:
                    self.app.cancelMktData(rid)
                except Exception:
                    pass
                self.app.req.pop(rid, None)

    def opt_contract(self, key, contract):
        with self._lock:
            self.opt_contracts[key] = contract

    def subscribe_opt(self, key):
        """Quotes for an option contract you hold (bid / ask / last), so it can be scaled at the touch."""
        with self._lock:
            if self.app is None or not self.ready or key in self.opt_ids or key not in self.opt_contracts:
                return
            rid = self._rid()
            self.app.req[rid] = ("opt", key)
            self.opt_ids[key] = rid
            try:
                self.app.reqMktData(rid, self.opt_contracts[key], "", False, False, [])
            except Exception as exc:
                log.warning("option quote request failed for %s: %s", key, exc)

    def send_option_order(self, key, action, qty, price, now, reducing=False, role="option"):
        """A LIMIT DAY order on an option contract you hold (scale in / out, close). Same gate as a stock order:
        reducing (taking the position down) is never blocked; adding goes through the caps, in real dollars."""
        with self._lock:
            if self.app is None or not self.ready or self.next_order_id is None:
                raise RuntimeError("not connected to TWS")
            contract = self.opt_contracts.get(key)
            if contract is None:
                raise RuntimeError(f"no contract on file for {key}")
            if self.gate is None or not (self.gate.can_trade() or (reducing and self.gate.can_reduce())):
                raise RuntimeError("trading gate closed")
            oid = self.next_order_id
            self.next_order_id += 1
            order = self.order_factory(action, qty, "LMT", price, "DAY", None, transmit=True)
            self.order_roles[oid] = role
            self.my_orders[oid] = {"symbol": key, "parent": None, "action": action, "qty": qty, "type": "LMT",
                                   "tif": "DAY", "aux": None, "price": price, "oca": None, "opt": True}
            self.app.placeOrder(oid, contract, order)
            self.engine.on_order(f"id{oid}", now, symbol=key, action=action, qty=float(qty), remaining=float(qty),
                                 type="LMT", lmt=price, aux=None, tif="DAY", status="PendingSubmit",
                                 order_id=oid, role=role, mine=True, parent=None, opt=True)
            self._orders_seen.add(f"id{oid}")
            self._next_orders = now + 1.0
            return oid

    def subscribe_l1(self):
        for sym, play in self.plays.items():
            if sym in self.l1_ids:
                continue
            rid = self._rid()
            self.app.req[rid] = ("l1", sym)
            self.l1_ids[sym] = rid
            self.app.reqMktData(rid, self.contract_factory(play), "", False, False, [])
            if self.cfg["chart"]["history"]:
                hid = self._rid()
                self.app.req[hid] = ("hist", sym)
                self.app.reqHistoricalData(hid, self.contract_factory(play), "", "5 D", "1 min", "TRADES",
                                           1 if self.cfg["chart"]["regular_hours_only"] else 0, 2, False, [])
                did = self._rid()
                self.app.req[did] = ("daily", sym)
                self.app.reqHistoricalData(did, self.contract_factory(play), "", "1 Y", "1 day", "TRADES",
                                           1, 2, False, [])

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
