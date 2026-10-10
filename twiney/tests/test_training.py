"""REPLAY TRAINING: the desk's call pauses the replay, you answer, five minutes later you are judged."""

import json
import os
import tempfile
import threading
import time
import unittest

from helpers import cfg, plays
from twiney.engine import Engine
from twiney.recorder import Recorder
from twiney.replay import replay, session_header
from twiney.sim import DemoFeed
from twiney.training import Trainer


def call(sym="NVDA", label="CLEANED UP", side="ask", t=1000.0, words="NVDA. Seller cleaned up"):
    return {"t": t, "symbol": sym, "role": "auto", "label": label, "side": side, "text": "seller at 100 cleaned up", "words": words}


class TrainerTests(unittest.TestCase):
    def test_off_asks_nothing(self):
        tr = Trainer()
        self.assertIsNone(tr.ask(call(), 1000.0, 100.0, 2.0))

    def test_only_spoken_directional_calls_are_asked(self):
        tr = Trainer(); tr.on = True
        self.assertIsNone(tr.ask(call(words=None, label="BUYERS TOOK", side="ask"), 1000.0, 100.0, 2.0))   # not spoken
        self.assertIsNotNone(tr.ask(call(words=None), 1000.0, 100.0, 2.0)); tr.skip(); tr.last_t.clear(); tr.last_any = -1e9  # a reload call speaks through the voice queue
        self.assertIsNone(tr.ask(call(label="STILL THERE"), 1000.0, 100.0, 2.0))      # no direction
        q = tr.ask(call(), 1000.0, 100.0, 2.0)
        self.assertEqual((q["kind"], q["dir"], q["p0"]), ("CLEANED UP", 1, 100.0))
        self.assertIsNone(tr.ask(call(t=1010.0), 1010.0, 100.0, 2.0))                 # one question at a time
        self.assertTrue(tr.answer("long"))
        self.assertIsNone(tr.ask(call(t=1030.0), 1030.0, 100.0, 2.0))                 # the same stock: a minute between questions
        self.assertIsNone(tr.ask(call(sym="AMD", t=1015.0), 1015.0, 50.0, 1.0))        # any stock: a breath of 20 s between questions
        self.assertIsNotNone(tr.ask(call(sym="AMD", t=1030.0), 1030.0, 50.0, 1.0))

    def test_answers_are_judged_five_minutes_later(self):
        d = tempfile.mkdtemp()
        tr = Trainer(os.path.join(d, "training.jsonl"), {"hit_atr": 0.1}); tr.on = True
        tr.ask(call(), 1000.0, 100.0, 2.0); tr.answer("long")              # went up 0.5 ≥ 0.2: LONG was right
        self.assertIsNotNone(tr.ask(call(sym="AMD", label="RELOAD SELLER", side="ask", t=1030.0, words="AMD. Reload seller"), 1030.0, 50.0, 1.0))
        self.assertTrue(tr.answer("short"))                                 # flat: WAIT was right
        self.assertEqual(tr.tick(1299.0, {"NVDA": 100.5, "AMD": 50.0}), [])
        out = tr.tick(1300.0, {"NVDA": 100.5, "AMD": 50.0})
        self.assertEqual([r["symbol"] for r in out], ["NVDA"])             # AMD's five minutes are not up yet
        out += tr.tick(1330.0, {"NVDA": 100.5, "AMD": 50.0})
        self.assertEqual([(r["symbol"], r["went"], r["right"], r["desk_right"]) for r in out],
                         [("NVDA", "long", True, True), ("AMD", "wait", False, False)])
        v = tr.view()
        self.assertEqual((v["n"], v["right"], v["pct"], v["pending"], v["quiz"]), (2, 1, 50, 0, None))
        self.assertEqual(v["recent"][0]["symbol"], "AMD")
        with open(tr.path) as f:
            rows = [json.loads(l) for l in f]
        self.assertEqual([r["answer"] for r in rows], ["long", "short"])

    def test_bad_answer_and_skip(self):
        tr = Trainer(); tr.on = True
        self.assertFalse(tr.answer("long"))                  # nothing asked
        tr.ask(call(), 1000.0, 100.0, 2.0)
        self.assertFalse(tr.answer("maybe"))
        self.assertIsNotNone(tr.view()["quiz"])
        tr.skip()
        self.assertIsNone(tr.view()["quiz"])
        self.assertEqual(tr.tick(2000.0, {"NVDA": 101.0}), [])


class ReplayTrainingTests(unittest.TestCase):
    def test_a_spoken_call_pauses_the_replay_until_answered(self):
        with tempfile.TemporaryDirectory() as d:
            c, ps = cfg(), plays()
            rec = Recorder(d, "t.jsonl")
            rec.write(session_header(ps, c, "test"))
            live = Engine(ps, c, rec)
            feed = DemoFeed(live, ps, seed=3)
            t = 1000.0
            feed.start(t)
            for _ in range(4 * 600):
                t += 0.25
                feed.step(t)
            rec.close()
            from twiney.scorecard import classify
            spoken = [a for a in live.alerts if a.get("words") and classify(a)]
            self.assertGreater(len(spoken), 0, "the demo should speak a call with a direction in it")
            tr = Trainer(os.path.join(d, "training.jsonl")); tr.on = True
            control = {"paused": False, "speed": 1000.0, "position": None}
            seen = {"paused_at": None, "answered": 0}

            def answerer():   # the trader at the screen: answers each question as it comes
                deadline = time.time() + 60
                while time.time() < deadline and not control.get("stop"):
                    if control.get("paused") and tr.quiz is not None:
                        seen["paused_at"] = seen["paused_at"] or control.get("position")
                        tr.answer("long"); seen["answered"] += 1
                        control["paused"] = False
                    time.sleep(0.01)
            th = threading.Thread(target=answerer, daemon=True); th.start()
            engine, _ = replay(rec.path, speed=1000.0, control=control, trainer=tr)
            control["stop"] = True; th.join(timeout=5)
            self.assertGreater(seen["answered"], 0, "the replay never asked")
            self.assertIs(engine.trainer, tr)
            v = tr.view()
            self.assertEqual(v["n"] + v["pending"], seen["answered"])
            self.assertGreater(v["n"], 0, "an answer should have been judged five minutes later")


if __name__ == "__main__":
    unittest.main()
