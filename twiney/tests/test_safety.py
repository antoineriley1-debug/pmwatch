import os
import re
import unittest

from helpers import cfg
from twiney.safety import ORDER_CALLS, ORDER_PATH
from twiney.trading import TradingGate

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def sources():
    yield "run_twiney.py"
    for dirpath, _dirs, files in os.walk(os.path.join(ROOT, "twiney")):
        for f in files:
            if f.endswith((".py", ".html")):
                yield os.path.relpath(os.path.join(dirpath, f), ROOT).replace(os.sep, "/")


class OrderPathTests(unittest.TestCase):
    def test_order_calls_only_in_the_gated_files(self):
        pattern = re.compile(r"\b(" + "|".join(ORDER_CALLS) + r")\b")
        for rel in sources():
            if rel in ORDER_PATH:
                continue
            with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
                for n, line in enumerate(fh, 1):
                    self.assertIsNone(pattern.search(line), f"{rel}:{n}: {line.strip()}")

    def test_gate_refuses_live_unless_allowed(self):
        g = TradingGate(cfg())
        g.set_accounts(["U1234567"])
        self.assertEqual(g.mode, "LIVE")
        self.assertFalse(g.can_trade())
        self.assertFalse(g.arm(True))
        self.assertIn("PAPER", g.why_not())
        g2 = TradingGate(cfg(trading={"allow_live": True}))
        g2.set_accounts(["U1234567"])
        self.assertTrue(g2.can_trade())

    def test_gate_paper_and_sim(self):
        g = TradingGate(cfg())
        g.set_accounts(["DU9876543"])
        self.assertEqual(g.mode, "PAPER")
        self.assertTrue(g.can_trade())
        self.assertFalse(g.armed)                       # disarmed at launch
        self.assertIsNotNone(g.check("BUY", 100, 10.0, 0.0))
        self.assertTrue(g.arm(True))
        self.assertIsNone(g.check("BUY", 100, 10.0, 0.0))
        s = TradingGate(cfg())
        s.set_sim()
        self.assertTrue(s.can_trade())

    def test_gate_caps(self):
        g = TradingGate(cfg(trading={"max_shares_per_order": 200, "max_dollars_per_order": 1000,
                                     "max_orders_per_minute": 2}))
        g.set_sim()
        g.arm(True)
        self.assertIn("cap", g.check("BUY", 500, 1.0, 0.0))
        self.assertIn("cap", g.check("BUY", 200, 10.0, 0.0))
        self.assertIn("LIMIT", g.check("BUY", 1, 1.0, 0.0, order_type="MKT"))
        self.assertIsNone(g.check("BUY", 1, 1.0, 0.0))
        self.assertIsNone(g.check("BUY", 1, 1.0, 1.0))
        self.assertIn("slow down", g.check("BUY", 1, 1.0, 2.0))
        self.assertIsNone(g.check("BUY", 1, 1.0, 70.0))
        self.assertEqual(len(g.snapshot()["blocked"]), 4)

    def test_disabled_in_config(self):
        g = TradingGate(cfg(trading={"enabled": False}))
        g.set_sim()
        self.assertFalse(g.can_trade())


if __name__ == "__main__":
    unittest.main()
