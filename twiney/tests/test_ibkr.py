import decimal
import unittest

from helpers import ASK, INSERT, cfg, plays
from twiney.engine import Engine
from twiney.ibkr import MarketDataSession, TwineyWrapper, num, parse_error_args
from twiney.trading import IbkrBroker, Trader, TradingGate


class FakeClient:
    """Stands in for ibapi.client.EClient; records every request."""

    def __init__(self):
        self.calls = []
        self.connected = False

    def connect(self, host, port, client_id):
        self.calls.append(("connect", host, port, client_id))
        self.connected = True

    def isConnected(self):
        return self.connected

    def disconnect(self):
        self.calls.append(("disconnect",))
        was = self.connected
        self.connected = False
        if was:
            self.connectionClosed()  # EClient.disconnect() does this too

    def __getattr__(self, name):
        if name.startswith(("req", "cancel", "place")):
            return lambda *a: self.calls.append((name,) + a)
        raise AttributeError(name)


class FakeApp(TwineyWrapper, FakeClient):
    def __init__(self, engine, session):
        FakeClient.__init__(self)
        TwineyWrapper.__init__(self, engine, session, clock=lambda: session.clock())


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def fake_order(action, qty, order_type, price, tif="DAY", parent_id=None, transmit=True, aux=None, oca=None):
    return {"action": action, "qty": qty, "type": order_type, "price": price, "tif": tif,
            "parent": parent_id, "transmit": transmit, "aux": aux, "oca": oca}


def make_session(**trading):
    trading.setdefault("sim_options_after_hours", False)     # the test clock sits after hours: real quotes unless a test asks
    c = cfg(trading=trading)
    engine = Engine(plays(), c)
    clock = Clock()
    gate = TradingGate(c)
    s = MarketDataSession(engine, c, plays(), FakeApp, contract_factory=lambda p: p["symbol"], clock=clock,
                          order_factory=fake_order, gate=gate)
    engine.trader = Trader(engine, c, IbkrBroker(engine, s), gate)
    return s, engine, clock


def names(app):
    return [c[0] for c in app.calls]


class ParsingTests(unittest.TestCase):
    def test_error_signatures(self):
        self.assertEqual(parse_error_args((5, 317, "reset")), (5, 317, "reset"))
        self.assertEqual(parse_error_args((5, 317, "reset", "")), (5, 317, "reset"))
        self.assertEqual(parse_error_args((5, 1712345678, 317, "reset", "")), (5, 317, "reset"))
        self.assertEqual(parse_error_args((-1, 2104, "farm ok")), (-1, 2104, "farm ok"))

    def test_num_handles_decimal_and_unset(self):
        self.assertEqual(num(decimal.Decimal("300")), 300.0)
        self.assertIsNone(num(decimal.Decimal(2 ** 127 - 1)))
        self.assertIsNone(num(1.7976931348623157e308))
        self.assertIsNone(num("x"))


class SessionTests(unittest.TestCase):
    def connect(self):
        s, engine, clock = make_session()
        s.step(clock())
        app = s.app
        self.assertEqual(app.calls[0], ("connect", "127.0.0.1", 7497, 61))
        app.nextValidId(1)
        return s, engine, clock, app

    def test_ready_subscribes_l1_for_every_active_play(self):
        s, engine, clock, app = self.connect()
        self.assertEqual(engine.connection["state"], "CONNECTED")
        self.assertIn(("reqMarketDataType", 1), app.calls)
        self.assertEqual(names(app).count("reqMktData"), 4)
        self.assertEqual(names(app).count("reqHistoricalData"), 8)  # 1-minute + daily per play

    def test_orders_positions_fills_are_shown_read_only(self):
        s, engine, clock, app = self.connect()
        self.assertIn("reqPositions", names(app))
        s.step(clock())
        self.assertIn("reqAllOpenOrders", names(app))
        self.assertIn("reqExecutions", names(app))
        O = lambda **k: type("O", (), k)()
        app.openOrder(7, O(symbol="AAA"), O(permId=555, action="BUY", totalQuantity=decimal.Decimal("200"),
                      orderType="LMT", lmtPrice=9.9, auxPrice=0.0, tif="DAY"), O(status="Submitted"))
        app.orderStatus(7, "Submitted", decimal.Decimal("0"), decimal.Decimal("200"), 0.0, 555, 0, 0.0, 1, "", 0.0)
        app.openOrderEnd()
        app.position("DU1", O(symbol="AAA"), decimal.Decimal("100"), 9.80)
        app.execDetails(1, O(symbol="AAA"), O(execId="e1", side="BOT", shares=decimal.Decimal("100"),
                                               price=9.80, time="20260926 09:45:00"))
        app.tickPrice(s.l1_ids["AAA"], 4, 10.0, None)
        acct = engine.snapshot(clock())["account"]
        self.assertEqual(acct["pending"][0]["action"], "BUY")
        self.assertEqual(acct["pending"][0]["lmt"], 9.9)
        self.assertEqual(acct["positions"][0]["qty"], 100)
        self.assertEqual(acct["fills"][0]["side"], "BOT")
        # the order disappears from "pending" once a refresh no longer lists it
        clock.t += 5
        s.step(clock())
        app.openOrderEnd()
        self.assertEqual(engine.snapshot(clock())["account"]["pending"], [])

    def test_history_bars_feed_the_chart(self):
        s, engine, clock, app = self.connect()
        hid = [c[1] for c in app.calls if c[0] == "reqHistoricalData" and c[2] == "AAA"][0]
        bar = type("Bar", (), {"date": "1712345640", "open": 10.0, "high": 10.1, "low": 9.9,
                               "close": 10.05, "volume": decimal.Decimal("12000")})()
        app.historicalData(hid, bar)
        app.historicalDataEnd(hid, "", "")
        self.assertEqual(engine.syms["AAA"].bar_list()[0][1:6], [10.0, 10.1, 9.9, 10.05, 12000.0])
        self.assertNotIn(hid, app.req)

    def test_l1_depth_and_tape_callbacks_reach_engine(self):
        s, engine, clock, app = self.connect()
        rid = s.l1_ids["AAA"]
        app.tickPrice(rid, 4, 10.0, None)
        app.tickPrice(rid, 1, -1.0, None)          # "no data" price ignored
        app.tickSize(rid, 0, decimal.Decimal("500"))
        self.assertEqual(engine.syms["AAA"].l1["last"], 10.0)
        self.assertIsNone(engine.syms["AAA"].l1["bid"])
        self.assertEqual(engine.syms["AAA"].l1["bid_size"], 500.0)
        for sym, px in (("BBB", 55.0), ("CCC", 21.0), ("DDD", 5.5)):
            app.tickPrice(s.l1_ids[sym], 4, px, None)
        s.step(clock())
        self.assertEqual(names(app).count("reqMktDepth"), 3)
        self.assertEqual(names(app).count("reqTickByTickData"), 3)
        d_id, t_id = s.depth_ids["AAA"]
        req = [c for c in app.calls if c[0] == "reqMktDepth" and c[1] == d_id][0]
        self.assertEqual(req[3:5], (10, True))  # rows requested, smart depth
        tbt = [c for c in app.calls if c[0] == "reqTickByTickData" and c[1] == t_id][0]
        self.assertEqual(tbt[3], "AllLast")
        app.updateMktDepthL2(d_id, 0, "NSDQ", INSERT, ASK, 10.0, decimal.Decimal("800"), True)
        self.assertEqual(engine.syms["AAA"].book.size_at(ASK, 10.0), 800)
        app.tickByTickAllLast(t_id, 1, 1712345678, 10.0, decimal.Decimal("100"), None, "ARCA", "")
        self.assertEqual(engine.syms["AAA"].tape.last()["size"], 100)

    def test_rotation_cancels_old_depth_and_tape(self):
        s, engine, clock, app = self.connect()
        for sym, px in (("AAA", 10.0), ("BBB", 50.0), ("CCC", 20.0), ("DDD", 5.5)):
            app.tickPrice(s.l1_ids[sym], 4, px, None)
        s.step(clock())
        old = s.depth_ids["DDD"] if "DDD" in s.depth_ids else None
        self.assertIsNone(old)
        clock.t += 60
        app.tickPrice(s.l1_ids["DDD"], 4, 5.0, None)
        app.tickPrice(s.l1_ids["CCC"], 4, 24.0, None)
        s.step(clock())
        self.assertIn("DDD", s.depth_ids)
        self.assertNotIn("CCC", s.depth_ids)
        self.assertIn("cancelMktDepth", names(app))
        self.assertIn("cancelTickByTickData", names(app))

    def test_error_317_resets_book(self):
        s, engine, clock, app = self.connect()
        app.tickPrice(s.l1_ids["AAA"], 4, 10.0, None)
        s.step(clock())
        d_id, _ = s.depth_ids["AAA"]
        app.updateMktDepthL2(d_id, 0, "", INSERT, ASK, 10.0, 800, True)
        app.error(d_id, 317, "Market depth data has been RESET", "")
        self.assertEqual(engine.syms["AAA"].book.levels(ASK), [])
        self.assertEqual(engine.syms["AAA"].resets, 1)

    def test_error_309_releases_slot_without_cancelling_dead_request(self):
        s, engine, clock, app = self.connect()
        app.tickPrice(s.l1_ids["AAA"], 4, 10.0, None)
        s.step(clock())
        d_id, t_id = s.depth_ids["AAA"]
        app.error(d_id, clock(), 309, "Max number (3) of market depth requests has been reached", "")
        s.step(clock())
        self.assertNotIn("AAA", s.depth_ids)
        self.assertNotIn(("cancelMktDepth", d_id, True), app.calls)
        self.assertIn(("cancelTickByTickData", t_id), app.calls)

    def test_1101_resubscribes_everything(self):
        s, engine, clock, app = self.connect()
        app.tickPrice(s.l1_ids["AAA"], 4, 10.0, None)
        s.step(clock())
        before = names(app).count("reqMktData")
        app.error(-1, 1101, "Connectivity restored - data lost")
        self.assertEqual(names(app).count("reqMktData"), before + 4)
        self.assertEqual(engine.slots, {})
        self.assertEqual(engine.connection["state"], "CONNECTED")
        s.step(clock())
        self.assertIn("AAA", s.depth_ids)

    def test_1100_pauses_rotation_until_data_is_back(self):
        s, engine, clock, app = self.connect()
        app.error(-1, 1100, "Connectivity between IB and TWS has been lost")
        self.assertEqual(engine.connection["state"], "FEED_DOWN")
        s.step(clock())
        self.assertEqual(s.depth_ids, {})                       # nothing is requested while the feed is down
        app.tickPrice(s.l1_ids["AAA"], 4, 10.0, None)           # a real tick: the feed is back, rotation resumes
        self.assertEqual(engine.connection["state"], "CONNECTED")
        s.step(clock())
        self.assertNotEqual(s.depth_ids, {})

    def test_reconnect_all_farms_clears_feed_down_without_a_1102(self):
        s, engine, clock, app = self.connect()
        app.error(-1, 2110, "Connectivity between Trader Workstation and server is broken.")
        self.assertEqual(engine.connection["state"], "FEED_DOWN")
        app.error(-1, 2104, "Market data farm connection is OK:usfarm")
        self.assertEqual(engine.connection["state"], "CONNECTED")

    def test_connection_closed_backs_off_and_reconnects(self):
        s, engine, clock, app = self.connect()
        app.connectionClosed()
        self.assertIsNone(s.app)
        self.assertEqual(engine.connection["state"], "DISCONNECTED")
        s.step(clock())
        self.assertIsNone(s.app)  # still in backoff
        clock.t += 2.1
        s.step(clock())
        self.assertIsNotNone(s.app)
        self.assertEqual(s.app.calls[0][0], "connect")

    def test_backoff_doubles_until_ready(self):
        s, engine, clock = make_session()
        s.step(clock())
        s.app.connectionClosed()
        self.assertEqual(s.backoff, 4.0)
        clock.t += 2.1
        s.step(clock())
        s.app.connectionClosed()
        self.assertEqual(s.backoff, 8.0)
        clock.t += 4.1
        s.step(clock())
        s.app.nextValidId(1)
        self.assertEqual(s.backoff, 2.0)

    def test_no_next_valid_id_times_out(self):
        s, engine, clock = make_session()
        s.step(clock())
        clock.t += 16
        s.step(clock())
        self.assertIsNone(s.app)
        self.assertIn("nextValidId", engine.connection["detail"])

    def test_live_account_never_gets_an_order(self):
        s, engine, clock, app = self.connect()
        app.managedAccounts("U1234567")
        tr = engine.trader
        self.assertFalse(tr.gate.arm(True))
        out = tr.submit("AAA", "BUY", 10.0, 100, clock())
        self.assertFalse(out["ok"])
        self.assertIn("PAPER", out["reason"])
        self.assertNotIn("placeOrder", names(app))

    def test_paper_account_order_round_trip(self):
        s, engine, clock, app = self.connect()
        app.managedAccounts("DU7654321")
        app.nextValidId(41)
        tr = engine.trader
        self.assertEqual(tr.gate.mode, "PAPER")
        self.assertTrue(tr.gate.arm(True))
        engine.syms["AAA"].play.update(stop=9.5, target=11.0)
        out = tr.submit("AAA", "BUY", 10.0, 100, clock())
        self.assertTrue(out["ok"], out)
        placed = [c for c in app.calls if c[0] == "placeOrder"]
        self.assertEqual([c[1] for c in placed], [41, 42, 43])
        self.assertEqual(placed[0][3]["type"], "LMT")
        self.assertEqual((placed[1][3]["type"], placed[1][3]["aux"], placed[1][3]["price"], placed[1][3]["parent"],
                          placed[1][3]["oca"]), ("STP LMT", 9.5, 9.4, 41, "twiney41-x1"))
        self.assertEqual((placed[2][3]["type"], placed[2][3]["price"], placed[2][3]["parent"]), ("LMT", 11.0, 41))
        self.assertEqual(s.next_order_id, 44)
        # TWS acknowledges with a permId: the same order, not a duplicate
        O = lambda **k: type("O", (), k)()
        app.openOrder(41, O(symbol="AAA"), O(permId=900, action="BUY", totalQuantity=decimal.Decimal("100"),
                      orderType="LMT", lmtPrice=10.0, auxPrice=0.0, tif="DAY"), O(status="Submitted"))
        app.orderStatus(41, "Submitted", decimal.Decimal("0"), decimal.Decimal("100"), 0.0, 900, 0, 0.0, 1, "", 0.0)
        pend = engine.snapshot(clock())["account"]["pending"]
        self.assertEqual(len([o for o in pend if o["role"] == "entry"]), 1)
        self.assertEqual([o for o in pend if o["role"] == "entry"][0]["status"], "Submitted")
        # moving the order re-sends placeOrder with the same id and the new price
        self.assertTrue(engine.trader.modify(41, 10.05, clock())["ok"])
        moved = [c for c in app.calls if c[0] == "placeOrder" and c[1] == 41][-1]
        self.assertEqual((moved[3]["price"], moved[3]["qty"], moved[3]["type"]), (10.05, 100, "LMT"))
        # cancel goes through cancelOrder with the TWS order id
        tr.cancel(41, clock())
        self.assertIn(("cancelOrder", 41, ""), app.calls)
        n = tr.cancel_all("AAA", clock())["cancelled"]
        self.assertEqual(n, 3)

    def test_no_order_before_next_valid_id(self):
        s, engine, clock = make_session()
        s.step(clock())
        s.app.managedAccounts("DU1")
        self.assertIsNone(s.next_order_id)
        engine.trader.gate.arm(True)
        out = engine.trader.submit("AAA", "BUY", 10.0, 1, clock())
        self.assertFalse(out["ok"])


if __name__ == "__main__":
    unittest.main()


class AuditFixTests(unittest.TestCase):
    """Things a live IBKR session gets wrong easily: each pinned by a test."""

    def connect(self):
        s, engine, clock = make_session()
        s.step(clock())
        app = s.app
        app.nextValidId(1)
        app.managedAccounts("DU1")
        return s, engine, clock, app

    def test_moving_a_stop_limit_twice_keeps_the_limit_under_the_stop(self):
        s, engine, clock, app = self.connect()
        engine.trader.gate.arm(True)
        engine.syms["AAA"].play.update(stop=9.5, target=11.0)
        engine.trader.submit("AAA", "BUY", 10.0, 100, clock())
        stop_id = [c[1] for c in app.calls if c[0] == "placeOrder" and c[3]["type"] == "STP LMT"][0]
        s.modify_order(stop_id, 9.0, clock())
        s.modify_order(stop_id, 9.7, clock())
        last = [c for c in app.calls if c[0] == "placeOrder" and c[1] == stop_id][-1][3]
        self.assertEqual((last["aux"], last["price"]), (9.7, 9.6))
        self.assertEqual(last["oca"], "twiney1-x1")        # still paired with its target

    def test_family_is_held_until_the_last_leg(self):
        s, engine, clock, app = self.connect()
        engine.trader.gate.arm(True)
        engine.syms["AAA"].play.update(stop=9.5, target=11.0)
        engine.trader.submit("AAA", "BUY", 10.0, 100, clock())
        self.assertEqual([c[3]["transmit"] for c in app.calls if c[0] == "placeOrder"], [False, False, True])

    def test_option_positions_and_fills_never_touch_the_stock(self):
        s, engine, clock, app = self.connect()
        O = lambda **k: type("O", (), k)()
        app.position("DU1", O(symbol="AAA", secType="STK"), decimal.Decimal("100"), 9.5)
        app.position("DU1", O(symbol="AAA", secType="OPT"), decimal.Decimal("5"), 120.0)
        app.execDetails(1, O(symbol="AAA", secType="OPT"), O(execId="x.1.1.01", side="BOT", shares=5, price=1.2, time=""))
        self.assertEqual(engine.trader.broker.position("AAA"), 100)
        self.assertEqual(engine.fills, {})                       # the stock's fills (and its P&L) untouched
        self.assertEqual(len(engine.opt_fills), 1)               # the contract's fill is journaled on its own

    def test_daily_bars_are_new_york_dates_and_today_is_skipped(self):
        s, engine, clock, app = self.connect()
        did = [c[1] for c in app.calls if c[0] == "reqHistoricalData" and c[2] == "AAA"][1]
        mk = lambda d: type("Bar", (), {"date": d, "open": 10.0, "high": 10.5, "low": 9.5, "close": 10.2, "volume": 1e6})()
        app.historicalData(did, mk("20260105"))
        from twiney.ibkr import ny_today
        app.historicalData(did, mk(ny_today(clock())))
        days = sorted(engine.syms["AAA"].daily)
        self.assertEqual(len(days), 1)
        import datetime
        self.assertEqual(datetime.datetime.utcfromtimestamp(days[0]).strftime("%Y-%m-%d %H"), "2026-01-05 05")

    def test_irregular_prints_never_reach_the_tape(self):
        s, engine, clock, app = self.connect()
        for sym, px in (("AAA", 10.0), ("BBB", 55.0), ("CCC", 21.0)):
            app.tickPrice(s.l1_ids[sym], 4, px, None)
        s.step(clock())
        d_id, t_id = s.depth_ids["AAA"]
        app.tickByTickAllLast(t_id, 1, 0, 11.50, decimal.Decimal("5000"), None, "FINRA", "B")   # average price
        app.tickByTickAllLast(t_id, 1, 0, 11.40, decimal.Decimal("100"), type("A", (), {"unreported": True})(), "X", "")
        app.tickByTickAllLast(t_id, 1, 0, 10.01, decimal.Decimal("100"), None, "ARCA", " I")    # odd lot: real
        self.assertEqual(engine.syms["AAA"].tape.last()["price"], 10.01)
        self.assertEqual(engine.syms["AAA"].l1["last"], 10.01)
        self.assertLess(max(b[2] for b in engine.syms["AAA"].bar_list()), 11.0)

    def test_no_bid_clears_the_quote(self):
        s, engine, clock, app = self.connect()
        rid = s.l1_ids["AAA"]
        app.tickPrice(rid, 1, 9.99, None)
        app.tickPrice(rid, 1, -1.0, None)
        self.assertIsNone(engine.syms["AAA"].l1["bid"])

    def test_rejected_order_is_not_left_working(self):
        s, engine, clock, app = self.connect()
        engine.trader.gate.arm(True)
        out = engine.trader.submit("AAA", "BUY", 10.0, 100, clock(), bracket=False)
        app.error(out["id"], 201, "Order rejected - reason: margin")
        self.assertEqual(engine.snapshot(clock())["account"]["pending"], [])

    def test_disconnect_disarms(self):
        s, engine, clock, app = self.connect()
        engine.trader.gate.arm(True)
        s.handle_closed("test")
        self.assertFalse(engine.trader.gate.armed)
        self.assertEqual(engine.trader.gate.mode, "NONE")

    def test_execution_correction_replaces_the_fill_and_commissions_count(self):
        s, engine, clock, app = self.connect()
        O = lambda **k: type("O", (), k)()
        app.execDetails(1, O(symbol="AAA", secType="STK"), O(execId="a.b.01.01", side="BOT", shares=100, price=10.0, time=""))
        app.execDetails(1, O(symbol="AAA", secType="STK"), O(execId="c.d.01.01", side="SLD", shares=100, price=10.5, time=""))
        app.execDetails(1, O(symbol="AAA", secType="STK"), O(execId="c.d.01.02", side="SLD", shares=100, price=10.4, time=""))
        app.commissionReport(O(execId="a.b.01.01", commission=1.0))
        app.commissionReport(O(execId="c.d.01.02", commission=1.0))
        self.assertEqual(len(engine.fills), 2)
        self.assertAlmostEqual(engine.day_pnl()["realized"], 38.0)

    def test_manual_tws_orders_are_shown_but_never_cancelled(self):
        s, engine, clock, app = self.connect()
        O = lambda **k: type("O", (), k)()
        for perm, sym in ((501, "AAA"), (502, "BBB")):
            app.openOrder(0, O(symbol=sym, secType="STK"), O(permId=perm, clientId=0, action="BUY", totalQuantity=100,
                          orderType="LMT", lmtPrice=9.0, auxPrice=0.0, tif="DAY"), O(status="Submitted"))
        self.assertEqual(len(engine.snapshot(clock())["account"]["pending"]), 2)
        self.assertEqual(s.cancel_all(clock()), 0)



class _Opt:
    """An option contract the way ibapi hands it to position()."""
    def __init__(self, symbol="TSLA", expiry="20261003", strike=240.0, right="C"):
        self.secType, self.symbol, self.lastTradeDateOrContractMonth, self.strike, self.right = "OPT", symbol, expiry, strike, right
        self.multiplier, self.localSymbol = "100", f"{symbol}  261003C00240000"


class OptionPositionTests(unittest.TestCase):
    """Option positions from TWS show in POSITIONS with their own quotes and can be scaled in / out of from the
    desk: LIMIT DAY orders on the contract they came in as. Closing is never blocked; adding goes through the
    caps in real dollars."""
    def test_option_price_off_the_step_is_resent_on_the_dime(self):
        s, engine, clock = make_session(max_dollars_per_order=20000)
        s.step(clock()); app = s.app; app.nextValidId(50)
        app.position("DU1", _Opt(), 5, 312.0)
        rid = s.opt_ids["TSLA 20261003 240C"]
        app.tickPrice(rid, 1, 3.40, None); app.tickPrice(rid, 2, 3.50, None)
        tr = engine.trader; tr.gate.set_accounts(["DU1"]); tr.gate.arm(True)
        out = tr.opt_adjust("TSLA 20261003 240C", 1, "add", 3.55, clock())     # 3.55: not a dime
        self.assertTrue(out["ok"], out)
        oid = out["id"]
        app.error(oid, 110, "The price does not conform to the minimum price variation for this contract.")
        last = [c for c in app.calls if c[0] == "placeOrder"][-1]
        self.assertNotEqual(last[1], oid); self.assertIsInstance(last[2], _Opt)
        self.assertEqual((last[3]["action"], last[3]["qty"], last[3]["price"]), ("BUY", 1, 3.6))     # up to buy
        app.error(last[1], 110, "again")                                                            # only once
        self.assertEqual([c for c in app.calls if c[0] == "placeOrder"][-1][1], last[1])

    def test_ibkr_halted_tick_is_said(self):
        s, engine, clock = make_session()
        s.step(clock()); app = s.app; app.nextValidId(50)
        sym, rid = next(iter(s.l1_ids.items()))
        app.tickGeneric(rid, 49, 1.0)
        self.assertEqual(engine.syms[sym].halt_kind, "HALTED")
        self.assertTrue(any(a["label"] == "HALTED" for a in engine.alerts))
        app.tickGeneric(rid, 49, 0.0)
        self.assertIsNone(engine.syms[sym].halt_kind)

    def test_option_quotes_come_back_after_a_reconnect(self):
        s, engine, clock = make_session(max_dollars_per_order=20000)
        s.step(clock()); app = s.app; app.nextValidId(50)
        app.position("DU1", _Opt(), 5, 312.0)
        self.assertIn("TSLA 20261003 240C", s.opt_ids)
        app.connectionClosed()                                   # TWS restarts / the network drops
        self.assertEqual(s.opt_ids, {})
        clock.t += 2.1; s.step(clock()); app2 = s.app; app2.nextValidId(60)
        self.assertIsNot(app2, app)
        app2.position("DU1", _Opt(), 5, 312.0)                    # IBKR re-sends the position on the new connection
        self.assertIn("TSLA 20261003 240C", s.opt_ids)
        self.assertTrue(any(c[0] == "reqMktData" and len(c) > 1 and c[1] == s.opt_ids["TSLA 20261003 240C"] for c in app2.calls))

    def test_position_quote_and_orders(self):
        s, engine, clock = make_session(max_dollars_per_order=20000)
        s.step(clock()); app = s.app; app.nextValidId(50)
        app.position("DU1", _Opt(), 5, 312.0)          # 5 calls, $3.12 a contract (IBKR: 312 with the multiplier in)
        p = engine.opt_positions["TSLA 20261003 240C"]
        self.assertEqual((p["qty"], p["avg_cost"], p["mult"], p["right"], p["strike"]), (5, 312.0, 100.0, "C", 240.0))
        rid = s.opt_ids["TSLA 20261003 240C"]
        self.assertIn("reqMktData", names(app))
        app.tickPrice(rid, 1, 3.40, None); app.tickPrice(rid, 2, 3.50, None); app.tickPrice(rid, 4, 3.45, None)
        v = next(x for x in engine.snapshot(clock())["account"]["opt_positions"])
        self.assertEqual((v["label"], v["bid"], v["ask"], v["per_contract"]), ("TSLA 10/03 240C", 3.40, 3.50, 3.12))
        self.assertAlmostEqual(v["pnl"], (3.45 * 100 - 312.0) * 5, places=2)
        tr = engine.trader; tr.gate.set_accounts(["DU1"]); tr.gate.arm(True)
        # scale out at the bid: one price step through it (3.40 -> 3.30) so it fills now
        out = tr.opt_adjust("TSLA 20261003 240C", 2, "close", None, clock())
        self.assertTrue(out["ok"], out)
        placed = [c for c in app.calls if c[0] == "placeOrder"][-1]
        oid, contract, order = placed[1], placed[2], placed[3]
        self.assertIsInstance(contract, _Opt)
        self.assertEqual((order["action"], order["qty"], order["price"], order["type"], order["tif"]), ("SELL", 2, 3.30, "LMT", "DAY"))
        pend = [o for o in engine._pending() if o.get("symbol") == "TSLA 20261003 240C"]
        self.assertEqual(len(pend), 1); self.assertTrue(pend[0]["opt"])
        # scale in one at the ask, at a typed price
        out = tr.opt_adjust("TSLA 20261003 240C", 1, "add", 3.55, clock())
        self.assertTrue(out["ok"], out)
        order = [c for c in app.calls if c[0] == "placeOrder"][-1][3]
        self.assertEqual((order["action"], order["qty"], order["price"]), ("BUY", 1, 3.55))
        # drag that order on the OPTION CHART: re-sent to IBKR on the option contract, on a nickel, same id
        oid = out["id"]
        mv = tr.modify(oid, 3.62, clock())
        self.assertTrue(mv["ok"], mv)
        last = [c for c in app.calls if c[0] == "placeOrder"][-1]
        self.assertEqual(last[1], oid); self.assertIsInstance(last[2], _Opt); self.assertEqual(last[3]["price"], 3.6)
        # adding over the dollar cap is blocked in real dollars (60 contracts × $3.55 × 100 = $21,300)
        out = tr.opt_adjust("TSLA 20261003 240C", 60, "add", 3.55, clock())
        self.assertFalse(out["ok"]); self.assertIn("cap", out["reason"])
        # closing works locked / disarmed
        tr.gate.arm(False); tr.gate.lock_out("day loss")
        out = tr.opt_adjust("TSLA 20261003 240C", 0, "close", None, clock())
        self.assertTrue(out["ok"], out)
        order = [c for c in app.calls if c[0] == "placeOrder"][-1][3]
        self.assertEqual((order["action"], order["qty"]), ("SELL", 5))
        # the fill lands in the journal, the position leaving clears the row
        class Ex: execId, side, shares, price, time = "e1", "SLD", 5, 3.40, ""
        app.execDetails(1, _Opt(), Ex())
        self.assertEqual(engine.fills, {}); self.assertEqual(len(engine.opt_fills), 1)
        self.assertTrue(engine.snapshot(clock())["account"]["fills"][0]["opt"])
        app.position("DU1", _Opt(), 0, 0.0)
        self.assertNotIn("TSLA 20261003 240C", engine.opt_positions)

    def test_no_quote_needs_a_price_and_sim_has_no_options(self):
        s, engine, clock = make_session()
        s.step(clock()); app = s.app; app.nextValidId(50)
        app.position("DU1", _Opt(), 2, 100.0)
        tr = engine.trader; tr.gate.set_accounts(["DU1"]); tr.gate.arm(True)
        out = tr.opt_adjust("TSLA 20261003 240C", 1, "close", None, clock())
        self.assertFalse(out["ok"]); self.assertIn("type a price", out["reason"])
        self.assertFalse(tr.opt_adjust("NOPE", 1, "close", None, clock())["ok"])


class NoSubscriptionTests(SessionTests):
    """IBKR refuses live quotes (354 / 10168): the desk says what to fix on the MKT light and falls back to DELAYED once."""
    def test_354_falls_back_to_delayed_and_explains(self):
        sess, engine, clock, app = self.connect()
        rid = sess.l1_ids["AAA"]
        app.error(rid, 354, "Requested market data is not subscribed. Delayed market data is available.", "")
        self.assertIn("NO LIVE DATA", sess.engine.data_problem); self.assertIn("Client Portal", sess.engine.data_problem)
        self.assertIn(("reqMarketDataType", 3), app.calls)
        self.assertEqual(sess.engine.connection["market_data_type"], 3)
        self.assertNotEqual(sess.l1_ids["AAA"], rid)                      # quotes asked for again, as delayed
        n = app.calls.count(("reqMarketDataType", 3))
        app.error(sess.l1_ids["AAA"], 10168, "Requested market data is not subscribed. Delayed market data is not enabled.", "")
        self.assertEqual(app.calls.count(("reqMarketDataType", 3)), n)    # only once
        light = sess.engine._feeds(sess.clock())["market"]
        self.assertEqual(light["label"], "DELAYED"); self.assertIn("not valid", light["detail"])


class OptionDepthTests(unittest.TestCase):
    """The contract on the OPTION CHART gets a real book (IBKR market depth on the option, each exchange's quote): it
    takes one depth line from the stock ladders while charted, the option LEVEL II shows every level, and a refusal
    falls back to the top of book, said in MESSAGES."""
    def _charted(self):
        s, engine, clock = make_session()
        s.step(clock()); app = s.app; app.nextValidId(50)
        app.position("DU1", _Opt(), 2, 312.0)            # IBKR knows the contract now
        key = "TSLA 20261003 240C"
        engine.opt_live = {key: clock()}                  # it is on the OPTION CHART
        return s, engine, clock, app, key

    def test_charted_contract_gets_a_book_and_a_depth_line(self):
        s, engine, clock, app, key = self._charted()
        self.assertEqual(engine.opt_depth_wanted(clock()), key)
        clock.t += 1; s.step(clock())
        reqs = [c for c in app.calls if c[0] == "reqMktDepth" and isinstance(c[2], _Opt)]
        self.assertEqual(len(reqs), 1)
        rid = reqs[0][1]
        self.assertLessEqual(len(engine.slots), engine.cfg["depth"]["slots"] - 1)     # one line went to the contract
        for i, (bp, ap, sz) in enumerate(((3.40, 3.50, 20), (3.35, 3.55, 40), (3.30, 3.60, 15))):
            app.updateMktDepthL2(rid, i, "CBOE", 0, 1, bp, sz, True)
            app.updateMktDepthL2(rid, i, "ISE", 0, 0, ap, sz + 5, True)
        rid_q = s.opt_ids[key]
        app.tickPrice(rid_q, 1, 3.40, None); app.tickPrice(rid_q, 2, 3.50, None)
        tape = engine.option_tape(key, clock())
        self.assertTrue(tape["deep_book"])
        rows = {round(r["price"], 2): r for r in tape["book"]}
        self.assertEqual(rows[3.35]["bid"], 40); self.assertEqual(rows[3.60]["ask"], 20)
        engine.opt_live = {}                                                          # chart closed: the line comes back
        clock.t += 120; s.step(clock())
        self.assertIn(("cancelMktDepth", rid, True), app.calls)
        self.assertIsNone(s.opt_depth)

    def test_refused_book_falls_back_to_top_of_book(self):
        s, engine, clock, app, key = self._charted()
        clock.t += 1; s.step(clock())
        rid = s.opt_depth[1]
        app.error(rid, 309, "Max number (3) of market depth requests has been reached")
        self.assertIsNone(s.opt_depth)
        self.assertIsNone(engine.opt_depth_wanted(clock()))                           # not asked again for 5 minutes
        self.assertTrue(any("no option book" in m["text"] for m in engine.messages))
        clock.t += 1; s.step(clock())
        self.assertEqual(len([c for c in app.calls if c[0] == "reqMktDepth" and isinstance(c[2], _Opt)]), 1)


class AfterHoursSimOptionsTests(unittest.TestCase):
    """PAPER after hours: the option chain / chart / L2 / T&S run on the practice model priced from the stock, the
    OPT light goes yellow SIM, stale IBKR option ticks are ignored, and no option order goes to IBKR on a
    simulated price. Never on a LIVE account."""
    def _session(self, acct="DU1"):
        s, engine, clock = make_session(sim_options_after_hours=True, max_dollars_per_order=50000)
        clock.t = 1759708800.0 + 21 * 3600          # Monday 5 pm New York: options closed
        s.step(clock()); app = s.app; app.nextValidId(50)
        engine.trader.gate.set_accounts([acct])
        sym = next(iter(s.l1_ids)); rid = s.l1_ids[sym]
        app.tickPrice(rid, 1, 99.9, None); app.tickPrice(rid, 2, 100.1, None); app.tickPrice(rid, 4, 100.0, None)
        return s, engine, clock, app, sym

    def test_paper_after_hours_chain_and_light_are_sim(self):
        s, engine, clock, app, sym = self._session()
        self.assertTrue(engine.opt_sim(clock()))
        ch = engine.option_chain(sym, t=clock())
        self.assertTrue(ch["available"]); self.assertTrue(ch["sim"]); self.assertEqual(ch["source"], "SIM")
        self.assertTrue(any(r["ask"] for r in ch["rows"]))
        lights = engine._feeds(clock())
        self.assertEqual((lights["options"]["color"], lights["options"]["label"]), ("amber", "SIM"))

    def test_live_account_never_sims(self):
        s, engine, clock, app, sym = self._session(acct="U123")
        self.assertFalse(engine.opt_sim(clock()))

    def test_market_hours_are_real(self):
        s, engine, clock, app, sym = self._session()
        clock.t = 1759708800.0 + 24 * 3600 + 15 * 3600     # Tuesday 11:00 ET
        self.assertFalse(engine.opt_sim(clock()))

    def test_option_order_is_held_and_ibkr_ticks_ignored(self):
        s, engine, clock, app, sym = self._session()
        app.position("DU1", _Opt(symbol=sym), 2, 312.0)
        key = next(k for k in s.opt_ids if k.startswith(sym + " "))
        app.tickPrice(s.opt_ids[key], 1, 0.01, None)
        self.assertNotEqual((engine.opt_quotes.get(key) or {}).get("bid"), 0.01)
        tr = engine.trader; tr.gate.arm(True)
        n = len([c for c in app.calls if c[0] == "placeOrder"])
        out = tr.opt_adjust(key, 1, "close", 3.0, clock())
        self.assertFalse(out["ok"]); self.assertIn("SIMULATED", out["reason"])
        self.assertEqual(len([c for c in app.calls if c[0] == "placeOrder"]), n)
