"""SIM's data source: with start_mode sim, sim_data picks the feed at launch (live IBKR, the practice market, or a
recorded day); the SIM menu saves the choice and restarts; a --demo / --replay command line is never overridden."""

import json
import os
import sys
import tempfile
import unittest
import urllib.request

from helpers import cfg, plays
from twiney.config import build_config
from twiney.dashboard import Dashboard
from twiney.engine import Engine

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import run_twiney  # noqa: E402


class LaunchRoutingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.rec = os.path.join(self.tmp.name, "recordings"); os.makedirs(self.rec)
        with open(os.path.join(self.rec, "twiney-20261013-0930.jsonl"), "w") as f:
            f.write("{}\n")
        self.calls = []
        self._orig = (run_twiney.run_live, run_twiney.run_demo, run_twiney.run_replay)
        run_twiney.run_live = lambda c, p, a: self.calls.append(("live", None)) or 0
        run_twiney.run_demo = lambda c, p, a: self.calls.append(("demo", None)) or 0
        run_twiney.run_replay = lambda c, p, a: self.calls.append(("replay", (os.path.basename(a.replay), a.speed))) or 0
        run_twiney.SOURCE[0] = None

    def tearDown(self):
        run_twiney.run_live, run_twiney.run_demo, run_twiney.run_replay = self._orig
        run_twiney.SOURCE[0] = None
        self.tmp.cleanup()

    def launch(self, trading, argv=()):
        c = os.path.join(self.tmp.name, "config.json")
        with open(c, "w") as f:
            json.dump({"trading": trading, "recording": {"dir": self.rec}}, f)
        p = os.path.join(self.tmp.name, "plays.json")
        with open(p, "w") as f:
            json.dump({"plays": [{"symbol": "AAA", "side": "long", "trigger": 10, "second_entry": 10.1}]}, f)
        run_twiney.main(["--config", c, "--plays", p, "--no-browser"] + list(argv))
        return self.calls[-1]

    def test_paper_is_live(self):
        self.assertEqual(self.launch({"start_mode": "paper", "sim_data": "practice"}), ("live", None))
        self.assertEqual(run_twiney.SOURCE[0], "live")

    def test_sim_live_data_is_live(self):
        self.assertEqual(self.launch({"start_mode": "sim", "sim_data": "live"}), ("live", None))

    def test_sim_practice_runs_the_practice_market(self):
        self.assertEqual(self.launch({"start_mode": "sim", "sim_data": "practice"}), ("demo", None))
        self.assertEqual(run_twiney.SOURCE[0], "practice")

    def test_sim_recorded_replays_the_day_in_real_time(self):
        self.assertEqual(self.launch({"start_mode": "sim", "sim_data": "recorded", "sim_recording": "twiney-20261013-0930.jsonl"}),
                         ("replay", ("twiney-20261013-0930.jsonl", 1.0)))
        self.assertEqual(run_twiney.SOURCE[0], "recorded")

    def test_a_missing_recording_falls_back_to_live(self):
        self.assertEqual(self.launch({"start_mode": "sim", "sim_data": "recorded", "sim_recording": "gone.jsonl"}), ("live", None))
        self.assertEqual(self.launch({"start_mode": "sim", "sim_data": "recorded", "sim_recording": "../../etc/passwd.jsonl"}), ("live", None))

    def test_a_demo_command_line_is_never_overridden(self):
        run_twiney.SOURCE[0] = None
        self.assertEqual(self.launch({"start_mode": "sim", "sim_data": "recorded", "sim_recording": "twiney-20261013-0930.jsonl"}, ["--demo"]), ("demo", None))
        self.assertIsNone(run_twiney.SOURCE[0])                 # no SIM menu switch on a fixed-feed desk


class HookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.rec = os.path.join(self.tmp.name, "recordings"); os.makedirs(self.rec)
        with open(os.path.join(self.rec, "twiney-20261013-0930.jsonl"), "w") as f:
            f.write("{}\n")
        self.path = os.path.join(self.tmp.name, "config.json")
        with open(self.path, "w") as f:
            json.dump({"recording": {"dir": self.rec}}, f)
        self.cfg = build_config({"recording": {"dir": self.rec}})
        self.restarts = []

    def tearDown(self):
        self.tmp.cleanup()

    def saved(self):
        with open(self.path) as f:
            return json.load(f)["trading"]

    def hook(self):
        return run_twiney.datasource_hook(self.cfg, self.path, lambda: self.restarts.append(1))

    def test_each_choice_is_saved_and_restarts(self):
        h = self.hook()
        self.assertTrue(h("practice")["ok"]); self.assertEqual((self.saved()["start_mode"], self.saved()["sim_data"]), ("sim", "practice"))
        self.assertTrue(h("recorded", "twiney-20261013-0930.jsonl")["ok"])
        self.assertEqual((self.saved()["sim_data"], self.saved()["sim_recording"]), ("recorded", "twiney-20261013-0930.jsonl"))
        self.assertTrue(h("paper")["ok"]); self.assertEqual((self.saved()["start_mode"], self.saved()["sim_data"]), ("paper", "live"))
        import time as _t; _t.sleep(1.0)
        self.assertEqual(len(self.restarts), 3)

    def test_refusals(self):
        h = self.hook()
        self.assertFalse(h("recorded", "nope.jsonl")["ok"])
        self.assertFalse(h("futures")["ok"])


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.engine = Engine(plays(), cfg())
        self.dash = Dashboard(self.engine, "127.0.0.1", 0, clock=lambda: 2.0).start()

    def tearDown(self):
        self.dash.stop()

    def req(self, method, body=None):
        r = urllib.request.Request(self.dash.url + "/api/datasource", data=json.dumps(body).encode() if body is not None else None,
                                   method=method, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(r, timeout=5) as x:
                return x.status, json.loads(x.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_get_says_what_it_can(self):
        code, out = self.req("GET")
        self.assertEqual(code, 200); self.assertFalse(out["can_switch"]); self.assertIn("recordings", out)

    def test_post_without_a_hook_says_why(self):
        code, out = self.req("POST", {"source": "practice"})
        self.assertEqual(code, 400); self.assertIn("fixed feed", out["reason"])

    def test_post_with_a_hook(self):
        got = []
        self.dash.hooks["datasource"] = lambda s, r=None: got.append((s, r)) or {"ok": True, "source": s, "restarting": True}
        code, out = self.req("POST", {"source": "practice"})
        self.assertEqual(code, 200); self.assertEqual(got, [("practice", None)])


if __name__ == "__main__":
    unittest.main()
