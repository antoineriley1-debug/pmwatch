"""THE PRACTICE DESK from the live desk: a second TED on the next port on the practice market, started by the
PRACTICE button, its address handed to the page; the practice desk itself never offers it."""

import json
import os
import sys
import unittest
import urllib.request

from helpers import cfg, plays
from twiney.dashboard import Dashboard
from twiney.engine import Engine

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from run_twiney import PracticeLauncher  # noqa: E402


class FakeProc:
    def __init__(self):
        self.alive = True
    def poll(self):
        return None if self.alive else 0
    def terminate(self):
        self.alive = False
    def wait(self, timeout=None):
        return 0
    def kill(self):
        self.alive = False


class LauncherTests(unittest.TestCase):
    def test_command_and_lifecycle(self):
        spawned = []
        probes = iter([False, True])
        pl = PracticeLauncher("/data/config.json", 8766, spawn=lambda cmd: (spawned.append(cmd), FakeProc())[1], probe=lambda: next(probes, True))
        cmd = pl.command()
        self.assertEqual(cmd[0], sys.executable); self.assertTrue(cmd[1].endswith("run_twiney.py"))
        self.assertIn("--demo", cmd); self.assertIn("--no-browser", cmd)
        self.assertEqual(cmd[cmd.index("--port") + 1], "8766"); self.assertEqual(cmd[cmd.index("--config") + 1], "/data/config.json")
        self.assertFalse(pl.running())
        out = pl.start(wait_s=3)
        self.assertTrue(out["ok"] and out["ready"] and out["running"]); self.assertEqual(out["port"], 8766); self.assertEqual(len(spawned), 1)
        pl.start(wait_s=1)                                   # a second START never starts a second one
        self.assertEqual(len(spawned), 1)
        self.assertTrue(pl.stop()["ok"]); self.assertFalse(pl.running())

    def test_a_desk_that_fails_to_come_up_says_so(self):
        dead = FakeProc(); dead.alive = False
        pl = PracticeLauncher(None, 8766, spawn=lambda cmd: dead, probe=lambda: False)
        out = pl.start(wait_s=1)
        self.assertFalse(out["ok"]); self.assertIn("did not start", out["reason"])


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.engine = Engine(plays(), cfg())
        self.dash = Dashboard(self.engine, "127.0.0.1", 0, clock=lambda: 2.0).start()

    def tearDown(self):
        self.dash.stop()

    def post(self, body):
        req = urllib.request.Request(self.dash.url + "/api/practice", data=json.dumps(body).encode(), method="POST", headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_without_a_launcher_the_route_says_where_it_lives(self):
        code, out = self.post({"action": "start"})
        self.assertEqual(code, 400); self.assertIn("LIVE desk", out["reason"])

    def test_with_a_launcher_start_hands_back_the_address(self):
        pl = PracticeLauncher(None, 8766, spawn=lambda cmd: FakeProc(), probe=lambda: True)
        self.dash.hooks["practice"] = pl
        code, out = self.post({"action": "start"})
        self.assertEqual(code, 200); self.assertTrue(out["ok"] and out["ready"]); self.assertEqual(out["port"], 8766)
        code, st = self.post({"action": "status"})
        self.assertTrue(st["running"])
        code, out = self.post({"action": "stop"})
        self.assertTrue(out["ok"]); self.assertFalse(pl.running())


if __name__ == "__main__":
    unittest.main()
