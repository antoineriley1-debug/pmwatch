import json
import os
import tempfile
import unittest

from twiney.config import ConfigError, DEFAULTS, build_config, load_config, load_plays, validate_plays

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class ConfigTests(unittest.TestCase):
    def test_defaults_and_merge(self):
        c = build_config({"ibkr": {"port": 4002}, "_note": "ignored"})
        self.assertEqual(c["ibkr"]["port"], 4002)
        self.assertEqual(c["ibkr"]["host"], DEFAULTS["ibkr"]["host"])
        self.assertEqual(c["depth"]["slots"], 3)

    def test_unknown_key_rejected(self):
        with self.assertRaises(ConfigError):
            build_config({"ibkr": {"prot": 1}})

    def test_dashboard_must_be_loopback(self):
        with self.assertRaises(ConfigError):
            build_config({"dashboard": {"host": "0.0.0.0"}})
        build_config({"dashboard": {"host": "localhost"}})

    def test_rows_displayed_cannot_exceed_requested(self):
        with self.assertRaises(ConfigError):
            build_config({"depth": {"rows_requested": 3, "rows_displayed": 5}})

    def test_example_files_load(self):
        cfg = load_config(os.path.join(ROOT, "config.example.json"))
        self.assertEqual(cfg["depth"]["slots"], 3)
        ps = load_plays(os.path.join(ROOT, "plays.example.json"))
        self.assertGreaterEqual(len(ps), 3)

    def test_missing_file_message(self):
        with self.assertRaises(ConfigError) as ctx:
            load_config(os.path.join(tempfile.gettempdir(), "nope-twiney.json"))
        self.assertIn("config.example.json", str(ctx.exception))


class PlayValidationTests(unittest.TestCase):
    def test_normalises(self):
        p = validate_plays([{"symbol": " aapl ", "side": "SHORT", "trigger": "10.5", "second_entry": 10.7}])[0]
        self.assertEqual((p["symbol"], p["side"], p["trigger"]), ("AAPL", "short", 10.5))
        self.assertEqual(p["exchange"], "SMART")
        self.assertTrue(p["active"])

    def test_rejections(self):
        bad = [
            [],
            [{"side": "long", "trigger": 1}],
            [{"symbol": "A", "side": "sideways", "trigger": 1}],
            [{"symbol": "A", "side": "long"}],
            [{"symbol": "A", "side": "long", "trigger": -1}],
            [{"symbol": "A", "trigger": 1}, {"symbol": "a", "trigger": 2}],
            [{"symbol": "A", "trigger": 1, "extra_levels": ["x"]}],
            [{"symbol": "A", "trigger": 1, "active": False}],
        ]
        for raw in bad:
            with self.assertRaises(ConfigError, msg=json.dumps(raw)):
                validate_plays(raw)


if __name__ == "__main__":
    unittest.main()
