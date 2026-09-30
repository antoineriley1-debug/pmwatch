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
        p = validate_plays([{"symbol": " aapl ", "side": "SHORT", "pivot": "10.5", "second_entry": 10.3}])[0]
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


class BlankStartTests(unittest.TestCase):
    """A chart starts blank: the example's made-up prices never show up as your levels."""

    def test_example_prices_in_plays_json_are_dropped(self):
        import json, os, tempfile
        from twiney.config import load_plays
        root = os.path.join(os.path.dirname(__file__), "..")
        with open(os.path.join(root, "plays.example.json"), encoding="utf-8") as fh:
            ex = json.load(fh)
        mine = dict(ex["plays"][1]); mine.update(pivot=128.40, second_entry=129.10)   # NVDA with MY 2nd entry: kept
        raw = {"plays": [ex["plays"][0], mine, {"symbol": "SOFI", "watch": True}]}
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "plays.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(raw, fh)
            with open(os.path.join(d, "plays.example.json"), "w", encoding="utf-8") as fh:
                json.dump(ex, fh)
            plays = load_plays(path)
        by = {p["symbol"]: p for p in plays}
        self.assertTrue(by["AAPL"]["watch"])
        self.assertIsNone(by["AAPL"]["trigger"]); self.assertIsNone(by["AAPL"]["stop"]); self.assertIsNone(by["AAPL"]["target"])
        self.assertEqual((by["NVDA"]["trigger"], by["NVDA"]["second_entry"], by["NVDA"]["watch"]), (128.40, 129.10, False))
        self.assertTrue(by["SOFI"]["watch"])
        from twiney.config import PLACEHOLDERS_STRIPPED
        self.assertEqual(PLACEHOLDERS_STRIPPED, ["AAPL"])

    def test_the_example_file_itself_keeps_its_prices(self):
        import os
        from twiney.config import load_plays
        plays = load_plays(os.path.join(os.path.dirname(__file__), "..", "plays.example.json"))
        self.assertTrue(all(p["trigger"] for p in plays))

    def test_clear_play_leaves_a_blank_watched_chart(self):
        from helpers import cfg, plays
        from twiney.engine import Engine
        e = Engine(plays(), cfg())
        e.syms["AAA"].play.update(stop=9.90, target=10.50, extra_levels=[10.30])
        self.assertTrue(e.clear_play("AAA", 5.0))
        p = e.syms["AAA"].play
        self.assertEqual([p.get(k) for k in ("trigger", "second_entry", "target", "stop", "mp")], [None] * 5)
        self.assertEqual(p["extra_levels"], [])
        self.assertTrue(p["watch"])
        self.assertEqual(e.syms["AAA"].trackers, {})
        self.assertIn("PLAY cleared", [n["text"] for n in e.symbol_log("AAA")][-1])
