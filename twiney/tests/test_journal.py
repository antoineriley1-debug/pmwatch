import os
import tempfile
import unittest

from helpers import cfg, plays
from twiney.desk import Desk
from twiney.engine import Engine


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.c = cfg()
        self.c["recording"]["dir"] = self.dir
        self.ps = plays()
        self.sym = self.ps[0]["symbol"]

    def desk(self):
        e = Engine(self.ps, self.c, None)
        return e, Desk(e, self.c, self.ps, "t")

    def test_ibkr_resend_is_counted_once(self):
        e, k = self.desk()
        for _ in range(3):   # the first delivery and two execution refreshes
            e.on_fill("E1", self.sym, "BOT", 100, 10.0, "", 1.0)
            e.on_fill("E2", self.sym, "SLD", 100, 10.5, "", 2.0)
        self.assertEqual([t["pnl"] for t in k.trades], [50.0])
        self.assertEqual(e.day_pnl()["realized"], 50.0)

    def test_reversal_is_two_trades(self):
        e, k = self.desk()
        e.on_fill("E1", self.sym, "BOT", 100, 10.0, "", 1.0)
        e.on_fill("E2", self.sym, "SLD", 200, 11.0, "", 2.0)
        e.on_fill("E3", self.sym, "BOT", 100, 11.5, "", 3.0)
        self.assertEqual([(t["side"], t["shares"], t["pnl"]) for t in k.trades], [("long", 100.0, 100.0), ("short", 100.0, -50.0)])
        self.assertEqual(len({t["id"] for t in k.trades}), 2)

    def test_open_trade_survives_a_restart(self):
        e, k = self.desk()
        e.on_fill("E1", self.sym, "BOT", 100, 20.0, "", 1.0)
        e2, k2 = self.desk()
        e2.on_fill("E1", self.sym, "BOT", 100, 20.0, "", 5.0)   # re-sent after the restart: already counted
        e2.on_fill("E2", self.sym, "SLD", 100, 21.0, "", 6.0)
        self.assertEqual([(t["side"], t["pnl"]) for t in k2.trades], [("long", 100.0)])

    def test_damaged_line_does_not_erase_the_journal(self):
        e, k = self.desk()
        e.on_fill("E1", self.sym, "BOT", 100, 10.0, "", 1.0)
        e.on_fill("E2", self.sym, "SLD", 100, 10.5, "", 2.0)
        with open(k.trades_path, "a", encoding="utf-8") as fh:
            fh.write('{"cut off')
        _e, k2 = self.desk()
        self.assertEqual(len(k2.trades), 1)

    def test_day_pnl_keeps_every_fill(self):
        e, _k = self.desk()
        for i in range(150):   # 300 executions, each round trip -10
            e.on_fill(f"B{i}", self.sym, "BOT", 100, 10.0, "", i)
            e.on_fill(f"S{i}", self.sym, "SLD", 100, 9.9, "", i + 0.5)
        self.assertAlmostEqual(e.day_pnl()["realized"], -1500.0)


class TradeLogTests(unittest.TestCase):
    """The symbol's trade log: levels you set, what you said, what you typed - and the closed trade carries it."""

    def _desk(self):
        import tempfile
        from twiney.engine import Engine
        from twiney.desk import Desk
        from helpers import cfg, plays
        e = Engine(plays(), cfg(), None)
        d = tempfile.mkdtemp()
        desk = Desk(e, cfg(), plays(), "0", prefix="t", base_dir=d)
        e.desk = desk
        return e, desk

    def test_levels_said_and_typed_land_in_the_log_in_order(self):
        e, desk = self._desk()
        s = e.plays[0]["symbol"]
        e.set_play_level(s, "stop", 9.5, 100.0, source="PLAY SETUP")
        e.set_play_level(s, "stop", 9.4, 101.0, source="chart")
        e.set_play_level(s, "second_entry", 10.6, 102.0)
        e.set_play_level(s, "second_entry", None, 103.0)
        v = desk.mic_start(104.0, s)                       # no recording on: still a voice note
        self.assertLess(v["n"], 0)
        desk.mic_text(v["n"], "seller at the half reloading, waiting for the second entry", 110.0)
        desk.add_note(111.0, "size thinning on the offer", s, kind="typed")
        log = e.symbol_log(s)
        self.assertEqual([n["kind"] for n in log], ["level", "level", "level", "level", "voice", "typed"])
        self.assertEqual([n["text"] for n in log][:4], ["STOP set 9.50", "STOP 9.50 → 9.40", "2ND ENTRY 10.10 → 10.60", "2ND ENTRY cleared (was 10.60)"])
        self.assertEqual(log[4]["t"], 104.0)                # stamped when the mic went on, not when it stopped
        self.assertTrue(log[4]["text"].startswith("🎙 seller at the half"))
        self.assertEqual(e.symbol_log("ZZZZ"), [])
        pane = e._pane(s, 0, 112.0, [], full=False)
        self.assertEqual(len(pane["log"]), 6)

    def test_the_closed_trade_carries_its_log_and_the_csv_has_it(self):
        e, desk = self._desk()
        s = e.plays[0]["symbol"]
        e.set_play_level(s, "stop", 9.5, 1000.0)
        desk.add_note(1005.0, "going long over the pivot", s, kind="typed")
        desk.on_fill({"symbol": s, "side": "BOT", "shares": 100, "price": 10.0, "exec_id": "a"}, 1010.0)
        desk.add_note(1020.0, "stop to breakeven", s, kind="typed")
        desk.on_fill({"symbol": s, "side": "SLD", "shares": 100, "price": 10.5, "exec_id": "b"}, 1030.0)
        tr = desk.trades[-1]
        self.assertIn("STOP set 9.50", tr["log"])
        self.assertIn("going long over the pivot | ", tr["log"])
        self.assertIn("stop to breakeven", tr["log"])
        csv = desk.trades_csv()
        self.assertIn("trade log", csv.splitlines()[0])
        self.assertIn("stop to breakeven", csv)
