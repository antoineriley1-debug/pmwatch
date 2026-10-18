"""OPTION MONEY: Quant Data's tools read by meaning, the desk's own reads when they are not there, the checks against
the play, the reads kept with every DESK SCORE call and THE ODDS built from them (live market only)."""

import json
import os
import tempfile
import time
import unittest
import urllib.request

from helpers import cfg, plays
from twiney import option_money as om
from twiney.dashboard import Dashboard
from twiney.engine import Engine
from twiney.scorecard import Scorecard


class ParseTests(unittest.TestCase):
    def test_max_pain_by_expiry_and_the_single_answer(self):
        rows = om.parse_max_pain_by_exp({"data": {"2026-10-24": 350.0, "2026-10-17": 355.0}})
        self.assertEqual(rows, [("20261017", 355.0), ("20261024", 350.0)])
        self.assertEqual(om.parse_max_pain({"data": {"ticker": "AAPL", "summary": {"maxPain": 352.5, "expiration": "2026-10-17"}}}),
                         {"strike": 352.5, "expiry": "20261017"})
        self.assertIsNone(om.parse_max_pain({"data": {"nothing": 1}}))

    def test_by_strike_rows_or_keyed_by_strike(self):
        rows = om.parse_by_strike({"data": [{"strike": 350, "callGamma": 1e6, "putGamma": -2e6},
                                            {"strike": 350, "callGamma": 5e5, "putGamma": 0}, {"strike": 360, "callGamma": 3e6}]})
        self.assertEqual(rows, [(350.0, 1.5e6, -2e6), (360.0, 3e6, 0.0)])
        keyed = om.parse_by_strike({"data": {"355": {"callOpenInterest": 1200, "putOpenInterest": 800}, "360": {"value": -5}}})
        self.assertEqual(keyed, [(355.0, 1200.0, 800.0), (360.0, 0.0, -5.0)])

    def test_term_structure_gives_dollars(self):
        rows = om.parse_term({"data": [{"expiration": "2026-10-24", "atmIv": 35}, {"expirationDate": "2026-10-17", "expectedMove": 4.2}]},
                             spot=100.0, now=1792245600)
        self.assertEqual(rows[0], ("20261017", 4.2, None))
        self.assertEqual(rows[1][0], "20261024")
        self.assertGreater(rows[1][1], 2.0)
        self.assertAlmostEqual(rows[1][2], 0.35)

    def test_trade_side_finds_calls_and_puts_bought_and_sold(self):
        d = om.parse_trade_side({"data": [{"contractType": "CALL", "askPremium": 900, "bidPremium": 300},
                                          {"contractType": "PUT", "aboveAskPremium": 100, "belowBidPremium": 700}]})
        self.assertEqual(d, {"calls_bought": 900, "calls_sold": 300, "puts_bought": 100, "puts_sold": 700})
        self.assertIsNone(om.parse_trade_side({"data": {"x": 1}}))


class LocalTests(unittest.TestCase):
    def test_max_pain_from_open_interest(self):
        calls = {95: 100, 100: 500, 105: 2000}
        puts = {95: 2000, 100: 500, 105: 100}
        self.assertEqual(om.max_pain_from_oi(calls, puts), 100)
        self.assertIsNone(om.max_pain_from_oi({1: 1}, {}))

    def test_big_strikes_above_and_below_biggest_first(self):
        rows = [(95, 0, 5e6), (97, 0, 1e6), (103, 2e6, 0), (105, 8e6, 0), (110, 1e5, 0)]
        b = om.big_strikes(rows, 100.0, n_each=2)
        self.assertEqual([x["strike"] for x in b], [105, 103, 97, 95])
        self.assertEqual(b[0]["rel"], 1.0)
        self.assertEqual(b[0]["side"], "calls")
        self.assertEqual(b[-1]["side"], "puts")

    def test_flow_lean_counts_prints_never_dollars(self):
        prints = [{"t": 100, "cp": "C", "side": "ask", "premium": 9e9}, {"t": 110, "cp": "P", "side": "ask", "premium": 1},
                  {"t": 120, "cp": "C", "side": "bid", "premium": 5e6}, {"t": 130, "cp": "C", "side": "ask", "premium": 10},
                  {"t": 50, "cp": "C", "side": "ask", "premium": 1}]
        d = om.local_drift(prints, 1000, 90)
        self.assertEqual((d["calls"], d["puts"], d["net"]), (2, 1, 1))          # paid-up prints only, counted
        self.assertEqual([v for _, v in d["series"]], [1, 0, 1])
        self.assertEqual((d["calls15"], d["puts15"]), (2, 1))
        self.assertEqual(om.lean_of(6, 2), "CALLS"); self.assertEqual(om.lean_of(2, 6), "PUTS")
        self.assertEqual(om.lean_of(4, 3), "EVEN"); self.assertEqual(om.lean_of(2, 0), "EVEN")

    def test_aggression(self):
        self.assertEqual(om.aggression([[1, 1.0, 30, "buy"], [2, 1.0, 10, "sell"], [3, 1.0, 10, None]]),
                         {"ask_pct": 60, "bid_pct": 20, "contracts": 50})
        self.assertIsNone(om.aggression([]))


class ViewTests(unittest.TestCase):
    def setUp(self):
        self.m = om.OptionMoney(cfg())

    def test_quant_data_first_then_the_desk(self):
        t = time.time()
        local = {"drift": {"series": [[t, 5]], "calls": 7, "puts": 2, "net": 5, "calls15": 3, "puts15": 0}, "drift_src": "FLOW",
                 "em": {"expiry": "20991231", "move": 2.0, "iv": 0.3}, "em_src": "CHAIN IV"}
        v = self.m.view("AAA", 100.0, t, local)
        self.assertEqual(v["src"]["drift"], "FLOW")
        self.assertEqual((v["drift"]["lean"], v["drift"]["lean15"]), ("CALLS", "CALLS"))
        self.assertEqual((v["em"]["lo"], v["em"]["hi"]), (98.0, 102.0))
        self.m.put("AAA", "max_pain_by_exp", [("20991231", 99.0)], time.time())
        v = self.m.view("AAA", 100.0, t, local)
        self.assertEqual((v["src"]["max_pain"], v["max_pain"]["strike"]), ("QUANT DATA", 99.0))

    def test_the_checks_against_a_play(self):
        t = time.time()
        today = time.strftime("%Y%m%d", time.gmtime(t - 4 * 3600))
        local = {"em": {"expiry": today, "move": 1.0, "iv": 0.3},
                 "oi_rows": [(102, 9e6, 0), (99, 0, 1e6)], "max_pain": {"strike": 98.0, "expiry": today},
                 "drift": {"series": [[t, -6]], "calls": 1, "puts": 7, "net": -6}}
        play = {"side": "long", "trigger": 100.0, "target": 104.0}
        v = self.m.view("AAA", 100.5, t, local, play)
        keys = {c["key"]: c for c in v["checks"]}
        self.assertEqual(keys["em"]["tone"], "warn")                     # MP 4.00 past a 1.00 expected move
        self.assertEqual(keys["strike"]["tone"], "warn")                 # 102 sits between 100 and 104
        self.assertEqual(keys["mp"]["tone"], "warn")                     # expiry today, option max pain under a long
        self.assertEqual(keys["drift"]["tone"], "warn")                  # the money leans puts against a long
        self.assertIn("option max pain", keys["mp"]["text"])

    def test_reads_in_the_calls_direction(self):
        t = time.time()
        local = {"oi_rows": [(100.5, 9e6, 0)], "max_pain": {"strike": 98.0, "expiry": "20991231"},
                 "drift": {"series": [[t, 6]], "calls": 8, "puts": 2, "net": 6, "calls15": 4, "puts15": 0}, "em": {"expiry": "20991231", "move": 3.0, "iv": 0.3},
                 "opening": om.opening_lean(500, 100, "CHAIN OI")}
        v = self.m.view("AAA", 100.0, t, local)
        up, dn = self.m.reads(v, 1, 2.0), self.m.reads(v, -1, 2.0)
        self.assertEqual((up["money"], dn["money"]), ("WITH", "AGAINST"))
        self.assertEqual((up["strike"], dn["strike"]), ("IN THE WAY", "CLEAR"))
        self.assertEqual((up["max_pain"], dn["max_pain"]), ("AWAY", "TOWARD"))
        self.assertEqual(up["em_room"], "ROOM")
        self.assertEqual((up["opening"], dn["opening"]), ("WITH", "AGAINST"))
        self.assertEqual(self.m.reads(None, 1, 1.0), {})

    def test_opening_lean_follows_the_numbers(self):
        self.assertEqual(om.opening_lean(500, 100, "x")["lean"], "CALLS")
        self.assertEqual(om.opening_lean(100, 500, "x")["lean"], "PUTS")
        self.assertEqual(om.opening_lean(100, 110, "x")["lean"], "EVEN")


class OddsTests(unittest.TestCase):
    def test_reads_ride_with_the_call_and_the_odds_count_the_live_market_only(self):
        d = tempfile.mkdtemp()
        sc = Scorecard(os.path.join(d, "score.jsonl"), {"hit_atr": 0.1})
        alert = {"role": "story", "key": "AAA|x|y|se:through", "side": "ask", "symbol": "AAA", "text": "2nd entry"}
        for i, (reads, end) in enumerate([({"money": "WITH"}, 11.0), ({"money": "WITH"}, 11.0), ({"money": "AGAINST"}, 9.0)]):
            row = sc.note(alert, 1000.0 + i, 10.0, 1.0)
            row["reads"] = reads
            sc.tick(2000.0 + i, {"AAA": end})
        practice = Scorecard(os.path.join(d, "score.jsonl"), {"hit_atr": 0.1})
        practice.src = "practice"
        row = practice.note(alert, 1000.0, 10.0, 1.0)
        row["reads"] = {"money": "AGAINST"}
        practice.tick(2000.0, {"AAA": 11.0})
        o = sc.odds()
        self.assertEqual(o["n"], 3)
        money = next(r for r in o["reads"] if r["read"] == "money")
        by = {a["answer"]: a for a in money["answers"]}
        self.assertEqual((by["WITH"]["n"], by["WITH"]["hit_pct"]), (2, 100))
        self.assertEqual((by["AGAINST"]["n"], by["AGAINST"]["hit_pct"]), (1, 0))
        self.assertEqual(practice.odds()["n"], 1)                 # the practice desk sees only its own


class FeedTests(unittest.TestCase):
    def test_check_saves_each_answer_and_says_which_tools_the_key_opens(self):
        e = Engine(plays(), cfg())
        e.cfg["recording"]["dir"] = tempfile.mkdtemp()
        e.on_l1("AAA", "last", 10.0, 1.0)

        def request(path, body):
            if path.endswith("max-pain-over-time"):
                return {"data": {"2099-12-31": 10.0}}
            if path.endswith("term-structure"):
                return {"weird": True}
            raise RuntimeError("HTTP 403 (this key's plan does not include this data)")
        f = om.OptionMoneyFeed(e, e.cfg, request)
        st = f.check()
        self.assertEqual(st["max_pain_by_exp"]["state"], "ok")
        self.assertEqual(st["term_structure"]["state"], "unread")
        self.assertEqual(st["exposure"]["state"], "no")
        self.assertTrue(os.path.exists(os.path.join(e.cfg["recording"]["dir"], "quantdata_tools", "max_pain_by_exp.json")))
        sym = f.symbols()[0] if "SPY" not in f.symbols() else "SPY"
        self.assertEqual(e.optmoney.got(sym, "max_pain_by_exp", 60), [("20991231", 10.0)])
        self.assertEqual(f.body("AAA", "exposure")["greekMode"], "GAMMA")


class EngineAndRouteTests(unittest.TestCase):
    def setUp(self):
        self.engine = Engine(plays(), cfg())
        self.engine.on_l1("AAA", "last", 10.0, 1.0)
        self.dash = Dashboard(self.engine, "127.0.0.1", 0, clock=lambda: 2.0).start()

    def tearDown(self):
        self.dash.stop()

    def test_the_pane_carries_the_option_money(self):
        t = time.time()
        self.engine.optmoney.put("AAA", "max_pain_by_exp", [("20991231", 9.5)], t)
        v = self.engine.optmoney_view("AAA", t)
        self.assertEqual(v["max_pain"]["strike"], 9.5)
        self.assertEqual(v["src"]["max_pain"], "QUANT DATA")

    def test_status_and_check_routes(self):
        with urllib.request.urlopen(self.dash.url + "/api/optmoney", timeout=5) as r:
            out = json.loads(r.read())
        self.assertTrue(out["ok"])
        self.assertFalse(out["feed"])
        self.assertIn("exposure", out["status"])
        self.assertIn("reads", out["odds"])
        req = urllib.request.Request(self.dash.url + "/api/optmoney/check", data=b"{}", method="POST", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            out = json.loads(r.read())
        self.assertFalse(out["ok"])

    def test_ps60_words_only(self):
        with open(om.__file__, encoding="utf-8") as fh:
            src = fh.read().lower()
        import re
        src = src.replace('play.get("trigger")', "")
        for bad in ("resistance", "support", "trigger", "iceberg", "dark pool", "zone", "gamma wall", "fading", "stale"):
            self.assertIsNone(re.search(r"\b" + bad + r"s?\b", src), bad)


if __name__ == "__main__":
    unittest.main()
