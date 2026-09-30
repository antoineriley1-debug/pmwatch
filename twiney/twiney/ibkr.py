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

INFO_CODES = {2104, 2106, 2107, 2108, 2119, 2158, 2150, 10167, 162, 2174, 2176}
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

    # account view (read-only) ------------------------------------------------
    def openOrder(self, orderId, contract, order, orderState):
        key = self.session.order_key(orderId, getattr(order, "permId", 0))
        self.session.order_seen(key)
        self.engine.on_order(
            key, self.clock(), symbol=getattr(contract, "symbol", "?"), action=getattr(order, "action", None),
            qty=num(getattr(order, "totalQuantity", None)), type=getattr(order, "orderType", None),
            lmt=num(getattr(order, "lmtPrice", None)) or None, aux=num(getattr(order, "auxPrice", None)) or None,
            tif=getattr(order, "tif", None), status=getattr(orderState, "status", None),
            order_id=int(orderId), role=self.session.order_roles.get(int(orderId)))

    def orderStatus(self, orderId, status, filled, remaining, avgFillPrice, permId, *rest):
        key = self.session.order_key(orderId, permId)
        self.engine.on_order(key, self.clock(), status=status, filled=num(filled),
                             remaining=num(remaining), avg_fill=num(avgFillPrice) or None, order_id=int(orderId))

    def openOrderEnd(self):
        self.session.orders_refreshed()

    def position(self, account, contract, position, avgCost):
        self.engine.on_position(account, getattr(contract, "symbol", "?"), num(position) or 0.0,
                                num(avgCost) or 0.0, self.clock())

    def positionEnd(self):
        pass

    def execDetails(self, reqId, contract, execution):
        self.engine.on_fill(getattr(execution, "execId", ""), getattr(contract, "symbol", "?"),
                            getattr(execution, "side", ""), num(getattr(execution, "shares", 0)) or 0.0,
                            num(getattr(execution, "price", 0)) or 0.0, getattr(execution, "time", ""),
                            self.clock())

    def execDetailsEnd(self, reqId):
        pass

    # chart history ----------------------------------------------------------
    def historicalData(self, reqId, bar):
        kind, sym = self.req.get(reqId, (None, None))
        if kind == "daily":
            try:
                t0 = float(bar.date)
            except (TypeError, ValueError):
                try:
                    t0 = time.mktime(time.strptime(str(bar.date)[:8], "%Y%m%d"))
                except ValueError:
                    return
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
        self.engine.on_print(sym, num(price), num(size), exchange or "", self.clock(), specialConditions or "")


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
        o.ocaType = 2         # a cash-flow fill reduces the other exits instead of cancelling them
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
        self._next_id = 1000
        self.l1_ids = {}      # symbol -> reqId
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
            if self.cfg["account"]["show"]:
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
    def order_key(self, order_id, perm_id):
        order_id = int(order_id)
        if perm_id and order_id not in self.perm_ids:
            self.perm_ids[order_id] = perm_id
            self.engine.rename_order(f"id{order_id}", perm_id)
        return self.perm_ids.get(order_id) or f"id{order_id}"

    def send_order(self, symbol, action, qty, price, order_type, parent, role, tif, now, aux=None):
        with self._lock:
            if self.app is None or not self.ready or self.next_order_id is None:
                raise RuntimeError("not connected to TWS")
            if self.gate is None or not self.gate.can_trade():
                raise RuntimeError("trading gate closed")
            oid = self.next_order_id
            self.next_order_id += 1
            play = self.plays[symbol]
            # bracket legs are sent with transmit=False on the parent so TWS holds
            # the family until the last leg arrives; a lone entry transmits at once
            extra = {}
            if order_type == "STP LMT":
                extra["aux"] = aux
            if parent is not None:
                extra["oca"] = f"twiney{parent}"
            order = self.order_factory(action, qty, order_type, price, tif, parent, transmit=True, **extra) \
                if extra else self.order_factory(action, qty, order_type, price, tif, parent, transmit=True)
            self.order_roles[oid] = role
            self.my_orders[oid] = {"symbol": symbol, "parent": parent, "action": action, "qty": qty,
                                   "type": order_type, "tif": tif, "aux": aux, "price": price}
            self.app.placeOrder(oid, self.contract_factory(play), order)
            self.engine.on_order(f"id{oid}", now, symbol=symbol, action=action, qty=float(qty), remaining=float(qty),
                                 type=order_type, lmt=price if order_type in ("LMT", "STP LMT") else None,
                                 aux=price if order_type == "STP" else aux, tif=tif, status="PendingSubmit",
                                 order_id=oid, role=role)
            self._orders_seen.add(f"id{oid}")
            self._next_orders = now + 1.0  # refresh the open-order list soon
            return oid

    def modify_order(self, oid, price, now):
        """IBKR modifies an order by re-sending placeOrder with the same id and new price."""
        with self._lock:
            info = self.my_orders.get(int(oid))
            if self.app is None or not self.ready or info is None:
                return False
            if self.gate is None or not self.gate.can_trade():
                raise RuntimeError("trading gate closed")
            if info["type"] == "STP LMT":
                # moving a stop-limit moves both the trigger and the limit by the same amount
                shift = price - (info.get("aux") or price)
                lmt = round(info["price"] + shift, 4)
                order = self.order_factory(info["action"], info["qty"], info["type"], lmt, info["tif"],
                                           info["parent"], transmit=True, aux=price)
                info["aux"] = price
            else:
                order = self.order_factory(info["action"], info["qty"], info["type"], price, info["tif"],
                                           info["parent"], transmit=True)
            self.app.placeOrder(int(oid), self.contract_factory(self.plays[info["symbol"]]), order)
            key = self.perm_ids.get(int(oid)) or f"id{oid}"
            self.engine.on_order(key, now, lmt=price if info["type"] == "LMT" else None,
                                 aux=price if info["type"] in ("STP", "STP LMT") else None)
            self._next_orders = now + 1.0
            return True

    def cancel_order(self, oid, now):
        with self._lock:
            if self.app is None or not self.ready:
                return False
            self.app.cancelOrder(int(oid), "")
            self._next_orders = now + 1.0
            return True

    def cancel_all(self, now, symbol=None):
        with self._lock:
            if self.app is None or not self.ready:
                return 0
            n = 0
            for o in self.engine._pending(symbol):
                oid = o.get("order_id")
                if oid is not None:
                    self.app.cancelOrder(int(oid), "")
                    n += 1
            self._next_orders = now + 1.0
            return n

    def refresh_account(self, now):
        """Poll open orders and today's fills for the display (read-only requests)."""
        if not self.cfg["account"]["show"] or self.app is None:
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
