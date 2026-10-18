"""The buy / sell path, front to back: each case is a defect the audit found, kept as a test so it stays fixed."""
import unittest

from helpers import BID, UPDATE
from test_trading import sim_setup


def long100(**kw):
    e, tr, gate, broker = sim_setup(**kw)
    gate.arm(True)
    out = tr.submit("AAA", "BUY", 10.00, 100, 2.0, bracket=False)
    assert out["ok"], out
    assert broker.position("AAA") == 100
    return e, tr, gate, broker


class OrderAuditTests(unittest.TestCase):
    def test_two_closes_never_flip_the_position(self):
        e, tr, gate, broker = long100()
        gate.arm(False)
        self.assertTrue(tr.submit("AAA", "SELL", 10.05, 100, 5.0, nonce="sb1")["ok"])
        b = tr.submit("AAA", "SELL", 10.05, 100, 5.1, nonce="sb2")
        self.assertFalse(b["ok"]); self.assertIn("already being closed", b["reason"])
        e.on_depth("AAA", 0, UPDATE, BID, 10.05, 1000, "", 6.0)
        self.assertEqual(broker.position("AAA"), 0)

    def test_flatten_with_a_partial_working_closes_everything(self):
        e, tr, gate, broker = long100()
        e.syms["AAA"].play.update(stop=9.50)
        tr.watchdog(10.0)
        self.assertTrue(tr.partial("AAA", 40, 10.50, 11.0)["ok"])
        f = tr.flatten("AAA", 12.0)
        self.assertTrue(f["ok"]); self.assertIn("SELL 60", f["sent"])          # the partial was moved, the flatten takes the rest
        e.on_depth("AAA", 0, UPDATE, BID, 9.99, 1000, "", 13.0)
        e.on_print("AAA", 9.99, 100, "X", 13.0)
        self.assertEqual(broker.position("AAA"), 0)

    def test_the_stop_line_goes_back_in_after_cancel_all(self):
        e, tr, gate, broker = long100()
        e.syms["AAA"].play.update(stop=9.50)
        tr.watchdog(10.0)
        tr.cancel_all("AAA", 11.0)
        for t in (12.0, 16.0):
            tr.watchdog(t)
        self.assertEqual([o["role"] for o in e._pending("AAA")], ["stop"])

    def test_practice_target_fill_takes_its_stop_with_it(self):
        e, tr, gate, broker = long100()
        e.syms["AAA"].play.update(stop=9.50, target=10.20)
        tr.watchdog(10.0)
        e.on_depth("AAA", 0, UPDATE, BID, 10.20, 1000, "", 11.0)
        self.assertEqual(broker.position("AAA"), 0)
        e.on_print("AAA", 9.45, 100, "X", 11.5)                               # the old stop must not fire on a flat book
        self.assertEqual(broker.position("AAA"), 0)

    def test_reverse_gets_a_stop(self):
        e, tr, gate, broker = long100()
        e.syms["AAA"].play.update(stop=9.50, target=10.50)
        tr.watchdog(10.0)
        self.assertTrue(tr.reverse("AAA", 11.0)["ok"])
        for t in (14.0, 20.0):
            tr.watchdog(t)
        self.assertEqual(broker.position("AAA"), -100)
        self.assertEqual([(o["role"], o["action"]) for o in e._pending("AAA")], [("stop", "BUY")])

    def test_a_stop_can_be_tightened_under_the_loss_lock(self):
        e, tr, gate, broker = long100()
        e.syms["AAA"].play.update(stop=9.50)
        tr.watchdog(10.0)
        stop = [o for o in e._pending("AAA") if o["role"] == "stop"][0]
        gate.lock_out("day loss"); gate.arm(False)
        self.assertTrue(tr.modify(stop["order_id"], 9.80, 12.0)["ok"])
