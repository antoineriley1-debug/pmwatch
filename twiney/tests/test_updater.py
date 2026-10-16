"""UPDATE from the desk: sees a newer build, installs it beside the running one, swaps the link, keeps the previous one,
never takes a config.json or a path outside its folder, refuses while you hold a trade."""

import io
import json
import os
import tempfile
import unittest
import urllib.error
import urllib.request
import zipfile

from helpers import cfg, plays
from twiney.dashboard import Dashboard
from twiney.engine import Engine
from twiney.updater import Updater


def page(build):
    return f'<html><head><meta name="build" content="{build}"><title>TED</title>'.encode()


def branch_zip(build, extra=()):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        top = "pmwatch-claude-branch/"
        z.writestr(top + "README.md", "repo root")
        z.writestr(top + "twiney/run_twiney.py", "print('ted')\n")
        z.writestr(top + "twiney/twiney/__init__.py", "")
        z.writestr(top + "twiney/twiney/static/dashboard.html", page(build))
        z.writestr(top + "twiney/config.json", '{"secret": 1}')
        for name, data in extra:
            z.writestr(name, data)
    return buf.getvalue()


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = self.tmp.name
        self.old = os.path.join(base, "unpack", "TWINEY", "twiney")
        os.makedirs(self.old)
        self.link = os.path.join(base, "app")
        os.symlink(self.old, self.link)
        self.remote = "20261016-0300"
        self.calls = []

    def tearDown(self):
        self.tmp.cleanup()

    def fetch(self, url, timeout):
        self.calls.append(url)
        if url.endswith("dashboard.html"):
            return page(self.remote)
        return branch_zip(self.remote, getattr(self, "extra", ()))

    def up(self, verify=lambda d: (True, "")):
        return Updater("20261016-0144", "me/repo", "claude/branch", self.link, fetch=self.fetch, verify=verify)

    def test_check_sees_a_newer_build(self):
        st = self.up().check(force=True)
        self.assertTrue(st["enabled"] and st["newer"]); self.assertEqual(st["latest"], "20261016-0300")
        self.remote = "20261016-0100"
        self.assertFalse(self.up().check(force=True)["newer"])

    def test_not_a_link_means_no_button(self):
        u = Updater("x", "me/repo", "b", os.path.join(self.tmp.name, "nope"), fetch=self.fetch)
        self.assertFalse(u.check(force=True)["enabled"]); self.assertFalse(u.install()["ok"])

    def test_install_swaps_the_link_and_keeps_the_previous(self):
        out = self.up().install()
        self.assertTrue(out["ok"], out); self.assertEqual(out["build"], "20261016-0300")
        new = os.readlink(self.link)
        self.assertNotEqual(new, self.old)
        self.assertTrue(os.path.exists(os.path.join(new, "run_twiney.py")))
        self.assertFalse(os.path.exists(os.path.join(new, "config.json")))           # never a private config
        self.assertEqual(os.readlink(self.link + ".prev"), self.old)
        self.assertTrue(os.path.isdir(self.old))                                       # the previous one stays for a rollback

    def test_a_build_that_does_not_start_changes_nothing(self):
        out = self.up(verify=lambda d: (False, "ImportError")).install()
        self.assertFalse(out["ok"]); self.assertIn("nothing changed", out["reason"])
        self.assertEqual(os.readlink(self.link), self.old)

    def test_no_path_outside_its_folder(self):
        self.extra = [("pmwatch-claude-branch/twiney/../../../evil.txt", "x")]
        self.assertTrue(self.up().install()["ok"])
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "evil.txt")))


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.engine = Engine(plays(), cfg())
        self.dash = Dashboard(self.engine, "127.0.0.1", 0, clock=lambda: 2.0).start()

    def tearDown(self):
        self.dash.stop()

    def call(self, method):
        r = urllib.request.Request(self.dash.url + "/api/update", data=b"{}" if method == "POST" else None, method=method,
                                   headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(r, timeout=5) as x:
                return x.status, json.loads(x.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_without_an_updater_the_button_stays_hidden(self):
        code, out = self.call("GET")
        self.assertEqual(code, 200); self.assertFalse(out["enabled"])
        self.assertEqual(self.call("POST")[0], 400)

    def test_refused_while_holding_a_position(self):
        class Fake:
            def enabled(self): return True
            def check(self, force=False): return {"newer": True, "latest": "20991231-0000", "current": "x"}
            def install(self): raise AssertionError("must not install")
        self.dash.hooks["update"] = Fake()
        self.engine.positions[("DU1", "AAA")] = {"qty": 100, "avg_cost": 10.0}
        code, out = self.call("POST")
        self.assertEqual(code, 409); self.assertIn("close out first", out["reason"])


if __name__ == "__main__":
    unittest.main()
