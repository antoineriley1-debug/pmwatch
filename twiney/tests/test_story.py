"""PS60 STORY: Daily context, places, zones, confluence, x.00 / x.50 reloads, option flow states, price response,
and the running story itself. PS60 stays the foundation: these only read on top of it."""
import datetime as dt
import unittest
from zoneinfo import ZoneInfo

from twiney import board, story
from twiney.config import DEFAULTS

CFG = dict(DEFAULTS["story"])
NY = ZoneInfo("America/New_York")


def ny_t(y, m, d, hh, mm=0):
    return dt.datetime(y, m, d, hh, mm, tzinfo=NY).timestamp()


def daily_rows(closes, start=None, rng=1.0):
    """[t0, o, h, l, c, v] for consecutive weekdays ending yesterday."""
    t0 = start or ny_t(2026, 1, 5, 0)
    out, d = [], dt.datetime.fromtimestamp(t0, NY)
    for c in closes:
        while d.weekday() >= 5:
            d += dt.timedelta(days=1)
        out.append([d.timestamp(), c, c + rng, c - rng, c, 1e6])
        d += dt.timedelta(days=1)
    return out


def prints(cp, usd, n, now, otm=3.0, dte=3, side="ask", age=60):
    return [{"t": now - age - k, "cp": cp, "side": side, "premium": usd / n, "otm_pct": otm, "dte": dte} for k in range(n)]


class QualifyTests(unittest.TestCase):
    def test_only_whole_and_half_dollars_count(self):
        for p in (142.00, 142.50, 143.00, 143.50):
            self.assertTrue(story.qualifies(p), p)
        for p in (142.23, 142.75, 143.17, 142.49, 142.01):
            self.assertFalse(story.qualifies(p), p)

    def test_board_reload_trap_ignores_a_reloader_off_the_half_dollar(self):
        play = {"side": "long", "trigger": 142.0, "second_entry": 142.3}
        seller = {"price": 142.75, "side": "ask", "kind": "confirmed", "stage": "RELOADING", "absorbed": 9000}
        cg = board.chart_gate(play, 142.4, {"state": "SECOND_ENTRY", "build": "building"}, None,
                              {"below": [], "above": [dict(seller, ps60=False)]}, None, 0, {})
        self.assertFalse(cg["reload_trap"])           # 142.75: on the ladder, not in PS60
        cg = board.chart_gate(play, 142.4, {"state": "SECOND_ENTRY", "build": "building"}, None,
                              {"below": [], "above": [dict(seller, price=143.0, ps60=True)]}, None, 0, {})
        self.assertTrue(cg["reload_trap"])            # 143.00 counts


class DailyTests(unittest.TestCase):
    def test_above_the_50_day_is_bullish_and_the_objective_is_the_prior_day_high(self):
        rows = daily_rows([100 + 0.2 * i for i in range(60)])
        ctx = story.daily_context(rows, False, rows[-1][4] + 0.1)
        self.assertEqual(ctx["bias"], "bull")
        self.assertEqual(ctx["objective"], [rows[-1][2], "prior-day high"])
        self.assertFalse(ctx["taken"])
        self.assertIn("Objective: take the prior-day high", ctx["text"])
        ctx = story.daily_context(rows, False, rows[-1][2] + 0.5)
        self.assertTrue(ctx["taken"])

    def test_below_the_50_day_is_bearish_and_the_objective_is_the_prior_day_low(self):
        rows = daily_rows([200 - 0.5 * i for i in range(60)])
        ctx = story.daily_context(rows, False, rows[-1][4])
        self.assertEqual(ctx["bias"], "bear")
        self.assertEqual(ctx["objective"][1], "prior-day low")

    def test_structure_has_day_week_month_and_52_week(self):
        rows = daily_rows([100 + (i % 7) for i in range(80)])
        t = rows[-1][0] + 86400 * 3
        kinds = {p["kind"] for p in story.structure_points(rows, False, t)}
        self.assertTrue({"pdh", "pdl", "pwh", "pwl", "mh", "ml", "yh", "yl"} <= kinds)


class ZoneTests(unittest.TestCase):
    def test_four_rejections_make_a_resistance_zone(self):
        rows, t = [], 1_000_000.0
        price = 140.0
        # 4 separate runs up into 145 that turn back, with quiet bars between them
        for run in range(4):
            for k in range(6):
                rows.append([t, price, price + 0.3, price - 0.3, price, 1000]); t += 1800
            rows.append([t, 144.6, 145.05 + 0.02 * run, 144.5, 144.6, 1000]); t += 1800
            for k in range(6):
                rows.append([t, 143.5, 143.8, 143.2, 143.5, 1000]); t += 1800
        z = story.detect_zones(rows, 143.4, 3.0, 0.01, CFG)
        res = [x for x in z if x["kind"] == "resistance" and x["lo"] > 144]
        self.assertTrue(res)
        self.assertEqual(res[0]["held"], 4)
        self.assertIn("RESISTANCE ZONE", res[0]["name"])
        self.assertIn("FOUR PRIOR REJECTIONS", res[0]["name"])
        self.assertLessEqual(res[0]["lo"], 145.05)
        self.assertGreaterEqual(res[0]["hi"], 145.11)


class ConfluenceTests(unittest.TestCase):
    def test_four_levels_at_145_are_one_major_place(self):
        pts = [{"p": 145.03, "name": "prior-day high", "kind": "pdh"}, {"p": 145.00, "name": "PS60 pivot", "kind": "pivot"}]
        zones = [{"lo": 144.90, "hi": 145.10, "kind": "resistance", "short": "resistance zone 144.90–145.10", "held": 4}]
        c = story.confluence(pts, zones, 144.70, 3.0, 0.01, CFG)
        self.assertEqual(len(c), 1)
        self.assertTrue(c[0]["major"])
        self.assertEqual(c[0]["p"], 145.0)
        self.assertTrue(c[0]["text"].startswith("Major PS60 confluence around 145.00"))
        for nm in ("prior-day high 145.03", "PS60 pivot 145.00", "whole dollar 145.00", "resistance zone 144.90–145.10"):
            self.assertIn(nm, c[0]["text"])

    def test_a_lone_level_is_not_confluence(self):
        self.assertEqual(story.confluence([{"p": 145.0, "name": "PS60 pivot", "kind": "pivot"}], [], 144.7, 3.0, 0.01, CFG), [])


class FlowTests(unittest.TestCase):
    def test_four_states(self):
        now = 10_000.0
        self.assertEqual(story.flow_state(story.flow_read([], now, CFG), True, CFG)["state"], "NOT YET CONFIRMED")
        dev = story.flow_state(story.flow_read(prints("C", 80_000, 1, now), now, CFG), True, CFG)
        self.assertEqual(dev["state"], "DEVELOPING")
        self.assertIn("OTM calls", dev["text"])
        conf = story.flow_state(story.flow_read(prints("C", 400_000, 4, now), now, CFG), True, CFG)
        self.assertEqual(conf["state"], "CONFIRMED")
        self.assertIn("Option flow confirming", conf["text"])
        bad = story.flow_state(story.flow_read(prints("P", 300_000, 3, now), now, CFG), True, CFG)
        self.assertEqual(bad["state"], "CONFLICTING")
        self.assertIn("puts", bad["text"])

    def test_deep_otm_is_named_and_months_out_does_not_count(self):
        now = 10_000.0
        d = story.flow_state(story.flow_read(prints("P", 100_000, 2, now, otm=8.0), now, CFG), False, CFG)
        self.assertIn("deep OTM puts", d["text"])
        far = story.flow_read(prints("C", 900_000, 4, now, dte=60), now, CFG)
        self.assertEqual(story.flow_state(far, True, CFG)["state"], "NOT YET CONFIRMED")


class ResponseTests(unittest.TestCase):
    def mins(self, closes):
        return [[k * 60, c, c, c, c, 100] for k, c in enumerate(closes)]

    def test_bearish_flow_with_price_not_going_lower(self):
        now = 10_000.0
        fr = story.flow_read(prints("P", 300_000, 3, now), now, CFG)
        r = story.response(self.mins([100.0, 100.02, 100.05, 100.04, 100.06, 100.08]), fr, None, 0.10, CFG)
        self.assertEqual(r["text"], "Bearish flow present, but price is not responding lower")

    def test_selling_absorbed(self):
        fr = story.flow_read([], 10_000.0, CFG)
        r = story.response(self.mins([100.0] * 6), fr, {"buy_pct": 25, "ratio": 1.8}, 0.10, CFG)
        self.assertEqual(r["text"], "Selling pressure being absorbed. Downside confirmation weakening")


class StoryRunTests(unittest.TestCase):
    """The bullish sequence: approaching, tested with a reload seller at the whole dollar, consumed, cleared, retest held."""

    def run_one(self, sb, t, last, reloads=(), consumed=(), flow=(), pace=None, mins=None):
        play = {"side": "long", "trigger": 145.0, "second_entry": 144.6}
        pts = story.ps60_points(play) + [{"p": 145.03, "name": "prior-day high", "kind": "pdh"}]
        ctx = {"bias": "bull", "text": "Daily above the 50-day (138.20): bullish PS60. Objective: take the prior-day high 145.03.", "taken": last > 145.03}
        conf = story.confluence(pts, [], last, 3.0, 0.01, CFG)
        fr = story.flow_read(list(flow), t, CFG)
        return story.build(sb, t, last, 0.01, 3.0, play, None, ctx, pts, [], conf, fr, pace, list(reloads), list(consumed),
                           mins or [[t - 300, last, last, last, last, 1], [t - 60, last, last, last, last, 1]], CFG)

    def test_the_bullish_sequence(self):
        sb = story.Story()
        t = ny_t(2026, 10, 5, 10, 0)
        out = self.run_one(sb, t, 144.10, pace={"state": "FAST", "buy_pct": 70, "ratio": 1.8})
        self.assertFalse(out["attention"])
        self.assertIn("approaching", out["now"])
        self.assertIn("Buyers stepping up", out["now"])
        self.assertIn("No confirming call flow yet", out["now"])
        # at 145: the reload seller on the whole dollar, calls coming in
        flow = prints("C", 120_000, 2, t + 60)
        out = self.run_one(sb, t + 60, 144.98, reloads=[{"price": 145.0, "side": "ask", "stage": "RELOADING", "absorbed": 8000}],
                           flow=flow, pace={"state": "FAST", "buy_pct": 72, "ratio": 1.7})
        self.assertTrue(out["attention"])
        self.assertIn("Major PS60 confluence around 145.00", out["now"])
        self.assertIn("Reload seller defending the whole dollar 145.00", out["now"])
        self.assertIn("Buyers continue attacking 145.00. Seller absorbing", out["now"])
        self.assertIn("Option confirmation developing", out["now"])
        self.assertTrue(any("Reload seller confirmed at the institutional whole dollar level 145.00" in s["text"] for s in out["said"]))
        # consumed: through 145 and the prior-day high, calls building
        flow = prints("C", 500_000, 5, t + 120)
        out = self.run_one(sb, t + 120, 145.12, consumed=[{"price": 145.0, "side": "ask"}], flow=flow,
                           pace={"state": "SURGE", "buy_pct": 80, "ratio": 3.0},
                           mins=[[t - 300 + 60 * k, c, c, c, c, 1] for k, c in enumerate((144.60, 144.75, 144.90, 145.0, 145.05, 145.12))])
        self.assertIn("Reload seller consumed at 145.00", out["now"])
        self.assertIn("Option flow confirming", out["now"])
        self.assertEqual(out["tone"], "bull")
        # pull back to the level and hold it
        self.run_one(sb, t + 400, 145.05, flow=flow)
        out = self.run_one(sb, t + 500, 145.40, flow=flow)
        feed = [f[1] for f in sb.feed]
        self.assertTrue(any(x.startswith("Retest holding above") and "Buyers remain in control" in x for x in feed), feed)
        self.assertTrue(any("Daily above the 50-day" in x for x in feed))

    def test_unusual_flow_is_remembered_then_aligned_with_the_second_entry(self):
        sb = story.Story()
        t = ny_t(2026, 10, 5, 10, 0)
        flow = prints("C", 150_000, 2, t)
        out = self.run_one(sb, t, 140.0, flow=flow)            # far from anything: no PS60 trigger
        self.assertTrue(any("Unusual OTM calls detected" in f[1] and "No immediate PS60 trigger. Watching" in f[1] for f in sb.feed))
        out = self.run_one(sb, t + 1200, 144.50)               # later: price comes to the 2nd entry from below
        self.assertTrue(any("Earlier OTM call activity" in s["text"] and "now aligning with PS60 Second Entry" in s["text"]
                            for s in out["said"]), [f[1] for f in sb.feed])

    def test_failed_breakout_is_called(self):
        sb = story.Story()
        t = ny_t(2026, 10, 5, 11, 0)
        self.run_one(sb, t, 144.80)
        self.run_one(sb, t + 60, 145.20)
        self.run_one(sb, t + 200, 145.05)
        out = self.run_one(sb, t + 260, 144.80)
        self.assertTrue(any("failed breakout" in s["text"] for s in out["said"]), [f[1] for f in sb.feed])


class EngineTests(unittest.TestCase):
    def test_zone_is_saved_and_in_the_story(self):
        from helpers import cfg, plays
        from twiney.engine import Engine
        e = Engine(plays(), cfg())
        e.on_connection("CONNECTED", "", 0.0)
        self.assertTrue(e.set_zone("AAA", 10.10, 10.00, True, 1.0))
        self.assertEqual(e.syms["AAA"].play["zones"], [[10.0, 10.1]])
        e.on_l1("AAA", "last", 10.04, 2.0)
        e.tick(3.0)
        s = e.syms["AAA"].story
        self.assertIsNotNone(s)
        self.assertTrue(any(z.get("user") for z in s["zones"]))
        self.assertTrue(s["attention"])                      # inside your zone: high attention, nothing to switch on
        self.assertTrue(e.set_zone("AAA", 10.05, 10.05, False, 4.0))
        self.assertEqual(e.syms["AAA"].play["zones"], [])


class MovingAverageTests(unittest.TestCase):
    def test_200_day_is_in_the_daily_context(self):
        rows = daily_rows([100 + 0.1 * i for i in range(220)])
        ctx = story.daily_context(rows, False, rows[-1][4])
        self.assertIsNotNone(ctx["sma200"])
        self.assertIn("above the 200-day", ctx["text"])
        kinds = [p["kind"] for p in story.ma_points(ctx)]
        self.assertEqual(kinds, ["d50", "d200"])

    def test_option_flow_at_the_200_day_is_called_and_a_reclaim_is_named(self):
        sb = story.Story()
        t = ny_t(2026, 10, 5, 10, 0)
        ctx = {"bias": "bear", "text": "Daily below the 50-day.", "sma50": 160.0, "sma200": 150.0}
        pts = story.ma_points(ctx)

        def one(tt, last, flow=()):
            fr = story.flow_read(list(flow), tt, CFG)
            return story.build(sb, tt, last, 0.01, 3.0, {"side": "long"}, None, ctx, pts, [], [], fr, None, [], [],
                               [[tt - 300, last, last, last, last, 1], [tt - 60, last, last, last, last, 1]], CFG)
        out = one(t, 149.90, prints("C", 300_000, 3, t))
        self.assertTrue(out["attention"])
        self.assertTrue(any("at the daily 200-day 150.00" in s["text"] and "Option flow confirming" in s["text"] for s in out["said"]),
                        [f[1] for f in sb.feed])
        out = one(t + 60, 150.20, prints("C", 300_000, 3, t + 60))
        self.assertIn("Daily 200-day reclaimed", out["now"])


class RefsTests(unittest.TestCase):
    def test_vwap_starts_at_930_and_both_lines_reach_the_ladder(self):
        from helpers import cfg, plays
        from twiney.engine import Engine
        e = Engine(plays(), cfg())
        e.on_connection("CONNECTED", "", 0.0)
        st = e.syms["AAA"]
        t930 = ny_t(2026, 10, 5, 9, 30)
        st.bars[t930 - 600] = [50.0, 50.0, 50.0, 50.0, 99999, 0, 0]     # premarket: not in the desk VWAP
        st.bars[t930] = [10.0, 10.3, 9.9, 10.2, 1000, 0, 0]              # typical 10.1333
        st.bars[t930 + 60] = [10.2, 10.6, 10.2, 10.5, 3000, 0, 0]        # typical 10.4333
        rows = daily_rows([9.0 + 0.02 * i for i in range(60)], start=ny_t(2026, 7, 1, 0))
        for r in rows:
            st.daily[r[0]] = r[1:5]
        e.on_l1("AAA", "last", 10.5, t930 + 90)
        refs = e._refs(st, t930 + 90)
        self.assertAlmostEqual(refs["vwap"], ((10.3 + 9.9 + 10.2) / 3 * 1000 + (10.6 + 10.2 + 10.5) / 3 * 3000) / 4000, places=3)
        self.assertEqual(refs["vwap_label"], "VWAP")
        # today's live bar (close 10.5) counts, like the daily chart's 50 SMA
        self.assertAlmostEqual(refs["sma50"], (sum(r[4] for r in rows[-49:]) + 10.5) / 50, places=3)
        marks = e._ladder_marks(st, t930 + 90, [], 10.5)
        self.assertEqual({m["role"] for m in marks} & {"vwap", "sma50"}, {"vwap", "sma50"})
