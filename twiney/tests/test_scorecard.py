"""THE DESK SCORE: directional calls judged 5 / 15 minutes later."""

import json
import os
import tempfile
import unittest

from twiney.scorecard import Scorecard, classify


def story(topic, side="ask", t=1000.0):
    return {"t": t, "symbol": "NVDA", "role": "story", "label": "PS60 STORY", "side": side, "text": "x",
            "key": f"{t}|NVDA|STORY|{topic}"}


class ClassifyTests(unittest.TestCase):
    def test_story_topics(self):
        self.assertEqual(classify(story("se:through")), ("SECOND ENTRY LIVE", 1))
        self.assertEqual(classify(story("se:through", "bid")), ("SECOND ENTRY LIVE", -1))
        self.assertEqual(classify(story("hype", "bid")), ("CALLS / PUTS POUNDED", -1))
        self.assertEqual(classify(story("break:PDH")), ("LEVEL BREAK (CLOSE)", 1))
        self.assertEqual(classify(story("openread")), ("OPEN READ", 1))
        self.assertEqual(classify(story("struct:ll", "bid")), ("STRUCTURE (60 / DAILY)", -1))
        self.assertIsNone(classify(story("coach")))        # no direction: not scored
        self.assertIsNone(classify(story("pbp")))
        self.assertIsNone(classify(story("se:step1")))     # a walk-in step is not the call

    def test_reloads_levels_pace_inst(self):
        self.assertEqual(classify({"role": "auto", "label": "CLEANED UP", "side": "ask"}), ("CLEANED UP", 1))
        self.assertEqual(classify({"role": "auto", "label": "CLEANED UP", "side": "bid"}), ("CLEANED UP", -1))
        self.assertEqual(classify({"role": "auto", "label": "RELOAD BUYER", "side": "bid"}), ("RELOAD BUYER", 1))
        self.assertEqual(classify({"role": "auto", "label": "RELOAD SELLER BACK", "side": "ask"}), ("RELOAD SELLER", -1))
        self.assertIsNone(classify({"role": "auto", "label": "STILL THERE", "side": "bid"}))
        self.assertIsNone(classify({"role": "auto", "label": "PULLED", "side": "bid"}))
        self.assertEqual(classify({"role": "level", "label": "BUYERS TOOK"}), ("LEVEL BUYERS TOOK", 1))
        self.assertEqual(classify({"role": "level", "label": "HELD AS SUPPLY"}), ("LEVEL HELD AS SUPPLY", -1))
        self.assertIsNone(classify({"role": "level", "label": "COMING INTO"}))
        self.assertEqual(classify({"role": "pace", "label": "BREAKOUT WITH SPEED + FLOW"}), ("BREAKOUT WITH SPEED", 1))
        self.assertIsNone(classify({"role": "pace", "label": "STALLING"}))
        self.assertEqual(classify({"role": "inst", "label": "CHILD ORDERS · SELL PROGRAM"}), ("SELL PROGRAM", -1))
        self.assertEqual(classify({"role": "inst", "label": "STEADY BUYING"}), ("BUY PROGRAM", 1))
        self.assertIsNone(classify({"role": "flow", "label": "URGENT FLOW", "side": "ask"}))


class ScorecardTests(unittest.TestCase):
    def test_hit_miss_flat_and_persist(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "score.jsonl")
        sc = Scorecard(path, {"hit_atr": 0.1})
        t0 = 1_700_000_000.0
        sc.note({"role": "auto", "label": "CLEANED UP", "side": "ask", "symbol": "NVDA", "text": "seller cleaned up"}, t0, 100.0, 5.0)
        sc.note({"role": "auto", "label": "RELOAD SELLER", "side": "ask", "symbol": "AMD"}, t0, 50.0, 2.0)
        sc.note(story("openread"), t0, 100.0, 5.0)        # NVDA too: it rides the same prices
        self.assertEqual(len(sc.open), 3)
        sc.tick(t0 + 299, {"NVDA": 100.2, "AMD": 50.0})
        self.assertEqual(sc.open[0]["moves"], {})
        sc.tick(t0 + 300, {"NVDA": 100.2, "AMD": 50.3})
        self.assertEqual(sc.open[0]["moves"]["300"], 0.2)
        self.assertEqual(sc.open[1]["moves"]["300"], -0.3)   # the seller call wanted it down: it went up
        self.assertEqual(len(sc.done), 0)
        sc.tick(t0 + 900, {"NVDA": 100.8, "AMD": 50.05})
        self.assertEqual(len(sc.open), 0)
        out = {r["kind"]: r["outcome"] for r in sc.done}
        self.assertEqual(out["CLEANED UP"], "HIT")           # +0.8 ≥ 0.1 × 5.0
        self.assertEqual(out["OPEN READ"], "HIT")
        self.assertEqual(out["RELOAD SELLER"], "FLAT")       # -0.05 against 0.2 threshold
        v = sc.view()
        kinds = {k["kind"]: k for k in v["kinds"]}
        self.assertEqual(kinds["CLEANED UP"]["hit_pct"], 100)
        self.assertEqual(kinds["RELOAD SELLER"]["flat"], 1)
        self.assertAlmostEqual(kinds["CLEANED UP"]["avg15"], 0.16)
        self.assertEqual(v["recent"][0]["symbol"], "NVDA")
        self.assertEqual(v["open"], 0)
        with open(path) as f:
            rows = [json.loads(l) for l in f]
        self.assertEqual(len(rows), 3)
        self.assertEqual({r["outcome"] for r in rows}, {"HIT", "FLAT"})

    def test_miss_and_no_atr(self):
        sc = Scorecard(None, {})
        t0 = 1_700_000_000.0
        sc.note({"role": "pace", "label": "BREAKDOWN WITH SPEED", "symbol": "X"}, t0, 100.0, None)   # ATR unknown: 1.8% of price
        sc.tick(t0 + 300, {"X": 101.0})
        sc.tick(t0 + 900, {"X": 101.0})
        self.assertEqual(sc.done[0]["outcome"], "MISS")     # wanted down, +1.0 against a 0.18 threshold

    def test_undirected_and_dropped(self):
        sc = Scorecard(None, {})
        t0 = 1_700_000_000.0
        self.assertIsNone(sc.note({"role": "auto", "label": "STILL THERE", "side": "bid", "symbol": "X"}, t0, 100.0, 1.0))
        self.assertIsNone(sc.note(story("coach"), t0, 100.0, 1.0))
        sc.note(story("openread"), t0, 100.0, 1.0)
        sc.tick(t0 + 2000, {})                                # no price ever came: dropped, not judged
        self.assertEqual(sc.open, [])
        self.assertEqual(len(sc.done), 0)

    def test_new_day_resets_the_review(self):
        sc = Scorecard(None, {})
        t0 = 1_700_000_000.0
        sc.note(story("openread"), t0, 100.0, 1.0)
        sc.tick(t0 + 300, {"NVDA": 100.5}); sc.tick(t0 + 900, {"NVDA": 100.5})
        self.assertEqual(len(sc.view()["kinds"]), 1)
        sc.tick(t0 + 86400, {"NVDA": 100.5})
        self.assertEqual(sc.view()["kinds"], [])
        self.assertEqual(len(sc.done), 1)                      # the list of judged calls is kept


class EngineHookTests(unittest.TestCase):
    def test_alert_noted_and_in_snapshot(self):
        import copy
        from twiney.config import DEFAULTS, validate_plays
        from twiney.engine import Engine
        cfg = copy.deepcopy(DEFAULTS)
        eng = Engine(validate_plays({"plays": [{"symbol": "NVDA", "watch": True}]}), cfg, None)
        st = eng.syms["NVDA"]
        t0 = 1_700_000_000.0
        st.l1["last"] = 100.0
        eng._rec({"ev": "alert", "t": t0, "symbol": "NVDA", "role": "auto", "label": "CLEANED UP", "side": "ask", "text": "x"})
        self.assertEqual(len(eng.score.open), 1)
        self.assertEqual(eng.score.open[0]["p0"], 100.0)
        eng._rec({"ev": "alert", "t": t0, "symbol": "NVDA", "role": "auto", "label": "STILL THERE", "side": "ask", "text": "x"})
        self.assertEqual(len(eng.score.open), 1)
        snap = eng.snapshot(t0)
        self.assertEqual(snap["score"]["open"], 1)
        cfg["score"]["enabled"] = False
        self.assertIsNone(eng.snapshot(t0)["score"])


if __name__ == "__main__":
    unittest.main()
