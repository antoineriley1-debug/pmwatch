"""The SIM / PAPER switch on a live desk: SIM fills orders on the desk against the live tape and sends nothing to
IBKR; PAPER is the IBKR paper account again; never switched with a position or a working order; the practice desk
cannot go to PAPER; the start mode in SETTINGS opens the desk in SIM."""

import datetime as dt
import unittest
from zoneinfo import ZoneInfo

from helpers import ASK, BID, INSERT, UPDATE, cfg, plays
from twiney.engine import Engine
from twiney.ibkr import MarketDataSession
from twiney.trading import IbkrBroker, SimBroker, Trader, TradingGate

NY = ZoneInfo("America/New_York")
T0 = dt.datetime(2026, 10, 14, 10, 0, tzinfo=NY).timestamp()


def quote(e, bid, ask, t, first=False):
    for i in range(3):
        e.on_depth("AAA", i, INSERT if first else UPDATE, BID, round(bid - i * 0.01, 2), 500, "", t)
        e.on_depth("AAA", i, INSERT if first else UPDATE, ASK, round(ask + i * 0.01, 2), 500, "", t)
    e.on_l1("AAA", "bid", bid, t); e.on_l1("AAA", "ask", ask, t); e.on_l1("AAA", "last", ask, t)


def live_desk(start_mode="paper"):
    from test_ibkr import FakeApp, fake_order
    c = cfg(trading={"sim_options_after_hours": False, "auto_second_entry": False, "start_mode": start_mode})
    e = Engine(plays(), c)
    gate = TradingGate(c)
    s = MarketDataSession(e, c, plays(), FakeApp, contract_factory=lambda p: p["symbol"], clock=lambda: T0, order_factory=fake_order, gate=gate)
    tr = Trader(e, c, IbkrBroker(e, s), gate); e.trader = tr
    s.step(T0); s.app.nextValidId(100); s.app.managedAccounts("DU1")
    e.on_connection("CONNECTED", "", T0); e.apply_slot("AAA", True, T0)
    quote(e, 9.99, 10.00, T0 + 1, first=True)
    return e, tr, s


class SimSwitchTests(unittest.TestCase):
    def test_paper_to_sim_and_back(self):
        e, tr, s = live_desk()
        self.assertEqual(tr.gate.mode, "PAPER")
        out = tr.set_mode("SIM", T0 + 2)
        self.assertTrue(out["ok"], out.get("reason")); self.assertEqual(tr.gate.mode, "SIM")
        self.assertIsInstance(tr.broker, SimBroker); self.assertIs(e.sim_broker, tr.broker)
        self.assertFalse(tr.gate.armed)                                   # a switch disarms: ARM again on purpose
        tr.gate.arm(True)
        placed_before = len([c for c in s.app.calls if c[0] == "placeOrder"])
        self.assertTrue(tr.submit("AAA", "BUY", 10.00, 100, T0 + 3, bracket=False)["ok"])
        quote(e, 9.99, 10.00, T0 + 4)
        self.assertEqual(int(tr.broker.position("AAA")), 100)             # filled on the desk
        self.assertEqual(len([c for c in s.app.calls if c[0] == "placeOrder"]), placed_before)   # nothing went to IBKR
        back = tr.set_mode("PAPER", T0 + 5)
        self.assertFalse(back["ok"]); self.assertIn("holding AAA", back["reason"])
        self.assertTrue(tr.flatten("AAA", T0 + 6)["ok"]); quote(e, 9.99, 10.00, T0 + 7)
        self.assertEqual(int(tr.broker.position("AAA")), 0)
        back = tr.set_mode("PAPER", T0 + 8)
        self.assertTrue(back["ok"], back.get("reason")); self.assertEqual(tr.gate.mode, "PAPER"); self.assertEqual(tr.gate.accounts, ["DU1"])
        self.assertIsInstance(tr.broker, IbkrBroker); self.assertIsNone(e.sim_broker)

    def test_a_working_order_blocks_the_switch(self):
        e, tr, s = live_desk(); tr.gate.arm(True)
        self.assertTrue(tr.submit("AAA", "BUY", 9.90, 100, T0 + 2, bracket=False)["ok"])
        out = tr.set_mode("SIM", T0 + 3)
        self.assertFalse(out["ok"]); self.assertIn("working order", out["reason"])
        self.assertEqual(tr.gate.mode, "PAPER")

    def test_the_practice_desk_cannot_go_to_paper(self):
        c = cfg(trading={"auto_second_entry": False})
        e = Engine(plays(), c); e.on_connection("DEMO", "", 0.0)
        gate = TradingGate(c); gate.set_sim()
        sim = SimBroker(e); e.sim_broker = sim
        tr = Trader(e, c, sim, gate); e.trader = tr
        out = tr.set_mode("PAPER", 1.0)
        self.assertFalse(out["ok"]); self.assertIn("Gateway", out["reason"])
        self.assertEqual(tr.set_mode("SIM", 1.0), {"ok": True, "mode": "SIM"})

    def test_bad_word(self):
        e, tr, s = live_desk()
        self.assertFalse(tr.set_mode("LIVE", T0)["ok"])

    def test_snapshot_says_sim(self):
        e, tr, s = live_desk()
        tr.set_mode("SIM", T0 + 2)
        self.assertEqual(tr.snapshot(run_watchdog=False)["mode"], "SIM")


if __name__ == "__main__":
    unittest.main()
