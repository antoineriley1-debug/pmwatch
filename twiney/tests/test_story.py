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
    # one print a minute: separate buyers (prints in the same minute are one order)
    return [{"t": now - age - 61 * k, "cp": cp, "side": side, "premium": usd / n, "otm_pct": otm, "dte": dte} for k in range(n)]


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
    def test_no_automatic_support_resistance_zones(self):
        self.assertFalse(hasattr(story, "detect_zones"))      # Twiney: support / resistance and flips are not his strategy
        z = story.user_zones({"zones": [[145.2, 144.9]]})
        self.assertEqual(len(z), 1)
        self.assertEqual((z[0]["lo"], z[0]["hi"]), (144.9, 145.2))
        self.assertTrue(z[0]["user"])


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
        self.assertIn("The dough is here: flow confirming", conf["text"])
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
        self.assertEqual(r["text"], "Puts coming in, but it's not breaking down: no follow-through")

    def test_selling_absorbed(self):
        fr = story.flow_read([], 10_000.0, CFG)
        r = story.response(self.mins([100.0] * 6), fr, {"buy_pct": 25, "ratio": 1.8}, 0.10, CFG)
        self.assertEqual(r["text"], "Sellers hitting it and it won't go down: they're getting absorbed")


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
        self.assertIn("Coming into PS60 Second Entry", out["now"])
        self.assertIn("Buyers stepping up", out["now"])
        self.assertIn("No call flow yet: no flow, no dough", out["now"])
        # at 145: the reload seller on the whole dollar, calls coming in
        flow = prints("C", 120_000, 2, t + 60)
        out = self.run_one(sb, t + 60, 144.98, reloads=[{"price": 145.0, "side": "ask", "stage": "RELOADING", "absorbed": 8000}],
                           flow=flow, pace={"state": "FAST", "buy_pct": 72, "ratio": 1.7})
        self.assertTrue(out["attention"])
        self.assertIn("major PS60 confluence around 145.00", out["now"])
        self.assertIn("Seller reloading at 145.00 ★ · buyers absorbed", out["now"])
        self.assertIn("Buyers keep lifting 145.00 and the seller keeps reloading", out["now"])
        self.assertIn("The flow is starting, not confirmed yet", out["now"])
        self.assertTrue(any("Seller reloading at 145.00 ★" in s["text"] and "supply sitting on it" in s["text"] for s in out["said"]))
        # consumed: through 145 and the prior-day high, calls building
        flow = prints("C", 500_000, 5, t + 120)
        out = self.run_one(sb, t + 120, 145.12, consumed=[{"price": 145.0, "side": "ask"}], flow=flow,
                           pace={"state": "SURGE", "buy_pct": 80, "ratio": 3.0},
                           mins=[[t - 300 + 60 * k, c, c, c, c, 1] for k, c in enumerate((144.60, 144.75, 144.90, 145.0, 145.05, 145.12))])
        self.assertIn("Seller exhausted at 145.00 · buyers breaking through", out["now"])
        self.assertIn("The dough is here: flow confirming", out["now"])
        self.assertEqual(out["tone"], "bull")
        # pull back to the level and hold it
        self.run_one(sb, t + 400, 145.05, flow=flow)
        out = self.run_one(sb, t + 500, 145.40, flow=flow)
        feed = [f[1] for f in sb.feed]
        self.assertTrue(any(x.startswith("Held the retest of") and "second entry back through the high" in x for x in feed), feed)
        self.assertTrue(any("Daily above the 50-day" in x for x in feed))

    def test_unusual_flow_is_remembered_then_aligned_with_the_second_entry(self):
        sb = story.Story()
        t = ny_t(2026, 10, 5, 10, 0)
        flow = prints("C", 150_000, 2, t)
        out = self.run_one(sb, t, 140.0, flow=flow)            # far from anything: no PS60 trigger
        self.assertTrue(any("Unusual OTM calls detected" in f[1] and "No PS60 pivot in play yet. Watching" in f[1] for f in sb.feed))
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
        self.assertTrue(any("failed break" in s["text"] for s in out["said"]), [f[1] for f in sb.feed])


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
        ctx = {"bias": "bull", "text": "Daily above the 50-day.", "sma50": 140.0, "sma200": 150.0}
        pts = story.ma_points(ctx)

        def one(tt, last, flow=()):
            fr = story.flow_read(list(flow), tt, CFG)
            return story.build(sb, tt, last, 0.01, 3.0, {"side": "long"}, None, ctx, pts, [], [], fr, None, [], [],
                               [[tt - 300, last, last, last, last, 1], [tt - 60, last, last, last, last, 1]], CFG)
        out = one(t, 149.90, prints("C", 300_000, 3, t))
        self.assertTrue(out["attention"])
        self.assertTrue(any("at the daily 200-day 150.00" in s["text"] and "flow confirming" in s["text"] for s in out["said"]),
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


class EdgeTests(unittest.TestCase):
    def test_moving_averages_join_a_pivot_but_never_make_a_place_alone(self):
        mas = story.ma_stack_points([("EMA 20", 145.02), ("SMA 50", 120.0)], [("EMA 200", 144.97), ("BB upper", 145.0)])
        self.assertEqual([m["name"] for m in mas], ["daily 20 EMA", "60m 200 EMA"])   # daily 50 SMA is its own place; no BB
        self.assertEqual(story.confluence(mas, [], 144.7, 3.0, 0.01, CFG), [])
        c = story.confluence(mas + [{"p": 145.0, "name": "PS60 pivot", "kind": "pivot"}], [], 144.7, 3.0, 0.01, CFG)
        self.assertEqual(len(c), 1)
        self.assertEqual(sorted(c[0]["mas"]), ["60m 200 EMA", "daily 20 EMA"])
        self.assertTrue(c[0]["major"])                           # pivot 3 + MAs 2 (capped) + whole dollar 1

    def test_everything_agreeing_is_high_probability_and_conflicting_flow_never_is(self):
        foc = {"name": "PS60 pivot", "p": 145.0, "lo": 145.0, "hi": 145.0, "kind": "pivot", "d": 0.05,
               "conf": {"major": True, "ps60": True, "members": ["PS60 pivot", "prior-day high", "60m 20 EMA"], "mas": ["60m 20 EMA"]}}
        ctx = {"bias": "bull", "sma200": 120.0}
        pace = {"state": "FAST", "buy_pct": 75}
        good = story.edge_read(True, ctx, foc, "SECOND_ENTRY", pace, [{"price": 144.5, "side": "bid", "stage": "RELOADING"}], [],
                               {"state": "CONFIRMED"}, {"tone": "bull", "text": "Price responding higher"}, 145.05, 0.3)
        self.assertEqual(good["label"], "HIGH PROBABILITY")
        self.assertEqual(good["score"], 7)                    # (no ROOM read given: seven checks)
        bad = story.edge_read(True, ctx, foc, "SECOND_ENTRY", pace, [{"price": 145.0, "side": "ask", "stage": "RELOADING"}], [],
                              {"state": "CONFLICTING"}, {"tone": "warn", "text": "x"}, 145.05, 0.3)
        self.assertNotEqual(bad["label"], "HIGH PROBABILITY")
        self.assertEqual({c["k"] for c in bad["checks"] if c["ok"] is False}, {"LEVEL II", "FLOW", "PRICE"})


class RoomTests(unittest.TestCase):
    def test_above_the_50_supply_to_supply_room_to_the_next_ma(self):
        ctx = {"bias": "bull"}
        foc = {"name": "PS60 pivot", "p": 145.0, "lo": 145.0, "hi": 145.0, "kind": "pivot"}
        pts = [{"p": 145.0, "name": "PS60 pivot", "kind": "pivot"}, {"p": 147.10, "name": "60m 200 EMA", "kind": "hma"},
               {"p": 148.0, "name": "prior-week high", "kind": "pwh"}, {"p": 143.0, "name": "daily 20 EMA", "kind": "dma"}]
        r = story.room_read(True, ctx, foc, pts, [], 145.05, 0.3, 3.0, CFG)
        self.assertEqual((r["frame"], r["to"], r["name"]), ("supply to supply", 147.10, "60m 200 EMA"))
        self.assertAlmostEqual(r["dollars"], 2.05)
        self.assertFalse(r["thin"])
        self.assertIn("Supply to supply: MP $2.05 of airspace to the next supply, 60m 200 EMA 147.10 (0.68 ATR)", r["text"])
        thin = story.room_read(True, ctx, foc, pts + [{"p": 145.9, "name": "daily 10 SMA", "kind": "dma"}], [], 145.05, 0.3, 3.0, CFG)
        self.assertTrue(thin["thin"])

    def test_below_the_50_demand_to_demand(self):
        r = story.room_read(False, {"bias": "bear"}, None, [{"p": 98.0, "name": "prior-day low", "kind": "pdl"}], [], 100.0, 0.2, 2.0, CFG)
        self.assertEqual((r["frame"], r["to"]), ("demand to demand", 98.0))
        self.assertIn("Demand to demand: MP $2.00 of airspace to the next demand, prior-day low 98.00", r["text"])


class DirectionTests(unittest.TestCase):
    def test_calls_on_a_pullback_to_the_50_day_in_a_bullish_daily_are_with_the_move(self):
        sb = story.Story()
        t = ny_t(2026, 10, 5, 10, 0)
        ctx = {"bias": "bull", "text": "Daily above the 50-day.", "sma50": 150.0, "sma200": 120.0}
        pts = story.ma_points(ctx)
        fr = story.flow_read(prints("C", 600_000, 4, t), t, CFG)
        out = story.build(sb, t, 150.10, 0.01, 3.0, {"side": "long"}, None, ctx, pts, [], [], fr, None, [], [],
                          [[t - 300, 150.1, 150.1, 150.1, 150.1, 1], [t - 60, 150.1, 150.1, 150.1, 150.1, 1]], CFG)
        self.assertEqual(out["flow"]["state"], "CONFIRMED")


class PlayByPlayTests(unittest.TestCase):
    """At the place: where price is, who is stepping up, the reload buyer / seller, calls / puts being bought, what it
    adds up to, said like a play-by-play."""

    def go(self, sb, t, last, **kw):
        play = {"side": "long", "trigger": 145.0, "second_entry": 144.6}
        pts = story.ps60_points(play)
        conf = story.confluence(pts, [], last, 3.0, 0.01, CFG)
        fr = story.flow_read(list(kw.get("flow", ())), t, CFG)
        return story.build(sb, t, last, 0.01, 3.0, play, None, None, pts, [], conf, fr, kw.get("pace"),
                           list(kw.get("reloads", ())), list(kw.get("consumed", ())),
                           [[t - 300, last, last, last, last, 1], [t - 60, last, last, last, last, 1]], CFG,
                           traps=kw.get("traps"), market=kw.get("market"), pulled=kw.get("pulled"))

    def test_buyers_and_calls_at_the_pivot_from_above_is_a_defend(self):
        sb, t = story.Story(), ny_t(2026, 10, 5, 10, 0)
        self.go(sb, t - 30, 145.70)                                  # was above the pivot, out of reach
        out = self.go(sb, t, 145.02, pace={"state": "FAST", "buy_pct": 70, "ratio": 1.6},
                      reloads=[{"price": 145.0, "side": "bid", "stage": "RELOADING", "absorbed": 6000}],
                      flow=[{"t": t - 30, "cp": "C", "side": "ask", "premium": 90000, "otm_pct": 2.0, "dte": 2, "strike": 147}])
        p = out["play"]
        self.assertIsNotNone(p)
        self.assertIn("pivot 145.00", p)
        self.assertIn("price 145.02", p)
        self.assertIn("Buyers stepping up, 70% of the tape lifting the offer", p)
        self.assertIn("Reload buyer at 145.00 RELOADING, 6,000 shares traded into him", p)
        self.assertIn("Calls being bought at the ask (biggest 147 call $90K): calls $90K, no puts against them in the last two minutes", p)
        self.assertTrue(any(w in p.lower() for w in story.PBP_READ["defend"]), p)
        self.assertTrue(any(x["topic"] == "pbp" for x in out["said"]))      # said out loud: the first read at the place
        self.assertTrue(any(f[3] == "pbp" for f in sb.feed))

    def test_sellers_and_puts_under_the_pivot_is_a_reject(self):
        sb, t = story.Story(), ny_t(2026, 10, 5, 10, 0)
        self.go(sb, t - 30, 144.30)
        out = self.go(sb, t, 144.97, pace={"state": "FAST", "buy_pct": 25, "ratio": 1.6},
                      flow=[{"t": t - 20, "cp": "P", "side": "ask", "premium": 60000, "otm_pct": 2.0, "dte": 1, "strike": 143}])
        p = out["play"]
        self.assertIn("Sellers stepping up, 75% of the tape hitting the bid", p)
        self.assertIn("Puts being bought at the ask (biggest 143 put $60K): puts $60K, no calls against them", p)
        self.assertTrue(any(w in p.lower() for w in story.PBP_READ["reject"]), p)

    def test_tape_against_the_options_is_mixed(self):
        sb, t = story.Story(), ny_t(2026, 10, 5, 10, 0)
        out = self.go(sb, t, 145.01, pace={"state": "FAST", "buy_pct": 72, "ratio": 1.6},
                      flow=[{"t": t - 20, "cp": "P", "side": "ask", "premium": 60000, "otm_pct": 2.0, "dte": 1, "strike": 143}])
        self.assertTrue(any(w in out["play"].lower() for w in story.PBP_READ["mixed"]), out["play"])

    def test_old_flow_does_not_count_as_now(self):
        sb, t = story.Story(), ny_t(2026, 10, 5, 10, 0)
        out = self.go(sb, t, 145.01, pace={"state": "FAST", "buy_pct": 72, "ratio": 1.6},
                      flow=[{"t": t - 600, "cp": "C", "side": "ask", "premium": 300000, "otm_pct": 2.0, "dte": 1, "strike": 150}])
        self.assertIn("No real option flow in the last two minutes", out["play"])

    def test_nothing_going_on_the_chart_stays_quiet(self):
        sb, t = story.Story(), ny_t(2026, 10, 5, 9, 45)
        for i in range(0, 300, 5):
            out = self.go(sb, t + i, 145.01)                     # at the pivot, no tape, no book, no option flow
            self.assertIsNone(out["play"])
            self.assertFalse([x for x in out["said"] if x["topic"] in ("pbp", "coach")], out["said"])
        self.assertFalse([f for f in sb.feed if f[3] == "pbp" or f[3].startswith("coach")])

    def test_far_from_any_place_says_nothing(self):
        sb, t = story.Story(), ny_t(2026, 10, 5, 10, 0)
        out = self.go(sb, t, 150.0, pace={"state": "FAST", "buy_pct": 72, "ratio": 1.6})
        self.assertIsNone(out["play"])

    def test_rate_limited_and_only_spoken_when_the_read_changes(self):
        sb, t = story.Story(), ny_t(2026, 10, 5, 10, 0)
        fast_buy = {"state": "FAST", "buy_pct": 72, "ratio": 1.6}
        spoken = 0
        for i in range(0, 120, 1):                                  # two minutes, the same read every second
            out = self.go(sb, t + i, 145.01, pace=fast_buy)
            spoken += sum(1 for x in out["said"] if x["topic"] == "pbp")
        self.assertEqual(spoken, 1)
        self.assertLessEqual(sum(1 for f in sb.feed if f[3] == "pbp"), 3)
        out = self.go(sb, t + 130, 145.01, pace={"state": "FAST", "buy_pct": 20, "ratio": 1.6})   # sellers take over
        self.assertTrue(any(x["topic"] == "pbp" for x in out["said"]))

    def test_the_wording_moves_around(self):
        sb, t = story.Story(), ny_t(2026, 10, 5, 10, 0)
        seen = {self.go(sb, t + 40 * i, 145.01, pace={"state": "FAST", "buy_pct": 72, "ratio": 1.6})["play"].split(":")[0] for i in range(4)}
        self.assertGreaterEqual(len(seen), 3)

    def test_no_banned_words(self):
        for opts in list(story.PBP_READ.values()) + list(story.PBP_OPEN.values()):
            for w in opts:
                for bad in ("fading", "stale", "gone", "trigger", "dark", "iceberg"):
                    self.assertNotIn(bad, w.lower())


class CoachTests(unittest.TestCase):
    """Stay patient, before 10 o'clock give it time, the first pivot of the day wants more context."""
    go = PlayByPlayTests.go

    def coach_said(self, out):
        return [x["text"] for x in out["said"] if x["topic"] == "coach"]

    def test_before_10_give_it_until_10_and_first_pivot_wants_context(self):
        sb, t = story.Story(), ny_t(2026, 10, 5, 9, 41)
        out = self.go(sb, t, 145.01, pace={"state": "FAST", "buy_pct": 72, "ratio": 1.6})
        said = " | ".join(self.coach_said(out))
        self.assertTrue(any(w in said for w in story.COACH["first"]), said)
        self.assertIn("10", said)
        # the first pivot is said once a day
        out = self.go(sb, t + 400, 145.01)
        self.assertNotIn("first pivot", " ".join(self.coach_said(out)).lower())

    def test_after_10_no_wait_until_10(self):
        sb, t = story.Story(), ny_t(2026, 10, 5, 10, 31)
        out = self.go(sb, t, 145.01, pace={"state": "FAST", "buy_pct": 72, "ratio": 1.6})
        self.assertFalse(any("until 10" in w or "Before 10" in w for w in self.coach_said(out)))

    def test_premarket_waits_for_the_open(self):
        sb, t = story.Story(), ny_t(2026, 10, 5, 8, 15)
        out = self.go(sb, t, 145.01, pace={"state": "FAST", "buy_pct": 72, "ratio": 1.6})
        self.assertTrue(any("open" in w for w in self.coach_said(out)), out["said"])
        self.assertFalse(any("first pivot" in w.lower() for w in self.coach_said(out)))

    def test_a_long_fight_gets_patience_not_every_second(self):
        sb, t = story.Story(), ny_t(2026, 10, 5, 11, 0)
        words = []
        for i in range(0, 600):
            # buyers on the tape, puts in the options: a real fight, nobody winning
            out = self.go(sb, t + i, 145.01, pace={"state": "FAST", "buy_pct": 70, "ratio": 1.4},
                          flow=[{"t": t + i - 20, "cp": "P", "side": "ask", "premium": 60000, "otm_pct": 2.0, "dte": 1, "strike": 143}])
            words += [w for w in self.coach_said(out) if w in story.COACH["patience"]]
        self.assertGreaterEqual(len(words), 2)
        self.assertLessEqual(len(words), 4)
        self.assertEqual(len(words), len(set(words)))              # different words each time

    def test_off_switch(self):
        sb, t = story.Story(), ny_t(2026, 10, 5, 9, 41)
        cfg = dict(CFG, coach=False)
        self.assertEqual(story.coach(sb, t, {"on": True, "kind": "pivot", "name": "x"}, {"read": "mixed"}, cfg), [])

    def test_no_banned_words(self):
        for opts in story.COACH.values():
            for w in opts:
                for bad in ("fading", "stale", "gone", "trigger", "dark", "iceberg"):
                    self.assertNotIn(bad, w.lower())


class VersusTests(unittest.TestCase):
    def test_puts_against_calls_with_the_gap(self):
        self.assertEqual(story.versus(1_200_000, 300_000, "puts", "calls"), "puts $1.2M vs calls $300K, puts out in front by $900K, 4 to 1")
        self.assertEqual(story.versus(500_000, 250_000, "calls", "puts"), "calls $500K vs puts $250K, calls out in front by $250K, 2.0 to 1")
        self.assertEqual(story.versus(100_000, 95_000, "calls", "puts"), "calls $100K vs puts $95K, about even")
        self.assertEqual(story.versus(80_000, 0, "puts", "calls"), "puts $80K, no calls against them")

    def test_flow_state_carries_the_comparison(self):
        t = ny_t(2026, 10, 5, 11, 0)
        fr = story.flow_read(prints("P", 600_000, 3, t) + prints("C", 100_000, 2, t), t, CFG)
        fs = story.flow_state(fr, False, CFG)
        self.assertIn("puts $600K vs calls $100K, puts out in front by $500K, 6 to 1", fs["text"])


class HypeTests(unittest.TestCase):
    def fr(self, t, strike, n, usd, otm, cp="C"):
        rows = [{"t": t - 10 * k, "cp": cp, "side": "ask", "premium": usd / n, "otm_pct": otm, "dte": 2, "strike": strike, "id": k} for k in range(n)]
        return story.flow_read(rows, t, CFG)

    def test_deep_otm_gets_excited(self):
        t = ny_t(2026, 10, 5, 11, 0)
        h = story.hype(self.fr(t, 300, 2, 200_000, 9.0), CFG)
        self.assertEqual(h["kind"], "deep")
        self.assertIn("300", h["text"]); self.assertIn("calls", h["text"]); self.assertIn("!", h["text"])

    def test_one_strike_pounded_non_stop(self):
        t = ny_t(2026, 10, 5, 11, 0)
        h = story.hype(self.fr(t, 300, 6, 400_000, 2.0, "P"), CFG)
        self.assertEqual(h["kind"], "pound")
        self.assertIn("300", h["text"]); self.assertIn("puts", h["text"]); self.assertIn("6 prints", h["text"])

    def test_small_or_near_the_money_once_is_not_exciting(self):
        t = ny_t(2026, 10, 5, 11, 0)
        self.assertIsNone(story.hype(self.fr(t, 300, 1, 200_000, 2.0), CFG))
        self.assertIsNone(story.hype(self.fr(t, 300, 2, 20_000, 9.0), CFG))

    def test_said_once_then_again_only_when_it_grows(self):
        sb, t = story.Story(), ny_t(2026, 10, 5, 11, 0)
        go = PlayByPlayTests.go
        n = 0
        rows = []
        for i in range(0, 120):
            rows = [{"t": t + i - 1, "cp": "C", "side": "ask", "premium": 50_000, "otm_pct": 9.0, "dte": 2, "strike": 300}] * (2 if i < 60 else 2) \
                if i % 30 == 0 else rows
            out = go(self, sb, t + i, 150.0, flow=rows)
            n += sum(1 for x in out["said"] if x["topic"] == "hype")
        self.assertEqual(n, 1)

    def test_no_banned_words(self):
        for opts in story.HYPE.values():
            for w in opts:
                for bad in ("fading", "stale", "gone", "trigger", "dark", "iceberg"):
                    self.assertNotIn(bad, w.lower())


class CloseConfirmsTests(unittest.TestCase):
    """A place is TAKEN only when a candle CLOSES through it. Trading through it, fast or not, is pressing."""

    def go(self, sb, t, last, closes, **kw):
        play = {"side": "long", "trigger": 145.0}
        pts = story.ps60_points(play)
        conf = story.confluence(pts, [], last, 3.0, 0.01, CFG)
        fr = story.flow_read([], t, CFG)
        m0 = int(t // 60) * 60
        mins = [[m0 - 60 * (len(closes) - i), c, c, c, c, 1] for i, c in enumerate(closes)] + [[m0, last, last, last, last, 1]]
        return story.build(sb, t, last, 0.01, 3.0, play, None, None, pts, [], conf, fr, kw.get("pace"), [], [], mins, CFG)

    def test_through_without_a_close_is_not_a_break(self):
        sb, t = story.Story(), ny_t(2026, 10, 5, 11, 0)
        self.go(sb, t - 60, 145.40, [145.40, 145.40])
        out = self.go(sb, t, 144.70, [145.40, 145.40, 145.30], pace={"state": "FAST", "buy_pct": 20, "ratio": 2.5})
        self.assertNotIn("PS60 pivot", sb.breaks)
        self.assertIn("no close under it yet", out["now"])
        self.assertIn("Not taken until a candle closes under it", out["now"])
        self.assertIn("no close under it yet", out["play"])

    def test_the_close_under_takes_it(self):
        sb, t = story.Story(), ny_t(2026, 10, 5, 11, 0)
        self.go(sb, t - 60, 145.40, [145.40, 145.40])
        out = self.go(sb, t, 144.70, [145.40, 145.40, 144.75])
        self.assertEqual(sb.breaks["PS60 pivot"]["dir"], "down")
        self.assertIn("a candle closed under it at 144.75", out["now"])

    def test_the_close_over_takes_it_upside_too(self):
        sb, t = story.Story(), ny_t(2026, 10, 5, 11, 0)
        self.go(sb, t - 60, 144.20, [144.20, 144.20])
        self.go(sb, t, 145.30, [144.20, 144.20, 144.90])
        self.assertNotIn("PS60 pivot", sb.breaks)                          # over it, no close over it
        self.go(sb, t + 60, 145.30, [144.20, 144.90, 145.25])
        self.assertEqual(sb.breaks["PS60 pivot"]["dir"], "up")


class CoachReadsTests(unittest.TestCase):
    go = PlayByPlayTests.go

    def said(self, out, kind=None):
        return [x["text"] for x in out["said"] if x["topic"] == "coach"]

    def test_reload_buyer_be_careful_until_cleaned_up(self):
        sb, t = story.Story(), ny_t(2026, 10, 5, 11, 0)
        rl = [{"price": 145.0, "side": "bid", "stage": "RELOADING", "absorbed": 9000}]
        out = self.go(sb, t, 145.01, pace={"state": "FAST", "buy_pct": 30, "ratio": 1.6}, reloads=rl)
        w = " ".join(self.said(out))
        self.assertIn("reload buyer", w.lower()); self.assertIn("145.00", w); self.assertIn("cleaned up", w.lower())
        again = []
        for i in range(1, 200, 5):
            again += self.said(self.go(sb, t + i, 145.01, pace={"state": "FAST", "buy_pct": 30, "ratio": 1.6}, reloads=rl))
        self.assertTrue(any("STILL THERE" in x for x in again), again)
        out = self.go(sb, t + 205, 144.90, pace={"state": "FAST", "buy_pct": 25, "ratio": 1.6},
                      consumed=[{"price": 145.0, "side": "bid", "absorbed": 15000}])
        self.assertTrue(any("CLEANED UP" in x and "145.00" in x for x in self.said(out)), out["said"])

    def test_reload_seller_the_reverse(self):
        sb, t = story.Story(), ny_t(2026, 10, 5, 11, 0)
        out = self.go(sb, t, 144.99, pace={"state": "FAST", "buy_pct": 75, "ratio": 1.6},
                      reloads=[{"price": 145.0, "side": "ask", "stage": "RELOADING", "absorbed": 9000}])
        w = " ".join(self.said(out))
        self.assertIn("reload seller", w.lower()); self.assertIn("145.00", w)

    def test_chop_and_clean(self):
        t = ny_t(2026, 10, 5, 11, 0)
        chop = [[t - 60 * (8 - i), 145.0, 145.10, 144.90, 145.05 if i % 2 else 144.95, 1] for i in range(8)]
        self.assertEqual(story.price_action(chop, 145.0)["kind"], "chop")
        up = [[t - 60 * (8 - i), 144.0 + 0.1 * i, 144.1 + 0.1 * i, 143.98 + 0.1 * i, 144.08 + 0.1 * i, 1] for i in range(8)]
        self.assertEqual(story.price_action(up, 145.0)["kind"], "clean_up")
        dn = [[t - 60 * (8 - i), 146.0 - 0.1 * i, 146.02 - 0.1 * i, 145.9 - 0.1 * i, 145.92 - 0.1 * i, 1] for i in range(8)]
        self.assertEqual(story.price_action(dn, 145.0)["kind"], "clean_down")

    def test_trapped_longs_named_with_their_exit(self):
        sb, t = story.Story(), ny_t(2026, 10, 5, 11, 0)
        foc = {"on": True, "kind": "pivot", "name": "PS60 pivot", "p": 145.0, "lo": 145.0, "hi": 145.0}
        traps = [{"name": "PS60 pivot", "level": 145.0, "up": True, "state": "TRAPPED", "shares": 42000, "avg": 145.12, "under": 0.30}]
        out = story.coach(sb, t, foc, {"read": "press_sup"}, CFG, traps=traps)
        txt = " ".join(x[1] for x in out if x[0] == "trapped")
        self.assertIn("ongs", txt); self.assertIn("42,000", txt); self.assertIn("145.12", txt)
        self.assertFalse([x for x in story.coach(sb, t + 5, foc, {"read": "press_sup"}, CFG, traps=traps) if x[0] == "trapped"])   # once
        traps[0]["state"] = "RECLAIMED"
        self.assertTrue([x for x in story.coach(sb, t + 10, foc, {"read": "defend"}, CFG, traps=traps) if x[0] == "freed"])

    def test_the_market_against_the_trade(self):
        sb, t = story.Story(), ny_t(2026, 10, 5, 11, 0)
        foc = {"on": True, "kind": "pivot", "name": "PS60 pivot", "p": 145.0, "lo": 145.0, "hi": 145.0}
        out = story.coach(sb, t, foc, {"read": "press_res"}, CFG, market={"dir": "down", "text": "SPY down 0.8%, under VWAP."}, up=True)
        self.assertTrue(any(k == "mkt_against" and "SPY down 0.8%" in w for k, w in out), out)

    def test_no_banned_words(self):
        for opts in story.COACH.values():
            for w in opts:
                for bad in ("fading", "stale", "gone", "trigger", "dark", "iceberg"):
                    self.assertNotIn(bad, w.lower())


class FrameworkTests(unittest.TestCase):
    """Who controls the 5, the 10 is the birth of the trade, rising 60-minute support (the 60m 5 / 10)."""

    def packs(self, d5, d10, h5, h10, h5p, h10p):
        return ([("SMA 5", d5), ("SMA 10", d10)], [("SMA 5", d5), ("SMA 10", d10)],
                [("SMA 5", h5), ("SMA 10", h10)], [("SMA 5", h5p), ("SMA 10", h10p)])

    def test_uptrend_read(self):
        dp, dpp, hp, hpp = self.packs(100.0, 99.0, 101.0, 100.5, 100.8, 100.3)
        fw = story.ma_framework(dp, dpp, hp, hpp, 101.5, CFG)
        self.assertEqual((fw["five"], fw["ten"], fw["h60"]), ("buyers", "over", "rising"))
        self.assertIn("Buyers control the 5-day", fw["text"])
        self.assertIn("the long trade is born", fw["text"])
        self.assertIn("wait for the 60-minute retrace into it to buy", fw["text"])

    def test_downtrend_read(self):
        dp, dpp, hp, hpp = self.packs(100.0, 101.0, 99.0, 99.5, 99.2, 99.8)
        fw = story.ma_framework(dp, dpp, hp, hpp, 98.5, CFG)
        self.assertEqual((fw["five"], fw["ten"], fw["h60"]), ("sellers", "under", "falling"))

    def test_retrace_into_rising_60m_support_is_called(self):
        sb, t = story.Story(), ny_t(2026, 10, 5, 11, 0)
        dp, dpp, hp, hpp = self.packs(140.0, 139.0, 144.95, 144.80, 144.7, 144.6)
        play = {"side": "long", "trigger": 150.0}
        pts = story.ps60_points(play)
        said = []
        for i, last in enumerate((145.60, 145.30, 144.92)):
            fw = story.ma_framework(dp, dpp, hp, hpp, last, CFG)
            out = story.build(sb, t + 30 * i, last, 0.01, 3.0, play, None, None, pts, [], [], story.flow_read([], t, CFG), None, [], [],
                              [[t - 120, last, last, last, last, 1]], CFG, fw=fw)
            said += [x["text"] for x in out["said"]]
        self.assertTrue(any("60-minute retrace into rising support" in w for w in said), said)

    def test_the_5_changing_hands_is_said(self):
        sb, t = story.Story(), ny_t(2026, 10, 5, 11, 0)
        play = {"side": "long", "trigger": 150.0}
        pts = story.ps60_points(play)
        said = []
        for i, last in enumerate((101.0, 99.0)):
            dp, dpp, hp, hpp = self.packs(100.0, 98.0, 100.0, 100.0, 100.0, 100.0)
            fw = story.ma_framework(dp, dpp, hp, hpp, last, CFG)
            out = story.build(sb, t + 30 * i, last, 0.01, 3.0, play, None, None, pts, [], [], story.flow_read([], t, CFG), None, [], [],
                              [[t - 120, last, last, last, last, 1]], CFG, fw=fw)
            said += [x["text"] for x in out["said"]]
        self.assertTrue(any("Sellers just took the 5-day" in w for w in said), said)

    def test_key_mas_include_the_daily_89_ema(self):
        dpack = [("SMA 5", 1.0), ("EMA 89", 2.0), ("EMA 34", 3.0)]
        hpack = [("EMA 20", 4.0), ("EMA 89", 5.0), ("SMA 150", 6.0)]
        names = [m["name"] for m in story.key_mas(dpack, hpack, CFG)]
        self.assertIn("daily 89 EMA", names); self.assertIn("daily 34 EMA", names); self.assertIn("5-day", names)
        self.assertIn("60m 20 EMA", names); self.assertIn("60m 150 SMA", names)
        self.assertNotIn("60m 89 EMA", names)                                  # the 34 / 65 / 89 EMA: daily only
        pts = story.ma_stack_points([("EMA 89", 2.0)], [("EMA 89", 5.0), ("EMA 20", 4.0)])
        self.assertEqual([p["name"] for p in pts], ["daily 89 EMA", "60m 20 EMA"])

    def test_mas_on_top_of_each_other_are_one(self):
        m = story.merge_mas([{"p": 100.00, "name": "5-day"}, {"p": 100.02, "name": "60m 20 SMA"}, {"p": 101.0, "name": "10-day"}], 0.05)
        self.assertEqual([x["name"] for x in m], ["5-day / 60m 20 SMA", "10-day"])


class MaWatchTests(unittest.TestCase):
    def run_path(self, prices, ma=100.0, closes=None):
        sb, t = story.Story(), ny_t(2026, 10, 5, 11, 0)
        mas = [{"p": ma, "name": "daily 89 EMA"}]
        pts = [{"p": 103.0, "name": "prior-day high", "kind": "pdh"}, {"p": 97.0, "name": "prior-day low", "kind": "pdl"}]
        out = []
        for i, px_ in enumerate(prices):
            cl = closes[i] if closes else None
            out += story.ma_watch(sb, t + 10 * i, px_, 0.30, mas, cl, (t + 10 * i) if cl is not None else None, pts, CFG)
        return out

    def test_bounce_off_demand(self):
        out = self.run_path([100.80, 100.40, 100.25, 100.10, 100.05, 100.30, 100.60])
        kinds = [k for k, _m, _w in out]
        self.assertIn("into", kinds); self.assertIn("bounce", kinds)
        w = next(w for k, _m, w in out if k == "bounce")
        self.assertIn("daily 89 EMA 100.00", w); self.assertIn("Next supply: prior-day high 103.00", w)

    def test_reject_at_supply(self):
        out = self.run_path([99.20, 99.60, 99.75, 99.90, 99.95, 99.70, 99.40])
        self.assertIn("reject", [k for k, _m, _w in out])

    def test_close_through_needs_a_close(self):
        prices = [100.80, 100.40, 100.10, 99.80, 99.70]
        out = self.run_path(prices, closes=[None, None, 100.10, 100.05, 100.02])        # wicks under, closes over
        self.assertNotIn("through_dn", [k for k, _m, _w in out])
        out = self.run_path(prices, closes=[None, None, 100.10, 99.85, 99.75])
        self.assertIn("through_dn", [k for k, _m, _w in out])


class TradeReadTests(unittest.TestCase):
    def trade(self, **kw):
        d = {"dir": "long", "what": "long 100 AAPL from 145.00", "pnl": 0.0, "entry": 145.0, "stop": 144.60, "target": 146.0,
             "qty": 100, "key": ("long", 100, ())}
        d.update(kw)
        return d

    def test_entering_says_the_stop_and_first_level(self):
        sb, t = story.Story(), ny_t(2026, 10, 5, 11, 0)
        foc = {"on": False, "approach": True, "kind": "pdh", "name": "prior-day high", "p": 145.40, "lo": 145.40, "hi": 145.40}
        out = story.trade_read(sb, t, self.trade(), foc, 145.0, 0.3, None, {"to": 145.4, "name": "prior-day high", "dollars": 0.4}, CFG)
        w = dict(out)
        self.assertIn("You're in: long 100 AAPL from 145.00", w["enter"])
        self.assertIn("Stop 144.60, 40 cents away", w["enter"])
        self.assertIn("needs a close over it", w["level"])

    def test_five_to_seven_minute_rule(self):
        sb, t = story.Story(), ny_t(2026, 10, 5, 11, 0)
        story.trade_read(sb, t, self.trade(), None, 145.0, 0.3, None, None, CFG)
        out = story.trade_read(sb, t + 330, self.trade(), None, 145.02, 0.3, None, None, CFG)
        self.assertTrue(any(k == "r57" and "reload seller" in w for k, w in out), out)
        self.assertFalse([1 for k, _w in story.trade_read(sb, t + 360, self.trade(), None, 145.02, 0.3, None, None, CFG) if k == "r57"])

    def test_first_move_pay_yourself(self):
        sb, t = story.Story(), ny_t(2026, 10, 5, 11, 0)
        story.trade_read(sb, t, self.trade(), None, 145.0, 0.3, None, None, CFG)
        out = story.trade_read(sb, t + 60, self.trade(pnl=45.0), None, 145.45, 0.3, None, None, CFG)
        self.assertTrue(any(k == "pay" and "breakeven" in w for k, w in out), out)

    def test_close_to_the_stop(self):
        sb, t = story.Story(), ny_t(2026, 10, 5, 11, 0)
        story.trade_read(sb, t, self.trade(), None, 145.0, 0.3, None, None, CFG)
        out = story.trade_read(sb, t + 60, self.trade(pnl=-30.0), None, 144.70, 0.3, None, None, CFG)
        self.assertTrue(any(k == "stop" for k, _w in out), out)

    def test_options_short_side(self):
        sb, t = story.Story(), ny_t(2026, 10, 5, 11, 0)
        tr = self.trade(dir="short", what="2 AAPL 10/09 140P at 1.20", entry=None, stop=None, target=None, key=("short", 0, (("k", 2),)))
        foc = {"on": False, "approach": True, "kind": "pdl", "name": "prior-day low", "p": 144.6, "lo": 144.6, "hi": 144.6}
        w = dict(story.trade_read(sb, t, tr, foc, 145.0, 0.3, None, None, CFG))
        self.assertIn("2 AAPL 10/09 140P", w["enter"]); self.assertIn("needs a close under it", w["level"])


class H60ConfirmTests(unittest.TestCase):
    def test_building_over_the_prior_60_minute_high(self):
        sb, t = story.Story(), ny_t(2026, 10, 5, 11, 20)
        h = int(t // 3600) * 3600
        h60 = [[h - 3600, 100, 101, 99.5, 100.8, 1], [h, 100.8, 100.9, 100.6, 100.7, 1]]
        self.assertIsNone(story.h60_confirm(sb, t, h60, 100.9))
        side, w = story.h60_confirm(sb, t + 60, h60, 101.05)
        self.assertEqual(side, "up"); self.assertIn("prior 60-minute high 101.00", w)
        self.assertIsNone(story.h60_confirm(sb, t + 120, h60, 101.10))           # once per candle
        side, w = story.h60_confirm(sb, t + 180, h60, 99.40)
        self.assertEqual(side, "down")


class TradeMpTests(unittest.TestCase):
    trade = TradeReadTests.trade

    def test_mp_clusters_measure_to_the_far_edge(self):
        pts = [{"p": 146.00, "name": "60m 20 SMA", "kind": "hma"}, {"p": 146.10, "name": "5-day", "kind": "dma"},
               {"p": 148.00, "name": "daily 89 EMA", "kind": "dma"}]
        r = story.room_read(True, {"bias": "bull"}, None, pts, [], 145.0, 0.3, 3.0, CFG)
        self.assertEqual(r["to"], 146.10); self.assertEqual(r["name"], "60m 20 SMA / 5-day")
        self.assertIn("one supply, far edge", r["text"])
        self.assertTrue(r["thin"]); self.assertIn("next MP beyond it: $3.00 to daily 89 EMA", r["text"])
        self.assertEqual([m["name"] for m in r["map"]], ["60m 20 SMA / 5-day", "daily 89 EMA"])
        self.assertAlmostEqual(r["map"][1]["room"], 1.90)

    def test_mp_left_while_it_works(self):
        sb, t = story.Story(), ny_t(2026, 10, 5, 11, 0)
        rm = {"to": 147.0, "name": "daily 89 EMA", "dollars": 2.0, "atr_x": 0.67, "thin": False}
        story.trade_read(sb, t, self.trade(), None, 145.0, 0.3, None, rm, CFG)
        out = story.trade_read(sb, t + 100, self.trade(pnl=20.0), None, 145.20, 0.3, None, dict(rm, dollars=1.80), CFG)
        w = [w for k, w in out if k == "mp"]
        self.assertTrue(w and "$1.80 of MP left to daily 89 EMA 147.00" in w[0], out)

    def test_weak_tape_market_and_puts_say_take_some_profit(self):
        sb, t = story.Story(), ny_t(2026, 10, 5, 11, 0)
        story.trade_read(sb, t, self.trade(), None, 145.0, 0.3, None, None, CFG)
        fr = {"C": {"now_usd": 10_000}, "P": {"now_usd": 400_000}}
        pace = {"state": "FAST", "buy_pct": 20, "ratio": 2.0}
        mkt = {"dir": "down", "text": "SPY down 0.6%, under VWAP; QQQ down 0.9%, under VWAP."}
        rm = {"to": 147.0, "name": "daily 89 EMA", "dollars": 1.6, "thin": False}
        story.trade_read(sb, t + 10, self.trade(pnl=40.0), None, 145.40, 0.3, None, rm, CFG, pace, mkt, fr)
        out = story.trade_read(sb, t + 80, self.trade(pnl=40.0), None, 145.40, 0.3, None, rm, CFG, pace, mkt, fr)
        self.assertFalse([1 for k, _w in out if k == "weak"])                 # a minute is not a breakdown
        out = story.trade_read(sb, t + 200, self.trade(pnl=40.0), None, 145.40, 0.3, None, rm, CFG, pace, mkt, fr)
        w = [w for k, w in out if k == "weak"]
        self.assertTrue(w, out)
        self.assertIn("SPY down 0.6%", w[0]); self.assertIn("puts $400K vs calls $10K", w[0]); self.assertIn("not a pullback", w[0])
        self.assertIn("paying yourself", w[0])
        for bad in ("fading", "stale", "gone"):
            self.assertNotIn(bad, w[0].lower())

    def test_a_pullback_never_gets_you_worked_out(self):
        """Sellers on the tape and the market soft, but no tremendous flow against you: a pullback. Not a word."""
        sb, t = story.Story(), ny_t(2026, 10, 5, 11, 0)
        story.trade_read(sb, t, self.trade(), None, 145.0, 0.3, None, None, CFG)
        fr = {"C": {"now_usd": 30_000}, "P": {"now_usd": 90_000}}
        mkt = {"dir": "down", "text": "SPY down 0.3%."}
        for i in range(30):
            out = story.trade_read(sb, t + 20 * i, self.trade(pnl=40.0), None, 145.30, 0.3, None, None, CFG,
                                   {"state": "FAST", "buy_pct": 35, "ratio": 1.5}, mkt, fr)
            self.assertFalse([1 for k, _w in out if k == "weak"])
        # tremendous flow but the tape still two-way: still a pullback
        fr = {"C": {"now_usd": 10_000}, "P": {"now_usd": 500_000}}
        for i in range(30):
            out = story.trade_read(sb, t + 600 + 20 * i, self.trade(pnl=40.0), None, 145.30, 0.3, None, None, CFG,
                                   {"state": "FAST", "buy_pct": 45, "ratio": 1.5}, mkt, fr)
            self.assertFalse([1 for k, _w in out if k == "weak"])

    def test_short_side_the_reverse(self):
        sb, t = story.Story(), ny_t(2026, 10, 5, 11, 0)
        tr = self.trade(dir="short", what="short 100 AAPL from 145.00", stop=145.40, target=144.0, key=("short", -100, ()))
        story.trade_read(sb, t, tr, None, 145.0, 0.3, None, None, CFG)
        fr = {"C": {"now_usd": 450_000}, "P": {"now_usd": 5_000}}
        pace = {"state": "SURGE", "buy_pct": 80, "ratio": 2.2}
        mkt = {"dir": "up", "text": "SPY up 0.7%, over VWAP."}
        story.trade_read(sb, t + 10, dict(tr, pnl=40.0), None, 144.60, 0.3, None, None, CFG, pace, mkt, fr)
        out = story.trade_read(sb, t + 200, dict(tr, pnl=40.0), None, 144.60, 0.3, None, None, CFG, pace, mkt, fr)
        w = [w for k, w in out if k == "weak"]
        self.assertTrue(w, out)
        self.assertIn("buyers own the tape, 80%", w[0]); self.assertIn("calls $450K vs puts $5K", w[0])


class StructureTests(unittest.TestCase):
    def test_lower_lows_on_the_60(self):
        sb, t = story.Story(), ny_t(2026, 10, 5, 12, 5)
        h = int(t // 3600) * 3600
        h60 = [[h - 7200, 101, 102, 100, 101, 1], [h - 3600, 101, 101.5, 99.5, 100, 1], [h, 100, 100.2, 99.8, 100, 1]]
        out = story.structure_read(sb, t, h60, None, False, 100.0, {"h10": 99.0}, CFG)
        self.assertEqual(out[0][0], "ll60")
        self.assertIn("Lower low on the 60-minute, 99.50 under 100.00", out[0][1]); self.assertIn("demand to demand", out[0][1])
        self.assertIn("Next demand: 99.00, the 60m 10", out[0][1])
        self.assertEqual(story.structure_read(sb, t + 60, h60, None, False, 100.0, None, CFG), [])      # once per candle

    def test_higher_high_on_the_daily(self):
        sb, t = story.Story(), ny_t(2026, 10, 5, 12, 5)
        rows = daily_rows([100, 101, 102, 101, 102, 103])
        rows[-1] = [t - 3600 * 3, 103, 105.5, 102.5, 105, 1e6]                 # today, live, over the five-day high
        out = story.structure_read(sb, t, None, rows, True, 105.0, None, CFG)
        self.assertEqual(out[0][0], "hhD"); self.assertIn("Higher high on the Daily", out[0][1]); self.assertIn("supply to supply", out[0][1])

    def test_no_banned_words_in_structure(self):
        sb, t = story.Story(), ny_t(2026, 10, 5, 12, 5)
        h = int(t // 3600) * 3600
        for h60 in ([[h - 7200, 101, 102, 100, 101, 1], [h - 3600, 101, 101.5, 99.5, 100, 1], [h, 100, 100.2, 99.8, 100, 1]],
                    [[h - 7200, 101, 102, 100, 101, 1], [h - 3600, 101, 103, 100.5, 102, 1], [h, 102, 102.2, 101.8, 102, 1]]):
            for _k, w in story.structure_read(story.Story(), t, h60, None, False, 100.0, None, CFG):
                for bad in ("fading", "stale", "gone", "trigger", "dark", "iceberg", "support", "resistance"):
                    self.assertNotIn(bad, w.lower(), w)


class DailyBriefTests(unittest.TestCase):
    def test_the_brain_of_the_trade(self):
        ctx = {"bias": "bull", "text": "Daily above the 50-day (138.20): bullish PS60, supply to supply. Objective: take the prior-day high 145.03."}
        fw = {"bits": ["Buyers control the 5-day (143.10): short-term sentiment bullish", "Over the 10-day (142.00): the long trade is born",
                       "Rising 60-minute support at the 60m 5 / 10 (144.00 / 143.80): wait for the 60-minute retrace into it to buy"]}
        up = {"to": 147.0, "name": "daily 89 EMA", "dollars": 2.0, "atr_x": 0.67, "thin": False}
        dn = {"to": 143.1, "name": "5-day", "dollars": 1.9}
        w = story.daily_brief(ctx, fw, up, dn, None, True, 3.0, CFG)
        self.assertIn("bullish PS60, supply to supply", w)
        self.assertIn("Buyers control the 5-day", w); self.assertIn("the long trade is born", w)
        self.assertNotIn("60-minute", w)                                           # the Daily brief is the Daily
        self.assertIn("MP $2.00 to the next supply, daily 89 EMA 147.00, 0.67 ATR: room to work", w)
        self.assertIn("Demand under us: 5-day 143.10, $1.90 away", w); self.assertIn("Daily ATR $3.00", w)

    def test_open_air(self):
        ctx = {"bias": "bear", "text": "Daily below the 50-day (150.00): bearish PS60, demand to demand."}
        w = story.daily_brief(ctx, None, None, {"to": None}, None, True, None, CFG)
        self.assertIn("Airspace below is clear: open air, no demand in the way", w)


class SecondEntryWatchTests(unittest.TestCase):
    def test_walked_into_the_second_entry_then_live(self):
        sb, t = story.Story(), ny_t(2026, 10, 5, 11, 0)
        play = {"side": "long", "trigger": 145.0, "second_entry": 146.0}
        out = story.second_entry_watch(sb, t, play, 144.80, 0.3, None, None, CFG)
        self.assertEqual(out[0][0], "set"); self.assertIn("Second entry marked at 146.00, 120 cents away", out[0][1])
        said = []
        for i, px_ in enumerate((145.00, 145.30, 145.52, 145.76, 145.92, 146.05, 146.20)):
            said += story.second_entry_watch(sb, t + 10 * (i + 1), play, px_, 0.3, {"tail": "Buyers stepping up, 70% of the tape lifting the offer"}, None, CFG)
        kinds = [k for k, _w in said]
        self.assertEqual(kinds, ["near", "near", "near", "near", "through"])
        self.assertIn("a dollar away", said[0][1]); self.assertIn("50 cents away", said[1][1]); self.assertIn("a quarter away", said[2][1])
        self.assertIn("a dime away", said[3][1]); self.assertIn("Get ready", said[3][1])
        self.assertIn("Through the second entry 146.00", said[4][1]); self.assertIn("it should go now", said[4][1])
        self.assertIn("Buyers stepping up", said[4][1])
        # the build, a minute on
        out = story.second_entry_watch(sb, t + 200, play, 146.40, 0.3, None, "SECOND_ENTRY", CFG)
        self.assertEqual(out[0][0], "build")

    def test_short_side_and_removing_it(self):
        sb, t = story.Story(), ny_t(2026, 10, 5, 11, 0)
        play = {"side": "short", "trigger": 145.0, "second_entry": 144.0}
        story.second_entry_watch(sb, t, play, 145.2, 0.3, None, None, CFG)
        out = story.second_entry_watch(sb, t + 10, play, 144.48, 0.3, None, None, CFG)
        self.assertIn("50 cents away", out[0][1])
        self.assertEqual(story.second_entry_watch(sb, t + 20, {"side": "short", "trigger": 145.0}, 144.3, 0.3, None, None, CFG), [])

    def test_no_banned_words(self):
        sb, t = story.Story(), ny_t(2026, 10, 5, 11, 0)
        play = {"side": "long", "trigger": 145.0, "second_entry": 146.0}
        ws = [w for _k, w in story.second_entry_watch(sb, t, play, 144.8, 0.3, None, None, CFG)]
        ws += [w for i, px_ in enumerate((145.0, 145.3, 145.52, 145.76, 145.92, 146.05)) for _k, w in story.second_entry_watch(sb, t + 10 * (i + 1), play, px_, 0.3, None, None, CFG)]
        for w in ws:
            for bad in ("fading", "stale", "gone", "trigger", "dark", "iceberg"):
                self.assertNotIn(bad, w.lower(), w)


class SessionPointsTests(unittest.TestCase):
    def test_premarket_and_after_hours_are_places(self):
        pts = story.session_points({"pmh": 101.2, "pml": 99.4, "ahh": 100.9, "ahl": 100.1, "open": 100.5, "pmc": 100.7})
        self.assertEqual([(p["name"], p["kind"]) for p in pts],
                         [("premarket high", "pmh"), ("premarket low", "pml"), ("after-hours high", "ahh"), ("after-hours low", "ahl"), ("today's open", "open")])
        self.assertEqual(story.session_points({}), [])
        self.assertEqual(story.session_points({"pmh": None, "ahl": 0}), [])


class OpenReadTests(unittest.TestCase):
    """A strong day, then selling in the extended hours: they run it low to take it high at the open (and the reverse)."""

    def rows(self, o, h, l, c):
        return daily_rows([100] * 30) + [[ny_t(2026, 10, 2, 0), o, h, l, c, 1e6]]

    def test_strong_day_sold_in_the_premarket_is_the_shakeout(self):
        r = story.prior_day_context(self.rows(100.0, 103.2, 99.8, 103.0), False, {"pmc": 102.3, "pml": 102.1, "pmh": 103.1}, 102.3, 2.0, ny_t(2026, 10, 5, 9, 10))
        self.assertEqual(r["read"], "shake_low")
        self.assertIn("run it low to take it high at the open", r["text"]); self.assertIn("Premarket low 102.10", r["text"])
        self.assertIn("reclaim 103.00", r["text"]); self.assertAlmostEqual(r["watch"], 102.1)

    def test_weak_day_bought_in_the_premarket_is_the_reverse(self):
        r = story.prior_day_context(self.rows(103.0, 103.2, 99.8, 100.0), False, {"pmc": 100.8, "pml": 99.9, "pmh": 101.0}, 100.8, 2.0, ny_t(2026, 10, 5, 9, 10))
        self.assertEqual(r["read"], "shake_high"); self.assertIn("run it up to take it down", r["text"])

    def test_an_ordinary_day_says_nothing(self):
        self.assertIsNone(story.prior_day_context(self.rows(100.0, 101.0, 99.0, 100.2), False, {"pmc": 99.9}, 99.9, 2.0, ny_t(2026, 10, 5, 9, 10)))
        # a strong day with a flat premarket: nothing to read either
        self.assertIsNone(story.prior_day_context(self.rows(100.0, 103.2, 99.8, 103.0), False, {"pmc": 102.9}, 102.9, 2.0, ny_t(2026, 10, 5, 9, 10)))

    def test_said_once_before_the_open_and_in_the_daily_brief(self):
        sb, t = story.Story(), ny_t(2026, 10, 5, 9, 12)
        play = {"side": "long", "trigger": 150.0}
        pts = story.ps60_points(play)
        drows = self.rows(100.0, 103.2, 99.8, 103.0)
        ctx = {"bias": "bull", "text": "Daily above the 50-day (100.00): bullish PS60, supply to supply."}
        sess = {"pmc": 102.3, "pml": 102.1, "pmh": 103.1}
        out = story.build(sb, t, 102.3, 0.01, 2.0, play, None, ctx, pts, [], [], story.flow_read([], t, CFG), None, [], [],
                          [[t - 120, 102.3, 102.3, 102.3, 102.3, 1]], CFG, drows=drows, live=False, sess=sess)
        said = [x["text"] for x in out["said"]]
        self.assertTrue(any("shakeout" in w for w in said), said)
        self.assertIn("shakeout", out["daily"])
        out = story.build(sb, t + 60, 102.3, 0.01, 2.0, play, None, ctx, pts, [], [], story.flow_read([], t, CFG), None, [], [],
                          [[t - 60, 102.3, 102.3, 102.3, 102.3, 1]], CFG, drows=drows, live=False, sess=sess)
        self.assertFalse(any("shakeout" in x["text"] for x in out["said"] if x["topic"].startswith("openread")))
