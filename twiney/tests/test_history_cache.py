"""The live desk's real histories, kept for the practice desk: practice AAPL trades at AAPL's price, ATR and levels."""
import datetime as dt
import os
import tempfile
import unittest
from zoneinfo import ZoneInfo

from helpers import cfg, plays
from twiney.engine import Engine
from twiney.sim import DemoFeed

NY = ZoneInfo("America/New_York")


def ny(h, m, day=5):
    return dt.datetime(2026, 10, day, h, m, tzinfo=NY).timestamp()


def fill_live(e, sym, t):
    """A live session's worth of history: 60 daily bars around $250 with a $5 range, five days of minutes."""
    day0 = dt.datetime(2026, 10, 5, 0, 0, tzinfo=NY).timestamp()
    px = 250.0
    for d in range(60, 0, -1):
        o = px; c = round(o + (1.5 if d % 3 else -2.0), 2)
        e.on_daily_bar(sym, day0 - d * 86400, o, round(max(o, c) + 2.5, 2), round(min(o, c) - 2.5, 2), c, 3e6)
        px = c
    last = px
    for d in range(5, 0, -1):
        base = day0 - d * 86400 + 34200
        for m in range(390):
            e.on_hist_bar(sym, base + 60 * m, last, last + 0.2, last - 0.2, last, 1000)
    for j in range(48):
        e.on_study_bar(sym, "m5x", day0 - 86400 + 16 * 3600 + 300 * j, last, last + 0.4, last - 0.3, last, 500)
    e.on_l1(sym, "last", last, t)
    return last


class CacheTests(unittest.TestCase):
    def test_a_live_session_saves_and_the_practice_desk_trades_the_real_stock(self):
        c, ps = cfg(), plays()
        sym = ps[0]["symbol"]
        e = Engine(ps, c, None)
        t = ny(15, 0)
        e.on_connection("CONNECTED", "live", t)
        last = fill_live(e, sym, t)
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(e.save_history(d, t, only={sym}), 1)
            cached = Engine.load_history(d, sym)
            self.assertEqual(len(cached["daily"]), 60); self.assertGreaterEqual(len(cached["bars"]), 1950); self.assertEqual(len(cached["m5x"]), 48)
            # the practice desk, seeded from it
            e2 = Engine(ps, c, None)
            f = DemoFeed(e2, ps, seed=3, history_dir=d)
            s = f.state[sym]
            self.assertAlmostEqual(s.mid0, last, delta=last * 0.007)        # practice price = the real price, give or take
            f.start(ny(22, 0))
            self.assertTrue(s.real_hist)
            st = e2.syms[sym]
            self.assertGreaterEqual(len(st.daily), 60)                       # the stock's own days
            self.assertGreaterEqual(len(st.bars), 1900)                      # its own minutes
            self.assertAlmostEqual(s.atr_day, 7.0, delta=1.0)                # its real ATR (a $5 range plus the gaps), not 1.8 %
            self.assertIsNotNone(s.ahh); self.assertIsNotNone(s.ahl)         # the after-hours from the cache

    def test_the_practice_desk_never_saves_its_own_bars(self):
        c, ps = cfg(), plays()
        e = Engine(ps, c, None)
        f = DemoFeed(e, ps, seed=3)
        f.start(ny(11, 0))
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(e.save_history(d, ny(11, 1)), 0)
            self.assertEqual(os.listdir(d), [])

    def test_no_cache_means_the_made_up_stock(self):
        c, ps = cfg(), plays()
        e = Engine(ps, c, None)
        with tempfile.TemporaryDirectory() as d:
            f = DemoFeed(e, ps, seed=3, history_dir=d)
            f.start(ny(11, 0))
            self.assertFalse(next(iter(f.state.values())).real_hist)
