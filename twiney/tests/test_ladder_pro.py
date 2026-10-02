"""The professional ladder: instrument ticks, order-flow engine, bracket templates, reverse, cancel a side,
error categories, the PS60 signal interface, replay step."""
import unittest

from helpers import ASK, BID, INSERT, cfg, plays
from twiney import orderflow, prices
from twiney.engine import Engine
from twiney.ibkr import categorize
from twiney.ps60 import SignalProvider
from twiney.trading import SimBroker, Trader, TradingGate, template_legs


def sim(**trading):
    trading.setdefault("auto_second_entry", False)
    c = cfg(trading=trading)
    e = Engine(plays(), c)
    e.on_connection("DEMO", "", 0.0)
    gate = TradingGate(c); gate.set_sim(); gate.arm(True)
    broker = SimBroker(e); e.sim_broker = broker
    e.trader = Trader(e, c, broker, gate)
    e.apply_slot("AAA", True, 0.0)
    return e, e.trader


class TickSizeTests(unittest.TestCase):
    def tearDown(self):
        prices.MIN_TICKS.clear()

    def test_instrument_tick_from_contract_details(self):
        self.assertEqual(prices.tick_size(10.0), 0.01); self.assertEqual(prices.tick_size(0.5), 0.0001)
        e = Engine(plays(), cfg())
        e.on_contract("AAA", {"min_tick": 0.05, "con_id": 123, "long_name": "AAA CORP"}, 1.0)
        self.assertEqual(prices.tick_size(10.0, "AAA"), 0.05)
        self.assertEqual(e.syms["AAA"].contract["con_id"], 123)
        self.assertIn("tick 0.05", e.messages[0]["text"])
        # the ladder grids on the instrument's increment, not a penny
        e.on_connection("DEMO", "", 0.0); e.apply_slot("AAA", True, 0.0)
        e.on_depth("AAA", 0, INSERT, BID, 9.95, 500, "", 1.0); e.on_depth("AAA", 0, INSERT, ASK, 10.05, 500, "", 1.0)
        rows = e._memory_ladder(e.syms["AAA"], 2.0, {})["rows"]
        steps = sorted({round(rows[i]["price"] - rows[i + 1]["price"], 4) for i in range(len(rows) - 1)})
        self.assertEqual(steps, [0.05])
        from twiney.trading import snap
        self.assertEqual(snap(10.02, 0, "AAA"), 10.0); self.assertEqual(snap(10.02, 1, "AAA"), 10.05)


class OrderFlowTests(unittest.TestCase):
    def test_delta_windows_and_pressure_labels(self):
        now = 100.0
        prints = [{"t": now - 14 + i, "size": 1000, "side": "buy"} for i in range(10)] + [{"t": now - 3, "size": 500, "side": "sell"}]
        p = orderflow.pressure(prints, now, {})
        self.assertEqual((p["long_delta"], p["basis"]), (9500, "ESTIMATED"))
        self.assertEqual(p["state"], "BUYING PRESSURE STRONG"); self.assertEqual(p["arrow"], "↑")
        self.assertEqual(p["short_delta"], 1000 - 500)        # only the last buy print is inside 5 s
        # too few prints: QUIET, never a label from noise
        self.assertEqual(orderflow.pressure(prints[:3], now, {})["state"], "QUIET")
        # balanced
        bal = [{"t": now - i, "size": 100, "side": "buy" if i % 2 else "sell"} for i in range(12)]
        self.assertEqual(orderflow.pressure(bal, now, {})["state"], "BALANCED")
        sell = [{"t": now - i, "size": 100, "side": "sell"} for i in range(12)] + [{"t": now - 1, "size": 150, "side": "buy"}]
        self.assertEqual(orderflow.pressure(sell, now, {})["state"], "SELLING PRESSURE STRONG")

    def test_pane_carries_order_flow(self):
        e = Engine(plays(), cfg()); e.on_connection("DEMO", "", 0.0); e.apply_slot("AAA", True, 0.0)
        e.on_l1("AAA", "bid", 9.99, 1.0); e.on_l1("AAA", "ask", 10.0, 1.0)
        for i in range(10):
            e.on_print("AAA", 10.0, 1000, "X", 1.0 + i)
        pane = next(x for x in e.snapshot(11.0)["panes"] if x and x["symbol"] == "AAA")
        self.assertEqual(pane["orderflow"]["state"], "BUYING PRESSURE STRONG")
        self.assertEqual(pane["orderflow"]["basis"], "ESTIMATED")


class BracketTemplateTests(unittest.TestCase):
    def test_template_legs_from_the_entry(self):
        tpl = {"stop": 0.25, "targets": [{"offset": 0.25, "pct": 34}, {"offset": 0.50, "pct": 33}, {"offset": 0.75, "pct": 33}]}
        legs = template_legs(tpl, "BUY", 100, 10.00, 10)
        tg = [l for l in legs if l["role"].startswith("target")]
        self.assertEqual([(l["role"], l["qty"], l["price"]) for l in tg], [("target_1", 34, 10.25), ("target_2", 33, 10.5), ("target_3", 33, 10.75)])
        stops = [l for l in legs if l["role"] == "stop"]
        self.assertEqual(sum(l["qty"] for l in stops), 100); self.assertTrue(all(l["aux"] == 9.75 and l["price"] == 9.65 for l in stops))
        self.assertEqual({l["oca"] for l in stops}, {l["oca"] for l in tg})     # every target paired with its own stop
        short = template_legs(tpl, "SELL", 50, 10.00, 10)
        self.assertEqual([l["price"] for l in short if l["role"].startswith("target")], [9.75, 9.5, 9.25])
        self.assertEqual(short[0]["aux"], 10.25)

    def test_trader_uses_the_picked_template(self):
        e, tr = sim(bracket=True)
        self.assertEqual(tr.set_bracket_template("QUARTERS"), {"ok": True, "template": "QUARTERS"})
        self.assertFalse(tr.set_bracket_template("NOPE")["ok"])
        e.on_l1("AAA", "bid", 9.99, 1.0); e.on_l1("AAA", "ask", 10.0, 1.0); e.tick(1.0)
        out = tr.submit("AAA", "BUY", 10.0, 100, 2.0)
        self.assertTrue(out["ok"], out)
        roles = sorted(o["role"] for o in e._pending("AAA")) + sorted(o["role"] for o in e.orders.values() if o.get("status") == "Filled")
        self.assertIn("target_1", roles); self.assertIn("target_3", roles); self.assertIn("stop", roles)
        self.assertIn("QUARTERS", e.trader.snapshot()["bracket_templates"]); self.assertEqual(e.trader.snapshot()["bracket_template"], "QUARTERS")


class ReverseAndCancelSideTests(unittest.TestCase):
    def test_reverse_closes_then_opens_the_other_way(self):
        e, tr = sim()
        e.on_l1("AAA", "bid", 9.99, 1.0); e.on_l1("AAA", "ask", 10.0, 1.0); e.tick(1.0)
        self.assertFalse(tr.reverse("AAA", 1.5)["ok"])                       # flat: nothing to reverse
        self.assertTrue(tr.submit("AAA", "BUY", 10.0, 100, 2.0)["ok"])
        self.assertEqual(tr.broker.position("AAA"), 100)
        out = tr.reverse("AAA", 3.0)
        self.assertTrue(out["ok"], out)
        self.assertEqual(tr.broker.position("AAA"), -100)                     # the sim fills both marketable limits
        self.assertTrue(any(o.get("role") == "reverse" for o in e.orders.values()))

    def test_cancel_one_side(self):
        e, tr = sim()
        e.on_l1("AAA", "bid", 9.99, 1.0); e.on_l1("AAA", "ask", 10.0, 1.0); e.tick(1.0)
        tr.submit("AAA", "BUY", 9.90, 100, 2.0); tr.submit("AAA", "BUY", 9.80, 100, 2.1); tr.submit("AAA", "SELL", 10.20, 100, 2.2)
        self.assertEqual(len(e._pending("AAA")), 3)
        self.assertEqual(tr.cancel_side("AAA", "bid", 3.0)["cancelled"], 2)
        left = [o for o in e._pending("AAA") if o.get("status") not in ("Cancelled", "PendingCancel")]
        self.assertEqual([o["action"] for o in left], ["SELL"])


class ErrorCategoryTests(unittest.TestCase):
    def test_every_code_lands_in_a_bucket(self):
        self.assertEqual(categorize(2104), "INFORMATION")
        self.assertEqual(categorize(1100), "CONNECTION"); self.assertEqual(categorize(504), "CONNECTION")
        self.assertEqual(categorize(10168), "PERMISSION"); self.assertEqual(categorize(354), "PERMISSION")
        self.assertEqual(categorize(201, order=True), "ORDER REJECTION"); self.assertEqual(categorize(110), "ORDER REJECTION")
        self.assertEqual(categorize(309, "depth"), "MARKET DATA"); self.assertEqual(categorize(317, "depth"), "MARKET DATA")
        self.assertEqual(categorize(501), "FATAL")
        self.assertEqual(categorize("x"), "WARNING")
        e = Engine(plays(), cfg())
        e.on_error("AAA", 10168, "no subscription", 1.0, level="error", category="PERMISSION")
        self.assertEqual(e.messages[0]["category"], "PERMISSION")


class SignalProviderTests(unittest.TestCase):
    def test_signals_come_from_the_real_play(self):
        e = Engine(plays(), cfg()); e.on_connection("DEMO", "", 0.0)
        sp = SignalProvider(e)
        self.assertFalse(sp.signals("ZZZZ")["available"])
        s = sp.signals("AAA")
        self.assertTrue(s["available"]); self.assertEqual(s["source"], "PS60")
        self.assertEqual(s["pivot"], e.syms["AAA"].play["trigger"])
        from twiney import board
        if board.side_picked(e.syms["AAA"].play):
            self.assertIn(s["direction"], ("LONG", "SHORT"))
        else:
            self.assertIsNone(s["direction"])


if __name__ == "__main__":
    unittest.main()


class OptionChainTests(unittest.TestCase):
    """Opening option positions from the desk: the chain, quotes, Greeks, the order through the gate, the fill."""
    def test_practice_chain_quotes_greeks_and_open(self):
        from twiney import options
        e, tr = sim(max_dollars_per_order=50000)
        e.on_l1("AAA", "bid", 99.99, 1.0); e.on_l1("AAA", "ask", 100.0, 1.0); e.on_l1("AAA", "last", 100.0, 1.0); e.tick(1.0)
        now = 1_800_000_000.0
        ch = e.option_chain("AAA", None, "C", now)
        self.assertTrue(ch["available"]); self.assertEqual(ch["source"], "PRACTICE")
        self.assertEqual(len(ch["expiries"]), 6); self.assertTrue(all(len(x) == 8 for x in ch["expiries"]))
        row = next(r for r in ch["rows"] if r["strike"] == 100.0)
        self.assertTrue(row["ask"] > row["bid"] >= 0); self.assertAlmostEqual(row["delta"], 0.5, delta=0.1)
        self.assertEqual(ch["right"], "C"); self.assertTrue(0 < row["dte"] < 60)
        put = next(r for r in e.option_chain("AAA", ch["expiry"], "P", now)["rows"] if r["strike"] == 100.0)
        self.assertTrue(-0.6 < put["delta"] < -0.4)
        # buy 2 calls at the ask: filled by the practice broker, position in contracts, Greeks on the row
        out = tr.opt_open("AAA", ch["expiry"], 100.0, "C", "BUY", 2, None, now)
        self.assertTrue(out["ok"], out)
        key = options.key_of("AAA", ch["expiry"], 100.0, "C")
        pos = e.opt_positions[key]
        self.assertEqual(pos["qty"], 2); self.assertAlmostEqual(pos["avg_cost"], row["ask"] * 100, places=2)
        view = e.snapshot(now)["account"]["opt_positions"][0]
        self.assertEqual(view["label"], f"AAA {ch['expiry'][4:6]}/{ch['expiry'][6:8]} 100C"); self.assertIsNotNone(view["delta"])
        # scale out one at the bid, then close
        self.assertTrue(tr.opt_adjust(key, 1, "close", None, now + 1)["ok"])
        self.assertEqual(e.opt_positions[key]["qty"], 1)
        self.assertTrue(tr.opt_adjust(key, 0, "close", None, now + 2)["ok"])
        self.assertNotIn(key, e.opt_positions)
        # the gate: dollars are real (price × 100 × contracts)
        out = tr.opt_open("AAA", ch["expiry"], 100.0, "C", "BUY", 700, None, now + 3)
        self.assertFalse(out["ok"]); self.assertIn("cap", out["reason"])
        far = ch["expiries"][-1]                                              # a dearer contract: the dollar cap
        e.option_chain("AAA", far, "C", now)
        out = tr.opt_open("AAA", far, 100.0, "C", "BUY", 400, None, now + 4)
        self.assertFalse(out["ok"]); self.assertIn("cap", out["reason"])
        self.assertFalse(tr.opt_open("AAA", "20991231", 100.0, "C", "BUY", 1, None, now)["ok"])   # not on the chain
        self.assertFalse(tr.opt_open("AAA", ch["expiry"], 100.0, "C", "BUY", 0, None, now)["ok"])

    def test_bs_sanity(self):
        from twiney import options
        c = options.bs_price(100, 100, 30, "C"); p = options.bs_price(100, 100, 30, "P")
        self.assertTrue(3 < c < 5); self.assertTrue(abs(c - p) < 0.5)
        self.assertEqual(options.bs_price(100, 90, 0, "C"), 10.0)
        g = options.bs_greeks(100, 100, 30, "C")
        self.assertTrue(0.45 < g["delta"] < 0.6); self.assertTrue(g["theta"] < 0); self.assertTrue(g["gamma"] > 0)


class LadderOrderAlignmentTests(unittest.TestCase):
    def test_stop_limit_chip_sits_at_its_trigger(self):
        e, tr = sim()
        e.on_l1("AAA", "bid", 9.99, 1.0); e.on_l1("AAA", "ask", 10.0, 1.0); e.tick(1.0)
        e.on_depth("AAA", 0, INSERT, BID, 9.99, 500, "", 1.0); e.on_depth("AAA", 0, INSERT, ASK, 10.0, 500, "", 1.0)
        out = tr.submit("AAA", "BUY", 10.15, 100, 2.0, bracket=False, order_type="STP LMT", aux=10.05)
        self.assertTrue(out["ok"], out)
        rows = e._memory_ladder(e.syms["AAA"], 3.0, {})["rows"]
        at = {r["price"]: [m["action"] for m in r["mine"]] for r in rows if r["mine"]}
        self.assertEqual(at, {10.05: ["BUY"]})                  # the trigger row, not the 10.15 limit
        out = tr.submit("AAA", "SELL", 10.08, 100, 2.5, bracket=False)
        rows = e._memory_ladder(e.syms["AAA"], 3.0, {})["rows"]
        self.assertIn(10.08, {r["price"] for r in rows if r["mine"]})     # a limit sits at its limit


class DayTrapTests(unittest.TestCase):
    """The strong morning move that reversed: everyone who paid up above here since the open is underwater."""
    def test_longs_trapped_after_a_failed_opening_drive(self):
        from twiney.ps60 import ny_day
        e = Engine(plays(), cfg(trap={"session_lean_fraction": 0.2, "session_heavy_fraction": 0.35, "session_min_move_pct": 1.0}))
        e.on_connection("DEMO", "", 0.0); e.apply_slot("AAA", True, 0.0)
        t0 = 1_800_000_000.0 + 13.5 * 3600            # a weekday morning, New York
        e.on_l1("AAA", "bid", 99.99, t0); e.on_l1("AAA", "ask", 100.0, t0)
        # the drive: buyers pay up from 100 to 103.5 over eight minutes (8,000 shares)
        for i in range(8):
            px_ = 100.0 + i * 0.5
            e.on_l1("AAA", "bid", px_ - 0.01, t0 + i * 60); e.on_l1("AAA", "ask", px_, t0 + i * 60)
            e.on_print("AAA", px_, 1000, "X", t0 + i * 60)
        # the reversal, twenty minutes after the high: sellers hit bids back down to 101 (3,000 shares)
        for i in range(3):
            px_ = 103.0 - i
            tt = t0 + 8 * 60 + 20 * 60 + i * 60
            e.on_l1("AAA", "bid", px_, tt); e.on_l1("AAA", "ask", px_ + 0.01, tt)
            e.on_print("AAA", px_, 1000, "X", tt)
        pane = next(x for x in e.snapshot(t0 + 31 * 60)["panes"] if x and x["symbol"] == "AAA")
        dt = pane["daytrap"]
        self.assertEqual(dt["state"], "LONGS TRAPPED HEAVY")
        self.assertEqual(dt["high"]["price"], 103.5)
        self.assertEqual(dt["longs"]["shares"], 5000)                 # bought at 101.5 .. 103.5, above 101
        self.assertAlmostEqual(dt["longs"]["avg"], 102.5, places=2)
        self.assertTrue(dt["longs"]["under_pct"] > 1.0)
        self.assertIn("were bought above here since the open", dt["text"]); self.assertIn("push back to 102.50", dt["text"])
        self.assertTrue(any(a["label"] == "LONGS TRAPPED HEAVY" and a["role"] == "trap" and "longs are trapped heavy" in a["words"] for a in e.alerts))
        self.assertEqual(e.syms["AAA"].day_key, ny_day(t0))
        # a new session starts the story over
        e.on_print("AAA", 101.0, 100, "X", t0 + 86400)
        self.assertEqual(len(e.syms["AAA"].day_sums), 1)


class DayTrapScenarioTests(unittest.TestCase):
    """Session shapes: a drive that reverses traps longs and their exit gets called when price returns; a gap-down
    flush that reverses traps shorts; chop inside a range and a clean trend stay quiet."""
    def _run(self, path, step=8.0):
        import random
        e = Engine(plays(), cfg()); e.on_connection("DEMO", "", 0.0); e.apply_slot("AAA", True, 0.0)
        t0 = 1_800_000_000.0 + 13.5 * 3600; t = t0; labels = []
        e.listeners.append(lambda a: labels.append(a["label"]) if a.get("role") == "trap" else None)
        for i, (px, sz, side) in enumerate(path):
            bid, ask = (px - 0.01, px) if side == "buy" else (px, px + 0.01)
            e.on_l1("AAA", "bid", bid, t); e.on_l1("AAA", "ask", ask, t); e.on_print("AAA", px, sz, "X", t); t += step
            if i % 4 == 0:
                e._day_trap_pane(e.syms["AAA"], t)
        return labels, e._day_trap_pane(e.syms["AAA"], t)

    @staticmethod
    def _drive(p0, p1, n, side):
        return [(round(p0 + (p1 - p0) * i / n, 2), 600, side) for i in range(n)]

    def test_shapes(self):
        d = self._drive
        labels, dt = self._run(d(185, 187.4, 60, "buy") + d(187.4, 186.8, 20, "sell") + d(186.8, 187.0, 10, "buy") + d(187.0, 183.0, 300, "sell") + d(183.0, 186.3, 120, "buy") + d(186.3, 184, 60, "sell"))
        self.assertEqual(labels, ["LONGS TRAPPED", "AT TRAPPED EXIT"]); self.assertEqual(dt["exit_level"]["side"], "long")
        gap = d(184, 180, 60, "sell") + d(180, 181, 10, "buy") + d(181, 180.5, 10, "sell") + d(180.5, 187, 400, "buy")
        # bad-news flush, reverse, climb, shallow pullback, close strong: the shorts stay trapped (fuel for the close),
        # the pullback does not flip the call to longs and their exit level is kept on the chart
        labels, dt = self._run(gap + d(187, 184.5, 100, "sell") + d(184.5, 186, 100, "buy"))
        self.assertEqual(labels, ["SHORTS TRAPPED"]); self.assertEqual(dt["exit_level"]["side"], "short")
        self.assertAlmostEqual(dt["exit_level"]["price"], 181.58, places=1)
        # a full retrace to the shorts' average calls their exit, and the longs from the run are trapped in turn
        labels, dt = self._run(gap + d(187, 181.5, 100, "sell") + d(181.5, 186, 100, "buy"))
        self.assertEqual(labels[:3], ["SHORTS TRAPPED", "AT TRAPPED EXIT", "LONGS TRAPPED HEAVY"])
        chop = []
        for _ in range(12):
            chop += d(100, 101.5, 15, "buy") + d(101.5, 100, 15, "sell")
        self.assertEqual(self._run(chop)[0], [])
        self.assertEqual(self._run(d(100, 108, 400, "buy"))[0], [])
