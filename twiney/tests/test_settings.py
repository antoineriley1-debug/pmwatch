import json
import os
import tempfile
import unittest

from twiney import settings
from twiney.config import DEFAULTS, ConfigError, build_config
from twiney.replay import session_header


class SettingsTests(unittest.TestCase):
    def test_every_setting_is_in_the_schema(self):
        cfg = build_config({})
        paths = {f["path"] for s in settings.schema(cfg) for f in s["fields"]}
        for path, _v in settings._leaves(DEFAULTS):
            self.assertIn(path, paths, path)
        f = {f["path"]: f for s in settings.schema(cfg) for f in s["fields"]}
        self.assertTrue(f["reload.min_refreshes"]["help"])
        self.assertFalse(f["flow.min_premium"]["restart"])
        self.assertTrue(f["ibkr.port"]["restart"])
        self.assertTrue(f["trading.allow_live"]["locked"])

    def test_save_writes_config_applies_live_and_protects_the_key(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "config.json")
            with open(path, "w") as fh:
                json.dump({"_note": "mine", "ibkr": {"port": 7497}}, fh)
            cfg = build_config(json.load(open(path)))
            applied, restart = settings.apply(cfg, path, {"flow.index_min_premium": "8000000", "reload.min_refreshes": 3,
                                                          "flow.index_symbols": "spy, qqq", "ibkr.port": 4002,
                                                          "quantdata.api_key": "SECRET-1234", "demo.scenario": "chop"})
            self.assertEqual(cfg["flow"]["index_min_premium"], 8000000)
            self.assertEqual(cfg["reload"]["min_refreshes"], 3)
            self.assertEqual(cfg["flow"]["index_symbols"], ["SPY", "QQQ"])
            self.assertIn("ibkr.port", restart); self.assertNotIn("reload.min_refreshes", restart)
            saved = json.load(open(path))
            self.assertEqual((saved["_note"], saved["ibkr"]["port"], saved["reload"]["min_refreshes"]), ("mine", 4002, 3))
            # the key is never sent back to the page, and never written into a recording
            f = {f["path"]: f for s in settings.schema(cfg) for f in s["fields"]}
            self.assertEqual((f["quantdata.api_key"]["value"], f["quantdata.api_key"]["set"], f["quantdata.api_key"]["hint"]), ("", True, "…1234"))
            self.assertEqual(session_header([], cfg, "t")["config"]["quantdata"]["api_key"], "***")
            self.assertEqual(cfg["quantdata"]["api_key"], "SECRET-1234")
            settings.apply(cfg, path, {"quantdata.api_key": ""})          # empty box keeps the key
            self.assertEqual(cfg["quantdata"]["api_key"], "SECRET-1234")
            # locked and invalid changes are refused and nothing is written
            with self.assertRaises(ConfigError):
                settings.apply(cfg, path, {"trading.allow_live": True})
            with self.assertRaises(ConfigError):
                settings.apply(cfg, path, {"depth.rows_displayed": 50})
            with self.assertRaises(ConfigError):
                settings.apply(cfg, path, {"reload.min_refreshes": "lots"})
            self.assertEqual(json.load(open(path))["reload"]["min_refreshes"], 3)
            self.assertFalse(cfg["trading"]["allow_live"])


class FeedLightTests(unittest.TestCase):
    def test_market_and_option_lights(self):
        from helpers import cfg, plays
        from twiney.engine import Engine
        e = Engine(plays(), cfg(), None)
        f = e.snapshot(1.0)["feeds"]
        self.assertEqual((f["market"]["color"], f["options"]["color"], f["options"]["label"]), ("red", "red", "OFF"))
        e.on_connection("CONNECTED", "", 2.0, market_data_type=1)
        self.assertEqual(e.snapshot(2.0)["feeds"]["market"]["label"], "QUIET")          # connected, no tick yet
        e.on_l1(plays()[0]["symbol"], "last", 10.0, 3.0)
        self.assertEqual(e.snapshot(4.0)["feeds"]["market"]["color"], "green")
        self.assertEqual(e.snapshot(40.0)["feeds"]["market"]["label"], "QUIET")         # ticks stopped
        e.on_market_data_type(3, 41.0); e.on_l1(plays()[0]["symbol"], "last", 10.1, 41.0)
        self.assertEqual(e.snapshot(41.0)["feeds"]["market"]["label"], "DELAYED")
        e.flow_status.update(source="quantdata", state="connecting")
        self.assertEqual(e.snapshot(42.0)["feeds"]["options"]["label"], "CONNECTING")
        e.flow_status.update(state="ok", last_ok=42.0)
        self.assertEqual(e.snapshot(44.0)["feeds"]["options"]["color"], "green")
        e.flow_status.update(state="error", detail="401 Unauthorized")
        self.assertEqual(e.snapshot(80.0)["feeds"]["options"]["color"], "red")
        self.assertIn("401", e.snapshot(80.0)["feeds"]["options"]["detail"])
        e.on_connection("DISCONNECTED", "socket closed", 81.0)
        self.assertEqual(e.snapshot(81.0)["feeds"]["market"]["color"], "red")
