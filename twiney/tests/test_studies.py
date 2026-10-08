"""The chart studies (GAS + ATR, AIRSPACE, UNVISITED HIGHS / LOWS) against hand-worked numbers."""
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from twiney import studies as S
from twiney.config import DEFAULTS

NY = ZoneInfo("America/New_York")
CFG = dict(DEFAULTS["studies"])


def nyt(y, m, d, hh=0, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=NY).timestamp()


def weekdays_before(y, m, d, n):
    out, cur = [], datetime(y, m, d)
    while len(out) < n:
        cur -= timedelta(days=1)
        if cur.weekday() < 5:
            out.append(cur)
    return out[::-1]


def make_st(daily_rows, minutes=None, m30=None, m5x=None, play=None, last=None):
    """daily_rows: [(datetime, o, h, l, c)]; minutes: {epoch: [o, h, l, c, v]}."""
    daily = {nyt(dt.year, dt.month, dt.day): [o, h, l, c] for dt, o, h, l, c in daily_rows}
    bars = {k: list(v) + [0.0, 0.0] for k, v in (minutes or {}).items()}
    st = SimpleNamespace(daily=daily, daily_vol={k: 1e6 for k in daily}, bars=bars, m30=m30 or {}, m5x=m5x or {}, m5={},
                         play=play or {"side": "long"}, study_ver=0, hist_ver=0, symbol="TEST")
    lp = last if last is not None else (bars[max(bars)][3] if bars else daily_rows[-1][4])
    st.price = lambda: lp
    return st


class SeriesTests(unittest.TestCase):
    def test_ema_seeded_with_sma_like_the_chart(self):
        src = [1, 2, 3, 4, 5, 6]
        e = S.ema(src, 3)
        self.assertEqual(e[:2], [None, None])
        self.assertAlmostEqual(e[2], 2.0)                         # SMA of 1, 2, 3
        self.assertAlmostEqual(e[3], 4 * 0.5 + 2.0 * 0.5)         # k = 2 / (3 + 1)
        self.assertAlmostEqual(S.sma(src, 3)[-1], 5.0)

    def test_rma_is_wilder(self):
        r = S.rma([2, 4, 6, 8], 3)
        self.assertAlmostEqual(r[2], 4.0)
        self.assertAlmostEqual(r[3], (8 + 2 * 4.0) / 3)

    def test_bb_population_stdev(self):
        up, dn = S.bbands([1.0, 2.0, 3.0], 3, 2.0)
        sd = (2 / 3) ** 0.5
        self.assertAlmostEqual(up[-1], 2 + 2 * sd); self.assertAlmostEqual(dn[-1], 2 - 2 * sd)

    def test_true_range_first_bar_is_high_minus_low(self):
        self.assertEqual(S.true_range([10, 12], [8, 11], [9, 11.5]), [2, 3])

    def test_pivot_needs_both_sides(self):
        hs = [1, 2, 5, 2, 1]
        self.assertEqual(S.pivot_at(hs, 4, 2, 2, True), 5)
        self.assertIsNone(S.pivot_at(hs, 3, 2, 2, True))           # only 1 bar to the right yet

    def test_60_minute_candles_start_at_930(self):
        d = (2026, 9, 14)
        rows = [[nyt(*d, 9, 30), 10, 11, 9, 10.5, 1], [nyt(*d, 10, 0), 10.5, 12, 10, 11, 1], [nyt(*d, 10, 30), 11, 11.5, 10.8, 11.2, 1]]
        h = S.h60_from_m30(rows)
        self.assertEqual([r[0] for r in h], [nyt(*d, 9, 30), nyt(*d, 10, 30)])
        self.assertEqual(h[0][2:5], [12, 9, 11])


class GasTests(unittest.TestCase):
    def setUp(self):
        days = weekdays_before(2026, 9, 14, 40)
        rows, c = [], 100.0
        for i, dt in enumerate(days):
            o = c; h = c + 2; l = c - 2; c = c + (0.5 if i % 2 else -0.3)
            rows.append((dt, o, h, l, c))
        self.rows = rows
        self.today = (2026, 9, 14)                    # a Monday
        # today: 9:30-10:29, range 100.0 .. 103.0
        mins = {}
        for k in range(60):
            t0 = nyt(*self.today, 9, 30) + 60 * k
            p = 100.0 + 3.0 * k / 59
            mins[t0] = [p, p, p, p, 100.0]
        mins[nyt(*self.today, 8, 0)] = [95.0, 95.0, 95.0, 95.0, 50.0]      # a premarket print: never the day's low
        self.st = make_st(rows, mins)
        self.t = nyt(*self.today, 10, 30)

    def test_tank_is_the_prior_completed_days_atr(self):
        drows, live = S.daily_series(self.st, self.t)
        self.assertTrue(live)
        self.assertEqual(drows[-1][3], 100.0)         # today's low = the regular session's, not the 95 premarket print
        g = S.gas(self.st, self.t, CFG, drows, live)
        hs = [r[2] for r in drows]; ls = [r[3] for r in drows]; cs = [r[4] for r in drows]
        self.assertAlmostEqual(g["y_atr"], S.atr_rma(hs, ls, cs, 14)[-2])
        prev_c = cs[-2]
        self.assertAlmostEqual(g["used"], max(3.0, abs(103.0 - prev_c), abs(100.0 - prev_c)))

    def test_atr_levels_from_todays_range(self):
        drows, live = S.daily_series(self.st, self.t)
        g = S.gas(self.st, self.t, CFG, drows, live)
        a, used = g["y_atr"], g["used"]
        ones = [ln for ln in g["lines"] if ln["l"].startswith("1 ATR")]
        self.assertEqual(len(ones), 1)                # one side only: the ladder draws on the side the day is moving
        prev_c = drows[-2][4]
        up = (103.0 - prev_c) >= (prev_c - 100.0)
        self.assertAlmostEqual(ones[0]["p"], 103.0 + (a - used) if up else 100.0 - (a - used))

    def test_prev_day_and_whole_numbers(self):
        drows, live = S.daily_series(self.st, self.t)
        off = S.gas(self.st, self.t, CFG, drows, live)          # whole numbers are off unless you switch them on
        self.assertFalse([ln for ln in off["lines"] if ln["l"].startswith("WHOLE ")])
        g = S.gas(self.st, self.t, dict(CFG, whole_numbers=True), drows, live)
        labels = [ln["l"] for ln in g["lines"]]
        self.assertTrue(any(l.startswith("PDH ") and S.s2(self.rows[-1][2]) in l for l in labels))
        wn = sorted(ln["p"] for ln in g["lines"] if ln["l"].startswith("WHOLE "))
        self.assertEqual(wn, [100.0, 101.0, 102.0, 104.0, 105.0, 106.0])
        self.assertTrue(any(l.startswith("HIGH OF DAY ") for l in labels) and any(l.startswith("LOW OF DAY ") for l in labels))    # $1 steps over $80, round(103) skipped

    def test_old_supply_is_last_finished_month(self):
        drows, live = S.daily_series(self.st, self.t)
        aug = [r for r in self.rows if r[0].month == 8]
        hi, lo = S.prev_month_hl(drows, self.t)
        self.assertEqual(hi, max(r[2] for r in aug)); self.assertEqual(lo, min(r[3] for r in aug))

    def test_premarket_high_low_locked(self):
        m5x = {nyt(*self.today, 8, 0): [95, 96, 94.5, 95.5, 100], nyt(*self.today, 9, 0): [97, 98, 96, 97, 100]}
        self.st.m5x = m5x
        s = S.session_levels(self.st, self.t)
        self.assertEqual((s["pmh"], s["pml"]), (98, 94.5))
        self.assertEqual(s["open"], 100.0)

    def test_premarket_close_from_the_one_minute_bars_and_locked_after_the_open(self):
        self.st.m5x = {nyt(*self.today, 9, 25): [97, 97.5, 96.8, 97.2, 100]}
        bars = dict(self.st.bars)
        bars[nyt(*self.today, 9, 28)] = [97.3, 97.4, 97.0, 97.1, 50.0, 0, 0]
        bars[nyt(*self.today, 9, 29)] = [97.1, 97.6, 97.05, 97.45, 50.0, 0, 0]
        self.st.bars = bars
        s = S.session_levels(self.st, self.t)
        self.assertEqual(s["pmc"], 97.45)                     # the 9:29 one-minute close, not the 9:25 five-minute one
        self.assertEqual(s["pmh"], 97.6)
        # later in the day the premarket numbers do not move
        bars[nyt(*self.today, 11, 0)] = [90.0, 99.0, 89.0, 95.0, 50.0, 0, 0]
        s2 = S.session_levels(self.st, nyt(*self.today, 11, 1))
        self.assertEqual((s2["pmh"], s2["pml"], s2["pmc"]), (s["pmh"], s["pml"], s["pmc"]))

    def test_second_entry_from_your_pivot(self):
        st = self.st
        st.play = {"side": "long", "trigger": 101.0}
        mins = {}
        path = [100.5, 101.5, 102.0, 103.0, 102.0, 101.6, 101.8]
        for k, p in enumerate(path):
            t0 = nyt(*self.today, 9, 30) + 60 * k
            mins[t0] = [p, p, p, p, 100.0, 0, 0]
        st.bars = mins
        drows, live = S.daily_series(st, nyt(*self.today, 9, 40))
        g = S.gas(st, nyt(*self.today, 9, 40), dict(CFG, se_min_retrace_x=0.01), drows, live)
        # push to 103, 30% of the 2.00 push = 0.60: the 102.0 retrace arms the 2nd
        self.assertIn("2ND", g["se"]["t"])

    def test_off_switch(self):
        out = S.compute(self.st, self.t, dict(CFG, gas=False, airspace=False, unvisited=False))
        self.assertIsNone(out["gas"]); self.assertIsNone(out["air"]); self.assertIsNone(out["uv"])


class AirspaceTests(unittest.TestCase):
    def test_bounce_is_nearest_indicator_under_the_low_never_structure(self):
        vals = [(95.0, "EMA 20"), (96.5, "PL"), (94.2, "SMA 50"), (105.0, "EMA 50"), (105.6, "SMA 100"), (110.0, "EMA 200")]
        out = S.band_levels(vals, p=100.0, high=101.0, low=99.0, atr_v=3.0, dist=1.0)
        self.assertEqual((out["near_dem"], out["near_dem_n"]), (95.0, "EMA 20"))     # PL at 96.5 is structure: skipped
        self.assertEqual((out["far_dem"], out["far_dem_n"]), (94.2, "SMA 50"))       # stacked within $1: MP band edge
        self.assertEqual((out["near_sup"], out["far_sup"]), (105.0, 105.6))
        self.assertEqual(out["next_sup"], 110.0)

    def test_tip_clear(self):
        # an MA sitting on the bar's low (inside the tip buffer) is not the Bounce
        out = S.band_levels([(98.995, "EMA 5"), (97.0, "EMA 10")], p=100.0, high=101.0, low=99.0, atr_v=2.0, dist=0.5)
        self.assertEqual(out["near_dem"], 97.0)

    def test_tags(self):
        self.assertEqual(S._tag("EMA 20"), "20E"); self.assertEqual(S._tag("W SMA 50"), "W50S"); self.assertEqual(S._tag("BB lower"), "BbL")

    def test_mt_supply_only_after_the_last_takeout(self):
        # day 0..: a high at 120 taken out, then three tags at 110 that held (closes under)
        days = weekdays_before(2026, 9, 14, 30)
        rows = []
        for i, dt in enumerate(days):
            h = 90.0 + i * 0.6; l = h - 3.0; c = h - 1.0          # ordinary highs, never three within the cluster
            if i == 5:
                h = 125.0                                 # sharply above everything: older highs are dead
            if i in (12, 18, 24):
                h, c = 110.0, 106.0
            rows.append([datetime(dt.year, dt.month, dt.day, tzinfo=NY).timestamp(), c, h, l, c, 1.0])
        m = S.mt_supply(rows, dict(CFG, air_mt_cluster_dollars=0.5, air_mt_cluster_atr=0.01), 5.0)
        self.assertIsNotNone(m)
        self.assertEqual((m["p"], m["n"]), (110.0, 3))
        self.assertEqual(m["t0"], rows[12][0])            # origin = the oldest of the three tags

    def test_fuel_words(self):
        self.assertTrue(S.fuel_words(0.8, 2.0, 3.0)[0].startswith("ENOUGH"))
        self.assertTrue(S.fuel_words(2.5, 9.0, 3.0)[0].startswith("NOT ENOUGH"))


class UnvisitedTests(unittest.TestCase):
    def _rows(self, highs, closes=None):
        days = weekdays_before(2026, 9, 14, len(highs))
        return [[datetime(d.year, d.month, d.day, tzinfo=NY).timestamp(), 100.0, h, 90.0, (closes or {}).get(i, 95.0), 1.0]
                for i, (d, h) in enumerate(zip(days, highs))]

    def test_pivot_high_stays_until_a_daily_close_through(self):
        hs = [100, 101, 102, 103, 104, 110, 104, 103, 102, 101, 100, 99, 98]
        rows = self._rows(hs)
        out = S.unvisited(rows, False, dict(CFG, uv_lows=False))
        self.assertEqual([round(l["p"], 2) for l in out["lines"]], [110.0])
        self.assertEqual(out["lines"][0]["d"], "solid")
        # a later day tags 109.9 (within 0.25%) and closes under: touched -> dashed, still there
        rows2 = self._rows(hs + [109.9], {13: 105.0})
        out = S.unvisited(rows2, False, dict(CFG, uv_lows=False))
        self.assertEqual(out["lines"][0]["d"], "dash")
        self.assertNotIn("x1", out["lines"][0]["l"])                   # the label is just the date, high and price
        # a daily CLOSE above clears it
        rows3 = self._rows(hs + [111.0], {13: 110.5})
        self.assertEqual(S.unvisited(rows3, False, dict(CFG, uv_lows=False))["lines"], [])

    def test_live_poke_never_clears(self):
        hs = [100, 101, 102, 103, 104, 110, 104, 103, 102, 101, 100, 99, 98, 111]
        rows = self._rows(hs, {13: 110.5})
        out = S.unvisited(rows, True, dict(CFG, uv_lows=False))        # today is live: only a flag
        self.assertEqual(len(out["lines"]), 1)
        self.assertIn("CLOSING THROUGH", out["lines"][0]["l"])

    def test_close_levels_merge(self):
        hs = [100, 101, 102, 103, 104, 110, 104, 103, 102, 101, 100, 101, 102, 103, 104, 110.3, 104, 103, 102, 101, 100]
        out = S.unvisited(self._rows(hs), False, dict(CFG, uv_lows=False))
        self.assertEqual(len(out["lines"]), 1)
        self.assertIn("110.00 / 110.30", out["lines"][0]["l"]); self.assertEqual(out["lines"][0]["w"], 3)


class ContTests(unittest.TestCase):
    def test_similar_days_matched_at_the_checkpoint(self):
        days = weekdays_before(2026, 9, 14, 40)
        drows = [[datetime(d.year, d.month, d.day, tzinfo=NY).timestamp(), 100, 102, 98, 100, 1] for d in days]
        drows.append([nyt(2026, 9, 14), 100, 101, 99.5, 100.5, 1])
        m30 = {}
        for i, d in enumerate(days[-25:]):
            for k in range(13):
                t0 = nyt(d.year, d.month, d.day, 9, 30) + 1800 * k
                # every past day moves 0.25 a bar: progress 1.0 ATR (ATR 4) at 10:00 already ... finishes 13 x 0.25 = 3.25
                lo = 100.0; hi = 100.0 + 0.25 * (k + 1)
                m30[t0] = [lo, hi, lo, hi, 1.0]
        st = make_st([(d, 100, 102, 98, 100) for d in days])
        st.m30 = m30
        t = nyt(2026, 9, 14, 10, 5)
        st.bars = {nyt(2026, 9, 14, 9, 30) + 60 * k: [100.0, 100.3, 100.0, 100.3, 1, 0, 0] for k in range(35)}
        c = S.cont_odds(drows, S.m30_series(st, t), t, dict(CFG, cont_min_days=5), True, 4.0, 100.0)
        self.assertEqual(c["k"], 0)
        self.assertGreater(c["tot"], 20)


if __name__ == "__main__":
    unittest.main()


class AtrLadderTests(unittest.TestCase):
    def test_eaten_rungs_are_coloured_and_the_rest_is_faint(self):
        from twiney.studies import atr_ladder
        cfg = {"atr_ladder_opacity": 18, "atr_ladder_left_opacity": 4, "atr_ladder_step": 0.25, "atr_ladder_max": 2.0}
        # ATR $4, the day went 100 -> 102.6: 65% of the tank eaten, moving up
        lad = atr_ladder(102.6, 100.0, 2.6, 4.0, True, True, cfg, 102.5)
        rungs = [l for l in lad["lines"]]
        self.assertEqual([l["rung"] for l in rungs], [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0])
        self.assertEqual([round(l["p"], 2) for l in rungs[:4]], [101.0, 102.0, 103.0, 104.0])
        self.assertTrue(rungs[0]["eaten"] and rungs[1]["eaten"] and not rungs[2]["eaten"])
        self.assertIn("½ ATR EATEN", rungs[1]["l"])
        self.assertEqual(rungs[2]["l"], "¾ ATR 103.00 · $0.50 away · 65% eaten")
        self.assertEqual(rungs[3]["l"], "1 ATR 104.00 · $1.50 away")
        hot = [z for z in lad["zones"] if z["eat"]]
        self.assertEqual(len(hot), 3)                       # ¼, ½ and the eaten part of ¾
        self.assertAlmostEqual(hot[-1]["b"], 102.6)
        self.assertTrue(all(z["c"].endswith("0.18)") for z in hot))
        self.assertTrue(all(z["c"].endswith("0.04)") for z in lad["zones"] if not z["eat"]))

    def test_down_move_ladders_down_from_the_high(self):
        from twiney.studies import atr_ladder
        lad = atr_ladder(50.0, 48.5, 1.5, 2.0, False, True, {}, 48.6)
        self.assertEqual(round(lad["lines"][3]["p"], 2), 48.0)            # 1 ATR under the high
        self.assertTrue(lad["lines"][2]["eaten"])                         # 1.5 of 2.0 = ¾ eaten
        self.assertEqual(lad["lines"][3]["l"], "1 ATR 48.00 · $0.60 away · 75% eaten")


class H60OnTheHourTests(unittest.TestCase):
    """60-minute candles like the user's TradingView 1h (extended hours): they start on the clock hour and the premarket
    is inside them (9:00-10:00 holds 9:00-9:30 premarket AND the 9:30 open)."""
    def test_on_the_hour_with_premarket(self):
        from types import SimpleNamespace
        from twiney import studies as S
        import calendar
        base = calendar.timegm((2026, 10, 6, 12, 0, 0)) # 8:00 New York (EDT = UTC-4)
        m5 = {}
        for i in range(36):                              # 8:00 .. 10:55 every 5 minutes
            t0 = base + i * 300
            m5[t0] = [100 + i, 100.5 + i, 99.5 + i, 100.2 + i, 1000]
        st = SimpleNamespace(m5=m5, bars={}, m30={})
        h = S.h60_series(st, base + 36 * 300, {"h60_on_hour": True})
        self.assertEqual([(r[0] - base) // 3600 for r in h], [0, 1, 2])        # 8:00, 9:00, 10:00
        nine = h[1]
        self.assertEqual(nine[1], 112)                                          # opens at 9:00 (premarket)
        self.assertEqual(nine[4], 123.2)                                        # closes at the 9:55 bar
        self.assertEqual(nine[5], 12000)                                        # 12 five-minute bars in it
        off = S.h60_series(st, base + 36 * 300, {"h60_on_hour": False})        # the old way: no 5-minute history used
        self.assertIsInstance(off, list)
