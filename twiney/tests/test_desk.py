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
            import io, zipfile
            data = desk.export_bundle(listed[0]["name"])
            names = zipfile.ZipFile(io.BytesIO(data)).namelist()
            stem = listed[0]["name"][:-6]
            for want in (listed[0]["name"], "SUMMARY.md", "calls.csv", stem + ".journal.md", stem + ".marks.jsonl"):
                self.assertIn(f"{stem}/{want}", names)
            summary = zipfile.ZipFile(io.BytesIO(data)).read(f"{stem}/SUMMARY.md").decode()
            self.assertIn("watching the pivot", summary)
            self.assertIn("| AAA | long |", summary)
            out = desk.delete_recording(listed[0]["name"])
            self.assertTrue(out["ok"])
            self.assertEqual(sorted(out["removed"]), sorted([listed[0]["name"], listed[0]["name"][:-6] + ".marks.jsonl", listed[0]["name"][:-6] + ".journal.md"]))
            self.assertEqual(desk.list_recordings(), [])
            self.assertFalse(desk.delete_recording("nope.jsonl")["ok"])


class TradeJournalTests(unittest.TestCase):
    def test_round_trips_are_filed_under_the_play_setup(self):
        import tempfile, json, os
        from helpers import cfg, plays
        from twiney.engine import Engine
        from twiney.desk import Desk
        with tempfile.TemporaryDirectory() as d:
            c, ps = cfg(), plays()
            c["recording"]["dir"] = d
            ps[0]["setup"] = "Macro break (60m supply)"
            e = Engine(ps, c, None)
            desk = Desk(e, c, ps, "test", prefix="t", base_dir=d)
            sym = ps[0]["symbol"]
            e.on_fill("x1", sym, "BOT", 100, 10.00, "09:31:00", 1.0)
            e.on_fill("x2", sym, "BOT", 100, 10.10, "09:32:00", 2.0)
            self.assertEqual(desk.trades, [])                       # still open
            e.on_fill("x3", sym, "SLD", 200, 10.45, "09:40:00", 3.0)
            self.assertEqual(len(desk.trades), 1)
            tr = desk.trades[0]
            self.assertEqual((tr["symbol"], tr["side"], tr["shares"], tr["entry"], tr["exit"], tr["setup"]),
                             (sym, "long", 200.0, 10.05, 10.45, "Macro break (60m supply)"))
            self.assertAlmostEqual(tr["pnl"], 80.0); self.assertAlmostEqual(tr["pnl_pct"], 3.98, places=2)
            self.assertTrue(desk.tag_trade(tr["id"], setup="Second entry", grade="A", note="clean"))
            rows = [json.loads(l) for l in open(os.path.join(d, "trades.jsonl"))]
            self.assertEqual((rows[0]["setup"], rows[0]["grade"], rows[0]["note"]), ("Second entry", "A", "clean"))
            # a short round trip
            e.on_fill("y1", sym, "SLD", 100, 20.00, "10:00:00", 4.0); e.on_fill("y2", sym, "BOT", 100, 19.50, "10:05:00", 5.0)
            self.assertEqual((desk.trades[-1]["side"], desk.trades[-1]["pnl"]), ("short", 50.0))
            self.assertIn("trades", e.snapshot(6.0)["desk"])
