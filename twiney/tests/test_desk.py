import json
import os
import tempfile
import unittest

from helpers import ASK, BID, INSERT, UPDATE, cfg, plays
from twiney.desk import Desk
from twiney.engine import Engine
from twiney.recorder import read_events
from twiney.replay import replay


class DeskTests(unittest.TestCase):
    def test_rec_marks_notes_journal_and_mid_session_replay(self):
        with tempfile.TemporaryDirectory() as d:
            c = cfg(recording={"enabled": True, "dir": d})
            e = Engine(plays(), c)
            e.on_connection("CONNECTED", "", 0.0)
            e.on_l1("AAA", "last", 10.01, 1.0)
            e.tick(1.0)
            for i in range(3):
                e.on_depth("AAA", i, INSERT, BID, round(9.99 - i * 0.01, 2), 500, "", 2.0)
                e.on_depth("AAA", i, INSERT, ASK, round(10.00 + i * 0.01, 2), 800, "", 2.0)
            desk = Desk(e, c, plays(), "test", prefix="t", base_dir=d)
            self.assertFalse(desk.recording)
            path = desk.start(5.0)                      # mid-session: the book is dumped first
            self.assertTrue(desk.recording)
            m = desk.mark(6.0, "AAA", "seller sitting at 10")
            desk.add_note(6.5, "watching the pivot", "AAA")
            e.on_print("AAA", 10.00, 300, "X", 7.0)
            self.assertEqual(desk.toggle(8.0)["recording"], False)
            self.assertTrue(os.path.exists(desk.journal_path))
            journal = open(desk.journal_path, encoding="utf-8").read()
            self.assertIn("seller sitting at 10", journal)
            self.assertIn("watching the pivot", journal)
            kinds = [ev["ev"] for ev in read_events(path)]
            self.assertEqual(kinds[0], "session")
            self.assertIn("depth", kinds); self.assertIn("mark", kinds); self.assertIn("note", kinds); self.assertIn("print", kinds)
            # the recording replays with the dumped book in place
            r, _ = replay(path)
            self.assertEqual(r.syms["AAA"].book.best(BID), 9.99)
            self.assertEqual(r.marks_list[0]["note"], "seller sitting at 10")
            self.assertEqual(r.notes_list[0]["text"], "watching the pivot")
            listed = desk.list_recordings()
            self.assertEqual(listed[0]["marks"][0]["n"], m["n"])
            self.assertTrue(listed[0]["journal"])
