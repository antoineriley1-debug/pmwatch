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
