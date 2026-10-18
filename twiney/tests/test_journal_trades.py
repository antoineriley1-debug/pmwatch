import os
import tempfile
import unittest

from helpers import cfg, plays
from twiney.desk import Desk
from twiney.engine import Engine
from twiney.trading import SimBroker, Trader, TradingGate


class TradeJournalTests(unittest.TestCase):
    """Every trade — stock or option — lands in the journal: the plan when you got in, every order, fill, line, mark and
    spoken word on the stock, the RESULT (win / loss, $, %, R against the planned stop), a name you can change, and a
    saved page per trade. A stock trade and an option trade on the same ticker are two journal entries."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        c = cfg(recording={"enabled": True, "dir": self.tmp.name, "mark_screenshot": False})
        self.e = e = Engine(plays(), c); e.on_connection("DEMO", "", 0.0)
        self.desk = Desk(e, c, plays(), "test", base_dir=self.tmp.name)
        gate = TradingGate(c); gate.set_sim(); gate.arm(True)
        self.tr = Trader(e, c, SimBroker(e), gate); e.trader = self.tr
        e.on_l1("AAA", "last", 10.00, 1.0)

    def tearDown(self):
        self.tmp.cleanup()

    def test_stock_trade_result_r_name_transcript_marks_and_page(self):
        e, d = self.e, self.desk
        e.set_play_level("AAA", "second_entry", 10.08, 1.0, source="chart")
        e.set_play_level("AAA", "stop", 9.60, 1.0, source="chart")
        e.set_play_level("AAA", "target", 11.00, 1.0, source="chart")
        e.on_fill("x1", "AAA", "BOT", 100, 10.10, "10:00", 2.0)
        n = d.mic_start(3.0, "AAA"); d.mic_text(n["n"], "reload seller got cleaned up, holding for the target", 4.0)
        m = d.mark(5.0, "AAA", "buyers stepping up")
        self.assertIn("AAA 10.0", m["context"]); self.assertIn("2nd 10.08", m["context"]); self.assertNotIn("tape ·", m["context"])
        self.assertEqual(len(d.open_view()), 1)
        tid = d.open_view()[0]["id"]
        self.assertTrue(d.tag_trade(tid, name="AAA 2nd entry breakout"))          # named while in it
        e.on_fill("x2", "AAA", "SLD", 100, 10.60, "10:05", 6.0)
        t = d.trades[-1]
        self.assertEqual((t["name"], t["result"], t["pnl"]), ("AAA 2nd entry breakout", "WIN", 50.0))
        self.assertEqual(t["r"], 1.0)                                              # +0.50 against a 0.50 planned risk
        self.assertEqual(t["plan"]["stop"], 9.60)
        self.assertEqual(t["transcript"][0]["text"], "reload seller got cleaned up, holding for the target")
        self.assertEqual(t["marks"][0]["note"], "buyers stepping up")
        self.assertIn("FILL BOUGHT 100 AAA @ 10.1", t["log"]); self.assertIn("2ND ENTRY 10.10 → 10.08", t["log"])
        page = os.path.join(d.journal_dir(), t["file"])
        body = open(page, encoding="utf-8").read()
        self.assertIn("# AAA 2nd entry breakout", body); self.assertIn("WIN", body); self.assertIn("holding for the target", body)
        self.assertTrue(d.tag_trade(t["id"], name="renamed play", grade="A"))     # renamed: the page follows
        self.assertFalse(os.path.exists(page))
        self.assertTrue(os.path.exists(os.path.join(d.journal_dir(), d.trades[-1]["file"])))

    def test_option_trade_is_journaled_in_dollars_beside_a_stock_trade(self):
        e, d = self.e, self.desk
        key = "AAA 20261009 10C"
        e.on_fill("s1", "AAA", "BOT", 100, 10.00, "10:00", 2.0)                    # the stock trade
        e.on_opt_fill("o1", key, "BOT", 2, 1.20, 2.5)                              # and an option trade on the same ticker
        self.assertEqual(sorted(v["symbol"] for v in d.open_view()), ["AAA", key])
        e.on_opt_fill("o2", key, "SLD", 2, 0.90, 4.0)
        t = d.trades[-1]
        self.assertEqual((t["symbol"], t["opt"], t["result"], t["pnl"]), (key, True, "LOSS", -60.0))   # (0.90-1.20) × 2 × 100
        self.assertEqual([v["symbol"] for v in d.open_view()], ["AAA"])           # the stock trade is still open
        self.assertIn("OPTION FILL BOT 2", t["log"])

    def test_a_stale_open_trade_is_dropped_when_the_position_is_flat(self):
        e, d = self.e, self.desk
        e.on_fill("s1", "AAA", "BOT", 100, 10.00, "10:00", 2.0)
        e.on_position("SIM", "AAA", 100, 10.0, 2.1)
        d.reconcile(30.0)
        self.assertIn("AAA", d._open)                                              # a real position: kept
        e.on_position("SIM", "AAA", 0, 0.0, 31.0)                                  # flat while TED was not watching
        d.reconcile(32.0)
        self.assertNotIn("AAA", d._open)
        e.on_fill("s2", "AAA", "BOT", 50, 10.00, "10:10", 40.0)                   # the next trade starts fresh
        e.on_fill("s3", "AAA", "SLD", 50, 10.20, "10:11", 41.0)
        self.assertEqual((d.trades[-1]["shares"], d.trades[-1]["pnl"]), (50, 10.0))

    def test_orders_land_in_the_trade_log(self):
        e, d = self.e, self.desk
        self.tr.submit("AAA", "BUY", 9.00, 100, 2.0, bracket=False)
        self.assertTrue(any(n["kind"] == "order" and "SENT BUY 100 AAA" in n["text"] for n in d.notes))


if __name__ == "__main__":
    unittest.main()
