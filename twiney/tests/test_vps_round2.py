"""Round two of the VPS findings: the OVERNIGHT venue for stock limits between 8 PM and 3:50 AM ET; the market
feed asks an unanswered request again instead of giving up; the snapshot comes down as diffs for a page that says
who it is."""

import datetime as dt
import json
import unittest
import urllib.request
from zoneinfo import ZoneInfo

from helpers import cfg, plays
from twiney.dashboard import Dashboard
from twiney.engine import Engine
from twiney.ibkr import MarketDataSession
from twiney.trading import IbkrBroker, Trader, TradingGate

NY = ZoneInfo("America/New_York")


def at(year, month, day, hour, minute):
    return dt.datetime(year, month, day, hour, minute, tzinfo=NY).timestamp()


class OvernightWindowTests(unittest.TestCase):
    def test_the_window(self):
        w = MarketDataSession.overnight_window
        self.assertTrue(w(at(2026, 10, 13, 22, 0)))        # Tuesday 10 PM
        self.assertTrue(w(at(2026, 10, 14, 3, 30)))        # Wednesday 3:30 AM
        self.assertFalse(w(at(2026, 10, 14, 3, 55)))       # 3:55 AM: the 4 AM session is next
        self.assertFalse(w(at(2026, 10, 14, 10, 0)))       # regular hours
        self.assertFalse(w(at(2026, 10, 14, 19, 0)))       # after hours, before 8 PM
        self.assertTrue(w(at(2026, 10, 18, 21, 0)))        # Sunday 9 PM: the week's first session
        self.assertFalse(w(at(2026, 10, 16, 21, 0)))       # Friday 9 PM: no session
        self.assertFalse(w(at(2026, 10, 17, 1, 0)))        # Saturday


class OvernightRoutingTests(unittest.TestCase):
    def make(self, t):
        from test_ibkr import FakeApp, fake_order
        c = cfg(trading={"sim_options_after_hours": False})
        e = Engine(plays(), c)
        clock = lambda: t
        gate = TradingGate(c); gate.arm(True)
        s = MarketDataSession(e, c, plays(), FakeApp, contract_factory=lambda p: (p["symbol"], p.get("exchange")), clock=clock,
                              order_factory=fake_order, gate=gate)
        e.trader = Trader(e, c, IbkrBroker(e, s), gate)
        s.step(t)                      # connects the fake app
        s.app.nextValidId(100)
        s.app.managedAccounts("DU1")   # a paper account: the gate opens
        gate.arm(True)
        return s, e

    def placed(self, s):
        return [c for c in s.app.calls if c[0] == "placeOrder"]

    def test_a_limit_at_10_pm_goes_to_the_overnight_venue(self):
        s, e = self.make(at(2026, 10, 13, 22, 0))
        s.send_order("AAA", "BUY", 100, 10.0, "LMT", None, "entry", "DAY", at(2026, 10, 13, 22, 0))
        _n, oid, contract, order = self.placed(s)[-1]
        self.assertEqual(contract, ("AAA", "OVERNIGHT"))
        self.assertTrue(order["outside_rth"]); self.assertEqual(order["tif"], "DAY")
        self.assertTrue(s.my_orders[oid]["overnight"])
        self.assertEqual(e.orders[f"id{oid}"].get("venue"), "OVERNIGHT")
        self.assertTrue(any("OVERNIGHT venue" in m.get("text", "") for m in e.messages))

    def test_a_stop_limit_at_10_pm_stays_on_smart_and_is_explained(self):
        s, e = self.make(at(2026, 10, 13, 22, 0))
        s.send_order("AAA", "SELL", 100, 9.80, "STP LMT", None, "stop", "DAY", at(2026, 10, 13, 22, 0), aux=9.90)
        _n, oid, contract, _o = self.placed(s)[-1]
        self.assertEqual(contract, ("AAA", "SMART"))
        self.assertFalse(s.my_orders[oid]["overnight"])
        self.assertTrue(any("4:00 AM" in m.get("text", "") for m in e.messages))

    def test_a_limit_in_regular_hours_stays_on_smart(self):
        s, e = self.make(at(2026, 10, 14, 10, 0))
        s.send_order("AAA", "BUY", 100, 10.0, "LMT", None, "entry", "DAY", at(2026, 10, 14, 10, 0))
        self.assertEqual(self.placed(s)[-1][2], ("AAA", "SMART"))

    def test_the_switch_off(self):
        s, e = self.make(at(2026, 10, 13, 22, 0))
        s.cfg["trading"]["overnight_venue"] = False
        s.send_order("AAA", "BUY", 100, 10.0, "LMT", None, "entry", "DAY", at(2026, 10, 13, 22, 0))
        self.assertEqual(self.placed(s)[-1][2], ("AAA", "SMART"))


class SnapshotDiffTests(unittest.TestCase):
    def setUp(self):
        self.engine = Engine(plays(), cfg())
        self.engine.on_l1("AAA", "last", 10.0, 1.0)
        self.dash = Dashboard(self.engine, "127.0.0.1", 0, clock=lambda: 2.0).start()

    def tearDown(self):
        self.dash.stop()

    def get(self, path):
        with urllib.request.urlopen(self.dash.url + path, timeout=5) as r:
            return r.read()

    def test_a_page_with_an_id_gets_only_what_changed(self):
        full = self.get("/api/state")
        first = self.get("/api/state?c=pageA")
        self.assertNotIn(b'"_keep"', full)
        j1 = json.loads(first)
        self.assertEqual(j1["_keep"], [])                       # the first time: everything
        self.assertIn("panes/n", j1); self.assertIn("ranking", j1)    # the panes come field by field
        self.assertNotIn("panes", j1)
        second = self.get("/api/state?c=pageA")
        j2 = json.loads(second)
        self.assertIn("ranking", j2["_keep"]); self.assertIn("panes/n", j2["_keep"])   # the clock is frozen: nothing changed
        self.assertNotIn("ranking", j2)
        self.assertLess(len(second), len(first) // 4)
        other = json.loads(self.get("/api/state?c=pageB"))       # another page starts from the whole thing
        self.assertEqual(other["_keep"], [])


if __name__ == "__main__":
    unittest.main()
