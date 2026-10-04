import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import run_twiney  # noqa: E402


def plays():
    return [{"symbol": "AAPL", "trigger": 150.0, "second_entry": 150.5, "stop": 149.0, "target": 153.0, "mp": 153.0,
             "alt": {"second_entry": 148.0}}, {"symbol": "NVDA", "trigger": None}]


class CleanChartTests(unittest.TestCase):
    def test_first_start_clears_lines_then_same_day_restart_keeps_them(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "plays.json"); open(path, "w").write("{}")
            cfg = {"trading": {"clean_chart_on_start": True}}
            ps = plays()
            self.assertEqual(run_twiney.clean_chart(ps, cfg, path), 1)
            self.assertEqual([ps[0].get(k) for k in run_twiney.LINE_KEYS], [None] * 5)
            self.assertNotIn("alt", ps[0]); self.assertEqual(ps[0]["symbol"], "AAPL")
            ps = plays()                                         # restart later today: today's lines stay
            self.assertEqual(run_twiney.clean_chart(ps, cfg, path), 0); self.assertEqual(ps[0]["trigger"], 150.0)
            old = time.time() - 2 * 86400; os.utime(path, (old, old))   # next morning: clean again
            self.assertEqual(run_twiney.clean_chart(plays(), cfg, path), 1)

    def test_switch_off_keeps_everything(self):
        ps = plays()
        self.assertEqual(run_twiney.clean_chart(ps, {"trading": {"clean_chart_on_start": False}}, None), 0)
        self.assertEqual(ps[0]["stop"], 149.0)


if __name__ == "__main__":
    unittest.main()
