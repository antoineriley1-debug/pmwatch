"""The order paths that protect money: getting out always works, stops stay on, exits never outgrow the position."""
import unittest

from helpers import ASK, BID, UPDATE
from test_trading import sim_setup
from twiney.trading import snap


def pend(e, t=9.0):
    return e.snapshot(t)["account"]["pending"]


class FlattenTests(unittest.TestCase):
    def test_flatten_works_disarmed_and_over_the_order_cap(self):
        e, tr, gate, broker = sim_setup(max_shares_per_order=300, max_position_shares=1000)
        gate.arm(True)
        e.syms["AAA"].play.update(stop=9.50, target=11.0)
        tr.submit("AAA", "BUY", 10.00, 300, 2.0)
        tr.submit("AAA", "BUY", 10.00, 300, 2.1)
        self.assertEqual(broker.position("AAA"), 600)
        gate.arm(False)
        out = tr.flatten("AAA", 3.0)
        self.assertTrue(out["ok"], out)
        self.assertEqual(broker.position("AAA"), 0)

    def test_flatten_works_when_locked_for_the_day(self):
        e, tr, gate, broker = sim_setup()
        gate.arm(True)
        tr.submit("AAA", "BUY", 10.00, 100, 2.0, bracket=False)
        gate.lock_out("test")
        self.assertTrue(tr.flatten("AAA", 3.0)["ok"])
        self.assertEqual(broker.position("AAA"), 0)

    def test_second_flatten_is_refused_while_the_first_works(self):
        e, tr, gate, broker = sim_setup()
        gate.arm(True)
        tr.submit("AAA", "BUY", 10.00, 100, 2.0, bracket=False)
        broker.on_market = lambda *a: None                        # the market doesn't take it yet: it works
        self.assertTrue(tr.flatten("AAA", 3.0)["ok"])
        out = tr.flatten("AAA", 3.1)
        self.assertFalse(out["ok"])
        self.assertIn("already working", out["reason"])


class LossLockTests(unittest.TestCase):
    def test_lock_keeps_the_stop_and_cancels_resting_entries(self):
        e, tr, gate, broker = sim_setup(max_daily_loss=50, loss_limit_on_paper=True)
        gate.arm(True)
        e.syms["AAA"].play.update(stop=9.00, target=12.0)
        tr.submit("AAA", "BUY", 10.00, 100, 2.0)                 # fills: stop 9.00 working
        tr.submit("AAA", "BUY", 9.50, 100, 2.1, bracket=False)   # resting entry
        e.on_depth("AAA", 0, UPDATE, BID, 9.40, 500, "", 3.0)
        e.on_depth("AAA", 0, UPDATE, ASK, 9.41, 500, "", 3.0)
        e.on_l1("AAA", "last", 9.40, 3.0)
        tr.watchdog(4.0)
        self.assertTrue(gate.locked)
        roles = sorted(o["role"] for o in pend(e))
        self.assertEqual(roles, ["stop", "target"])              # the resting entry is gone, the stop stays


class ExitGuardTests(unittest.TestCase):
    def test_manual_close_cancels_leftover_exits(self):
        e, tr, gate, broker = sim_setup()
        gate.arm(True)
        e.syms["AAA"].play.update(stop=9.50, target=11.0)
        tr.submit("AAA", "BUY", 10.00, 100, 2.0)
        self.assertTrue(tr.adjust("AAA", 100, "close", 3.0)["ok"])
        self.assertEqual(broker.position("AAA"), 0)
        tr.watchdog(3.5)
        self.assertEqual(pend(e), [])                             # CLOSE of the whole position takes its stop / target with it
        tr.watchdog(5.1); tr.watchdog(7.2)
        self.assertEqual(pend(e), [])

    def test_partial_close_trims_the_stop(self):
        e, tr, gate, broker = sim_setup()
        gate.arm(True)
        e.syms["AAA"].play.update(stop=9.50, target=11.0)
        tr.submit("AAA", "BUY", 10.00, 100, 2.0)
        tr.adjust("AAA", 40, "close", 3.0)
        tr.watchdog(3.1); tr.watchdog(5.1); tr.watchdog(7.2)
        self.assertEqual({o["role"]: o["remaining"] for o in pend(e)}, {"stop": 60.0, "target": 60.0})


class EntryChecks(unittest.TestCase):
    def test_position_cap_counts_working_entries(self):
        e, tr, gate, broker = sim_setup(max_position_shares=1000, max_orders_per_minute=50)
        gate.arm(True)
        ok = [tr.submit("AAA", "BUY", 9.00, 400, 2.0 + i, bracket=False)["ok"] for i in range(4)]
        self.assertEqual(ok, [True, True, False, False])

    def test_stop_on_the_wrong_side_gets_a_right_side_stop(self):
        # the chart's stop points the other way: the entry goes out with a stop $1 the right way, never with none
        e, tr, gate, broker = sim_setup()
        gate.arm(True)
        e.syms["AAA"].play.update(stop=10.60, target=11.0)
        out = tr.submit("AAA", "BUY", 9.50, 100, 2.0)
        self.assertTrue(out["ok"], out)
        stops = [o for o in pend(e) if o.get("role") == "stop"]
        self.assertEqual(len(stops), 1); self.assertAlmostEqual(stops[0]["aux"], 8.50)
        self.assertIn("stop 8.50", out["sent"])

    def test_wrong_side_stop_uses_the_other_side_you_drew(self):
        e, tr, gate, broker = sim_setup()
        gate.arm(True)
        e.syms["AAA"].play.update(side="long", stop=9.00, target=11.0, alt={"stop": 10.40, "target": 9.20})
        out = tr.submit("AAA", "SELL", 10.50, 100, 2.0)          # a short: the SHORT side's stop 10.40 is under 10.50: wrong too
        self.assertTrue(out["ok"], out)
        self.assertAlmostEqual([o for o in pend(e) if o.get("role") == "stop"][0]["aux"], 11.50)
        e.syms["AAA"].play.update(alt={"stop": 10.80, "target": 9.20})
        tr.cancel_all(None, 3.0)
        out = tr.submit("AAA", "SELL", 10.50, 100, 4.0)
        self.assertAlmostEqual([o for o in pend(e) if o.get("role") == "stop"][0]["aux"], 10.80)

    def test_stop_on_the_wrong_side_refuses_when_auto_stop_is_off(self):
        e, tr, gate, broker = sim_setup()
        gate.arm(True)
        tr.cfg["auto_stop_dollars"] = 0
        e.syms["AAA"].play.update(stop=10.60, target=11.0)
        out = tr.submit("AAA", "BUY", 10.00, 100, 2.0)
        self.assertFalse(out["ok"])
        self.assertIn("wrong side", out["reason"])
        self.assertEqual(pend(e), [])

    def test_marketable_entry_gets_its_stop_working(self):
        e, tr, gate, broker = sim_setup()
        gate.arm(True)
        e.syms["AAA"].play.update(stop=9.90, target=10.20)
        tr.submit("AAA", "BUY", 10.00, 100, 2.0)
        self.assertEqual(broker.position("AAA"), 100)
        self.assertEqual({o["role"]: o["status"] for o in pend(e)}, {"stop": "Submitted", "target": "Submitted"})
        e.on_print("AAA", 9.85, 100, "X", 3.0)
        e.on_depth("AAA", 0, UPDATE, BID, 9.85, 500, "", 3.1)
        self.assertEqual(broker.position("AAA"), 0)

    def test_marketable_limit_fills_at_the_touch(self):
        e, tr, gate, broker = sim_setup()
        gate.arm(True)
        tr.submit("AAA", "BUY", 10.00, 100, 2.0, bracket=False)
        tr.submit("AAA", "SELL", 9.90, 100, 3.0, bracket=False)   # bid is 9.99
        self.assertEqual(e.day_pnl()["realized"], -1.0)

    def test_snap_to_valid_ticks(self):
        self.assertEqual(snap(0.9995 + 0.001, +1), 1.01)
        self.assertEqual(snap(10.004), 10.0)
        self.assertEqual(snap(0.12345, -1), 0.1234)


class Round2Tests(unittest.TestCase):
    def test_close_never_oversells_while_a_flatten_works(self):
        e, tr, gate, broker = sim_setup()
        gate.arm(True)
        tr.submit("AAA", "BUY", 10.00, 100, 2.0, bracket=False)
        broker.on_market = lambda *a: None                      # nothing fills for now
        self.assertTrue(tr.flatten("AAA", 3.0)["ok"])
        self.assertFalse(tr.adjust("AAA", 100, "close", 3.1)["ok"])
        self.assertFalse(tr.adjust("AAA", 100, "close", 3.2)["ok"])
        sells = sum(o["remaining"] for o in pend(e) if o["action"] == "SELL")
        self.assertEqual(sells, 100)

    def test_resting_add_on_does_not_keep_stale_exits_alive(self):
        e, tr, gate, broker = sim_setup()
        gate.arm(True)
        e.syms["AAA"].play.update(stop=9.50, target=11.0)
        tr.submit("AAA", "BUY", 10.00, 100, 2.0)
        tr.submit("AAA", "BUY", 9.00, 100, 2.1, bracket=False)   # resting add-on
        tr.adjust("AAA", 100, "close", 3.0)
        for t in (5.1, 7.2):
            tr.watchdog(t)
        self.assertEqual(sorted(o["role"] for o in pend(e)), ["entry"])

    def test_a_lagging_position_report_never_cancels_a_stop(self):
        e, tr, gate, broker = sim_setup()
        gate.arm(True)
        e.syms["AAA"].play.update(stop=9.50, target=11.0)
        tr.submit("AAA", "BUY", 10.00, 100, 2.0)
        e.fill_t["AAA"] = 3.0; e.pos_t["AAA"] = 2.5              # a fill the broker's position hasn't caught up with
        broker.pos["AAA"][0] = 0
        for t in (5.1, 7.2, 9.3):
            tr.watchdog(t)
        self.assertEqual(sorted(o["role"] for o in pend(e)), ["stop", "target"])

    def test_position_cap_is_per_side(self):
        e, tr, gate, broker = sim_setup(max_position_shares=1000, max_orders_per_minute=50, max_shares_per_order=1000,
                                        max_dollars_per_order=100000)
        gate.arm(True)
        self.assertTrue(tr.submit("AAA", "SELL", 10.05, 1000, 2.0, bracket=False)["ok"])
        self.assertTrue(tr.submit("AAA", "BUY", 9.95, 1000, 2.1, bracket=False)["ok"])
        self.assertFalse(tr.submit("AAA", "BUY", 9.95, 1000, 2.2, bracket=False)["ok"])

    def test_feed_and_clicks_on_two_threads_never_deadlock(self):
        import threading
        e, tr, gate, broker = sim_setup(max_orders_per_minute=100000, max_position_shares=10 ** 7)
        gate.arm(True)
        stop = threading.Event()

        def feed():
            t = 3.0
            while not stop.is_set():
                t += 0.001
                e.on_print("AAA", 10.00, 100, "X", t)
        th = threading.Thread(target=feed, daemon=True); th.start()
        done = threading.Event()

        def clicks():
            for i in range(300):
                tr.submit("AAA", "BUY", 9.90, 100, 4.0 + i, bracket=False)
                tr.cancel_all("AAA", 4.0 + i)
            done.set()
        threading.Thread(target=clicks, daemon=True).start()
        ok = done.wait(20); stop.set()
        self.assertTrue(ok, "deadlock")

    def test_day_pnl_counts_a_position_carried_from_yesterday(self):
        e, tr, gate, broker = sim_setup()
        e.syms["AAA"].l1["close"] = 9.00                        # yesterday's close
        e.on_position("DU1", "AAA", 100, 8.00, 1.0)             # held overnight
        e.on_fill("X1", "AAA", "SLD", 100, 10.00, "", 2.0)
        e.on_position("DU1", "AAA", 0, 0.0, 2.1)
        self.assertAlmostEqual(e.day_pnl()["realized"], 100.0)  # 9.00 -> 10.00 on 100 shares today


class PartialProfitTests(unittest.TestCase):
    def test_partial_trims_target_then_stop_after_fill(self):
        e, tr, gate, broker = sim_setup()
        gate.arm(True)
        e.syms["AAA"].play.update(stop=9.50, target=11.0)
        tr.submit("AAA", "BUY", 10.00, 100, 2.0)
        out = tr.partial("AAA", 40, 10.50, 3.0)
        self.assertTrue(out["ok"], out)
        roles = {o["role"]: o["remaining"] for o in pend(e)}
        self.assertEqual(roles, {"stop": 100.0, "target": 60.0, "partial": 40.0})
        e.on_depth("AAA", 0, UPDATE, BID, 10.50, 500, "", 4.0)      # bid comes up: the partial fills
        self.assertEqual(broker.position("AAA"), 60)
        for t in (6.1, 8.2):
            tr.watchdog(t)
        self.assertEqual({o["role"]: o["remaining"] for o in pend(e)}, {"stop": 60.0, "target": 60.0})

    def test_partial_limits(self):
        e, tr, gate, broker = sim_setup()
        gate.arm(True)
        self.assertFalse(tr.partial("AAA", 10, 10.5, 2.0)["ok"])          # no position
        tr.submit("AAA", "BUY", 10.00, 100, 2.0, bracket=False)
        self.assertIn("whole position", tr.partial("AAA", 100, 10.5, 3.0)["reason"])
        gate.arm(False)
        self.assertTrue(tr.partial("AAA", 30, 10.5, 3.1)["ok"])           # works disarmed, like close
        out = tr.partial("AAA", 80, 10.6, 3.2)                             # only 70 left to take
        self.assertTrue(out["ok"]); self.assertIn("70", out["sent"])


class BreakevenTests(unittest.TestCase):
    def test_breakeven_moves_every_stop_to_the_entry(self):
        e, tr, gate, broker = sim_setup()
        gate.arm(True)
        e.syms["AAA"].play.update(stop=9.50, target=11.0)
        tr.scale = True
        e.syms["AAA"].play.update(target=10.60)
        tr.submit("AAA", "BUY", 10.00, 100, 2.0)
        e.on_depth("AAA", 0, UPDATE, BID, 10.20, 500, "", 3.0)
        e.on_depth("AAA", 0, UPDATE, ASK, 10.21, 500, "", 3.0)
        e.on_l1("AAA", "last", 10.20, 3.0)
        gate.arm(False)                                   # protective: works disarmed
        out = tr.breakeven("AAA", 4.0)
        self.assertTrue(out["ok"], out)
        stops = [o for o in pend(e) if o["role"] == "stop"]
        self.assertTrue(stops and all(o["aux"] == 10.00 for o in stops))

    def test_breakeven_refused_when_price_is_through_the_entry(self):
        e, tr, gate, broker = sim_setup()
        gate.arm(True)
        e.syms["AAA"].play.update(stop=9.50, target=11.0)
        tr.submit("AAA", "BUY", 10.00, 100, 2.0)
        e.on_depth("AAA", 0, UPDATE, BID, 9.80, 500, "", 3.0)
        e.on_l1("AAA", "last", 9.80, 3.0)
        out = tr.breakeven("AAA", 4.0)
        self.assertFalse(out["ok"])
        self.assertIn("below your entry", out["reason"])


    def test_breakeven_leaves_one_set_of_stops_covering_the_position(self):
        e, tr, gate, broker = sim_setup(max_orders_per_minute=100)
        gate.arm(True)
        e.syms["AAA"].play.update(stop=9.50, target=11.0)
        tr.submit("AAA", "BUY", 10.00, 100, 2.0)                                       # bracket stop 100
        tr.submit("AAA", "SELL", 9.40, 100, 2.1, bracket=False, order_type="STP LMT", aux=9.45)   # a hand-placed stop
        tr.submit("AAA", "BUY", 10.60, 100, 2.2, bracket=False, order_type="STP LMT", aux=10.55)  # a buy-stop add-on
        e.on_depth("AAA", 0, UPDATE, BID, 10.20, 500, "", 3.0); e.on_l1("AAA", "last", 10.20, 3.0)
        out = tr.breakeven("AAA", 4.0)
        self.assertTrue(out["ok"], out); self.assertEqual(out["cancelled"], 2)
        stops = [o for o in pend(e) if o.get("type") in ("STP LMT", "STP") or o["role"] == "stop"]
        self.assertEqual([(o["role"], o["remaining"], o["aux"]) for o in stops], [("stop", 100.0, 10.0)])


class LockedCloseTests(unittest.TestCase):
    """Getting OUT is never blocked: with the day-loss lock on, a ticket SELL that takes the long down goes out as
    a close; a SELL bigger than the position (a flip) and a fresh BUY stay blocked."""

    def test_ticket_sell_closes_while_locked(self):
        e, tr, gate, broker = sim_setup()
        gate.arm(True)
        tr.submit("AAA", "BUY", 10.00, 100, 1.0, False)      # marketable at the 10.00 offer
        self.assertEqual(broker.position("AAA"), 100)
        gate.lock_out("daily loss limit hit (test)")
        blocked = tr.submit("AAA", "BUY", 10.00, 100, 2.0, False)
        self.assertFalse(blocked["ok"]); self.assertIn("LOCKED", blocked["reason"])
        flip = tr.submit("AAA", "SELL", 9.99, 150, 2.1, False)
        self.assertFalse(flip["ok"]); self.assertIn("would close them and open", flip["reason"])   # never a flip by accident
        out = tr.submit("AAA", "SELL", 9.99, 60, 2.2, False, "LMT", None, "DAY", "n-close")
        self.assertTrue(out["ok"], out); self.assertIn("close", out["sent"])
        self.assertEqual(broker.position("AAA"), 40)          # bid 9.99: filled at once
        again = tr.submit("AAA", "SELL", 9.99, 60, 2.3, False, "LMT", None, "DAY", "n-close")
        self.assertTrue(again.get("duplicate"))
        rest = tr.submit("AAA", "SELL", 9.99, 40, 2.4, False)
        self.assertTrue(rest["ok"]); self.assertEqual(broker.position("AAA"), 0)
        self.assertTrue(tr.flatten("AAA", 3.0)["flat"])
