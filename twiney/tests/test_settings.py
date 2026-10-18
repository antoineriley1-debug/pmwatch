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
            if path in settings.RETIRED:
                self.assertNotIn(path, paths)          # a retired setting loads but is not offered
                continue
            self.assertIn(path, paths, path)
        f = {f["path"]: f for s in settings.schema(cfg) for f in s["fields"]}
        self.assertTrue(f["reload.min_refreshes"]["help"])
        self.assertFalse(f["flow.min_premium"]["restart"])
        self.assertTrue(f["ibkr.port"]["restart"])
        self.assertFalse(f["trading.allow_live"]["locked"]); self.assertTrue(f["trading.allow_live"]["restart"])
        self.assertIn("REAL MONEY", f["trading.allow_live"]["help"])

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
                settings.apply(cfg, path, {"dashboard.host": "0.0.0.0"})
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


class HistoryVersionTests(unittest.TestCase):
    def test_history_arriving_late_bumps_the_version_the_page_watches(self):
        from helpers import cfg, plays
        from twiney.engine import Engine
        e = Engine(plays(), cfg(), None)
        sym = plays()[0]["symbol"]
        e.on_l1(sym, "last", 10.0, 1000.0)
        pane = lambda full: next(iter([d for d in (e.snapshot(1001.0, [sym], full)["extra"].values()) if d["symbol"] == sym]
                                      + [d for d in e.snapshot(1001.0, [sym], full)["panes"] if d and d["symbol"] == sym]))
        before = pane(set())["hist_ver"]
        for k in range(1, 50):
            e.on_hist_bar(sym, 1000.0 - k * 60, 10, 10.1, 9.9, 10, 100)
        e.on_daily_bar(sym, 0.0, 9, 11, 8, 10)
        after = pane(set())
        self.assertGreater(after["hist_ver"], before)
        self.assertEqual(len(after["bars"]), 6)            # a plain poll still carries only the tail
        self.assertGreaterEqual(len(pane({sym})["bars"]), 49)   # the full fetch the page makes on the new version


class DailyVolumeTests(unittest.TestCase):
    def test_daily_bars_keep_their_volume_through_the_pane_and_replay(self):
        import tempfile
        from helpers import cfg, plays
        from twiney.engine import Engine
        from twiney.recorder import Recorder
        from twiney.replay import replay
        with tempfile.TemporaryDirectory() as d:
            c, ps = cfg(), plays()
            rec = Recorder(d, "t.jsonl"); rec.write(session_header(ps, c, "t"))
            e = Engine(ps, c, rec)
            sym = ps[0]["symbol"]
            e.on_daily_bar(sym, 86400.0, 9, 11, 8, 10, 1234567)
            e.on_daily_bar(sym, 2 * 86400.0, 10, 12, 9, 11)          # no volume given: 0, not an error
            rec.close()
            row = [r for r in e.snapshot(3 * 86400.0)["panes"] + list(e.snapshot(3 * 86400.0, [sym])["extra"].values()) if r and r["symbol"] == sym][0]["daily"]
            self.assertEqual((row[0][5], row[1][5]), (1234567, 0))
            eng, _ = replay(rec.path)
            self.assertEqual(eng.syms[sym].daily_vol.get(86400.0), 1234567)
