"""A chart loads at once: history arriving bar by bar moves the history version a couple of times, not thousands
(the page refetches the whole history on every change)."""
import unittest

from helpers import cfg, plays
from twiney.engine import Engine


class HistoryVersionTests(unittest.TestCase):
    def test_a_streamed_history_is_a_couple_of_versions_not_one_per_bar(self):
        e = Engine(plays(), cfg(), None)
        sym = plays()[0]["symbol"]
        st = e.syms[sym]
        e.last_t = 1000.0
        v0 = st.hist_ver
        t0 = 1000.0 - 5 * 86400
        for i in range(1950):                                   # five days of minute bars, all at once
            e.on_hist_bar(sym, t0 + 60 * i, 10.0, 10.1, 9.9, 10.05, 1000)
        for i in range(2500):                                   # ten years of daily bars
            e.on_daily_bar(sym, t0 - 86400 * (2500 - i), 10.0, 10.5, 9.5, 10.2, 5e6)
        self.assertLessEqual(st.hist_ver - v0, 2)
        self.assertTrue(st.hist_dirty)
        # the snapshot a little later carries the last change exactly once
        e.last_t = 1003.0
        e._hist_flush(st, 1003.0)
        v1 = st.hist_ver
        self.assertEqual(v1 - v0, 2)
        self.assertFalse(st.hist_dirty)
        e._hist_flush(st, 1006.0)
        self.assertEqual(st.hist_ver, v1)

    def test_bars_spread_over_time_each_get_seen(self):
        e = Engine(plays(), cfg(), None)
        sym = plays()[0]["symbol"]
        st = e.syms[sym]
        vs = []
        for k in range(5):
            e.last_t = 1000.0 + 3.0 * k                         # a bar every three seconds (the live update)
            e.on_hist_bar(sym, 900.0 + 60 * k, 10.0, 10.1, 9.9, 10.05, 1000)
            vs.append(st.hist_ver)
        self.assertEqual(len(set(vs)), 5)
