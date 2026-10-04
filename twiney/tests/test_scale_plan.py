import unittest
from helpers import cfg, plays
from twiney.engine import Engine
from twiney.book import INSERT, UPDATE, BID, ASK
from twiney.trading import SimBroker, Trader, TradingGate


def make():
    c = cfg(trading={"auto_second_entry": False})
    e = Engine(plays(), c); e.on_connection("DEMO", "", 0.0)
    gate = TradingGate(c); gate.set_sim(); gate.arm(True)
    broker = SimBroker(e); e.sim_broker = broker
    tr = Trader(e, c, broker, gate); e.trader = tr
    e.apply_slot("AAA", True, 0.0)
    quote(e, 9.99, 10.00, 1.0)
    return e, tr, broker


def quote(e, bid, ask, t):
    for i in range(3):
        e.on_depth("AAA", i, INSERT if t == 1.0 else UPDATE, BID, round(bid - i * 0.01, 2), 500, "", t)
        e.on_depth("AAA", i, INSERT if t == 1.0 else UPDATE, ASK, round(ask + i * 0.01, 2), 500, "", t)
    e.on_l1("AAA", "bid", bid, t); e.on_l1("AAA", "ask", ask, t); e.on_l1("AAA", "last", ask, t)
    e.on_print("AAA", ask, 100, "X", t)


class ScalePlanTests(unittest.TestCase):
    """Dan's scaling on the position: a dollar, take a quarter; two, take a third; the rest rides. ADD rungs build
    on strength. Rungs fire at the touch when price has moved their dollars from the average entry."""
    def test_mp_plan_scales_out_as_price_moves(self):
        e, tr, broker = make()
        self.assertTrue(tr.submit("AAA", "BUY", 10.0, 100, 2.0, bracket=False)["ok"])
        quote(e, 9.99, 10.00, 3.0)                              # the sim fills the marketable buy
        self.assertEqual(broker.position("AAA"), 100)
        out = tr.set_scale_plan("AAA", kind="MP", now=4.0)
        self.assertTrue(out["ok"]); plan = out["plan"]
        self.assertEqual((plan["kind"], plan["basis"], plan["side"], plan["entry"]), ("MP", 100, "long", 10.0))
        self.assertEqual([(r["move"], r["action"], r["pct"]) for r in plan["rungs"]], [(1.0, "TAKE", 25.0), (2.0, "TAKE", 33.0), (4.0, "TAKE", 50.0)])
        tr.watchdog(5.0); self.assertFalse(any(r["done"] for r in tr.scale_plans["AAA"]["rungs"]))   # nothing moved yet
        quote(e, 10.99, 11.00, 6.0); tr.watchdog(6.5); quote(e, 10.99, 11.00, 7.0)                  # +$1: a quarter comes off at the bid
        self.assertTrue(tr.scale_plans["AAA"]["rungs"][0]["done"]); self.assertEqual(broker.position("AAA"), 75)
        v = tr.snapshot(run_watchdog=False)["scale_plans"]["AAA"]; self.assertEqual((v["left"], v["left_pct"], v["next"]), (75, 75, 1))
        quote(e, 11.99, 12.00, 8.0); tr.watchdog(8.5); quote(e, 11.99, 12.00, 9.0)                  # +$2: a third of what is LEFT
        self.assertEqual(broker.position("AAA"), 50)
        self.assertEqual(tr.scale_plans["AAA"]["rungs"][1]["shares"], 25)
        fire = tr.fire_scale_rung("AAA", 2, 10.0); self.assertTrue(fire["ok"]); quote(e, 11.99, 12.00, 11.0)   # by hand: half of 50
        self.assertEqual(broker.position("AAA"), 25)
        self.assertFalse(tr.fire_scale_rung("AAA", 2, 12.0)["ok"])                                    # a rung fires once
        tr.flatten("AAA", 13.0); quote(e, 11.99, 12.00, 14.0); tr.watchdog(15.0)
        self.assertNotIn("AAA", tr.scale_plans)                                                        # flat: plan finished

    def test_build_plan_adds_on_strength_then_scales_and_manual_mode_waits(self):
        e, tr, broker = make()
        tr.submit("AAA", "BUY", 10.0, 100, 2.0, bracket=False); quote(e, 9.99, 10.00, 3.0)
        out = tr.set_scale_plan("AAA", kind="BUILD", auto=False, now=4.0); self.assertTrue(out["ok"])
        quote(e, 10.49, 10.50, 5.0); tr.watchdog(5.5)
        r0 = tr.scale_plans["AAA"]["rungs"][0]
        self.assertTrue(r0["ready"]); self.assertFalse(r0["done"]); self.assertEqual(broker.position("AAA"), 100)   # manual: READY, not fired
        tr.set_scale_plan("AAA", auto=True, now=6.0); tr.watchdog(6.5); quote(e, 10.49, 10.50, 7.0)
        self.assertEqual(broker.position("AAA"), 150)                                                  # ADD 50% on strength
        self.assertEqual(tr.scale_plans["AAA"]["rungs"][0]["action"], "ADD")

    def test_custom_rungs_and_short_side(self):
        e, tr, broker = make()
        tr.submit("AAA", "SELL", 9.99, 100, 2.0, bracket=False); quote(e, 9.99, 10.00, 3.0)
        self.assertEqual(broker.position("AAA"), -100)
        out = tr.set_scale_plan("AAA", rungs=[{"move": 0.3, "action": "TAKE", "pct": 10}, {"move": 0.6, "action": "TAKE", "pct": 20}], now=4.0)
        self.assertTrue(out["ok"]); self.assertEqual(out["plan"]["kind"], "CUSTOM"); self.assertEqual(out["plan"]["side"], "short")
        quote(e, 9.29, 9.30, 5.0); tr.watchdog(5.5); quote(e, 9.29, 9.30, 6.0)                       # down 69c for a short: both rungs
        self.assertEqual(broker.position("AAA"), -72)                                                  # 10% of 100, then 20% of 90
        self.assertFalse(tr.set_scale_plan("BBB", kind="MP", now=7.0)["ok"])                           # no position, no plan


class ChartStopTests(unittest.TestCase):
    """A stop drawn on the chart on a position opened from the ticket (no bracket) goes in as a real stop order,
    follows the line when dragged, and gets you out when price trades through it."""
    def test_drawn_stop_protects_a_manual_position(self):
        e, tr, broker = make()
        self.assertTrue(tr.submit("AAA", "BUY", 10.0, 100, 2.0, bracket=False)["ok"])
        quote(e, 9.99, 10.00, 3.0)
        self.assertEqual(broker.position("AAA"), 100)
        tr.watchdog(3.5)
        self.assertFalse([o for o in e._pending("AAA") if o.get("role") == "stop"])     # no line, no stop
        ok, why = e.set_play_setup("AAA", {"stop": 9.50}, 4.0); self.assertTrue(ok, why)  # draw a stop under a long
        tr.watchdog(4.5)
        stops = [o for o in e._pending("AAA") if o.get("role") == "stop"]
        self.assertEqual(len(stops), 1); self.assertEqual(stops[0].get("aux"), 9.5); self.assertEqual(stops[0].get("qty"), 100)
        self.assertTrue(e.set_play_level("AAA", "stop", 9.70, 5.0, source="chart")); tr.watchdog(5.5)   # drag the line up on the chart
        stops = [o for o in e._pending("AAA") if o.get("role") == "stop"]
        self.assertEqual(len(stops), 1); self.assertEqual(stops[0].get("aux"), 9.7)
        quote(e, 9.60, 9.61, 6.0); quote(e, 9.60, 9.61, 6.5)                            # price trades through the stop
        self.assertEqual(broker.position("AAA"), 0)


class BreakevenTests(unittest.TestCase):
    """BE puts a stop at your entry: with no stop yet it places one (the STOP line goes to the entry and becomes the
    order); with a chart stop working it moves that stop and its line to the entry."""
    def test_breakeven_places_a_stop_when_there_is_none(self):
        e, tr, broker = make()
        tr.submit("AAA", "BUY", 10.0, 100, 2.0, bracket=False); quote(e, 9.99, 10.00, 3.0)
        quote(e, 10.29, 10.30, 4.0)
        out = tr.breakeven("AAA", 4.5); self.assertTrue(out["ok"], out)
        stops = [o for o in e._pending("AAA") if o.get("role") == "stop" or o.get("type") in ("STP", "STP LMT")]
        self.assertEqual(len(stops), 1); self.assertEqual(stops[0].get("aux"), 10.0); self.assertEqual(stops[0].get("qty"), 100)
        self.assertEqual(e.syms["AAA"].play["stop"], 10.0)
        tr.watchdog(5.0)
        self.assertEqual([o.get("aux") for o in e._pending("AAA") if o.get("role") == "stop"], [10.0])   # nothing doubled

    def test_breakeven_moves_the_chart_stop_and_its_line(self):
        e, tr, broker = make()
        tr.submit("AAA", "BUY", 10.0, 100, 2.0, bracket=False); quote(e, 9.99, 10.00, 3.0)
        e.set_play_level("AAA", "stop", 9.50, 3.5, source="chart"); tr.watchdog(3.6)
        quote(e, 10.29, 10.30, 4.0)
        self.assertTrue(tr.breakeven("AAA", 4.5)["ok"]); tr.watchdog(5.0)
        self.assertEqual([o.get("aux") for o in e._pending("AAA") if o.get("role") == "stop"], [10.0])
        self.assertEqual(e.syms["AAA"].play["stop"], 10.0)


class TicketStopTrailTests(unittest.TestCase):
    """From ORDER ENTRY: a stop by price (refused when it is through the market) and a trailing stop that only moves
    in your favour; both ride the STOP line, which is the stop order."""
    def test_stop_and_trail(self):
        e, tr, broker = make()
        tr.submit("AAA", "BUY", 10.0, 100, 2.0, bracket=False); quote(e, 9.99, 10.00, 3.0)
        self.assertFalse(tr.set_stop("AAA", 10.20, 4.0)["ok"])                       # above the price on a long: refused
        self.assertTrue(tr.set_stop("AAA", 9.60, 4.0)["ok"]); tr.watchdog(4.5)
        stops = [o for o in e._pending("AAA") if o.get("role") == "stop"]
        self.assertEqual([o.get("aux") for o in stops], [9.6])
        self.assertTrue(tr.set_trail("AAA", 0.50, True, 5.0)["ok"]); tr.watchdog(5.5)   # 10.00 - 0.50 = 9.50 is worse: stop stays
        self.assertEqual(e.syms["AAA"].play["stop"], 9.6)
        quote(e, 10.49, 10.50, 6.0); tr.watchdog(6.5)                                  # new high 10.50: stop to 10.00
        self.assertEqual(e.syms["AAA"].play["stop"], 10.0)
        self.assertEqual([o.get("aux") for o in e._pending("AAA") if o.get("role") == "stop"], [10.0])
        quote(e, 10.29, 10.30, 7.0); tr.watchdog(7.5)                                  # pullback: the stop never moves back
        self.assertEqual(e.syms["AAA"].play["stop"], 10.0)
        quote(e, 9.95, 9.96, 8.0); quote(e, 9.95, 9.96, 8.5)                          # trades through 10.00: out
        self.assertEqual(broker.position("AAA"), 0)
        tr.watchdog(9.0); self.assertNotIn("AAA", tr.trails)


class DemoStartsWithPartialLevelsTests(unittest.TestCase):
    """The practice feed starts whatever levels a play has: a stop with no target, a target with no stop, or none."""
    def test_stop_only_target_only_none(self):
        from twiney.sim import DemoFeed
        e = Engine(plays(), cfg())
        for p in (dict(plays()[0], symbol="S1", stop=12.0, target=None, trigger=None, second_entry=None, active=True),
                  dict(plays()[0], symbol="S2", stop=None, target=15.0, trigger=None, second_entry=None, active=True),
                  dict(plays()[0], symbol="S3", stop=None, target=None, trigger=None, second_entry=None, active=True)):
            feed = DemoFeed(e, [p], seed=1)
            self.assertIn(p["symbol"], feed.state)


class TwoSidedPlayTests(unittest.TestCase):
    """Pivots both ways at once: a long side over the price and a short side under it. Only the 2nd entries are orders
    (their stop and target ride as children, live only once the entry fills). Whichever fills first, the other entry is
    cancelled; the side you are in has its stop and target working."""
    def test_short_side_fills_long_entry_cancelled_stop_gets_out(self):
        e, tr, broker = make()
        tr.set_risk(20); tr.set_auto(True, None, 1.5)
        self.assertTrue(e.set_side_level("AAA", "long", "trigger", 10.20, 2.0))
        self.assertTrue(e.set_side_level("AAA", "long", "second_entry", 10.25, 2.0))
        self.assertTrue(e.set_side_level("AAA", "long", "stop", 10.05, 2.0))
        self.assertTrue(e.set_side_level("AAA", "long", "target", 10.80, 2.0))
        self.assertTrue(e.set_side_level("AAA", "short", "trigger", 9.80, 2.0))
        self.assertTrue(e.set_side_level("AAA", "short", "second_entry", 9.75, 2.0))
        self.assertTrue(e.set_side_level("AAA", "short", "stop", 9.95, 2.0))
        self.assertTrue(e.set_side_level("AAA", "short", "target", 9.20, 2.0))
        p = e.syms["AAA"].play
        self.assertEqual((p["side"], p["second_entry"], p["alt"]["second_entry"]), ("long", 10.25, 9.75))
        labels = [l["label"] for l in e._user_levels(p)]
        self.assertIn("↓ 2ND ENTRY", labels); self.assertIn("↓ STOP", labels)
        tr.watchdog(3.0)
        entries = [o for o in e._pending("AAA") if o.get("role") == "entry"]
        self.assertEqual(sorted((o["action"], o.get("aux")) for o in entries), [("BUY", 10.25), ("SELL", 9.75)])   # both 2nd entries working
        self.assertEqual(broker.position("AAA"), 0)
        # price breaks down through the short 2nd entry: the short fills
        quote(e, 9.70, 9.71, 4.0); quote(e, 9.70, 9.71, 4.2)
        self.assertLess(broker.position("AAA"), 0)
        tr.watchdog(4.5); quote(e, 9.70, 9.71, 4.7); tr.watchdog(5.0)
        entries = [o for o in e._pending("AAA") if o.get("role") == "entry"]
        self.assertEqual(entries, [])                                                     # the long entry is gone
        stops = [o for o in e._pending("AAA") if o.get("role") == "stop"]
        self.assertTrue(stops and all(o["action"] == "BUY" and abs(o.get("aux") - 9.95) < 1e-9 for o in stops))   # the short side's stop
        quote(e, 9.96, 9.97, 6.0); quote(e, 9.96, 9.97, 6.3)                            # back up through 9.95: stopped out
        self.assertEqual(broker.position("AAA"), 0)

    def test_other_side_saved_and_cleared(self):
        import json, os, tempfile
        e, tr, broker = make()
        d = tempfile.mkdtemp(); e.plays_path = os.path.join(d, "plays.json")
        e.set_side_level("AAA", "long", "second_entry", 10.25, 2.0); e.set_side_level("AAA", "short", "second_entry", 9.75, 2.0)
        saved = json.load(open(e.plays_path))["plays"][0]
        self.assertEqual(saved["alt"]["second_entry"], 9.75)
        from twiney.config import validate_plays
        back = validate_plays({"plays": [saved]})[0]
        self.assertEqual(back["alt"]["second_entry"], 9.75)
        e.clear_play("AAA", 3.0)
        self.assertNotIn("alt", e.syms["AAA"].play)


class OptionThroughTests(unittest.TestCase):
    def test_buy_and_sell_go_one_valid_step_through_the_touch(self):
        from twiney.trading import opt_through
        self.assertEqual(opt_through(2.93, "BUY"), 2.95); self.assertEqual(opt_through(2.93, "SELL"), 2.9)
        self.assertEqual(opt_through(3.12, "BUY"), 3.2); self.assertEqual(opt_through(0.05, "SELL"), 0.05)


class PracticeOptionsMoveWithTheStockTests(unittest.TestCase):
    """The practice desk: a call you hold gains as the stock rises and loses as it falls; a put the other way —
    re-priced every tick even with the OPTION CHAIN closed."""
    def test_calls_gain_on_the_way_up_puts_on_the_way_down(self):
        import time as _t
        from twiney import options as _o
        e, tr, broker = make(); T = _t.time()
        e.on_l1("AAA", "last", 10.00, T)
        ch = e.option_chain("AAA", None, "C", T); exp = ch["expiry"]
        kc, kp = _o.key_of("AAA", exp, 10, "C"), _o.key_of("AAA", exp, 10, "P")
        self.assertTrue(tr.opt_open("AAA", exp, 10, "C", "BUY", 1, None, T)["ok"])
        self.assertTrue(tr.opt_open("AAA", exp, 10, "P", "BUY", 1, None, T)["ok"])
        e.practice_opt_tick(T + 1)
        self.assertIn(kc, e.opt_positions); self.assertIn(kp, e.opt_positions)
        c0, p0 = e.opt_quotes[kc]["last"], e.opt_quotes[kp]["last"]
        e.on_l1("AAA", "last", 10.60, T + 2); e.practice_opt_tick(T + 3)         # stock up: call up, put down
        self.assertGreater(e.opt_quotes[kc]["last"], c0); self.assertLess(e.opt_quotes[kp]["last"], p0)
        self.assertGreater(e._opt_view(e.opt_positions[kc])["pnl"], 0)
        e.on_l1("AAA", "last", 9.40, T + 4); e.practice_opt_tick(T + 5)          # stock down: put up, call down
        self.assertGreater(e.opt_quotes[kp]["last"], p0); self.assertLess(e.opt_quotes[kc]["last"], c0)
        self.assertGreater(e._opt_view(e.opt_positions[kp])["pnl"], 0)


class StopGrowsWithAddsTests(unittest.TestCase):
    def test_adding_shares_grows_the_chart_stop(self):
        e, tr, broker = make()
        tr.submit("AAA", "BUY", 10.0, 100, 2.0, bracket=False); quote(e, 9.99, 10.00, 3.0)
        e.set_play_level("AAA", "stop", 9.50, 3.5, source="chart"); tr.watchdog(3.6)
        self.assertEqual([o.get("remaining") or o.get("qty") for o in e._pending("AAA") if o.get("role") == "stop"], [100])
        tr.submit("AAA", "BUY", 10.0, 50, 4.0, bracket=False); quote(e, 9.99, 10.00, 4.5)       # add 50
        self.assertEqual(broker.position("AAA"), 150)
        tr.watchdog(5.0); tr.watchdog(8.0)
        stops = [o for o in e._pending("AAA") if o.get("role") == "stop"]
        self.assertEqual(sum(int(o.get("remaining") or o.get("qty")) for o in stops), 150)
        self.assertEqual({o.get("aux") for o in stops}, {9.5})


class OptionStopTests(unittest.TestCase):
    """A contract is stopped out on the STOCK's price (the chart's STOP line, or one you set) or on its own price."""
    def setUp(self):
        import time as _t
        from twiney import options as _o
        self.e, self.tr, self.broker = make(); self.T = _t.time()
        self.e.on_l1("AAA", "last", 10.00, self.T)
        exp = self.e.option_chain("AAA", None, "C", self.T)["expiry"]
        self.kc, self.kp = _o.key_of("AAA", exp, 10, "C"), _o.key_of("AAA", exp, 10, "P")
        self.exp = exp

    def held(self, key):
        return int((self.e.opt_positions.get(key) or {}).get("qty") or 0)

    def test_the_chart_stop_line_takes_a_call_out(self):
        e, tr, T = self.e, self.tr, self.T
        self.assertTrue(tr.opt_open("AAA", self.exp, 10, "C", "BUY", 2, None, T)["ok"]); e.practice_opt_tick(T + 1)
        self.assertEqual(self.held(self.kc), 2)
        e.set_play_level("AAA", "stop", 9.80, T + 1, source="chart")
        self.assertEqual(tr.snapshot()["opt_stops"][self.kc]["source"], "chart")
        e.on_l1("AAA", "last", 9.90, T + 2); tr.watchdog(T + 2); e.practice_opt_tick(T + 3)
        self.assertEqual(self.held(self.kc), 2)                                          # above the stop: held
        e.on_l1("AAA", "last", 9.78, T + 4); tr.watchdog(T + 4); e.practice_opt_tick(T + 5)
        self.assertEqual(self.held(self.kc), 0)                                          # through it: out

    def test_a_put_with_a_stock_stop_and_a_call_with_an_option_stop(self):
        e, tr, T = self.e, self.tr, self.T
        tr.opt_open("AAA", self.exp, 10, "P", "BUY", 1, None, T); tr.opt_open("AAA", self.exp, 10, "C", "BUY", 1, None, T); e.practice_opt_tick(T + 1)
        self.assertFalse(tr.set_opt_stop(self.kp, 9.90, "stock", T + 1)["ok"])           # under the stock on a put: through it
        self.assertTrue(tr.set_opt_stop(self.kp, 10.25, "stock", T + 1)["ok"])
        c_bid = e.opt_quotes[self.kc]["bid"]
        self.assertTrue(tr.set_opt_stop(self.kc, round(c_bid - 0.10, 2), "option", T + 1)["ok"])
        e.on_l1("AAA", "last", 10.30, T + 2); e.practice_opt_tick(T + 2.6); tr.watchdog(T + 3); e.practice_opt_tick(T + 4)
        self.assertEqual(self.held(self.kp), 0)                                          # stock over 10.25: the put is out
        self.assertEqual(self.held(self.kc), 1)                                          # the call gained: its stop holds
        e.on_l1("AAA", "last", 9.70, T + 5); e.practice_opt_tick(T + 5.6); tr.watchdog(T + 6); e.practice_opt_tick(T + 7)
        self.assertEqual(self.held(self.kc), 0)                                          # the call's bid fell to its stop
