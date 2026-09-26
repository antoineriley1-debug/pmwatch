import json
import unittest
import urllib.error
import urllib.request

from helpers import cfg, plays
from twiney.dashboard import Dashboard
from twiney.engine import Engine


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.engine = Engine(plays(), cfg())
        self.engine.on_l1("AAA", "last", 10.0, 1.0)
        self.dash = Dashboard(self.engine, "127.0.0.1", 0, clock=lambda: 2.0).start()

    def tearDown(self):
        self.dash.stop()

    def get(self, path):
        return urllib.request.urlopen(self.dash.url + path, timeout=5)

    def test_state_json(self):
        data = json.loads(self.get("/api/state").read())
        self.assertEqual(data["mode"], "READ-ONLY · MARKET DATA ONLY")
        self.assertEqual(data["ranking"][0]["symbol"], "AAA")
        self.assertEqual(data["slots"], 3)

    def test_page_and_404(self):
        html = self.get("/").read().decode()
        self.assertIn("TWINEY", html)
        self.assertIn("/api/state", html)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.get("/nope")
        self.assertEqual(ctx.exception.code, 404)

    def post(self, path, body, headers=None):
        h = {"Content-Type": "application/json"}
        h.update(headers or {})
        req = urllib.request.Request(self.dash.url + path, data=json.dumps(body).encode(), method="POST", headers=h)
        return urllib.request.urlopen(req, timeout=5)

    def test_pin_and_autorotate_controls(self):
        self.assertEqual(self.post("/api/pin", {"symbol": "bbb", "pinned": True}).status, 200)
        self.assertIn("BBB", self.engine.pinned)
        self.post("/api/pin", {"symbol": "BBB", "pinned": False})
        self.assertNotIn("BBB", self.engine.pinned)
        self.post("/api/autorotate", {"on": False})
        self.assertFalse(self.engine.auto_rotate)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/pin", {"symbol": "NOPE", "pinned": True})
        self.assertEqual(ctx.exception.code, 404)

    def test_other_websites_cannot_post(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/autorotate", {"on": False}, {"Origin": "http://evil.example"})
        self.assertEqual(ctx.exception.code, 403)
        self.assertTrue(self.engine.auto_rotate)
        req = urllib.request.Request(self.dash.url + "/api/autorotate", data=b"on=0", method="POST",
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(ctx.exception.code, 415)


if __name__ == "__main__":
    unittest.main()
