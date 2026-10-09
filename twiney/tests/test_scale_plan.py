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


class CancelFromOrdersTests(unittest.TestCase):
    """CANCEL in ORDERS: the order goes, a cancelled STOP / TARGET takes its line off the chart (so the chart never
    shows an exit that is not working and the desk never sends it again), and a dead order says why."""
    def test_cancel_a_working_limit(self):
        e, tr, broker = make()
        oid = tr.submit("AAA", "BUY", 9.00, 100, 2.0, bracket=False)["id"]
        self.assertTrue(tr.cancel(oid, 3.0)["ok"])
        self.assertEqual(e._pending("AAA"), [])
        again = tr.cancel(oid, 4.0)
        self.assertFalse(again["ok"]); self.assertIn("already", again["reason"])

    def test_cancelled_stop_takes_its_line_off_and_is_not_resent(self):
        e, tr, broker = make()
        tr.submit("AAA", "BUY", 10.0, 100, 2.0, bracket=False); quote(e, 9.99, 10.00, 3.0)
        e.set_play_level("AAA", "stop", 9.50, 3.5, source="chart"); tr.watchdog(3.6)
        stop = [o for o in e._pending("AAA") if o.get("role") == "stop"]
        self.assertEqual(len(stop), 1)
        self.assertTrue(tr.cancel(stop[0]["order_id"], 4.0)["ok"])
        self.assertIsNone(e.syms["AAA"].play.get("stop"))
        tr.watchdog(5.0); tr.watchdog(7.0)
        self.assertEqual([o for o in e._pending("AAA") if o.get("role") == "stop"], [])
        self.assertEqual(broker.position("AAA"), 100)          # the shares are untouched


class OptionsFromTheStockChartTests(unittest.TestCase):
    """OPTIONS mode: the stock chart's 2nd entry, STOP and TARGET trade the contract on the OPTION CHART. The stock
    trades up through the 2nd entry: the call is bought (a limit, never market). It reaches the target: every
    contract is sold. Flat: the lines come off. No stock order is ever sent for those lines."""
    def _setup(self, right="C"):
        import time as _t
        from twiney import options as _o
        e, tr, broker = make(); T = _t.time()
        e.on_l1("AAA", "last", 10.00, T)
        exp = e.option_chain("AAA", None, right, T)["expiry"]
        key = _o.key_of("AAA", exp, 10, right)
        return e, tr, broker, T, key

    def _move(self, e, tr, px, t):
        e.on_l1("AAA", "last", px, t); e.practice_opt_tick(t + 0.6); tr.watchdog(t + 0.7); e.practice_opt_tick(t + 1.4)

    def test_call_in_on_the_entry_out_at_the_target_lines_cleared(self):
        e, tr, broker, T, key = self._setup("C")
        self.assertTrue(tr.set_trade_as("AAA", "option", key, 2, T)["ok"])
        self.assertEqual(e.syms["AAA"].play["trade_as"], "option")
        e.set_play_level("AAA", "second_entry", 10.20, T, source="chart")
        e.set_play_level("AAA", "stop", 9.80, T, source="chart")
        e.set_play_level("AAA", "target", 10.60, T, source="chart")
        self._move(e, tr, 10.05, T + 1)
        self.assertEqual([o for o in e._pending() if o.get("opt")], [])          # not crossed yet: nothing
        self._move(e, tr, 10.25, T + 3)                                           # up through 10.20: the call is bought
        sent = [o for o in e.orders.values() if o.get("symbol") == key and o.get("action") == "BUY"]
        self.assertEqual(len(sent), 1); self.assertEqual(sent[0]["qty"], 2)
        self.assertFalse([o for o in e._pending("AAA")])                         # never a stock order
        for i in range(6):
            self._move(e, tr, 10.25 + 0.01 * (i % 2), T + 5 + 2 * i)
        self.assertEqual(int(e.opt_positions[key]["qty"]), 2)
        self._move(e, tr, 10.65, T + 20)                                          # the target: every contract goes
        for i in range(6):
            self._move(e, tr, 10.65 + 0.01 * (i % 2), T + 22 + 2 * i)
        self.assertEqual(int((e.opt_positions.get(key) or {}).get("qty") or 0), 0)
        play = e.syms["AAA"].play
        self.assertEqual((play.get("second_entry"), play.get("stop"), play.get("target")), (None, None, None))

    def test_put_in_when_the_stock_breaks_down_through_the_short_entry(self):
        e, tr, broker, T, key = self._setup("P")
        tr.set_trade_as("AAA", "option", key, 1, T)
        self.assertEqual(e.syms["AAA"].play["side"], "short")                   # a put makes the play SHORT
        e.set_play_level("AAA", "second_entry", None, T, source="chart")
        e.set_play_level("AAA", "second_entry", 9.80, T, source="chart")
        self._move(e, tr, 9.95, T + 1)
        self.assertFalse([o for o in e.orders.values() if o.get("symbol") == key])
        self._move(e, tr, 9.75, T + 3)
        self.assertEqual(len([o for o in e.orders.values() if o.get("symbol") == key and o.get("action") == "BUY"]), 1)

    def test_the_stop_line_takes_the_call_out(self):
        e, tr, broker, T, key = self._setup("C")
        tr.set_trade_as("AAA", "option", key, 1, T)
        e.set_play_level("AAA", "second_entry", 10.20, T, source="chart"); e.set_play_level("AAA", "stop", 9.90, T, source="chart")
        self._move(e, tr, 10.05, T + 1); self._move(e, tr, 10.25, T + 3)
        for i in range(6):
            self._move(e, tr, 10.25, T + 5 + 2 * i)
        self.assertEqual(int(e.opt_positions[key]["qty"]), 1)
        self._move(e, tr, 9.85, T + 20)
        for i in range(6):
            self._move(e, tr, 9.85, T + 22 + 2 * i)
        self.assertEqual(int((e.opt_positions.get(key) or {}).get("qty") or 0), 0)

    def test_no_entry_when_price_was_already_past_and_disarmed_says_why(self):
        e, tr, broker, T, key = self._setup("C")
        tr.set_trade_as("AAA", "option", key, 1, T)
        e.set_play_level("AAA", "second_entry", None, T, source="chart")
        self._move(e, tr, 10.30, T + 1)
        e.set_play_level("AAA", "second_entry", 10.20, T + 2, source="chart")    # drawn under the price: waits
        self._move(e, tr, 10.35, T + 3)
        self.assertFalse([o for o in e.orders.values() if o.get("symbol") == key])
        tr.gate.arm(False)
        self._move(e, tr, 10.10, T + 5)
        self.assertIn("DISARMED", tr.snapshot(run_watchdog=False)["opt_links"]["AAA"]["why"].upper())

    def test_a_contract_of_another_ticker_is_refused_and_stock_mode_comes_back(self):
        e, tr, broker, T, key = self._setup("C")
        self.assertFalse(tr.set_trade_as("AAA", "option", "BBB 20261009 10C", 1, T)["ok"])
        self.assertFalse(tr.set_trade_as("AAA", "option", None, 1, T)["ok"])
        tr.set_trade_as("AAA", "option", key, 1, T)
        self.assertTrue(tr.set_trade_as("AAA", "stock", None, None, T)["ok"])
        self.assertEqual(e.syms["AAA"].play["trade_as"], "stock"); self.assertNotIn("opt_key", e.syms["AAA"].play)


class AutoStopAndAddsTests(unittest.TestCase):
    """A new 2nd entry brings its STOP $1 away (SETTINGS: trading.auto_stop_dollars); you move it. Adding to a position
    with brackets on joins the working stop and take profit: they grow to every share, never a second set. Taking
    profit along the way trims the take profit to what is left."""
    def test_new_second_entry_gets_a_stop_a_dollar_away_and_keeps_yours(self):
        e, tr, broker = make()
        e.set_play_level("AAA", "second_entry", None, 1.0, source="chart")
        e.set_play_level("AAA", "second_entry", 10.30, 2.0, source="chart")
        self.assertEqual(e.syms["AAA"].play["stop"], 9.30)
        e.set_play_level("AAA", "stop", 9.80, 3.0, source="chart")                 # moved by you
        e.set_play_level("AAA", "second_entry", 10.35, 4.0, source="chart")        # dragging the entry leaves it
        self.assertEqual(e.syms["AAA"].play["stop"], 9.80)
        e.set_side_level("AAA", "short", "second_entry", 9.50, 5.0)                # the other side: over a short
        self.assertEqual(e.syms["AAA"].play["alt"]["stop"], 10.50)

    def test_adds_grow_the_stop_and_take_profit_and_partials_trim_it(self):
        e, tr, broker = make(); tr.bracket = True
        e.set_play_level("AAA", "stop", 9.50, 1.5, source="chart"); e.set_play_level("AAA", "target", 11.00, 1.5, source="chart")
        self.assertTrue(tr.submit("AAA", "BUY", 10.0, 100, 2.0)["ok"]); quote(e, 9.99, 10.00, 3.0)
        exits = lambda r: [o for o in e._pending("AAA") if o.get("role") == r]
        self.assertEqual([o["qty"] for o in exits("stop")], [100]); self.assertEqual([o["qty"] for o in exits("target")], [100])
        out = tr.submit("AAA", "BUY", 10.0, 50, 4.0); self.assertTrue(out["ok"]); self.assertIn("adds to your working stop", out["sent"])
        quote(e, 9.99, 10.00, 5.0); tr.watchdog(8.0)
        self.assertEqual(broker.position("AAA"), 150)
        self.assertEqual([o.get("remaining") or o["qty"] for o in exits("stop")], [150])         # one stop, every share
        self.assertEqual([o.get("remaining") or o["qty"] for o in exits("target")], [150])       # one take profit
        tr.adjust("AAA", 50, "close", 9.0); quote(e, 10.29, 10.30, 9.5); tr.watchdog(12.0); tr.watchdog(15.0)
        self.assertEqual(broker.position("AAA"), 100)
        self.assertEqual([o.get("remaining") for o in exits("target")], [100])                    # took profit: trimmed


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
        self.assertEqual(opt_through(2.93, "BUY"), 2.94); self.assertEqual(opt_through(2.93, "SELL"), 2.92)   # quoted in pennies
        self.assertEqual(opt_through(2.95, "BUY"), 3.0); self.assertEqual(opt_through(2.95, "SELL"), 2.9)    # quoted in nickels
        self.assertEqual(opt_through(3.12, "BUY"), 3.2); self.assertEqual(opt_through(0.05, "SELL"), 0.05)
        self.assertEqual(opt_through(0.03, "SELL"), 0.02)                    # a 3-cent bid never gets a nickel sell


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
        mid = lambda k: (e.opt_quotes[k]["bid"] + e.opt_quotes[k]["ask"]) / 2
        c0, p0 = mid(kc), mid(kp)
        e.on_l1("AAA", "last", 10.60, T + 2); e.practice_opt_tick(T + 3)         # stock up: call up, put down
        self.assertGreater(mid(kc), c0); self.assertLess(mid(kp), p0)
        self.assertGreater(e._opt_view(e.opt_positions[kc])["pnl"], 0)
        e.on_l1("AAA", "last", 9.40, T + 4); e.practice_opt_tick(T + 5)          # stock down: put up, call down
        self.assertGreater(mid(kp), p0); self.assertLess(mid(kc), c0)
        self.assertGreater(e._opt_view(e.opt_positions[kp])["pnl"], 0)


class OptionChartDrawsTradesTests(unittest.TestCase):
    """The OPTION CHART's candles and LAST are the contract's trades: the same prices the OPTION T&S prints and the
    OPTION LEVEL II shows traded, never a mid between the bid and the ask that nothing traded at."""
    def test_quotes_alone_draw_nothing_trades_do(self):
        e, tr, broker = make(); T = 1_790_000_000.0
        k = "AAA 20261009 10C"
        e.on_opt_quote(k, "bid", 1.00, T); e.on_opt_quote(k, "ask", 1.10, T)
        self.assertFalse(e.opt_bars.get(k))
        e.on_opt_quote(k, "last", 1.10, T + 1); e.on_opt_print(k, 1.10, 5, T + 1, "buy")
        e.on_opt_quote(k, "bid", 1.02, T + 2)
        bar = list(e.opt_bars[k].values())[-1]
        self.assertEqual(bar[:4], [1.10, 1.10, 1.10, 1.10])

    def test_practice_chart_last_is_a_print_on_the_tape(self):
        import time as _t
        from twiney import options as _o
        e, tr, broker = make(); T = _t.time()
        e.on_l1("AAA", "last", 10.00, T)
        exp = e.option_chain("AAA", None, "C", T)["expiry"]; k = _o.key_of("AAA", exp, 10, "C")
        e.option_bars(k, T)
        for i in range(40):
            e.on_l1("AAA", "last", 10.00 + 0.01 * (i % 7), T + i); e.practice_opt_tick(T + i + 0.6)
        d = e.option_bars(k, T + 41)
        prints = d["tape"]["prints"]
        self.assertTrue(prints)
        self.assertAlmostEqual(d["last"], prints[0][1], places=2)
        self.assertAlmostEqual(d["bars"][-1][4], prints[0][1], places=2)


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
        import datetime, zoneinfo
        # a fixed Monday 11:00 New York, the week's contracts days out: the same option prices every run (on the real
        # clock a contract near expiry at night is worth a cent or two and this went one way or the other)
        self.e, self.tr, self.broker = make(); self.T = datetime.datetime(2026, 10, 12, 11, 0, tzinfo=zoneinfo.ZoneInfo("America/New_York")).timestamp()
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
        self.assertFalse(tr.set_opt_stop(self.kc, 0, "option", T + 1)["ok"])                 # a stop at 0 never fires
        self.assertTrue(tr.set_opt_stop(self.kc, max(0.01, round(c_bid * 0.6, 2)), "option", T + 1)["ok"])
        e.on_l1("AAA", "last", 10.30, T + 2); e.practice_opt_tick(T + 2.6); tr.watchdog(T + 3); e.practice_opt_tick(T + 4)
        self.assertEqual(self.held(self.kp), 0)                                          # stock over 10.25: the put is out
        self.assertEqual(self.held(self.kc), 1)                                          # the call gained: its stop holds
        e.on_l1("AAA", "last", 9.40, T + 5); e.practice_opt_tick(T + 5.6); tr.watchdog(T + 6); e.practice_opt_tick(T + 7)
        self.assertEqual(self.held(self.kc), 0)                                          # the call's bid fell to its stop


class SellToOpenTests(unittest.TestCase):
    """Writing a contract you don't own (SHORT) is off unless switched on; covered calls always work; selling what
    you hold is never blocked; option P&L counts in the day's P&L (the loss lock sees it)."""
    def setUp(self):
        import time as _t
        self.e, self.tr, self.broker = make(); self.T = _t.time()
        self.e.on_l1("AAA", "last", 10.00, self.T)
        self.exp = self.e.option_chain("AAA", None, "C", self.T)["expiry"]

    def test_blocked_by_default_allowed_when_switched_on(self):
        tr, T = self.tr, self.T
        out = tr.opt_open("AAA", self.exp, 10, "P", "SELL", 1, None, T)
        self.assertFalse(out["ok"]); self.assertIn("Allow selling to open", out["reason"])
        out = tr.opt_open("AAA", self.exp, 10, "C", "SELL", 1, None, T)
        self.assertFalse(out["ok"]); self.assertIn("not covered", out["reason"])
        tr.cfg["allow_sell_to_open"] = True
        self.assertTrue(tr.opt_open("AAA", self.exp, 10, "P", "SELL", 1, None, T)["ok"])

    def test_covered_calls_and_selling_what_you_hold(self):
        e, tr, T = self.e, self.tr, self.T
        tr.submit("AAA", "BUY", 10.0, 200, T, bracket=False); quote(e, 9.99, 10.00, T + 1)
        self.assertEqual(self.broker.position("AAA"), 200)
        self.assertTrue(tr.opt_open("AAA", self.exp, 10, "C", "SELL", 2, None, T + 2)["ok"])      # 2 calls on 200 shares
        e.practice_opt_tick(T + 3)
        self.assertFalse(tr.opt_open("AAA", self.exp, 10, "C", "SELL", 1, None, T + 4)["ok"])     # a 3rd is naked
        tr.opt_open("AAA", self.exp, 10, "P", "BUY", 2, None, T + 4); e.practice_opt_tick(T + 5)
        self.assertTrue(tr.opt_open("AAA", self.exp, 10, "P", "SELL", 2, None, T + 6)["ok"])      # selling what you own

    def test_option_pnl_is_in_the_day_pnl(self):
        e, tr, T = self.e, self.tr, self.T
        tr.opt_open("AAA", self.exp, 10, "C", "BUY", 2, None, T); e.practice_opt_tick(T + 1)
        e.on_l1("AAA", "last", 10.80, T + 2); e.practice_opt_tick(T + 3)
        pnl = e.day_pnl()
        self.assertGreater(pnl["options"], 0); self.assertAlmostEqual(pnl["total"], pnl["realized"] + pnl["open"], places=2)


class ExpiryAndHaltTests(unittest.TestCase):
    def test_expiring_contracts_are_called_out_then_closed_before_four(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from twiney import options as _o
        e, tr, broker = make()
        ny = ZoneInfo("America/New_York")
        t_warn = datetime(2026, 10, 9, 15, 31, tzinfo=ny).timestamp(); t_close = datetime(2026, 10, 9, 15, 51, tzinfo=ny).timestamp()
        e.on_l1("AAA", "last", 10.40, t_warn - 60)
        key = _o.key_of("AAA", "20261009", 10, "C")
        e.on_opt_position("SIM", key, {"symbol": "AAA", "expiry": "20261009", "strike": 10.0, "right": "C", "mult": 100, "local": ""}, 3, 30.0, t_warn - 60)
        e.practice_quote_key(key, t_warn - 30)
        said = []; e.listeners.append(lambda a: said.append(a["label"]))
        tr.watchdog(t_warn)
        self.assertIn("EXPIRES TODAY", said)
        self.assertTrue(any("exercised into 300 AAA shares" in a["text"] for a in e.alerts))
        tr.watchdog(t_warn + 1); self.assertEqual(said.count("EXPIRES TODAY"), 1)            # said once
        e.practice_quote_key(key, t_close - 1)
        tr.watchdog(t_close); e.practice_quote_key(key, t_close + 1)
        self.assertIn("EXPIRY CLOSE", said)
        self.assertEqual(int((e.opt_positions.get(key) or {}).get("qty") or 0), 0)           # closed before 4:00

    def test_halt_and_resume_are_said(self):
        e, tr, broker = make()
        said = []; e.listeners.append(lambda a: said.append(a["label"]))
        e.on_halt("AAA", 2, 10.0); e.on_halt("AAA", 2, 11.0); e.on_halt("AAA", 0, 300.0)
        self.assertEqual(said, ["HALTED", "RESUMED"])
        self.assertTrue(any("volatility pause" in a["text"] for a in e.alerts))


class SharesAndContractIndependentTests(unittest.TestCase):
    """Shares AND a contract on the same stock: each chart trades its own. The stock chart's STOP line is the shares'
    stop only; the contract keeps its own stop (set on the OPTION CHART) and the stock lines never touch it."""
    def test_stock_stop_takes_only_the_shares(self):
        import time as _t
        from twiney import options as _o
        e, tr, broker = make(); T = _t.time()
        e.on_l1("AAA", "last", 10.00, T)
        exp = e.option_chain("AAA", None, "C", T)["expiry"]
        kc = _o.key_of("AAA", exp, 10, "C")
        self.assertTrue(tr.submit("AAA", "BUY", 10.0, 100, T, bracket=False)["ok"]); quote(e, 9.99, 10.00, T + 0.5)
        self.assertTrue(tr.opt_open("AAA", exp, 10, "C", "BUY", 1, None, T + 0.5)["ok"]); e.practice_opt_tick(T + 1)
        self.assertEqual(broker.position("AAA"), 100); self.assertEqual(int(e.opt_positions[kc]["qty"]), 1)
        e.set_play_level("AAA", "stop", 9.80, T + 1, source="chart"); tr.watchdog(T + 1.5)
        self.assertNotIn(kc, tr.snapshot()["opt_stops"])                  # the stock line is NOT the contract's stop
        quote(e, 9.75, 9.76, T + 2); quote(e, 9.75, 9.76, T + 2.5); tr.watchdog(T + 3); e.practice_opt_tick(T + 3.5); tr.watchdog(T + 4)
        self.assertEqual(broker.position("AAA"), 0)                       # the shares stopped out
        self.assertEqual(int(e.opt_positions[kc]["qty"]), 1)              # the call is still on

    def test_with_no_shares_the_stock_line_still_drives_the_contract(self):
        import time as _t
        from twiney import options as _o
        e, tr, broker = make(); T = _t.time()
        e.on_l1("AAA", "last", 10.00, T)
        exp = e.option_chain("AAA", None, "C", T)["expiry"]
        kc = _o.key_of("AAA", exp, 10, "C")
        tr.opt_open("AAA", exp, 10, "C", "BUY", 1, None, T); e.practice_opt_tick(T + 1)
        e.set_play_level("AAA", "stop", 9.80, T + 1, source="chart")
        self.assertEqual(tr.snapshot()["opt_stops"][kc]["source"], "chart")
