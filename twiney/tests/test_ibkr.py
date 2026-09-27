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


def fake_order(action, qty, order_type, price, tif="DAY", parent_id=None, transmit=True):
    return {"action": action, "qty": qty, "type": order_type, "price": price, "tif": tif,
            "parent": parent_id, "transmit": transmit}


def make_session(**trading):
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
        self.assertEqual(names(app).count("reqHistoricalData"), 4)

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

    def test_1100_pauses_rotation(self):
        s, engine, clock, app = self.connect()
        app.error(-1, 1100, "Connectivity between IB and TWS has been lost")
        self.assertEqual(engine.connection["state"], "FEED_DOWN")
        app.tickPrice(s.l1_ids["AAA"], 4, 10.0, None)
        s.step(clock())
        self.assertEqual(s.depth_ids, {})

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
        self.assertEqual((placed[1][3]["type"], placed[1][3]["price"], placed[1][3]["parent"]), ("STP", 9.5, 41))
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
