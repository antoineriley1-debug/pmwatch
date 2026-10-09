"""TRADE OVER: however a trade was opened (a ticket, the ladder, the order bar, a right-click), once it is flat its 2nd
entry, stop and target come off the chart. A contract's own stop and lines come off when it is out. Lines drawn as a
plan before any trade stay, and so does a new 2nd entry drawn after the stop-out. The stop the desk draws with a 2nd
entry goes when that 2nd entry is taken off before any trade. Option stops fire on the price update itself."""
import time
import unittest

from helpers import cfg, plays
from twiney.book import ASK, BID, INSERT, UPDATE
from twiney.engine import Engine
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


def lines(e):
    p = e.syms["AAA"].play
    return {r: p.get(r) for r in ("trigger", "second_entry", "stop", "target")}


class StockFlatTests(unittest.TestCase):
    def test_a_ticket_trade_clears_its_lines_when_flat(self):
        e, tr, broker = make()
        self.assertTrue(tr.submit("AAA", "BUY", 10.0, 100, 2.0, bracket=False)["ok"]); quote(e, 9.99, 10.00, 3.0)
        self.assertEqual(broker.position("AAA"), 100)
        e.set_play_level("AAA", "stop", 9.50, 3.5, source="chart"); e.set_play_level("AAA", "target", 11.0, 3.5, source="chart")
        tr.watchdog(4.0)
        self.assertTrue(tr.flatten("AAA", 5.0)["ok"]); quote(e, 9.99, 10.00, 5.5)
        self.assertEqual(broker.position("AAA"), 0)
        for t in (6.0, 8.0, 12.0):
            tr.watchdog(t)
        got = lines(e)
        self.assertIsNone(got["stop"]); self.assertIsNone(got["target"])
        self.assertIsNotNone(got["trigger"])                                # the pivot always stays

    def test_a_short_clears_too(self):
        e, tr, broker = make()
        self.assertTrue(tr.submit("AAA", "SELL", 9.99, 100, 2.0, bracket=False)["ok"]); quote(e, 9.99, 10.00, 3.0)
        self.assertEqual(broker.position("AAA"), -100)
        e.set_play_level("AAA", "stop", 10.50, 3.5, source="chart"); tr.watchdog(4.0)
        self.assertTrue(tr.flatten("AAA", 5.0)["ok"]); quote(e, 9.99, 10.00, 5.5)
        for t in (6.0, 12.0):
            tr.watchdog(t)
        self.assertEqual(broker.position("AAA"), 0)
        self.assertIsNone(lines(e)["stop"])

    def test_a_plan_with_no_trade_stays(self):
        e, tr, broker = make()
        e.set_play_level("AAA", "stop", 9.50, 2.0, source="chart"); e.set_play_level("AAA", "target", 11.0, 2.0, source="chart")
        for t in (3.0, 10.0, 30.0):
            tr.watchdog(t)
        self.assertEqual((lines(e)["stop"], lines(e)["target"]), (9.5, 11.0))

    def test_a_new_2nd_entry_after_the_stop_out_stays(self):
        e, tr, broker = make()
        self.assertTrue(tr.submit("AAA", "BUY", 10.0, 100, 2.0, bracket=False)["ok"]); quote(e, 9.99, 10.00, 3.0)
        e.set_play_level("AAA", "stop", 9.50, 3.5, source="chart"); tr.watchdog(4.0)
        self.assertTrue(tr.flatten("AAA", 5.0)["ok"]); quote(e, 9.99, 10.00, 5.5); tr.watchdog(6.0)
        e.set_play_level("AAA", "second_entry", 10.20, 7.0, source="setup")        # the next setup, drawn at once
        for t in (8.0, 12.0, 20.0):
            tr.watchdog(t)
        self.assertEqual(lines(e)["second_entry"], 10.2)
        self.assertNotEqual(lines(e)["stop"], 9.5)                           # the old trade's stop is off


class AutoStopTests(unittest.TestCase):
    def test_the_desk_stop_goes_with_its_2nd_entry(self):
        e, tr, broker = make()
        e.set_play_level("AAA", "second_entry", None, 1.5, source="chart")       # the test play starts with one
        e.set_play_level("AAA", "second_entry", 10.30, 2.0, source="chart")
        self.assertEqual(lines(e)["stop"], 9.3)                              # the desk drew it $1 under
        e.set_play_level("AAA", "second_entry", None, 3.0, source="chart")
        self.assertIsNone(lines(e)["stop"])

    def test_a_stop_you_moved_stays(self):
        e, tr, broker = make()
        e.set_play_level("AAA", "second_entry", None, 1.5, source="chart")
        e.set_play_level("AAA", "second_entry", 10.30, 2.0, source="chart")
        self.assertEqual(lines(e)["stop"], 9.3)
        e.set_play_level("AAA", "stop", 9.60, 2.5, source="chart")
        e.set_play_level("AAA", "second_entry", None, 3.0, source="chart")
        self.assertEqual(lines(e)["stop"], 9.6)


    def test_in_a_trade_the_stop_stays(self):
        e, tr, broker = make()
        e.set_play_level("AAA", "second_entry", None, 1.5, source="chart")
        e.set_play_level("AAA", "second_entry", 10.30, 2.0, source="chart")
        self.assertTrue(tr.submit("AAA", "BUY", 10.0, 100, 2.5, bracket=False)["ok"]); quote(e, 9.99, 10.00, 3.0)
        e.set_play_level("AAA", "second_entry", None, 4.0, source="chart")
        self.assertEqual(lines(e)["stop"], 9.3)


class OptionFlatTests(unittest.TestCase):
    def setUp(self):
        from twiney import options as _o
        self.e, self.tr, self.broker = make(); self.T = time.time()
        self.e.on_l1("AAA", "last", 10.00, self.T)
        self.exp = self.e.option_chain("AAA", None, "C", self.T)["expiry"]
        self.kc = _o.key_of("AAA", self.exp, 10, "C")

    def held(self):
        return int((self.e.opt_positions.get(self.kc) or {}).get("qty") or 0)

    def test_a_contract_closed_by_hand_drops_its_stop_and_lines(self):
        e, tr, T = self.e, self.tr, self.T
        self.assertTrue(tr.opt_open("AAA", self.exp, 10, "C", "BUY", 1, None, T)["ok"]); e.practice_opt_tick(T + 1)
        self.assertEqual(self.held(), 1)
        self.assertTrue(tr.set_opt_stop(self.kc, 9.50, "stock", T + 1)["ok"])
        bid = e.opt_quotes[self.kc]["bid"]
        self.assertTrue(tr.set_opt_level(self.kc, "target", round(bid * 3, 2), now=T + 1)["ok"])
        tr.watchdog(T + 1.5)
        self.assertTrue(tr.opt_adjust(self.kc, 0, "close", None, T + 2)["ok"]); e.practice_opt_tick(T + 2.5); e.practice_opt_tick(T + 3)
        self.assertEqual(self.held(), 0)
        for dt in (3.5, 5.0, 8.0):
            tr.watchdog(T + dt)
        self.assertNotIn(self.kc, tr.opt_stops)
        self.assertFalse((tr.opt_levels.get(self.kc) or {}).get("target"))
        self.assertNotIn(self.kc, tr.snapshot()["opt_stops"])

    def test_the_stock_chart_lines_clear_when_the_contract_is_out(self):
        e, tr, T = self.e, self.tr, self.T
        e.set_play_level("AAA", "stop", 9.50, T, source="chart")
        self.assertTrue(tr.opt_open("AAA", self.exp, 10, "C", "BUY", 1, None, T)["ok"]); e.practice_opt_tick(T + 1)
        tr.watchdog(T + 1.5)
        self.assertTrue(tr.opt_adjust(self.kc, 0, "close", None, T + 2)["ok"]); e.practice_opt_tick(T + 2.5); e.practice_opt_tick(T + 3)
        for dt in (3.5, 6.0, 9.0):
            tr.watchdog(T + dt)
        self.assertIsNone(lines(e)["stop"])

    def test_an_option_stop_fires_on_the_price_update(self):
        e, tr, T = self.e, self.tr, self.T
        self.assertTrue(tr.opt_open("AAA", self.exp, 10, "C", "BUY", 1, None, T)["ok"]); e.practice_opt_tick(T + 1)
        self.assertTrue(tr.set_opt_stop(self.kc, 9.80, "stock", T + 1)["ok"])
        e.price_evt.clear()
        e.on_l1("AAA", "last", 9.75, T + 2)
        self.assertTrue(e.price_evt.is_set())                               # the price update wakes the stop check
        tr.fast_stops(T + 2)                                                 # what the woken thread runs: no half-second wait
        self.assertIn(self.kc, tr.opt_stop_fired)
        e.practice_opt_tick(T + 2.5)
        self.assertEqual(self.held(), 0)


if __name__ == "__main__":
    unittest.main()


class ManagementTests(unittest.TestCase):
    """Taking some off shrinks the stop with it; a take-profit filling shrinks the stop; CLOSE takes everything with it;
    an order bigger than the position the other way is refused unless you said so; BE on a contract."""
    def pend(self, e):
        return sorted((o.get("role"), int(o.get("remaining") if o.get("remaining") is not None else o.get("qty"))) for o in e._pending("AAA"))

    def test_scale_out_take_profit_and_close(self):
        e, tr, broker = make(); tr.watchdog(1.5)
        tr.submit("AAA", "BUY", 10.0, 100, 2.0, bracket=False); quote(e, 9.99, 10.00, 3.0)
        e.set_play_level("AAA", "stop", 9.50, 3.5, source="chart"); e.set_play_level("AAA", "target", 11.0, 3.5, source="chart"); tr.watchdog(4.0)
        self.assertEqual(self.pend(e), [("stop", 100), ("target", 100)])
        self.assertTrue(tr.adjust("AAA", 25, "close", 5.0)["ok"]); quote(e, 9.99, 10.00, 5.2); tr.fast_stops(5.2)
        self.assertEqual(broker.position("AAA"), 75); self.assertEqual(self.pend(e), [("stop", 75), ("target", 75)])
        self.assertTrue(tr.partial("AAA", 25, 10.30, 6.0)["ok"])
        quote(e, 10.30, 10.31, 6.5); tr.fast_stops(6.5)
        self.assertEqual(broker.position("AAA"), 50); self.assertEqual(self.pend(e), [("stop", 50), ("target", 50)])
        for t in (7, 8, 10, 13):
            tr.watchdog(t)
        self.assertEqual(self.pend(e), [("stop", 50), ("target", 50)])          # never grown back
        self.assertTrue(tr.partial("AAA", 20, 10.60, 13.5)["ok"])
        self.assertTrue(tr.adjust("AAA", 50, "close", 14.0)["ok"]); quote(e, 10.30, 10.31, 14.2)
        self.assertEqual(broker.position("AAA"), 0); self.assertEqual(self.pend(e), [])

    def test_close_keeps_an_entry_you_placed(self):
        e, tr, broker = make(); tr.watchdog(1.5)
        tr.submit("AAA", "BUY", 10.0, 100, 2.0, bracket=False); quote(e, 9.99, 10.00, 3.0)
        tr.submit("AAA", "BUY", 9.00, 50, 3.1, bracket=False)                   # a resting add-on lower down
        self.assertTrue(tr.adjust("AAA", 100, "close", 4.0)["ok"]); quote(e, 9.99, 10.00, 4.2)
        self.assertEqual(broker.position("AAA"), 0); self.assertEqual([r for r, _n in self.pend(e)], ["entry"])

    def test_no_accidental_flip(self):
        e, tr, broker = make(); tr.watchdog(1.5)
        tr.submit("AAA", "BUY", 10.0, 100, 2.0, bracket=False); quote(e, 9.99, 10.00, 3.0)
        out = tr.submit("AAA", "SELL", 10.50, 200, 4.0)
        self.assertFalse(out["ok"]); self.assertIn("would close them and open 100 short", out["reason"])
        self.assertTrue(tr.submit("AAA", "SELL", 10.50, 200, 4.1, flip=True)["ok"])  # the order bar, after you said yes

    def test_breakeven_on_a_contract(self):
        import datetime, zoneinfo
        from twiney import options as _o
        e, tr, broker = make()
        T = datetime.datetime(2026, 10, 12, 11, 0, tzinfo=zoneinfo.ZoneInfo("America/New_York")).timestamp()
        e.on_l1("AAA", "last", 10.0, T)
        exp = e.option_chain("AAA", None, "C", T)["expiry"]; k = _o.key_of("AAA", exp, 10, "C")
        tr.opt_open("AAA", exp, 10, "C", "BUY", 1, None, T); e.practice_opt_tick(T + 1)
        self.assertFalse(tr.opt_breakeven(k, T + 1.5)["ok"])                     # not over what you paid yet
        e.on_l1("AAA", "last", 10.60, T + 2); e.practice_opt_tick(T + 2.5); e.practice_opt_tick(T + 3)
        out = tr.opt_breakeven(k, T + 3.5)
        self.assertTrue(out["ok"], out)
        paid = e.opt_positions[k]["avg_cost"] / (e.opt_positions[k].get("mult") or 100)
        self.assertGreaterEqual(tr.opt_stops[k]["price"], paid - 1e-9)                # never under what you paid
        self.assertLess(tr.opt_stops[k]["price"] - paid, 0.05 + 1e-9); self.assertEqual(tr.opt_stops[k]["on"], "option")


class BackupStopTests(unittest.TestCase):
    """A BACKUP STOP at IBKR on a contract you hold: placed at the contract's price where your stop is (plus a cushion),
    sized to what you hold, moved with your stop, off when you are out, and it alone gets you out with the desk off."""
    def setUp(self):
        import datetime, zoneinfo
        from twiney import options as _o
        self.e, self.tr, self.broker = make()
        self.T = datetime.datetime(2026, 10, 12, 11, 0, tzinfo=zoneinfo.ZoneInfo("America/New_York")).timestamp()
        self.e.on_l1("AAA", "last", 10.0, self.T)
        self.exp = self.e.option_chain("AAA", None, "C", self.T)["expiry"]
        self.k = _o.key_of("AAA", self.exp, 9, "C")          # in the money: a real premium to put a stop under

    def backups(self):
        return [o for o in self.e._pending(self.k) if o.get("role") == "backup_stop"]

    def held(self):
        return int((self.e.opt_positions.get(self.k) or {}).get("qty") or 0)

    def buy(self, n):
        self.assertTrue(self.tr.opt_open("AAA", self.exp, 9, "C", "BUY", n, None, self.T)["ok"]); self.e.practice_opt_tick(self.T + 1)
        self.assertEqual(self.held(), n)

    def test_placed_sized_moved_and_off(self):
        e, tr, T, k = self.e, self.tr, self.T, self.k
        self.buy(2)
        tr.watchdog(T + 1.5); self.assertEqual(self.backups(), [])                    # no stop: nothing to back up
        self.assertTrue(tr.set_opt_stop(k, 9.70, "stock", T + 2)["ok"]); tr.watchdog(T + 2.5)
        b = self.backups(); self.assertEqual(len(b), 1)
        bid = e.opt_quotes[k]["bid"]
        self.assertEqual((b[0]["action"], b[0]["type"], int(b[0]["remaining"])), ("SELL", "STP LMT", 2))
        self.assertLess(b[0]["aux"], bid)                                               # under the contract now
        trig1 = b[0]["aux"]
        # the desk's own stop is not blocked by it (it is not a close)
        self.assertEqual(tr._opt_working(k, "SELL"), 0)
        # move the stop lower: the backup follows
        tr.set_opt_stop(k, 9.40, "stock", T + 3); tr.watchdog(T + 5.5)
        self.assertLess(self.backups()[0]["aux"], trig1)
        # take one off: the backup covers the one left
        self.assertTrue(tr.opt_adjust(k, 1, "close", None, T + 6)["ok"]); e.practice_opt_tick(T + 6.5); tr.watchdog(T + 7)
        self.assertEqual(self.held(), 1); self.assertEqual(int(self.backups()[0]["remaining"]), 1)
        # out: the backup is off
        self.assertTrue(tr.opt_adjust(k, 0, "close", None, T + 8)["ok"]); e.practice_opt_tick(T + 8.5); tr.watchdog(T + 9)
        self.assertEqual(self.held(), 0); self.assertEqual(self.backups(), [])

    def test_the_backup_alone_gets_you_out_with_the_desk_off(self):
        e, tr, T, k = self.e, self.tr, self.T, self.k
        self.buy(1)
        tr.set_opt_stop(k, 9.70, "stock", T + 2); tr.watchdog(T + 2.5)
        self.assertEqual(len(self.backups()), 1)
        # the desk is off: no watchdog, no fast stops — only IBKR (the simulator) and the market
        for i, px in enumerate((9.6, 9.3, 9.0, 8.7)):
            e.on_l1("AAA", "last", px, T + 3 + i); e.practice_opt_tick(T + 3.5 + i)
        self.assertEqual(self.held(), 0)

    def test_setting_off_means_no_backup(self):
        e, tr, T, k = self.e, self.tr, self.T, self.k
        tr.cfg["option_backup_stop"] = False
        self.buy(1); tr.set_opt_stop(k, 9.70, "stock", T + 2); tr.watchdog(T + 2.5)
        self.assertEqual(self.backups(), [])


class PartialTargetTests(unittest.TestCase):
    def test_half_at_the_target_the_rest_at_breakeven(self):
        import datetime, zoneinfo
        from twiney import options as _o
        e, tr, broker = make(); tr.cfg["option_target_take_pct"] = 50; tr.cfg["option_backup_stop"] = False
        T = datetime.datetime(2026, 10, 12, 11, 0, tzinfo=zoneinfo.ZoneInfo("America/New_York")).timestamp()
        e.on_l1("AAA", "last", 10.0, T)
        exp = e.option_chain("AAA", None, "C", T)["expiry"]; k = _o.key_of("AAA", exp, 10, "C")
        tr.opt_open("AAA", exp, 10, "C", "BUY", 4, None, T); e.practice_opt_tick(T + 1)
        paid = e.opt_positions[k]["avg_cost"] / 100
        bid = e.opt_quotes[k]["bid"]
        self.assertTrue(tr.set_opt_level(k, "target", round(bid + 0.30, 2), now=T + 1)["ok"])
        tr.watchdog(T + 1.5)
        for i, px in enumerate((10.3, 10.6, 10.9, 11.2)):
            e.on_l1("AAA", "last", px, T + 2 + i); e.practice_opt_tick(T + 2.5 + i); tr.watchdog(T + 2.7 + i)
        self.assertEqual(int(e.opt_positions[k]["qty"]), 2)                            # half out, half runs
        self.assertEqual(tr.opt_stops[k]["on"], "option"); self.assertGreaterEqual(tr.opt_stops[k]["price"], paid - 1e-9)


class WalkingCallTests(unittest.TestCase):
    def test_a_walking_call_never_breaks_the_desk(self):
        """A side WALKING the price (institutional footprints) used to join raw prices and crash the whole snapshot."""
        e, tr, broker = make()
        st = e.syms["AAA"]
        v = {"walk": {"side": "SELLER", "steps": [10.05, 10.0, 9.95, 9.9], "dir": "down"}}
        try:
            e._inst_calls(st, v, 100.0, dict(e.cfg.get("inst") or {}, voice=True))
        except TypeError as exc:
            self.fail(f"walking call crashed: {exc}")
