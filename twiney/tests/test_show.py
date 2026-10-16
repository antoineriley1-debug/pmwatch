"""THE SHOW page: its own page at /show, and a light feed (/api/show) with the watchlist, the charts in view (candles,
levels, PS60 lines), the calls for BREAKING and the day's trades; nothing on it can trade."""

import json
import os
import unittest
import urllib.request

from helpers import cfg, plays
from twiney.dashboard import Dashboard, SHOW_PAGE
from twiney.engine import Engine


class ShowTests(unittest.TestCase):
    def setUp(self):
        self.engine = Engine(plays(), cfg())
        self.engine.on_l1("AAA", "last", 10.0, 1.0)
        self.dash = Dashboard(self.engine, "127.0.0.1", 0, clock=lambda: 2.0).start()

    def tearDown(self):
        self.dash.stop()

    def get(self, path):
        with urllib.request.urlopen(self.dash.url + path, timeout=5) as r:
            return r.status, r.read()

    def test_the_feed(self):
        code, body = self.get("/api/show?view=AAA,NOPE&full=AAA")
        out = json.loads(body)
        self.assertEqual(code, 200); self.assertTrue(out["ok"])
        self.assertEqual([w["symbol"] for w in out["watchlist"]], [p["symbol"] for p in plays()])
        self.assertIn("AAA", out["charts"]); self.assertNotIn("NOPE", out["charts"])
        ch = out["charts"]["AAA"]
        for k in ("bars", "studies", "user_levels", "play", "refs", "se"):
            self.assertIn(k, ch)
        self.assertIn("build", out); self.assertIsInstance(out["alerts"], list); self.assertIsInstance(out["trades"], list)

    def test_the_page_is_built_and_served(self):
        self.assertTrue(os.path.exists(SHOW_PAGE))
        code, body = self.get("/show")
        self.assertEqual(code, 200); self.assertIn(b'name="build"', body)
        for word in (b"/api/trade", b"/api/order"):
            self.assertNotIn(word, body)                       # the broadcast screen never places or cancels an order

    def test_ps60_words_only_on_the_page(self):
        with open(SHOW_PAGE, encoding="utf-8") as fh:
            page = fh.read().lower()
        page = page.replace("trigger:", "").replace(".trigger", "")   # the pivot's data field in plays.json (shown as PIVOT)
        for bad in ("resistance", "support", "trigger", "iceberg", "dark pool", "fading", "stale", " zone"):
            self.assertNotIn(bad, page, bad)
        self.assertIn("pivot", page)


if __name__ == "__main__":
    unittest.main()
