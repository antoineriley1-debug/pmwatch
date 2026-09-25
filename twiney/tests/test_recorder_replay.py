import json
import os
import tempfile
import unittest

from helpers import cfg, plays
from twiney.engine import Engine
from twiney.recorder import Recorder, read_events
from twiney.replay import compare, replay, session_header
from twiney.sim import DemoFeed


class RecorderReplayTests(unittest.TestCase):
    def test_replay_reproduces_recorded_alerts(self):
        with tempfile.TemporaryDirectory() as d:
            c, ps = cfg(), plays()
            rec = Recorder(d, "t.jsonl")
            rec.write(session_header(ps, c, "test"))
            live = Engine(ps, c, rec)
            feed = DemoFeed(live, ps, seed=3)
            t = 1000.0
            feed.start(t)
            for _ in range(4 * 240):
                t += 0.25
                feed.step(t)
            rec.close()
            self.assertGreater(len(live.alerts), 0, "demo should produce calls")
            engine, recorded = replay(rec.path)
            got, want = compare(engine, recorded)
            self.assertEqual(got, want)
            self.assertEqual(sum(want.values()), sum(1 for a in live.alerts))

    def test_replay_with_overridden_settings(self):
        with tempfile.TemporaryDirectory() as d:
            c, ps = cfg(), plays()
            rec = Recorder(d, "t.jsonl")
            rec.write(session_header(ps, c, "test"))
            live = Engine(ps, c, rec)
            feed = DemoFeed(live, ps, seed=3)
            t = 1000.0
            feed.start(t)
            for _ in range(4 * 120):
                t += 0.25
                feed.step(t)
            rec.close()
            strict = cfg(reload={"min_refreshes": 1000})
            engine, _ = replay(rec.path, plays=ps, cfg=strict)
            self.assertFalse([a for a in engine.alerts if "RELOAD" in a["label"]])

    def test_truncated_final_line_is_tolerated(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "x.jsonl")
            with open(path, "w") as fh:
                fh.write(json.dumps({"ev": "l1", "t": 1}) + "\n")
                fh.write('{"ev": "print", "t": 2, "sym"')
            self.assertEqual(len(list(read_events(path))), 1)


if __name__ == "__main__":
    unittest.main()
