import decimal
import unittest

from helpers import ASK, INSERT, cfg, plays
from twiney.engine import Engine
from twiney.ibkr import MarketDataSession, TwineyWrapper, num, parse_error_args
from twiney.safety import ReadOnlyGuard, ReadOnlyViolation


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

    def placeOrder(self, *a):  # present on the real EClient; the guard must win
        self.calls.append(("placeOrder",))

    def __getattr__(self, name):
        if name.startswith(("req", "cancel")):
            return lambda *a: self.calls.append((name,) + a)
        raise AttributeError(name)


class FakeApp(TwineyWrapper, ReadOnlyGuard, FakeClient):
    def __init__(self, engine, session):
        FakeClient.__init__(self)
        TwineyWrapper.__init__(self, engine, session, clock=lambda: session.clock())


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def make_session():
    c = cfg()
    engine = Engine(plays(), c)
    clock = Clock()
    s = MarketDataSession(engine, c, plays(), FakeApp, contract_factory=lambda p: p["symbol"], clock=clock)
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

    def test_order_calls_blocked_on_app(self):
        s, engine, clock, app = self.connect()
        with self.assertRaises(ReadOnlyViolation):
            app.placeOrder(1, None, None)
        with self.assertRaises(ReadOnlyViolation):
            app.cancelOrder(1)
        self.assertNotIn("placeOrder", names(app))


if __name__ == "__main__":
    unittest.main()
