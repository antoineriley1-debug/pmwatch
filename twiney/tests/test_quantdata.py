import io
import json
import os
import unittest
import urllib.error
import urllib.request
from unittest import mock

from helpers import cfg
from twiney.config import build_config, load_plays
from twiney.engine import Engine
from twiney.flow import QuantDataFeed

PLAYS = os.path.join(os.path.dirname(__file__), "..", "plays.example.json")


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _print(sym, strike, prem, t="2026-09-30T14:31:05Z"):
    return {"ticker": sym, "strike": strike, "expiration": "2026-10-16", "type": "CALL", "side": "ASK",
            "size": 500, "price": 5.0, "premium": prem, "spot": 128.4, "time": t}


class QuantDataRequestTests(unittest.TestCase):
    def _feed(self, **q):
        c = cfg()
        c["quantdata"].update(api_key="qd_test_key_not_real", **q)
        ps = load_plays(PLAYS)
        e = Engine(ps, c, None)
        return e, QuantDataFeed(e, c, [p["symbol"] for p in ps])

    def test_documented_endpoint_and_body(self):
        e, f = self._feed()
        seen = {}

        def fake(req, timeout=10):
            seen["url"], seen["method"] = req.full_url, req.get_method()
            seen["auth"] = req.get_header("Authorization")
            seen["body"] = json.loads(req.data.decode("utf-8"))
            return _Resp(json.dumps({"data": []}).encode("utf-8"))
        with mock.patch.object(urllib.request, "urlopen", fake):
            f._request()
        self.assertEqual(seen["url"], "https://api.quantdata.us/v1/options/tool/order-flow/consolidated")
        self.assertEqual(seen["method"], "POST")
        self.assertEqual(seen["auth"], "Bearer qd_test_key_not_real")
        self.assertRegex(seen["body"]["sessionDate"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertNotIn("tickers", seen["body"])

    def test_watchlist_scope_filters_here_not_by_more_requests(self):
        e, f = self._feed()
        mine = f.symbols[0]
        payload = {"data": [_print(mine, 130, 300000), _print("ZZZZ", 50, 900000)]}
        with mock.patch.object(urllib.request, "urlopen", lambda req, timeout=10: _Resp(json.dumps(payload).encode())):
            e.set_flow_scope("watchlist")
            f.sample_written = True
            f.poll()
        syms = {p["symbol"] for p in e.flow.recent}
        self.assertEqual(syms, {mine})

    def test_http_errors_say_what_went_wrong_without_the_key(self):
        e, f = self._feed()

        def fail(req, timeout=10):
            raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, io.BytesIO(b'{"error":"invalid key"}'))
        with mock.patch.object(urllib.request, "urlopen", fail):
            with self.assertRaises(RuntimeError) as cm:
                f._request()
        msg = str(cm.exception)
        self.assertIn("HTTP 401", msg)
        self.assertIn("check it in SETTINGS", msg)
        self.assertNotIn("qd_test_key_not_real", msg)

    def test_old_placeholder_path_is_migrated(self):
        c = build_config({"quantdata": {"flow_path": "/v1/options/flow"}})
        self.assertEqual(c["quantdata"]["flow_path"], "/v1/options/tool/order-flow/consolidated")
        c = build_config({"quantdata": {"flow_path": "/v1/custom"}})
        self.assertEqual(c["quantdata"]["flow_path"], "/v1/custom")


if __name__ == "__main__":
    unittest.main()
