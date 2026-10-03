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
