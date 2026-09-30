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
