"""The DOM in contract mode: a click above the offer / below the bid is a WATCH — BUY or SELL the picked contract the
moment the STOCK trades that price. Fires once, at the touch, through the option gate; cancels; refuses a price the
stock is already past."""

import time
import unittest

from helpers import cfg, plays
from twiney import options as _o
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


class OptWatchTests(unittest.TestCase):
    def setUp(self):
        self.e, self.tr = make(); self.T = time.time()
        self.e.on_l1("AAA", "bid", 9.99, self.T); self.e.on_l1("AAA", "ask", 10.00, self.T); self.e.on_l1("AAA", "last", 10.00, self.T)
        self.exp = self.e.option_chain("AAA", None, "C", self.T)["expiry"]
        self.kc = _o.key_of("AAA", self.exp, 10, "C")

    def held(self):
        return int((self.e.opt_positions.get(self.kc) or {}).get("qty") or 0)

    def test_buy_the_call_when_the_stock_trades_the_pivot(self):
        out = self.tr.opt_watch("AAA", self.exp, 10, "C", "BUY", 2, 10.25, "above", self.T)
        self.assertTrue(out["ok"], out.get("reason"))
        self.assertEqual(len(self.tr.opt_watches), 1)
        self.e.on_l1("AAA", "last", 10.10, self.T + 1); self.tr.fast_stops(self.T + 1)
        self.assertEqual(len(self.tr.opt_watches), 1)                  # not there yet
        self.e.on_l1("AAA", "last", 10.25, self.T + 2); self.tr.fast_stops(self.T + 2)
        self.assertEqual(self.tr.opt_watches, [])                       # fired once and gone
        self.e.practice_opt_tick(self.T + 3)
        self.assertEqual(self.held(), 2)
        self.assertTrue(any("WATCH BUY 2" in n["text"] for n in self.tr.log))

    def test_sell_the_call_when_the_stock_trades_under_the_stop(self):
        self.assertTrue(self.tr.opt_open("AAA", self.exp, 10, "C", "BUY", 1, None, self.T)["ok"]); self.e.practice_opt_tick(self.T + 1)
        self.assertEqual(self.held(), 1)
        self.assertTrue(self.tr.opt_watch("AAA", self.exp, 10, "C", "SELL", 1, 9.80, "below", self.T + 2)["ok"])
        self.e.on_l1("AAA", "last", 9.79, self.T + 3); self.tr.fast_stops(self.T + 3); self.e.practice_opt_tick(self.T + 4)
        self.assertEqual(self.held(), 0)
        self.assertEqual(self.tr.opt_watches, [])

    def test_already_past_the_price_is_refused_and_cancel_works(self):
        out = self.tr.opt_watch("AAA", self.exp, 10, "C", "BUY", 1, 9.90, "above", self.T)
        self.assertFalse(out["ok"]); self.assertIn("already", out["reason"])
        wid = self.tr.opt_watch("AAA", self.exp, 10, "C", "BUY", 1, 10.50, "above", self.T)["id"]
        self.assertTrue(self.tr.opt_unwatch(wid, self.T + 1)["ok"])
        self.assertEqual(self.tr.opt_watches, [])
        self.assertFalse(self.tr.opt_unwatch(wid, self.T + 1)["ok"])
        self.assertIn("opt_watches", self.tr.snapshot(run_watchdog=False))


if __name__ == "__main__":
    unittest.main()
