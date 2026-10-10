"""A contract never rides the wrong side. A SHORT 2nd entry (under the pivot) with a CALL hanging around trades the
STOCK; a CALL cannot be linked against drawn SHORT levels; a new pivot drops yesterday's link; a saved link only loads
when it fits the saved levels."""

import time as _t
import unittest

from helpers import cfg, plays
from twiney import options as _o
from twiney.config import validate_plays
from twiney.engine import Engine
from twiney.trading import SimBroker, Trader, TradingGate


def make():
    c = cfg(trading={"auto_second_entry": False})
    e = Engine(plays(), c); e.on_connection("DEMO", "", 0.0)
    gate = TradingGate(c); gate.set_sim(); gate.arm(True)
    broker = SimBroker(e); e.sim_broker = broker
    tr = Trader(e, c, broker, gate); e.trader = tr
    e.apply_slot("AAA", True, 0.0)
    return e, tr


def setup(right):
    """AAA with no levels drawn (the fixture's pivot and 2nd entry cleared) and a contract key on its chain."""
    e, tr = make(); T = _t.time()
    e.on_l1("AAA", "last", 10.00, T)
    e.set_play_level("AAA", "second_entry", None, T, source="chart")
    e.set_play_level("AAA", "trigger", None, T, source="chart")
    exp = e.option_chain("AAA", None, right, T)["expiry"]
    return e, tr, T, _o.key_of("AAA", exp, 10, right)


class FitsSideTests(unittest.TestCase):
    def test_rule(self):
        self.assertTrue(_o.fits_side("AAA 20261016 10C", "long"))
        self.assertFalse(_o.fits_side("AAA 20261016 10C", "short"))
        self.assertTrue(_o.fits_side("AAA 20261016 10P", "short"))
        self.assertFalse(_o.fits_side("AAA 20261016 10P", "long"))
        self.assertIsNone(_o.fits_side("", "long"))

    def test_short_second_entry_drops_a_leftover_call_and_trades_the_stock(self):
        e, tr, T, call = setup("C")
        self.assertTrue(tr.set_trade_as("AAA", "option", call, 1, T)["ok"])    # a call linked with no levels: fine, the play is LONG
        e.set_play_level("AAA", "trigger", 10.50, T, source="chart")           # a new pivot: the link comes off, STOCK / OPTIONS is asked again
        play = e.syms["AAA"].play
        self.assertEqual((play["trade_as"], play.get("opt_key"), play["trade_as_set"]), ("stock", None, False))
        # link it again, then draw a SHORT 2nd entry under the pivot: the call cannot ride it
        self.assertTrue(tr.set_trade_as("AAA", "option", call, 1, T)["ok"])
        e.set_play_level("AAA", "second_entry", 10.20, T, source="chart")
        play = e.syms["AAA"].play
        self.assertEqual(play["side"], "short")
        self.assertEqual((play["trade_as"], play.get("opt_key")), ("stock", None))
        self.assertNotIn("AAA", tr.opt_link)
        msgs = [m["text"] for m in e.messages if "CALL" in m["text"]]
        self.assertTrue(msgs and "trades the STOCK" in msgs[-1], msgs)

    def test_a_call_cannot_be_linked_against_short_levels(self):
        e, tr, T, call = setup("C")
        e.set_play_level("AAA", "trigger", 10.50, T, source="chart")
        e.set_play_level("AAA", "second_entry", 10.20, T, source="chart")
        self.assertEqual(e.syms["AAA"].play["side"], "short")
        out = tr.set_trade_as("AAA", "option", call, 1, T)
        self.assertFalse(out["ok"])
        self.assertIn("pick a PUT", out["reason"])
        self.assertEqual(e.syms["AAA"].play["side"], "short")                   # never turned by the contract
        self.assertEqual(e.syms["AAA"].play["trade_as"], "stock")

    def test_a_put_rides_the_short_second_entry(self):
        e, tr, T, put = setup("P")
        e.set_play_level("AAA", "trigger", 10.50, T, source="chart")
        e.set_play_level("AAA", "second_entry", 10.20, T, source="chart")
        self.assertTrue(tr.set_trade_as("AAA", "option", put, 1, T)["ok"])
        e.set_play_level("AAA", "stop", 10.40, T, source="chart")
        play = e.syms["AAA"].play
        self.assertEqual((play["side"], play["trade_as"], play["opt_key"]), ("short", "option", put))

    def test_with_no_levels_the_contract_still_sets_the_side(self):
        e, tr, T, put = setup("P")
        self.assertTrue(tr.set_trade_as("AAA", "option", put, 1, T)["ok"])
        self.assertEqual(e.syms["AAA"].play["side"], "short")

    def test_saved_link_loads_only_when_it_fits(self):
        base = {"symbol": "AAA", "trade_as": "option", "opt_key": "AAA 20261016 10C", "opt_qty": 2, "trade_as_set": True}
        short = validate_plays({"plays": [dict(base, trigger=10.5, second_entry=10.2)]})[0]
        self.assertEqual((short["trade_as"], short.get("opt_key"), short["trade_as_set"]), ("stock", None, False))
        long_ = validate_plays({"plays": [dict(base, trigger=10.5, second_entry=10.8)]})[0]
        self.assertEqual((long_["trade_as"], long_["opt_key"], long_["opt_qty"], long_["trade_as_set"]), ("option", "AAA 20261016 10C", 2, False))
        none = validate_plays({"plays": [dict(base, trigger=10.5)]})[0]      # no 2nd entry drawn: nothing to ride
        self.assertEqual((none["trade_as"], none.get("opt_key")), ("stock", None))


if __name__ == "__main__":
    unittest.main()
