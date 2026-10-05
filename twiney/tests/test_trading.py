import unittest

from helpers import ASK, BID, INSERT, UPDATE, cfg, plays
from twiney.engine import Engine
from twiney.trading import SimBroker, Trader, TradingGate, bracket_legs


def sim_setup(**trading):
    # the fixture play carries a 2nd entry: the auto entry stays off unless a test asks for it
    trading.setdefault("auto_second_entry", False)
    c = cfg(trading=trading)
    e = Engine(plays(), c)
    e.on_connection("DEMO", "", 0.0)
    gate = TradingGate(c)
    gate.set_sim()
    broker = SimBroker(e)
    e.sim_broker = broker
    tr = Trader(e, c, broker, gate)
    e.trader = tr
    e.apply_slot("AAA", True, 0.0)
    for i in range(3):
        e.on_depth("AAA", i, INSERT, BID, round(9.99 - i * 0.01, 2), 500, "", 1.0)
        e.on_depth("AAA", i, INSERT, ASK, round(10.00 + i * 0.01, 2), 500, "", 1.0)
    e.on_l1("AAA", "last", 10.0, 1.0)
    return e, tr, gate, broker


class BracketTests(unittest.TestCase):
    def test_legs_from_play(self):
        play = {"stop": 9.5, "target": 11.0}
        legs = bracket_legs(play, "BUY", 100, 10.0)
        self.assertEqual([(l["role"], l["type"], l["action"]) for l in legs],
                         [("stop", "STP LMT", "SELL"), ("target", "LMT", "SELL")])
        self.assertEqual((legs[0]["aux"], legs[0]["price"]), (9.5, 9.4))  # stop-limit: trigger 9.50, limit 10 ticks through
        # a stop on the wrong side of the entry is dropped rather than sent
        self.assertEqual([l["role"] for l in bracket_legs({"stop": 10.5, "target": 11.0}, "BUY", 1, 10.0)],
                         ["target"])
        self.assertEqual(bracket_legs({}, "BUY", 1, 10.0), [])


class SimTradingTests(unittest.TestCase):
    def test_disarmed_blocks_everything(self):
        e, tr, gate, broker = sim_setup()
        out = tr.submit("AAA", "BUY", 9.99, 100, 2.0)
        self.assertFalse(out["ok"])
        self.assertIn("DISARMED", out["reason"])
        self.assertEqual(broker.orders, {})

    def test_limit_rests_then_fills_and_bracket_manages_exit(self):
        e, tr, gate, broker = sim_setup()
        e.syms["AAA"].play.update(stop=9.90, target=10.20)
        gate.arm(True)
        out = tr.submit("AAA", "BUY", 9.99, 100, 2.0)
        self.assertTrue(out["ok"], out)
        self.assertIn("stop 9.90", out["sent"])
        pend = e.snapshot(2.5)["account"]["pending"]
        self.assertEqual({o["role"] for o in pend}, {"entry", "stop", "target"})
        self.assertEqual([o["status"] for o in pend if o["role"] == "entry"], ["Submitted"])
        # offer drops to 9.99 -> entry fills at its limit
        e.on_depth("AAA", 0, UPDATE, ASK, 9.99, 300, "", 3.0)
        self.assertEqual(broker.position("AAA"), 100)
        snap = e.snapshot(3.5)
        self.assertEqual(snap["account"]["fills"][0]["side"], "BOT")
        pane = snap["panes"][0]
        self.assertEqual(pane["position"]["qty"], 100)
        roles = {o["role"]: o["status"] for o in pane["orders"]}
        self.assertEqual(roles, {"stop": "Submitted", "target": "Submitted"})
        # price runs to target: target fills, stop is cancelled (OCO)
        e.on_depth("AAA", 0, UPDATE, BID, 10.20, 300, "", 4.0)
        self.assertEqual(broker.position("AAA"), 0)
        self.assertEqual(e.snapshot(4.5)["account"]["pending"], [])

    def test_stop_leg_triggers_on_last_print(self):
        e, tr, gate, broker = sim_setup()
        e.syms["AAA"].play.update(stop=9.90, target=10.20)
        gate.arm(True)
        tr.submit("AAA", "BUY", 9.99, 100, 2.0)
        e.on_depth("AAA", 0, UPDATE, ASK, 9.99, 300, "", 3.0)
        e.on_print("AAA", 9.89, 200, "X", 4.0)
        self.assertEqual(broker.position("AAA"), 0)
        self.assertEqual(e.snapshot(4.5)["account"]["pending"], [])

    def test_cancel_and_cancel_all(self):
        e, tr, gate, broker = sim_setup()
        gate.arm(True)
        a = tr.submit("AAA", "BUY", 9.90, 100, 2.0, bracket=False)["id"]
        tr.submit("AAA", "BUY", 9.80, 100, 2.1, bracket=False)
        self.assertTrue(tr.cancel(a, 3.0)["ok"])
        self.assertEqual(len(e._pending("AAA")), 1)
        self.assertEqual(tr.cancel_all("AAA", 3.5)["cancelled"], 1)
        self.assertEqual(e._pending("AAA"), [])

    def test_flatten_uses_marketable_limit_and_clears_working_orders(self):
        e, tr, gate, broker = sim_setup()
        gate.arm(True)
        tr.submit("AAA", "BUY", 10.00, 100, 2.0, bracket=False)   # lifts the offer at once
        self.assertEqual(broker.position("AAA"), 100)
        tr.submit("AAA", "SELL", 10.50, 100, 2.5, bracket=False)  # a resting target
        out = tr.flatten("AAA", 3.0)
        self.assertTrue(out["ok"])
        self.assertEqual(broker.position("AAA"), 0)
        self.assertEqual(e._pending("AAA"), [])

    def test_close_and_add_from_positions_panel(self):
        e, tr, gate, broker = sim_setup()
        gate.arm(True)
        tr.submit("AAA", "BUY", 10.00, 100, 2.0, bracket=False)     # long 100
        self.assertEqual(broker.position("AAA"), 100)
        out = tr.adjust("AAA", 10, "add", 3.0)                       # buys 10 at the ask
        self.assertTrue(out["ok"], out)
        self.assertIn("BUY 10 AAA @ 10.00", out["sent"])
        self.assertEqual(broker.position("AAA"), 110)
        out = tr.adjust("AAA", 5, "close", 4.0)                      # sells 5 at the bid
        self.assertIn("SELL 5 AAA @ 9.99", out["sent"])
        self.assertEqual(broker.position("AAA"), 105)
        out = tr.adjust("AAA", 500, "close", 5.0)                    # never closes more than you have
        self.assertIn("SELL 105 AAA", out["sent"])
        self.assertEqual(broker.position("AAA"), 0)
        self.assertFalse(tr.adjust("AAA", 1, "close", 6.0)["ok"])    # flat: nothing to close
        gate.arm(False)
        self.assertFalse(tr.adjust("AAA", 1, "add", 7.0)["ok"])      # disarmed: blocked by the gate

    def test_move_a_working_order(self):
        e, tr, gate, broker = sim_setup()
        gate.arm(True)
        oid = tr.submit("AAA", "BUY", 9.90, 100, 2.0, bracket=False)["id"]
        out = tr.modify(oid, 9.95, 3.0)
        self.assertTrue(out["ok"], out)
        self.assertEqual(e._pending("AAA")[0]["lmt"], 9.95)
        self.assertIn("cap", tr.modify(oid, 9999.0, 4.0)["reason"])          # gate still applies
        tr.modify(oid, 10.00, 5.0)                                             # moved onto the offer: fills
        self.assertEqual(broker.position("AAA"), 100)
        self.assertFalse(tr.modify(oid, 9.0, 6.0)["ok"])                       # filled orders can't move

    def test_max_position_cap(self):
        e, tr, gate, broker = sim_setup(max_position_shares=150)
        gate.arm(True)
        self.assertTrue(tr.submit("AAA", "BUY", 10.00, 100, 2.0, bracket=False)["ok"])
        out = tr.submit("AAA", "BUY", 10.00, 100, 3.0, bracket=False)
        self.assertFalse(out["ok"])
        self.assertIn("cap is 150", out["reason"])
        self.assertTrue(tr.submit("AAA", "SELL", 9.99, 100, 4.0, bracket=False)["ok"])  # reducing is always fine

    def test_paper_never_locks_and_an_old_lock_lifts(self):
        e, tr, gate, broker = sim_setup(max_daily_loss=50)                 # default: the lock guards LIVE only
        gate.arm(True)
        tr.submit("AAA", "BUY", 10.00, 100, 2.0, bracket=False)
        e.on_depth("AAA", 0, UPDATE, BID, 9.40, 500, "", 3.0)
        e.on_l1("AAA", "bid", 9.40, 3.0); e.on_l1("AAA", "last", 9.40, 3.0)
        tr.watchdog(4.0)
        self.assertIsNone(gate.locked); self.assertTrue(gate.armed)          # practice / paper: down $60, still trading
        gate.lock_out("daily loss limit hit ($60.00 against a $50.00 limit)")  # a lock from an older build
        tr.watchdog(5.0)
        self.assertIsNone(gate.locked)                                      # lifted by itself
        self.assertTrue(gate.arm(True))
        self.assertFalse(tr.snapshot(run_watchdog=False)["loss_lock_on"])

    def test_daily_loss_locks_trading_for_the_session(self):
        e, tr, gate, broker = sim_setup(max_daily_loss=50, loss_limit_live_only=False)
        gate.arm(True)
        tr.submit("AAA", "BUY", 10.00, 100, 2.0, bracket=False)     # long 100 @ 10.00
        e.on_depth("AAA", 0, UPDATE, BID, 9.40, 500, "", 3.0)         # market drops: open loss $60
        e.on_depth("AAA", 0, UPDATE, ASK, 9.41, 500, "", 3.0)
        e.on_l1("AAA", "last", 9.40, 3.0)
        tr.watchdog(4.0)                                               # the dashboard runs it before each snapshot
        snap = e.snapshot(4.0)["trading"]
        self.assertLessEqual(snap["pnl"]["total"], -50)
        self.assertFalse(snap["armed"])
        self.assertIn("LOCKED", snap["why_not"])
        self.assertFalse(gate.arm(True))                                # cannot re-arm today
        self.assertFalse(tr.submit("AAA", "BUY", 9.41, 1, 5.0)["ok"])

    def test_day_pnl_realized_and_open(self):
        e, tr, gate, broker = sim_setup()
        gate.arm(True)
        tr.submit("AAA", "BUY", 10.00, 100, 2.0, bracket=False)
        tr.submit("AAA", "SELL", 9.99, 50, 3.0, bracket=False)       # realize -$0.50
        pnl = e.day_pnl()
        self.assertAlmostEqual(pnl["realized"], -0.5)
        self.assertAlmostEqual(pnl["open"], (10.0 - 10.0) * 50, places=2)

    def test_size_and_caps_reach_the_dashboard_snapshot(self):
        e, tr, gate, broker = sim_setup(default_shares=50, max_shares_per_order=75)
        self.assertTrue(tr.set_size(500))
        self.assertEqual(tr.default_shares, 75)
        s = e.snapshot(1.0)["trading"]
        self.assertEqual((s["mode"], s["armed"], s["default_shares"]), ("SIM", False, 75))
        self.assertIn("DISARMED", s["why_not"])

    def test_orders_are_recorded_for_replay_audit(self):
        rec = []
        e, tr, gate, broker = sim_setup()
        e.recorder = type("R", (), {"write": staticmethod(rec.append), "path": "x"})()
        gate.arm(True)
        tr.submit("AAA", "SELL", 10.01, 100, 2.0, bracket=False)
        self.assertTrue(any(ev.get("ev") == "order" and ev["action"] == "SELL" for ev in rec))


if __name__ == "__main__":
    unittest.main()


class PS60ExitTests(unittest.TestCase):
    def test_cash_flow_legs_runner_and_breakeven_stop(self):
        e, tr, gate, broker = sim_setup()
        e.syms["AAA"].play.update(stop=9.90, target=10.60)
        gate.arm(True)
        tr.scale = True
        out = tr.submit("AAA", "BUY", 9.99, 100, 2.0)
        self.assertTrue(out["ok"], out)
        self.assertIn("cash flow 1 50 @ 10.49", out["sent"])
        self.assertIn("runner 25 @ 10.60", out["sent"])
        e.on_depth("AAA", 0, UPDATE, ASK, 9.99, 300, "", 3.0)   # entry fills
        orders = e.snapshot(3.5)["panes"][0]["orders"]
        # every exit piece has its own stop for the same shares: 50 + 25 + 25 covers the 100
        self.assertEqual(sorted(o["qty"] for o in orders if o["role"] == "stop"), [25.0, 25.0, 50.0])
        self.assertEqual({o["role"]: o["qty"] for o in orders if o["role"] != "stop"},
                         {"cash_flow_1": 50.0, "cash_flow_2": 25.0, "runner": 25.0})
        # first cash flow fills: its stop goes with it, the other pieces stay, and their stops move to breakeven
        e.on_depth("AAA", 0, UPDATE, BID, 10.49, 300, "", 4.0)
        self.assertEqual(broker.position("AAA"), 50)
        tr.watchdog(4.1)
        orders = e.snapshot(4.5)["panes"][0]["orders"]
        self.assertEqual(sorted((o["role"], o["qty"]) for o in orders),
                         [("cash_flow_2", 25.0), ("runner", 25.0), ("stop", 25.0), ("stop", 25.0)])
        self.assertEqual({o["price"] for o in orders if o["role"] == "stop"}, {9.99})
        self.assertTrue(any("breakeven" in m["text"] for m in e.snapshot(4.5)["messages"]))
        # stop-limit: last trades through 9.99, the stop becomes a limit and fills
        e.on_print("AAA", 9.98, 100, "X", 5.0)
        e.on_depth("AAA", 0, UPDATE, BID, 9.98, 300, "", 5.1)
        self.assertEqual(broker.position("AAA"), 0)
        self.assertEqual(e.snapshot(5.5)["account"]["pending"], [])


class TicketTests(unittest.TestCase):
    def test_nonce_blocks_double_submit_and_stop_limit_entry(self):
        e, tr, gate, broker = sim_setup()
        gate.arm(True)
        a = tr.submit("AAA", "BUY", 9.99, 100, 2.0, False, "LMT", None, "DAY", "n1")
        b = tr.submit("AAA", "BUY", 9.99, 100, 2.1, False, "LMT", None, "DAY", "n1")   # the same click twice
        self.assertTrue(a["ok"]); self.assertTrue(b.get("duplicate")); self.assertEqual(a["id"], b["id"])
        self.assertEqual(len([o for o in broker.orders.values()]), 1)
        # stop-limit entry: trigger 10.20, limit 10.25
        c = tr.submit("AAA", "BUY", 10.25, 100, 3.0, False, "STP LMT", 10.20, "DAY", "n2")
        self.assertTrue(c["ok"], c); self.assertIn("STP LMT stop 10.20", c["sent"])
        # market stays off by default
        m = tr.submit("AAA", "BUY", None, 100, 4.0, False, "MKT", None, "DAY", "n3")
        self.assertFalse(m["ok"]); self.assertIn("LIMIT", m["reason"])
        # order states as the trader sees them
        snap = e.snapshot(4.5)["account"]
        self.assertEqual({o["state"] for o in snap["pending"]}, {"ACKNOWLEDGED"})
        self.assertEqual(e.order_state({"status": "PendingCancel"}), "CANCEL PENDING")
        self.assertEqual(e.order_state({"status": "Submitted", "filled": 40.0, "remaining": 60.0}), "PARTIALLY FILLED")
        self.assertEqual(e.order_state({"status": "Inactive"}), "REJECTED")


class AutoSecondEntryTests(unittest.TestCase):
    """The 2nd entry drawn on the chart is an automatic entry: a stop-limit through it with the play's stop and
    target attached, sized from the risk dollars, placed while ARMED, one entry per drawn level."""

    def _ready(self):
        e, tr, gate, broker = sim_setup(auto_second_entry=True)
        e.syms["AAA"].play.update(second_entry=10.10, stop=9.90, target=10.50)
        tr.risk_dollars = 100          # $0.20 risk/share -> 500 shares (the per-order cap)
        return e, tr, gate, broker

    def _entries(self, e, sym="AAA"):
        return [o for o in e._pending(sym) if o.get("role") == "entry"]

    def test_disarmed_waits_and_says_why(self):
        e, tr, gate, broker = self._ready()
        tr.watchdog(2.0)
        self.assertEqual(self._entries(e), [])
        st = tr.auto_status()["AAA"]
        self.assertEqual(st["state"], "WAITING")
        self.assertIn("DISARMED", st["text"])

    def test_armed_places_stop_limit_through_the_second_entry_with_bracket(self):
        e, tr, gate, broker = self._ready()
        gate.arm(True)
        tr.watchdog(2.0)
        ent = self._entries(e)
        self.assertEqual(len(ent), 1)
        o = ent[0]
        self.assertEqual((o["action"], o["type"], o["aux"], o["lmt"], o["qty"]), ("BUY", "STP LMT", 10.10, 10.20, 500.0))
        self.assertEqual({x["role"] for x in e._pending("AAA")}, {"entry", "stop", "target"})
        self.assertEqual(tr.auto_status()["AAA"]["state"], "WORKING")
        # the watchdog running again does not send a second one
        tr.watchdog(2.5)
        self.assertEqual(len(self._entries(e)), 1)
        # price comes through the 2nd entry: the entry fills, stop and target go live, no re-entry
        e.on_print("AAA", 10.12, 200, "X", 3.0)
        self.assertEqual(broker.position("AAA"), 500)
        tr.watchdog(3.5)
        self.assertEqual({x["role"] for x in e._pending("AAA")}, {"stop", "target"})
        self.assertEqual(tr.auto_status()["AAA"]["state"], "DONE")
        # flat again: the same drawn level does not enter twice
        tr.flatten("AAA", 4.0)
        e.on_depth("AAA", 0, UPDATE, BID, 10.12, 900, "", 4.1)
        tr.watchdog(4.5)
        self.assertEqual(self._entries(e), [])
        # redraw the 2nd entry: armed again
        e.set_play_level("AAA", "second_entry", 10.20, 5.0)
        tr.watchdog(5.5)
        self.assertEqual([o["aux"] for o in self._entries(e)], [10.20])

    def test_level_change_replaces_and_clearing_or_disarming_cancels(self):
        e, tr, gate, broker = self._ready()
        gate.arm(True)
        tr.watchdog(2.0)
        first = self._entries(e)[0]["order_id"]
        e.set_play_level("AAA", "stop", 9.95, 2.5)          # $0.15 risk -> 500 still (cap); stop leg must follow
        tr.watchdog(3.0)
        ent = self._entries(e)
        self.assertEqual(len(ent), 1)
        self.assertNotEqual(ent[0]["order_id"], first)
        stops = [o for o in e._pending("AAA") if o["role"] == "stop"]
        self.assertEqual([s["aux"] for s in stops], [9.95])
        gate.arm(False)
        tr.watchdog(3.5)
        self.assertEqual(e._pending("AAA"), [])
        gate.arm(True)
        e.set_play_level("AAA", "second_entry", None, 4.0)
        tr.watchdog(4.5)
        self.assertEqual(e._pending("AAA"), [])
        self.assertIn("2nd entry", tr.auto_status()["AAA"]["text"])

    def test_price_above_the_level_waits_then_goes_in_as_a_stop_limit(self):
        e, tr, gate, broker = self._ready()
        gate.arm(True)
        def quote(bid, t):
            for i in range(3):
                e.on_depth("AAA", i, UPDATE, BID, round(bid - i * 0.01, 2), 500, "", t)
                e.on_depth("AAA", i, UPDATE, ASK, round(bid + 0.01 + i * 0.01, 2), 500, "", t)
            e.on_l1("AAA", "last", bid + 0.01, t)
        quote(10.29, 1.5)                                    # the market is above the 2nd entry
        tr.watchdog(2.0)
        self.assertEqual(self._entries(e), [])               # no limit on the pullback: nothing yet
        self.assertIn("back under", tr.auto_status()["AAA"]["text"])
        quote(10.04, 2.5)                                    # back under the level
        tr.watchdog(3.0)
        self.assertEqual([(o["type"], o["aux"]) for o in self._entries(e)], [("STP LMT", 10.10)])
        self.assertEqual(broker.position("AAA"), 0)          # not filled on the way down
        e.on_print("AAA", 10.11, 200, "X", 3.5)              # comes back up through it: filled
        self.assertEqual(broker.position("AAA"), 500)

    def test_lines_become_orders_as_they_are_drawn(self):
        """2nd entry first (ticket size, no legs yet), then the target joins, then the stop joins and sizes it."""
        e, tr, gate, broker = sim_setup(auto_second_entry=True, default_shares=100)
        tr.risk_dollars = 50
        gate.arm(True)
        p = e.syms["AAA"].play
        p.update(second_entry=None, stop=None, target=None)
        tr.watchdog(1.5)
        self.assertEqual(self._entries(e), [])
        e.set_play_level("AAA", "second_entry", 10.10, 2.0)
        tr.watchdog(2.1)
        self.assertEqual([(o["type"], o["aux"], o["qty"]) for o in e._pending("AAA")], [("STP LMT", 10.10, 100.0)])
        e.set_play_level("AAA", "target", 10.50, 2.5)
        tr.watchdog(2.6)
        self.assertEqual(sorted(o["role"] for o in e._pending("AAA")), ["entry", "target"])
        e.set_play_level("AAA", "stop", 9.90, 3.0)
        tr.watchdog(3.1)
        pend = e._pending("AAA")
        self.assertEqual(sorted(o["role"] for o in pend), ["entry", "stop", "target"])
        self.assertEqual([o["qty"] for o in pend if o["role"] == "entry"], [250.0])   # $50 / $0.20

    def test_stop_and_target_drawn_after_the_fill_go_in_and_follow_the_line(self):
        e, tr, gate, broker = sim_setup(auto_second_entry=True, default_shares=100)
        gate.arm(True)
        e.syms["AAA"].play.update(second_entry=None, stop=None, target=None)
        e.set_play_level("AAA", "second_entry", 10.10, 1.0)
        tr.watchdog(1.1)
        e.on_print("AAA", 10.12, 200, "X", 1.5)              # through the level: filled, nothing protecting it yet
        self.assertEqual(broker.position("AAA"), 100)
        tr.watchdog(1.6)
        self.assertEqual(e._pending("AAA"), [])
        e.set_play_level("AAA", "stop", 9.95, 2.0)
        tr.watchdog(2.1)
        stops = [o for o in e._pending("AAA") if o["role"] == "stop"]
        self.assertEqual([(s["action"], s["aux"], s["qty"]) for s in stops], [("SELL", 9.95, 100.0)])
        e.set_play_level("AAA", "stop", 10.00, 2.5)          # drag the line: the order moves with it
        tr.watchdog(2.6)
        self.assertEqual([o["aux"] for o in e._pending("AAA") if o["role"] == "stop"], [10.00])
        e.set_play_level("AAA", "target", 10.60, 3.0)
        tr.watchdog(3.1)
        self.assertEqual([(o["type"], o["lmt"]) for o in e._pending("AAA") if o["role"] == "target"], [("LMT", 10.60)])
        e.set_play_level("AAA", "stop", None, 3.5)            # clearing the line never pulls the stop
        tr.watchdog(3.6)
        self.assertEqual(len([o for o in e._pending("AAA") if o["role"] == "stop"]), 1)

    def test_hand_cancel_switches_the_play_off_until_redrawn(self):
        e, tr, gate, broker = self._ready()
        gate.arm(True)
        tr.watchdog(2.0)
        oid = self._entries(e)[0]["order_id"]
        tr.cancel(oid, 2.5)
        tr.watchdog(3.0)
        self.assertEqual(self._entries(e), [])
        self.assertFalse(e.syms["AAA"].play["auto"])
        self.assertEqual(tr.auto_status()["AAA"]["state"], "OFF")
        tr.set_auto(True, "AAA", 3.5)
        self.assertEqual(len(self._entries(e)), 1)

    def test_manual_position_keeps_the_auto_entry_out(self):
        e, tr, gate, broker = self._ready()
        gate.arm(True)
        tr.submit("AAA", "BUY", 10.00, 100, 1.5, False)     # marketable: fills at the offer
        self.assertEqual(broker.position("AAA"), 100)
        tr.watchdog(2.0)
        self.assertEqual(self._entries(e), [])
        self.assertIn("long 100", tr.auto_status()["AAA"]["text"])


class AutoEntryFillTests(unittest.TestCase):
    """The entry fills when price goes through the 2nd entry, even on a fast print; a cross with no order is said."""

    def test_fast_print_through_the_level_still_fills(self):
        e, tr, gate, broker = sim_setup(auto_second_entry=True)
        e.syms["AAA"].play.update(second_entry=10.10, stop=9.90, target=10.50)
        tr.risk_dollars = 100
        gate.arm(True)
        tr.watchdog(2.0)
        o = [x for x in e._pending("AAA") if x["role"] == "entry"][0]
        self.assertEqual((o["aux"], o["lmt"]), (10.10, 10.20))        # cap: 10 ticks (0.3% of $10 is 3 cents)
        e.on_print("AAA", 10.18, 200, "X", 3.0)                       # 8 cents through in one print
        self.assertEqual(broker.position("AAA"), 500)

    def test_cap_scales_with_the_stock_price(self):
        e, tr, gate, broker = sim_setup()
        self.assertAlmostEqual(tr.auto_slip(242.0), 0.726)            # 0.3% of $242
        self.assertAlmostEqual(tr.auto_slip(10.0), 0.10)              # 10 ticks floor

    def test_ran_past_the_cap_is_reported(self):
        e, tr, gate, broker = sim_setup(auto_second_entry=True)
        e.syms["AAA"].play.update(second_entry=10.10, stop=9.90, target=10.50)
        tr.risk_dollars = 100
        gate.arm(True)
        tr.watchdog(2.0)
        e.on_print("AAA", 10.30, 200, "X", 3.0)                       # 20 cents through: past the cap
        tr.watchdog(3.5)
        self.assertEqual(broker.position("AAA"), 0)
        self.assertEqual(tr.auto_status()["AAA"]["state"], "TRIGGERED")
        self.assertTrue(any("ran past your cap" in l["text"] for l in tr.log))

    def test_cross_with_no_order_working_says_why(self):
        e, tr, gate, broker = sim_setup(auto_second_entry=True)
        e.syms["AAA"].play.update(second_entry=10.10, stop=9.90, target=10.50)
        tr.watchdog(2.0)                                              # DISARMED: nothing sent
        e.on_print("AAA", 10.12, 100, "X", 2.5)
        tr.watchdog(3.0)
        said = [l["text"] for l in tr.log if "NO ENTRY" in l["text"]]
        self.assertEqual(len(said), 1)
        self.assertIn("DISARMED", said[0])
        tr.watchdog(3.5)
        self.assertEqual(len([l for l in tr.log if "NO ENTRY" in l["text"]]), 1)   # once per cross


class AutoEntryLiveTests(unittest.TestCase):
    def test_part_fill_keeps_the_rest_working(self):
        """IBKR fills in pieces: the first piece is a position, but the rest of the entry must not be cancelled."""
        e, tr, gate, broker = sim_setup(auto_second_entry=True)
        e.syms["AAA"].play.update(second_entry=10.10, stop=9.90, target=10.50)
        tr.risk_dollars = 100
        gate.arm(True)
        tr.watchdog(2.0)
        oid = [o for o in e._pending("AAA") if o["role"] == "entry"][0]["order_id"]
        e.on_order(f"sim{oid}", 2.5, filled=200.0, remaining=300.0)      # 200 of 500 filled so far
        broker.pos["AAA"] = [200.0, 10.11]
        tr.watchdog(3.0)
        ent = [o for o in e._pending("AAA") if o["role"] == "entry"]
        self.assertEqual([o["order_id"] for o in ent], [oid])            # still working, not cancelled
        st = tr.auto_status()["AAA"]
        self.assertEqual(st["state"], "PARTIAL")
        self.assertIn("200 of 500 filled", st["text"])

    def test_drawing_a_second_entry_arms_the_practice_desk(self):
        e, tr, gate, broker = sim_setup(auto_second_entry=True)
        e.syms["AAA"].play.update(second_entry=None, stop=9.90, target=10.50)
        tr.watchdog(1.0)                                                  # what is on the chart at start: seen
        self.assertFalse(gate.armed)
        e.set_play_level("AAA", "second_entry", 10.10, 1.5)               # you draw it
        tr.watchdog(2.0)
        self.assertTrue(gate.armed)
        self.assertEqual(len([o for o in e._pending("AAA") if o["role"] == "entry"]), 1)

    def test_levels_already_on_the_chart_at_start_do_not_arm(self):
        e, tr, gate, broker = sim_setup(auto_second_entry=True)
        e.syms["AAA"].play.update(second_entry=10.10, stop=9.90, target=10.50)
        tr.watchdog(1.0); tr.watchdog(1.5)
        self.assertFalse(gate.armed)
        self.assertEqual(e._pending("AAA"), [])

    def test_locked_desk_is_never_armed_by_a_drawing(self):
        e, tr, gate, broker = sim_setup(auto_second_entry=True)
        tr.watchdog(1.0)
        gate.lock_out("daily loss limit hit (test)")
        e.set_play_level("AAA", "second_entry", 10.20, 1.5)
        tr.watchdog(2.0)
        self.assertFalse(gate.armed)
        self.assertEqual(e._pending("AAA"), [])


class StopEntryBracketTests(unittest.TestCase):
    def test_target_inside_the_cap_still_joins_the_entry(self):
        e, tr, gate, broker = sim_setup(auto_second_entry=True)
        e.syms["AAA"].play.update(second_entry=10.10, stop=9.95, target=10.15)   # target 5c past the level, cap 10c
        tr.risk_dollars = 100
        gate.arm(True)
        tr.watchdog(2.0)
        roles = sorted(o["role"] for o in e._pending("AAA"))
        self.assertEqual(roles, ["entry", "stop", "target"])
        self.assertEqual([o["lmt"] for o in e._pending("AAA") if o["role"] == "target"], [10.15])


class TradeOverTests(unittest.TestCase):
    def _filled(self):
        e, tr, gate, broker = sim_setup(auto_second_entry=True)
        e.syms["AAA"].play.update(second_entry=10.10, stop=9.95, target=10.50)
        tr.risk_dollars = 100
        gate.arm(True)
        tr.watchdog(2.0)
        e.on_print("AAA", 10.11, 200, "X", 3.0)
        tr.watchdog(3.5)
        self.assertEqual(broker.position("AAA"), 500)
        return e, tr, gate, broker

    def test_stopped_out_clears_the_second_entry_stop_and_target(self):
        e, tr, gate, broker = self._filled()
        tr.watchdog(4.0)
        e.on_print("AAA", 9.94, 500, "X", 5.0)                  # through the stop: out
        self.assertEqual(broker.position("AAA"), 0)
        tr.watchdog(9.0)                                         # position settled past the 5 s guard
        p = e.syms["AAA"].play
        self.assertEqual([p.get(k) for k in ("second_entry", "stop", "target")], [None, None, None])
        self.assertEqual(p["trigger"], 10.00)                   # the pivot stays
        self.assertTrue(any("stopped out" in l["text"] for l in tr.log))
        tr.watchdog(10.0)
        self.assertEqual(e._pending("AAA"), [])                  # and nothing re-enters

    def test_still_in_the_trade_keeps_the_lines(self):
        e, tr, gate, broker = self._filled()
        tr.watchdog(20.0)
        p = e.syms["AAA"].play
        self.assertEqual((p["second_entry"], p["stop"], p["target"]), (10.10, 9.95, 10.50))

    def test_filled_chip_carries_the_fill_time(self):
        e, tr, gate, broker = self._filled()
        st = tr.auto_status()["AAA"]
        self.assertEqual(st["state"], "DONE")
        self.assertEqual(st["filled_t"], 3.5)
        self.assertEqual(tr.snapshot(run_watchdog=False)["filled_chip_seconds"], 90.0)


class DollarCapSizingTests(unittest.TestCase):
    def test_tight_stop_on_a_pricey_stock_is_capped_at_the_limit_price(self):
        """AAPL-like: 2nd entry 120.95, stop 120.86 — risk sizes to the share cap, the $ cap trims it, and the trimmed
        order must pass the gate at its LIMIT (2nd entry + fill cap), not come out a few dollars over."""
        e, tr, gate, broker = sim_setup(auto_second_entry=True, max_shares_per_order=5000, max_position_shares=5000)
        e.syms["AAA"].play.update(second_entry=10.10, stop=10.09, target=10.50)
        tr.risk_dollars = 100
        tr.cfg["max_dollars_per_order"] = 25000
        gate.arm(True)
        tr.watchdog(2.0)
        ent = [o for o in e._pending("AAA") if o["role"] == "entry"]
        self.assertEqual(len(ent), 1, [l["text"] for l in tr.log][:3])
        self.assertLessEqual(ent[0]["qty"] * ent[0]["lmt"], 25000)
        self.assertEqual(ent[0]["qty"], int(25000 // 10.20))
