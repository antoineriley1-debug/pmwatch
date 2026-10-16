"""The VPS test-day findings (2026-10-13), fixed: a move is checked like a new order and never puts a stop through
the market; a bracket with nothing to attach is refused, not sent bare; a bad size or price is refused with words;
FLATTEN takes working entries off even when flat, FLATTEN ALL does every symbol; cancelling one exit of a paired
stop / target re-sends the other on its own; an unknown grade key is refused; IBKR's 399 (queued) is information;
a 162 from another login is said loud; a crossed book and missing venues are reported."""

import time
import unittest

from helpers import ASK, BID, INSERT, UPDATE, cfg, plays
from twiney import ibkr
from twiney.engine import Engine
from twiney.trading import SimBroker, Trader, TradingGate


def make(**over):
    c = cfg(trading=dict({"auto_second_entry": False}, **over))
    e = Engine(plays(), c); e.on_connection("DEMO", "", 0.0)
    gate = TradingGate(c); gate.set_sim(); gate.arm(True)
    broker = SimBroker(e); e.sim_broker = broker
    tr = Trader(e, c, broker, gate); e.trader = tr
    e.apply_slot("AAA", True, 0.0)
    return e, tr, broker


def quote(e, bid, ask, t, first=False):
    for i in range(3):
        e.on_depth("AAA", i, INSERT if first else UPDATE, BID, round(bid - i * 0.01, 2), 500, "", t)
        e.on_depth("AAA", i, INSERT if first else UPDATE, ASK, round(ask + i * 0.01, 2), 500, "", t)
    e.on_l1("AAA", "bid", bid, t); e.on_l1("AAA", "ask", ask, t); e.on_l1("AAA", "last", ask, t)


def pending(e, role=None):
    return [o for o in e._pending("AAA") if role is None or o.get("role") == role]


class SizeAndPriceTests(unittest.TestCase):
    def setUp(self):
        self.e, self.tr, self.broker = make(); self.T = time.time()
        quote(self.e, 9.99, 10.00, self.T, first=True)

    def test_bad_sizes_are_refused_not_coerced(self):
        for bad in (0, -5, 1.5, "abc"):
            out = self.tr.submit("AAA", "BUY", 10.0, bad, self.T, bracket=False)
            self.assertFalse(out["ok"], bad); self.assertIn("whole number", out["reason"])
        self.assertEqual(pending(self.e), [])
        self.assertTrue(self.tr.submit("AAA", "BUY", 9.90, None, self.T, bracket=False)["ok"])   # omitted = the default size
        self.assertEqual(pending(self.e, "entry")[0]["qty"], self.tr.default_shares)

    def test_a_price_that_is_not_a_number_is_a_plain_refusal(self):
        out = self.tr.submit("AAA", "BUY", "abc", 100, self.T, bracket=False)
        self.assertFalse(out["ok"]); self.assertIn("price must be a number", out["reason"])


class BracketTests(unittest.TestCase):
    def test_a_bracket_with_nothing_to_attach_never_goes_out_bare(self):
        e, tr, _ = make(); T = time.time(); quote(e, 9.99, 10.00, T, first=True)
        e.set_play_level("AAA", "stop", None, T, source="chart"); e.set_play_level("AAA", "target", None, T, source="chart")
        tr.bracket = True; tr.bracket_template = "PLAY"
        # the desk's default: a stop auto_stop_dollars away goes with it
        out = tr.submit("AAA", "BUY", 9.90, 100, T)
        self.assertTrue(out["ok"], out.get("reason")); self.assertIn("stop 8.90", out["sent"])
        self.assertTrue(any(o.get("role") == "stop" for o in pending(e)))
        # with that fallback off, the bare order is refused
        tr.cfg["auto_stop_dollars"] = 0
        out = tr.submit("AAA", "BUY", 9.80, 100, T + 1)
        self.assertFalse(out["ok"]); self.assertIn("nothing to attach", out["reason"])
        self.assertTrue(tr.submit("AAA", "BUY", 9.80, 100, T + 1, bracket=False)["ok"])     # bare on purpose is allowed


class ModifyTests(unittest.TestCase):
    def setUp(self):
        self.e, self.tr, self.broker = make(); self.T = time.time()
        quote(self.e, 15.24, 15.25, self.T, first=True)

    def test_a_stop_is_never_moved_through_the_market(self):
        self.assertTrue(self.tr.submit("AAA", "BUY", 15.25, 100, self.T, bracket=False)["ok"])
        quote(self.e, 15.24, 15.25, self.T + 1)                      # the sim fills the marketable buy on the next quote
        self.assertEqual(int(self.broker.position("AAA")), 100)
        out = self.tr.submit("AAA", "SELL", 14.90, 100, self.T + 2, bracket=False, order_type="STP LMT", aux=15.00)
        self.assertTrue(out["ok"], out.get("reason"))
        sid = out["id"]
        bad = self.tr.modify(sid, 16.00, self.T + 3)
        self.assertFalse(bad["ok"]); self.assertIn("fire at once", bad["reason"])
        good = self.tr.modify(sid, 14.80, self.T + 3)
        self.assertTrue(good["ok"], good.get("reason")); self.assertTrue(good.get("pending"))

    def test_an_entry_moved_far_through_the_market_is_refused(self):
        out = self.tr.submit("AAA", "BUY", 15.00, 100, self.T, bracket=False)
        self.assertTrue(out["ok"], out.get("reason"))
        bad = self.tr.modify(out["id"], 30.00, self.T + 1)
        self.assertFalse(bad["ok"]); self.assertIn("over", bad["reason"])


class FlattenTests(unittest.TestCase):
    def test_flatten_when_flat_takes_the_working_entries_off(self):
        e, tr, _ = make(); T = time.time(); quote(e, 9.99, 10.00, T, first=True)
        self.assertTrue(tr.submit("AAA", "BUY", 9.90, 100, T, bracket=False)["ok"])
        self.assertTrue(tr.submit("AAA", "BUY", 9.80, 100, T, bracket=False)["ok"])
        self.assertEqual(len(pending(e, "entry")), 2)
        out = tr.flatten("AAA", T + 1)
        self.assertTrue(out["ok"] and out["flat"]); self.assertEqual(out["cancelled"], 2)
        self.assertEqual(pending(e, "entry"), [])

    def test_flatten_all(self):
        e, tr, _ = make(); T = time.time(); quote(e, 9.99, 10.00, T, first=True)
        self.assertTrue(tr.submit("AAA", "BUY", 9.90, 100, T, bracket=False)["ok"])
        out = tr.flatten_all(T + 1)
        self.assertTrue(out["ok"]); self.assertEqual(out["cancelled"], 1)


class OcaPartnerTests(unittest.TestCase):
    def test_cancelling_the_stop_by_hand_re_sends_the_target_on_its_own(self):
        e, tr, broker = make(); T = time.time(); quote(e, 9.99, 10.00, T, first=True)
        tr.bracket = True; tr.bracket_template = "QUARTERS"
        out = tr.submit("AAA", "BUY", 10.00, 100, T)
        self.assertTrue(out["ok"], out.get("reason"))
        stops = [o for o in pending(e) if o.get("role") == "stop" and o.get("oca")]
        self.assertTrue(stops, "a QUARTERS bracket pairs each target with its own stop")
        stop = stops[0]
        partners_before = [o for o in pending(e) if o.get("oca") == stop["oca"] and o.get("role") != "stop"]
        self.assertTrue(partners_before)
        res = tr.cancel(stop["order_id"], T + 1)
        self.assertTrue(res["ok"]); self.assertIn("re-sent", res.get("warning", ""))
        again = [o for o in pending(e) if o.get("role") == partners_before[0]["role"] and not o.get("oca")]
        self.assertTrue(again, "the paired target is working again, on its own")
        self.assertEqual(again[0]["qty"], partners_before[0]["qty"])


class GradeTests(unittest.TestCase):
    def test_unknown_key_is_refused(self):
        e = Engine(plays(), cfg())
        self.assertFalse(e.grade("no-such-call", "good", 1.0))


class Eng:
    def __init__(self):
        self.msgs = []; self.orders = []; self.connection = {"state": "CONNECTED"}
    def on_error(self, sym, code, msg, t, level="warn", category=None):
        self.msgs.append((sym, code, level, category, msg))
    def on_order(self, key, t, **f):
        self.orders.append((key, f))


class Sess:
    def __init__(self):
        self.my_orders = {7: {"symbol": "AAA", "type": "LMT", "price": 10.0, "qty": 100, "action": "BUY", "_mod_t": 0.5, "_prev": (None, 9.9, 100)}}
        self.perm_ids = {}
        self.HIST_RETRY_CODES = {162, 165, 366, 420, 10197, 2104, 2106}
    def _hist_refused(self, *a):
        return True


class AdapterCodeTests(unittest.TestCase):
    def test_399_is_queued_information_not_a_rejection(self):
        eng, sess = Eng(), Sess()
        app = ibkr.TwineyWrapper(eng, sess, clock=lambda: 1.0)
        app.error(7, 399, "Order Message: Warning: your order will not be placed at the exchange until 2026-10-14 04:00:00 US/Eastern")
        sym, code, level, cat, msg = eng.msgs[-1]
        self.assertEqual((code, level, cat), (399, "info", "INFORMATION")); self.assertIn("QUEUED", msg)
        self.assertEqual(eng.orders, [])                                   # the order stays working

    def test_10326_rolls_the_move_back_and_says_refused(self):
        eng, sess = Eng(), Sess()
        app = ibkr.TwineyWrapper(eng, sess, clock=lambda: 1.0)
        app.error(7, 10326, "OCA group revision is not allowed")
        self.assertEqual(sess.my_orders[7]["price"], 9.9)                  # the old price stands
        self.assertEqual(eng.msgs[-1][3], "ORDER REJECTION"); self.assertIn("still working at its old price", eng.msgs[-1][4])

    def test_162_from_another_login_is_said_loud(self):
        eng, sess = Eng(), Sess()
        app = ibkr.TwineyWrapper(eng, sess, clock=lambda: 1.0)
        app.req[55] = ("hist", "AAA")
        app.error(55, 162, "Historical Market Data Service error message:Trading TWS session is connected from a different IP address")
        self.assertTrue(any(c == 162 and lvl == "error" and cat == "CONNECTION" for _s, c, lvl, cat, _m in eng.msgs))


class CrossedBookTests(unittest.TestCase):
    def test_crossed_book_and_missing_venues_are_reported(self):
        e = Engine(plays(), cfg()); e.on_connection("CONNECTED", "", 0.0); e.apply_slot("AAA", True, 0.0)
        e.on_depth("AAA", 0, INSERT, BID, 229.42, 100, "", 1.0)
        e.on_depth("AAA", 0, INSERT, ASK, 229.00, 100, "", 1.0)
        e.on_l1("AAA", "bid", 229.42, 1.0); e.on_l1("AAA", "ask", 229.00, 1.0)
        self.assertTrue(e._health(e.syms["AAA"], 2.0)["crossed"])
        e.on_error("AAA", 2152, "Depth data is only available for the following exchanges: BATS, ARCA, BEX, IEX", 2.0, level="warn", category="CONNECTION")
        self.assertIn("BATS", e.snapshot(2.5)["depth_partial"])


if __name__ == "__main__":
    unittest.main()
