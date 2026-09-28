import unittest

from helpers import ASK, BID, INSERT, UPDATE, cfg, plays
from twiney.engine import Engine
from twiney.trading import SimBroker, Trader, TradingGate, bracket_legs


def sim_setup(**trading):
    c = cfg(trading=trading)
    e = Engine(plays(), c)
    e.on_connection("DEMO", "", 0.0)
    gate = TradingGate(c)
    gate.set_sim()
    broker = SimBroker(e)
    e.sim_broker = broker
    tr = Trader(e, c, broker, gate)
    e.trader = tr
    e.apply_slot("AAA", True, 0.0)
    for i in range(3):
        e.on_depth("AAA", i, INSERT, BID, round(9.99 - i * 0.01, 2), 500, "", 1.0)
        e.on_depth("AAA", i, INSERT, ASK, round(10.00 + i * 0.01, 2), 500, "", 1.0)
    e.on_l1("AAA", "last", 10.0, 1.0)
    return e, tr, gate, broker


class BracketTests(unittest.TestCase):
    def test_legs_from_play(self):
        play = {"stop": 9.5, "target": 11.0}
        legs = bracket_legs(play, "BUY", 100, 10.0)
        self.assertEqual([(l["role"], l["type"], l["action"]) for l in legs],
                         [("stop", "STP", "SELL"), ("target", "LMT", "SELL")])
        # a stop on the wrong side of the entry is dropped rather than sent
        self.assertEqual([l["role"] for l in bracket_legs({"stop": 10.5, "target": 11.0}, "BUY", 1, 10.0)],
                         ["target"])
        self.assertEqual(bracket_legs({}, "BUY", 1, 10.0), [])


class SimTradingTests(unittest.TestCase):
    def test_disarmed_blocks_everything(self):
        e, tr, gate, broker = sim_setup()
        out = tr.submit("AAA", "BUY", 9.99, 100, 2.0)
        self.assertFalse(out["ok"])
        self.assertIn("DISARMED", out["reason"])
        self.assertEqual(broker.orders, {})

    def test_limit_rests_then_fills_and_bracket_manages_exit(self):
        e, tr, gate, broker = sim_setup()
        e.syms["AAA"].play.update(stop=9.90, target=10.20)
        gate.arm(True)
        out = tr.submit("AAA", "BUY", 9.99, 100, 2.0)
        self.assertTrue(out["ok"], out)
        self.assertIn("stop 9.90", out["sent"])
        pend = e.snapshot(2.5)["account"]["pending"]
        self.assertEqual({o["role"] for o in pend}, {"entry", "stop", "target"})
        self.assertEqual([o["status"] for o in pend if o["role"] == "entry"], ["Submitted"])
        # offer drops to 9.99 -> entry fills at its limit
        e.on_depth("AAA", 0, UPDATE, ASK, 9.99, 300, "", 3.0)
        self.assertEqual(broker.position("AAA"), 100)
        snap = e.snapshot(3.5)
        self.assertEqual(snap["account"]["fills"][0]["side"], "BOT")
        pane = snap["panes"][0]
        self.assertEqual(pane["position"]["qty"], 100)
        roles = {o["role"]: o["status"] for o in pane["orders"]}
        self.assertEqual(roles, {"stop": "Submitted", "target": "Submitted"})
        # price runs to target: target fills, stop is cancelled (OCO)
        e.on_depth("AAA", 0, UPDATE, BID, 10.20, 300, "", 4.0)
        self.assertEqual(broker.position("AAA"), 0)
        self.assertEqual(e.snapshot(4.5)["account"]["pending"], [])

    def test_stop_leg_triggers_on_last_print(self):
        e, tr, gate, broker = sim_setup()
        e.syms["AAA"].play.update(stop=9.90, target=10.20)
        gate.arm(True)
        tr.submit("AAA", "BUY", 9.99, 100, 2.0)
        e.on_depth("AAA", 0, UPDATE, ASK, 9.99, 300, "", 3.0)
        e.on_print("AAA", 9.89, 200, "X", 4.0)
        self.assertEqual(broker.position("AAA"), 0)
        self.assertEqual(e.snapshot(4.5)["account"]["pending"], [])

    def test_cancel_and_cancel_all(self):
        e, tr, gate, broker = sim_setup()
        gate.arm(True)
        a = tr.submit("AAA", "BUY", 9.90, 100, 2.0, bracket=False)["id"]
        tr.submit("AAA", "BUY", 9.80, 100, 2.1, bracket=False)
        self.assertTrue(tr.cancel(a, 3.0)["ok"])
        self.assertEqual(len(e._pending("AAA")), 1)
        self.assertEqual(tr.cancel_all("AAA", 3.5)["cancelled"], 1)
        self.assertEqual(e._pending("AAA"), [])

    def test_flatten_uses_marketable_limit_and_clears_working_orders(self):
        e, tr, gate, broker = sim_setup()
        gate.arm(True)
        tr.submit("AAA", "BUY", 10.00, 100, 2.0, bracket=False)   # lifts the offer at once
        self.assertEqual(broker.position("AAA"), 100)
        tr.submit("AAA", "SELL", 10.50, 100, 2.5, bracket=False)  # a resting target
        out = tr.flatten("AAA", 3.0)
        self.assertTrue(out["ok"])
        self.assertEqual(broker.position("AAA"), 0)
        self.assertEqual(e._pending("AAA"), [])

    def test_close_and_add_from_positions_panel(self):
        e, tr, gate, broker = sim_setup()
        gate.arm(True)
        tr.submit("AAA", "BUY", 10.00, 100, 2.0, bracket=False)     # long 100
        self.assertEqual(broker.position("AAA"), 100)
        out = tr.adjust("AAA", 10, "add", 3.0)                       # buys 10 at the ask
        self.assertTrue(out["ok"], out)
        self.assertIn("BUY 10 AAA @ 10.00", out["sent"])
        self.assertEqual(broker.position("AAA"), 110)
        out = tr.adjust("AAA", 5, "close", 4.0)                      # sells 5 at the bid
        self.assertIn("SELL 5 AAA @ 9.99", out["sent"])
        self.assertEqual(broker.position("AAA"), 105)
        out = tr.adjust("AAA", 500, "close", 5.0)                    # never closes more than you have
        self.assertIn("SELL 105 AAA", out["sent"])
        self.assertEqual(broker.position("AAA"), 0)
        self.assertFalse(tr.adjust("AAA", 1, "close", 6.0)["ok"])    # flat: nothing to close
        gate.arm(False)
        self.assertFalse(tr.adjust("AAA", 1, "add", 7.0)["ok"])      # disarmed: blocked by the gate

    def test_size_and_caps_reach_the_dashboard_snapshot(self):
        e, tr, gate, broker = sim_setup(default_shares=50, max_shares_per_order=75)
        self.assertTrue(tr.set_size(500))
        self.assertEqual(tr.default_shares, 75)
        s = e.snapshot(1.0)["trading"]
        self.assertEqual((s["mode"], s["armed"], s["default_shares"]), ("SIM", False, 75))
        self.assertIn("DISARMED", s["why_not"])

    def test_orders_are_recorded_for_replay_audit(self):
        rec = []
        e, tr, gate, broker = sim_setup()
        e.recorder = type("R", (), {"write": staticmethod(rec.append), "path": "x"})()
        gate.arm(True)
        tr.submit("AAA", "SELL", 10.01, 100, 2.0, bracket=False)
        self.assertTrue(any(ev.get("ev") == "order" and ev["action"] == "SELL" for ev in rec))


if __name__ == "__main__":
    unittest.main()
