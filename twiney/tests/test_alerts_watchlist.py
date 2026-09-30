import json
import os
import tempfile
import time
import unittest

from helpers import cfg, plays
from twiney.engine import Engine
from twiney.flow import normalize_equity


def _print(sym, strike, prem, cp="C", dte=3, spot=100.0, side="ask", t=1000.0):
    return {"t": t, "symbol": sym, "strike": strike, "cp": cp, "expiry": "2026-10-03", "dte": dte, "size": 100, "price": prem / 10000.0,
            "premium": prem, "spot": spot, "side": side, "kind": "sweep", "otm_pct": 2.0, "oi": None, "iv": None, "t_ok": True, "vid": f"{sym}{t}"}


class WatchlistTests(unittest.TestCase):
    def test_typed_ticker_can_be_removed_with_its_quotes_and_alerts(self):
        e = Engine(plays(), cfg(), None)
        gone = []
        e.remove_listeners.append(gone.append)
        self.assertIsNotNone(e.add_play("XYZ", 1.0))
        self.assertIn("XYZ", e.syms)
        e.add_user_alert("XYZ", "price", 1.0, price=10.0)
        self.assertTrue(e.remove_play("XYZ", 2.0))
        self.assertNotIn("XYZ", e.syms)
        self.assertNotIn("XYZ", [p["symbol"] for p in e.plays])
        self.assertEqual(gone, ["XYZ"])
        self.assertEqual(e.user_alerts, [])
        self.assertFalse(e.remove_play("XYZ", 3.0))
        self.assertNotIn("XYZ", e.snapshot(3.0)["symbols"])


class UserAlertTests(unittest.TestCase):
    def setUp(self):
        self.e = Engine(plays(), cfg(), None)
        self.sym = plays()[0]["symbol"]
        self.got = []
        self.e.listeners.append(self.got.append)

    def test_price_alert_fires_on_the_hit_then_is_gone(self):
        e, s = self.e, self.sym
        e.on_l1(s, "last", 99.0, 1.0)
        a, why = e.add_user_alert(s, "price", 1.0, price=100.0)
        self.assertEqual(a["side"], "below")
        e.on_l1(s, "last", 99.5, 2.0)
        self.assertEqual(self.got, [])
        e.on_l1(s, "last", 100.2, 3.0)
        self.assertEqual([g["label"] for g in self.got], ["PRICE ALERT"])
        self.assertIn("hit 100.00", self.got[0]["text"])
        self.assertEqual(e.user_alerts, [])                               # one-shot
        self.assertEqual(e.voice[0]["kind"], "alert")
        self.assertIn("price alert", e.voice[0]["text"])

    def test_above_and_below_need_a_cross_and_repeat_keeps_it(self):
        e, s = self.e, self.sym
        e.on_l1(s, "last", 105.0, 1.0)
        e.add_user_alert(s, "price", 1.0, price=100.0, when="above", repeat=True)    # already above: needs a dip and a cross
        e.on_l1(s, "last", 106.0, 2.0)
        self.assertEqual(self.got, [])
        e.on_l1(s, "last", 99.0, 3.0)
        e.on_l1(s, "last", 100.5, 4.0)
        self.assertEqual(len(self.got), 1)
        self.assertEqual(len(e.user_alerts), 1)                            # repeat: still there
        e.on_l1(s, "last", 99.0, 5.0); e.on_l1(s, "last", 101.0, 6.0)
        self.assertEqual(len(self.got), 1)                                 # inside the cooldown
        e.on_l1(s, "last", 99.0, 70.0); e.on_l1(s, "last", 101.0, 71.0)
        self.assertEqual(len(self.got), 2)
        e.add_user_alert(s, "price", 71.0, price=95.0, when="below")
        e.on_print(s, 94.9, 100, "NSDQ", 72.0)                              # prints count too
        self.assertEqual(self.got[-1]["label"], "PRICE ALERT")
        self.assertIn("went below 95.00", self.got[-1]["text"])

    def test_flow_alert_fires_on_bought_premium_of_the_asked_kind(self):
        e, s = self.e, self.sym
        e.add_user_alert(s, "flow", 1.0, min_premium=200000, cp="C")
        e.on_flow(_print(s, 105, 150000, t=2.0), 2.0)                       # too small
        e.on_flow(_print(s, 105, 300000, cp="P", t=3.0), 3.0)               # puts: not asked
        e.on_flow(_print(s, 105, 300000, side="bid", t=4.0), 4.0)           # sold, not bought
        self.assertEqual([g["label"] for g in self.got if g["label"] == "FLOW ALERT"], [])
        e.on_flow(_print(s, 105, 300000, t=5.0), 5.0)
        fa = [g for g in self.got if g["label"] == "FLOW ALERT"]
        self.assertEqual(len(fa), 1)
        self.assertIn("$300K of calls bought at the ask", fa[0]["text"])
        self.assertEqual(e.user_alerts, [])

    def test_equity_alert_and_the_equity_feed(self):
        e, s = self.e, self.sym
        e.add_user_alert(s, "equity", 1.0, min_dollars=1000000)
        e.on_equity({"t": 2.0, "symbol": s, "size": 5000, "price": 100.0, "dollars": 500000, "side": "mid", "dark": True, "venue": "DARK", "vid": "a"}, 2.0)
        e.on_equity({"t": 3.0, "symbol": s, "size": 20000, "price": 100.0, "dollars": 2000000, "side": "ask", "dark": True, "venue": "DARK", "vid": "b"}, 3.0)
        eq = [g for g in self.got if g["label"] == "EQUITY FLOW"]
        self.assertEqual(len(eq), 1)
        self.assertIn("$2.0M print", eq[0]["text"])
        self.assertIn("dark pool", eq[0]["text"])
        snap = e.snapshot(4.0)
        self.assertEqual([p["vid"] for p in snap["equity"]], ["b", "a"])
        self.assertEqual(snap["user_alerts"], [])

    def test_alerts_survive_a_restart(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "alerts.json")
            e = Engine(plays(), cfg(), None); e.load_user_alerts(path)
            e.add_user_alert(self.sym, "price", 1.0, price=123.45, note="pivot retest")
            e.add_user_alert(self.sym, "flow", 1.0, min_premium=250000)
            e2 = Engine(plays(), cfg(), None); e2.load_user_alerts(path)
            self.assertEqual([(a["kind"], a.get("price"), a.get("note")) for a in e2.user_alerts],
                             [("price", 123.45, "pivot retest"), ("flow", None, "")])
            e2.remove_user_alert(e2.user_alerts[0]["id"], 2.0)
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(len(json.load(fh)["alerts"]), 1)


class LadderFlowMarkTests(unittest.TestCase):
    def test_big_flow_marks_the_row_where_the_stock_traded_and_repeat_short_dated_is_hot(self):
        e = Engine(plays(), cfg(), None); s = plays()[0]["symbol"]; st = e.syms[s]
        got = []; e.listeners.append(got.append)
        e.on_flow(_print(s, 105, 50000, spot=100.2, t=1.0), 1.0)              # under the mark floor
        self.assertEqual(len(st.flow_marks), 0)
        e.on_flow(_print(s, 105, 400000, spot=100.2, t=2.0), 2.0)
        e.on_flow(_print(s, 110, 250000, cp="P", spot=100.2, t=3.0), 3.0)
        e.on_flow(_print(s, 105, 600000, spot=100.5, t=60.0), 60.0)           # the same strike again, 3 days out: repeat
        rows = e._flow_rows(st, 61.0, 0.01)
        from twiney.prices import price_key
        r1 = rows[price_key(100.2, 0.01)]
        self.assertEqual((r1["c"], r1["p"], r1["n"]), (400000, 250000, 2))
        self.assertTrue(r1["hot"] and rows[price_key(100.5, 0.01)]["hot"])
        self.assertEqual(r1["items"][0]["strike"], 105)
        rf = [g for g in got if g["label"] == "REPEAT FLOW"]
        self.assertEqual(len(rf), 1)
        self.assertIn("105.00 strike expiring in 3 days bought at the ask 2 times", rf[0]["text"])
        self.assertEqual(rf[0]["premium"], 1000000)
        self.assertTrue(any(v["kind"] == "rflow" for v in e.voice))
        # the ladder rows carry it
        e.on_l1(s, "bid", 100.4, 62.0); e.on_l1(s, "ask", 100.41, 62.0)
        lad = e._memory_ladder(st, 62.0, e._user_levels(st.play), half_rows=40)
        marked = [r for r in lad["rows"] if r.get("flow")]
        self.assertEqual({float(r["price"]) for r in marked}, {100.2, 100.5})
        # a print a week+ out is marked but never hot on its own
        e.on_flow(_print(s, 120, 900000, dte=30, spot=100.4, t=63.0), 63.0)
        self.assertFalse(e._flow_rows(st, 64.0, 0.01)[price_key(100.4, 0.01)]["hot"])

    def test_index_products_need_more(self):
        e = Engine(plays(), cfg(), None)
        e.add_play("SPY", 1.0); st = e.syms["SPY"]
        e.on_flow(_print("SPY", 570, 400000, spot=568.0, t=2.0), 2.0)
        self.assertEqual(len(st.flow_marks), 0)
        e.on_flow(_print("SPY", 570, 4000000, spot=568.0, t=3.0), 3.0)
        self.assertEqual(len(st.flow_marks), 1)


class EquityNormalizeTests(unittest.TestCase):
    def test_vendor_shapes(self):
        p = normalize_equity({"ticker": "NVDA", "shares": 25000, "price": 128.4, "notional": 3210000, "side": "ASK", "venue": "FINRA ADF", "time": "2026-09-30T14:31:05Z", "id": "x1"}, 1_790_000_000)
        self.assertEqual((p["symbol"], p["size"], p["dollars"], p["side"], p["dark"], p["vid"]), ("NVDA", 25000, 3210000, "ask", True, "x1"))
        q = normalize_equity({"symbol": "amd", "tradeSize": "10000", "tradePrice": 158.7, "tradeType": "block", "exchange": "NYSE"}, 1_790_000_000)
        self.assertEqual((q["symbol"], q["dollars"], q["dark"], q["venue"]), ("AMD", 1587000.0, False, "NYSE"))
        self.assertIsNone(normalize_equity({"ticker": "AMD"}, 1.0))


if __name__ == "__main__":
    unittest.main()
