"""OPEN INTEREST on the OPTION CHAIN and the option chart: the morning number kept per day, the change against
yesterday morning, today's traded contracts against this morning's open interest (MORE / LESS), the file across
restarts, NEW on a flow print bigger than the open interest, the IBKR tick routing."""

import json
import os
import tempfile
import time
import unittest

from helpers import cfg, plays
from twiney import studies
from twiney.engine import Engine
from twiney.options import key_of


def noon(day_offset=0):
    d = studies.ny(time.time()).replace(hour=12, minute=0, second=0, microsecond=0)
    return d.timestamp() + day_offset * 86400


class OpenInterestTests(unittest.TestCase):
    def setUp(self):
        self.eng = Engine(plays(), cfg())
        self.key = key_of("AAA", "20261016", 10.0, "C")

    def test_morning_number_is_the_first_of_the_day(self):
        t = noon()
        self.eng.on_opt_oi(self.key, 1200, t)
        self.eng.on_opt_oi(self.key, 1500, t + 60)           # a later tick the same day: this morning's stays 1200
        v = self.eng.oi_view(self.key, t + 120)
        self.assertEqual(v["oi"], 1200)
        self.assertIsNone(v["oi_prev"]); self.assertIsNone(v["oi_change"]); self.assertIsNone(v["open_read"])

    def test_more_and_less_against_this_morning(self):
        t = noon()
        self.eng.on_opt_oi(self.key, 1000, t)
        self.eng.on_opt_size(self.key, "volume", 400, t + 10)
        self.assertEqual(self.eng.oi_view(self.key, t + 20)["open_read"], "LESS")
        self.eng.on_opt_size(self.key, "volume", 1600, t + 30)
        v = self.eng.oi_view(self.key, t + 40)
        self.assertEqual((v["open_read"], v["vol"]), ("MORE", 1600))

    def test_change_against_yesterday_morning_and_the_file(self):
        with tempfile.TemporaryDirectory() as d:
            self.eng.oi_path = os.path.join(d, "oi.jsonl")
            self.eng.on_opt_oi(self.key, 900, noon(-1))      # yesterday's morning number
            self.eng.on_opt_oi(self.key, 1300, noon())       # this morning
            v = self.eng.oi_view(self.key, noon() + 60)
            self.assertEqual((v["oi"], v["oi_prev"], v["oi_change"]), (1300, 900, 400))
            rows = [json.loads(x) for x in open(self.eng.oi_path, encoding="utf-8")]
            self.assertEqual([r["oi"] for r in rows], [900, 1300])
            # a restart: the file brings yesterday back
            eng2 = Engine(plays(), cfg())
            eng2.oi_path = self.eng.oi_path
            self.assertEqual(eng2.load_oi(), 2)
            eng2.on_opt_oi(self.key, 1350, noon() + 3600)    # today's first tick after the restart: this morning's stays the file's 1300
            v2 = eng2.oi_view(self.key, noon() + 3700)
            self.assertEqual((v2["oi"], v2["oi_prev"], v2["oi_change"]), (1300, 900, 400))

    def test_chain_rows_carry_the_read_on_practice(self):
        t = noon()
        self.eng.connection["state"] = "DEMO"
        self.eng.on_l1("AAA", "last", 10.0, t)
        ch = self.eng.option_chain("AAA", right="C", t=t)
        self.assertTrue(ch["available"])
        r = ch["rows"][len(ch["rows"]) // 2]
        self.assertIsNotNone(r["oi"]); self.assertIsNotNone(r["vol"]); self.assertIn(r["open_read"], ("MORE", "LESS"))
        # the practice numbers are steady: the same strike reads the same next poll
        ch2 = self.eng.option_chain("AAA", right="C", t=t + 5)
        r2 = next(x for x in ch2["rows"] if x["key"] == r["key"])
        self.assertEqual((r2["oi"], r2["vol"]), (r["oi"], r["vol"]))

    def test_option_chart_header_carries_it(self):
        t = noon()
        self.eng.connection["state"] = "DEMO"
        self.eng.on_l1("AAA", "last", 10.0, t)
        ch = self.eng.option_chain("AAA", right="C", t=t)
        key = ch["rows"][0]["key"]
        d = self.eng.option_bars(key, t)
        self.assertIn("oi", d); self.assertIsNotNone(d["oi"]["oi"]); self.assertIn(d["oi"]["open_read"], ("MORE", "LESS"))

    def test_flow_print_bigger_than_open_interest_is_new(self):
        t = noon()
        self.eng.on_opt_oi(self.key, 800, t)
        base = {"symbol": "AAA", "strike": 10.0, "cp": "C", "expiry": "2026-10-16", "dte": 5.0, "price": 0.5, "spot": 10.0,
                "side": "ask", "kind": "sweep", "otm_pct": 0.0, "oi": None, "iv": None, "t_ok": True}
        self.eng.on_flow(dict(base, t=t + 10, size=1200, premium=60000, vid="a"), t + 10)
        self.eng.on_flow(dict(base, t=t + 20, size=300, premium=15000, vid="b"), t + 20)
        recent = {p["vid"]: p for p in self.eng.flow.recent}
        self.assertEqual(recent["a"]["opening"], "NEW"); self.assertEqual(recent["a"]["oi"], 800)
        self.assertIsNone(recent["b"]["opening"])            # smaller than the open interest: the tape does not say
        # the vendor's own open interest on the print wins when it is there
        self.eng.on_flow(dict(base, t=t + 30, size=500, premium=25000, vid="c", oi=200), t + 30)
        self.assertEqual({p["vid"]: p for p in self.eng.flow.recent}["c"]["opening"], "NEW")


class IbkrTickRoutingTests(unittest.TestCase):
    def test_oi_and_volume_ticks_reach_the_engine(self):
        from twiney import ibkr
        calls = []

        class Eng:
            connection = {"state": "CONNECTED"}
            def opt_sim(self, t): return False
            def on_opt_oi(self, key, v, t): calls.append(("oi", key, v))
            def on_opt_size(self, key, f, v, t): calls.append((f, key, v))
            def on_l1(self, *a): calls.append(("l1",) + a)
        app = ibkr.TwineyWrapper(Eng(), None, clock=lambda: 1.0)     # the wrapper's tick handlers, no ibapi needed
        app.req[7] = ("opt", "AAA 20261016 10C")
        app.tickSize(7, 27, 4321)        # call open interest
        app.tickSize(7, 29, 987)         # call volume
        app.tickSize(7, 0, 12)           # bid size: the usual path
        self.assertIn(("oi", "AAA 20261016 10C", 4321), calls)
        self.assertIn(("volume", "AAA 20261016 10C", 987), calls)
        self.assertIn(("bid_size", "AAA 20261016 10C", 12), calls)
        self.assertEqual(ibkr.OPT_GENERIC_TICKS, "100,101")


if __name__ == "__main__":
    unittest.main()
