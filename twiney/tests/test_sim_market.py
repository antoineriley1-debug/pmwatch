"""THE MARKET DAY in the practice feed: the session's shape, the VWAP magnet, a trend that breathes, the key levels
defended or taken, volatility that clusters, the news shock."""
import datetime as dt
import unittest
from zoneinfo import ZoneInfo

from helpers import cfg, plays
from twiney.engine import Engine
from twiney.sim import ASK, BID, DemoFeed

NY = ZoneInfo("America/New_York")


def ny(h, m, day=5):
    return dt.datetime(2026, 10, day, h, m, tzinfo=NY).timestamp()       # Monday Oct 5 2026


class PhaseTests(unittest.TestCase):
    def test_the_session_has_a_shape(self):
        names = {h_m: DemoFeed._phase_at(ny(*h_m))["name"] for h_m in ((9, 35), (10, 15), (11, 0), (13, 0), (15, 0), (15, 45), (8, 0), (17, 0))}
        self.assertEqual(names[(9, 35)], "open"); self.assertEqual(names[(10, 15)], "reversal"); self.assertEqual(names[(11, 0)], "morning")
        self.assertEqual(names[(13, 0)], "midday"); self.assertEqual(names[(15, 0)], "afternoon"); self.assertEqual(names[(15, 45)], "close")
        self.assertEqual(names[(8, 0)], "closed"); self.assertEqual(names[(17, 0)], "closed")
        self.assertGreater(DemoFeed._phase_at(ny(9, 35))["rate"], 2.0)
        self.assertLess(DemoFeed._phase_at(ny(13, 0))["rate"], 0.8)
        self.assertGreater(DemoFeed._phase_at(ny(13, 0))["vwap"], DemoFeed._phase_at(ny(9, 35))["vwap"])


class FeedTests(unittest.TestCase):
    def feed(self, t, seed=3):
        c, ps = cfg(), plays()
        live = Engine(ps, c, None)
        f = DemoFeed(live, ps, seed=seed)
        f.start(t)
        return live, f

    def test_the_vwap_pulls_price_back_at_midday(self):
        t = ny(13, 0)
        live, f = self.feed(t)
        s = next(iter(f.state.values()))
        s.regime, s.regime_until, s.script = "chop", t + 600, []
        s.vwap_pv, s.vwap_v = s.last * 0.99 * 1000, 1000.0            # VWAP 1% under price
        b_hi = f._params(s, t)[0]
        s.vwap_pv = s.last * 1000                                        # VWAP at the price
        b_at = f._params(s, t)[0]
        self.assertLess(b_hi, b_at)                                       # stretched over it: the lean comes back down

    def test_a_trend_breathes_push_then_pullback(self):
        t = ny(11, 0)
        live, f = self.feed(t)
        s = next(iter(f.state.values()))
        s.regime, s.regime_until, s.script = "trend_up", t + 1200, []
        modes = set()
        for i in range(0, 900, 5):
            f._params(s, t + i)
            if s.pulse:
                modes.add(s.pulse["mode"])
        self.assertEqual(modes, {"push", "pullback"})
        f.mkt.pulse = {"mode": "pullback", "until": t + 2000}
        b_pb = f._params(s, t + 1000)[0]
        f.mkt.pulse = {"mode": "push", "until": t + 2000}
        b_push = f._params(s, t + 1000)[0]
        self.assertLess(b_pb, b_push)                                    # the pullback leans against the trend, shallow

    def test_the_prior_day_high_gets_someone_working_it(self):
        t = ny(11, 0)
        live, f = self.feed(t)
        sym, s = next(iter(f.state.items()))
        s.pdh = round(s.asks[2][0], 2)                                   # the prior-day high two ticks over the offer
        s.pdl = s.pdc = None; s.hod = s.lod = None
        s.hot_dir = 1; s.lv_next = t; s.parts = []
        f.rng.seed(1)
        for k in range(12):
            f._participants(sym, s, t + k * 25)
            if any(pt.get("key") == "PDH" for pt in s.parts):
                break
        pt = next((pt for pt in s.parts if pt.get("key") == "PDH"), None)
        self.assertIsNotNone(pt); self.assertEqual(pt["side"], ASK); self.assertAlmostEqual(pt["price"], s.pdh, places=2)

    def test_news_hits_the_tape(self):
        t = ny(11, 0)
        live, f = self.feed(t)
        f.shock_next = t
        f._news(t)
        hit = [s for s in f.state.values() if s.episode == "news"]
        self.assertTrue(hit)
        self.assertGreaterEqual(hit[0].vs, 3.0)
        self.assertEqual(len(hit[0].script), 2)
        self.assertGreater(f.shock_next, t + 3000)

    def test_volatility_clusters_then_fades(self):
        t = ny(11, 0)
        live, f = self.feed(t)
        s = next(iter(f.state.values()))
        s.vs = 3.0
        s.regime, s.regime_until, s.script = "chop", t + 3600, []
        for i in range(1, 4 * 60 * 6):                                    # six quiet minutes in a chop
            f.step(t + i * 0.25)
        self.assertLess(s.vs, 2.4)

    def test_the_day_opens_with_its_high_low_and_vwap(self):
        t = ny(9, 31)
        live, f = self.feed(t)
        s = next(iter(f.state.values()))
        for i in range(1, 4 * 60):
            f.step(t + i * 0.25)
        self.assertIsNotNone(s.day_open); self.assertGreaterEqual(s.hod, s.lod); self.assertGreater(s.vwap_v, 0)


class PracticeClockTests(unittest.TestCase):
    def test_at_night_the_practice_day_opens_when_the_feed_starts(self):
        c, ps = cfg(), plays()
        live = Engine(ps, c, None)
        f = DemoFeed(live, ps, seed=3)
        t = ny(22, 0)                                                     # 10 pm New York
        f.start(t)
        self.assertEqual(f._phase(t + 60)["name"], "open")
        self.assertEqual(f._phase(t + 200 * 60)["name"], "midday")
        self.assertEqual(f._phase(t + 380 * 60)["name"], "close")
        self.assertEqual(f._phase(t + 395 * 60)["name"], "open")          # the next practice day
        self.assertNotEqual(f._day_key(t + 60), f._day_key(t + 395 * 60))

    def test_during_the_session_the_real_clock_is_the_clock(self):
        c, ps = cfg(), plays()
        live = Engine(ps, c, None)
        f = DemoFeed(live, ps, seed=3)
        t = ny(13, 0)
        f.start(t)
        self.assertEqual(f._phase(t)["name"], "midday")
        self.assertEqual(f._phase(t + 150 * 60)["name"], "close")


class ExtendedHoursTests(unittest.TestCase):
    def test_the_practice_desk_has_premarket_and_after_hours_levels(self):
        from twiney import studies
        c, ps = cfg(), plays()
        live = Engine(ps, c, None)
        f = DemoFeed(live, ps, seed=3)
        t = ny(11, 0)
        f.start(t)
        for i in range(1, 12):                                  # a few seconds of tape: a price to tell the story from
            f.step(t + i * 0.25)
        sym, s = next(iter(f.state.items()))
        st = live.syms[sym]
        sess = studies.session_levels(st, t)
        self.assertIsNotNone(sess["pmh"]); self.assertIsNotNone(sess["pml"]); self.assertGreater(sess["pmh"], sess["pml"])
        self.assertIsNotNone(sess["ahh"]); self.assertIsNotNone(sess["ahl"])
        self.assertAlmostEqual(s.pmh, sess["pmh"], places=2)
        codes = {c for L in live.key_levels(st, t) for c in str(L["code"]).split("/")}   # levels on top of each other share a row
        self.assertTrue({"PMH", "PML", "AHH", "AHL"} <= codes, codes)
        live._story(st, t, c.get("story") or {})                # the story builds with them in
        pts = [p["name"] for p in __import__("twiney.story", fromlist=["x"]).session_points(sess)]
        self.assertIn("premarket high", pts)
