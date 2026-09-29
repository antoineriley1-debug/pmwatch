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
