"""The order paths that protect money: getting out always works, stops stay on, exits never outgrow the position."""
import unittest

from helpers import ASK, BID, UPDATE
from test_trading import sim_setup
from twiney.trading import snap


def pend(e, t=9.0):
    return e.snapshot(t)["account"]["pending"]


class FlattenTests(unittest.TestCase):
    def test_flatten_works_disarmed_and_over_the_order_cap(self):
        e, tr, gate, broker = sim_setup(max_shares_per_order=300, max_position_shares=1000)
        gate.arm(True)
        e.syms["AAA"].play.update(stop=9.50, target=11.0)
        tr.submit("AAA", "BUY", 10.00, 300, 2.0)
        tr.submit("AAA", "BUY", 10.00, 300, 2.1)
        self.assertEqual(broker.position("AAA"), 600)
        gate.arm(False)
        out = tr.flatten("AAA", 3.0)
        self.assertTrue(out["ok"], out)
        self.assertEqual(broker.position("AAA"), 0)

    def test_flatten_works_when_locked_for_the_day(self):
        e, tr, gate, broker = sim_setup()
        gate.arm(True)
        tr.submit("AAA", "BUY", 10.00, 100, 2.0, bracket=False)
        gate.lock_out("test")
        self.assertTrue(tr.flatten("AAA", 3.0)["ok"])
        self.assertEqual(broker.position("AAA"), 0)

    def test_second_flatten_is_refused_while_the_first_works(self):
        e, tr, gate, broker = sim_setup()
        gate.arm(True)
        tr.submit("AAA", "BUY", 10.00, 100, 2.0, bracket=False)
        broker.on_market = lambda *a: None                        # the market doesn't take it yet: it works
        self.assertTrue(tr.flatten("AAA", 3.0)["ok"])
        out = tr.flatten("AAA", 3.1)
        self.assertFalse(out["ok"])
        self.assertIn("already working", out["reason"])


class LossLockTests(unittest.TestCase):
    def test_lock_keeps_the_stop_and_cancels_resting_entries(self):
        e, tr, gate, broker = sim_setup(max_daily_loss=50)
        gate.arm(True)
        e.syms["AAA"].play.update(stop=9.00, target=12.0)
        tr.submit("AAA", "BUY", 10.00, 100, 2.0)                 # fills: stop 9.00 working
        tr.submit("AAA", "BUY", 9.50, 100, 2.1, bracket=False)   # resting entry
        e.on_depth("AAA", 0, UPDATE, BID, 9.40, 500, "", 3.0)
        e.on_depth("AAA", 0, UPDATE, ASK, 9.41, 500, "", 3.0)
        e.on_l1("AAA", "last", 9.40, 3.0)
        tr.watchdog(4.0)
        self.assertTrue(gate.locked)
        roles = sorted(o["role"] for o in pend(e))
        self.assertEqual(roles, ["stop", "target"])              # the resting entry is gone, the stop stays


class ExitGuardTests(unittest.TestCase):
    def test_manual_close_cancels_leftover_exits(self):
        e, tr, gate, broker = sim_setup()
        gate.arm(True)
        e.syms["AAA"].play.update(stop=9.50, target=11.0)
        tr.submit("AAA", "BUY", 10.00, 100, 2.0)
        self.assertTrue(tr.adjust("AAA", 100, "close", 3.0)["ok"])
        self.assertEqual(broker.position("AAA"), 0)
        tr.watchdog(3.5)
        self.assertTrue(pend(e))                                  # waits for fills / positions to settle
        tr.watchdog(6.0)
        self.assertEqual(pend(e), [])

    def test_partial_close_trims_the_stop(self):
        e, tr, gate, broker = sim_setup()
        gate.arm(True)
        e.syms["AAA"].play.update(stop=9.50, target=11.0)
        tr.submit("AAA", "BUY", 10.00, 100, 2.0)
        tr.adjust("AAA", 40, "close", 3.0)
        tr.watchdog(3.1); tr.watchdog(6.0)
        self.assertEqual({o["role"]: o["remaining"] for o in pend(e)}, {"stop": 60.0, "target": 60.0})


class EntryChecks(unittest.TestCase):
    def test_position_cap_counts_working_entries(self):
        e, tr, gate, broker = sim_setup(max_position_shares=1000, max_orders_per_minute=50)
        gate.arm(True)
        ok = [tr.submit("AAA", "BUY", 9.00, 400, 2.0 + i, bracket=False)["ok"] for i in range(4)]
        self.assertEqual(ok, [True, True, False, False])

    def test_stop_on_the_wrong_side_refuses_the_entry(self):
        e, tr, gate, broker = sim_setup()
        gate.arm(True)
        e.syms["AAA"].play.update(stop=10.60, target=11.0)
        out = tr.submit("AAA", "BUY", 10.00, 100, 2.0)
        self.assertFalse(out["ok"])
        self.assertIn("wrong side", out["reason"])
        self.assertEqual(pend(e), [])

    def test_marketable_entry_gets_its_stop_working(self):
        e, tr, gate, broker = sim_setup()
        gate.arm(True)
        e.syms["AAA"].play.update(stop=9.90, target=10.20)
        tr.submit("AAA", "BUY", 10.00, 100, 2.0)
        self.assertEqual(broker.position("AAA"), 100)
        self.assertEqual({o["role"]: o["status"] for o in pend(e)}, {"stop": "Submitted", "target": "Submitted"})
        e.on_print("AAA", 9.85, 100, "X", 3.0)
        e.on_depth("AAA", 0, UPDATE, BID, 9.85, 500, "", 3.1)
        self.assertEqual(broker.position("AAA"), 0)

    def test_marketable_limit_fills_at_the_touch(self):
        e, tr, gate, broker = sim_setup()
        gate.arm(True)
        tr.submit("AAA", "BUY", 10.00, 100, 2.0, bracket=False)
        tr.submit("AAA", "SELL", 9.90, 100, 3.0, bracket=False)   # bid is 9.99
        self.assertEqual(e.day_pnl()["realized"], -1.0)

    def test_snap_to_valid_ticks(self):
        self.assertEqual(snap(0.9995 + 0.001, +1), 1.01)
        self.assertEqual(snap(10.004), 10.0)
        self.assertEqual(snap(0.12345, -1), 0.1234)
