import os
import tempfile
import time
import unittest

from helpers import cfg, plays
from twiney import clips
from twiney.desk import Desk
from twiney.engine import Engine
from twiney.recorder import Recorder
from twiney.replay import replay, session_header, span
from twiney.sim import DemoFeed


class RecordingToolsTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.c = cfg(); self.c["recording"]["dir"] = self.dir
        self.ps = plays()

    def _recording(self, seconds=20):
        rec = Recorder(self.dir, "s.jsonl"); rec.write(session_header(self.ps, self.c, "t"))
        e = Engine(self.ps, self.c, rec); f = DemoFeed(e, self.ps, seed=2); t = 1000.0; f.start(t)
        for _ in range(int(seconds * 4)):
            t += 0.25; f.step(t)
        rec.close()
        return rec.path, t

    def test_clips_add_list_note_delete(self):
        path, t = self._recording()
        c = clips.add(self.dir, "s.jsonl", 1005, 1015, "aaa", "the reload")
        self.assertEqual((c["symbol"], c["t0"], c["t1"]), ("AAA", 1005.0, 1015.0))
        self.assertTrue(clips.note(self.dir, c["id"], "better note"))
        self.assertEqual(clips.load(self.dir)[0]["note"], "better note")
        with self.assertRaises(ValueError):
            clips.add(self.dir, "nope.jsonl", 1, 5)
        self.assertTrue(clips.delete(self.dir, c["id"]))
        self.assertEqual(clips.load(self.dir), [])

    def test_span_and_clip_end_pauses_the_replay(self):
        path, t = self._recording(20)
        a, b = span(path)
        self.assertAlmostEqual(a, 1000.0, places=1); self.assertAlmostEqual(b, t, places=1)
        control = {"paused": False, "speed": 100.0, "position": None, "seek": 1005.0, "pause_at": 1008.0}
        import threading
        th = threading.Thread(target=lambda: replay(path, speed=100.0, control=control), daemon=True); th.start()
        time.sleep(1.5)
        self.assertTrue(control.get("paused")); self.assertTrue(control.get("clip_done"))
        self.assertLess(abs(control["position"] - 1008.0), 1.0)
        control["stop"] = True; control["paused"] = False; th.join(3)

    def test_flag_sessions_and_journal_files_are_not_sessions(self):
        path, t = self._recording(2)
        e = Engine(self.ps, self.c, None); d = Desk(e, self.c, self.ps, "t")
        open(os.path.join(self.dir, "trades.jsonl"), "w").close(); open(os.path.join(self.dir, "clips.jsonl"), "w").close()
        self.assertEqual([r["name"] for r in d.list_recordings()], ["s.jsonl"])
        self.assertTrue(d.flag("s.jsonl", True))
        self.assertTrue(d.list_recordings()[0]["flag"])
        self.assertTrue(d.flag("s.jsonl", False))
        self.assertFalse(d.list_recordings()[0]["flag"])
        self.assertFalse(d.flag("../etc.jsonl", True))

    def test_voice_note_becomes_the_journal_entry(self):
        e = Engine(self.ps, self.c, None); d = Desk(e, self.c, self.ps, "t")
        with self.assertRaises(ValueError):
            d.mic_start(10.0)                          # needs a recording
        d.start(10.0)
        m = d.mic_start(11.0, "AAA")
        d.mic_text(m["n"], "  seller reloading at ten   twenty ", 15.0)
        self.assertEqual(d.notes[-1]["text"], "🎙 seller reloading at ten twenty")
        self.assertEqual(d.notes[-1]["t"], 11.0)       # stamped when the mic went on
        self.assertTrue(d.marks[-1]["note"].startswith("🎙 seller"))
        d.mic_audio(m["n"], b"OggS....", "ogg", 15.0)
        self.assertTrue(os.path.exists(os.path.join(self.dir, "voice", d.marks[-1]["audio"])))
        d.stop(16.0)
