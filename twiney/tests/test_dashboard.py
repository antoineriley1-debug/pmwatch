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

    def test_post_is_not_supported(self):
        req = urllib.request.Request(self.dash.url + "/api/state", data=b"{}", method="POST")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(ctx.exception.code, 501)


if __name__ == "__main__":
    unittest.main()
