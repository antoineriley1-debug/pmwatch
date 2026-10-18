"""THE TRADE BOT on the practice broker: it takes over, sets the stop at max pain, pays you early or gives it room,
moves to break even, trails under the 5 / 60 lows, gets out on the danger calls, and TAKE BACK stops it cold."""
import unittest

from helpers import ASK, BID, UPDATE
from test_trading import sim_setup
from twiney.tradebot import EARLY, ROOM

T0 = 1791813600.0          # Monday 2026-10-12 10:00 New York


def tape(e, sym, t_from, t_to, path):
    """Prints every 20 s from t_from to t_to, price from path(t)."""
    t = t_from
    while t < t_to:
        px = round(path(t), 2)
        e.on_depth(sym, 0, UPDATE, BID, round(px - 0.01, 2), 500, "", t)
        e.on_depth(sym, 0, UPDATE, ASK, px, 500, "", t)
        e.on_print(sym, px, 100, "X", t)
        t += 20


def setup(atr=2.0, **play):
    e, tr, gate, broker = sim_setup()
    st = e.syms["AAA"]
    st.play.update(atr=atr, auto=False, **play)
    tape(e, "AAA", T0 - 1800, T0, lambda t: 9.95 if T0 - 300 <= t < T0 - 240 else 10.00)   # the last 5-min candle's low 9.95
    gate.arm(True)
    out = tr.submit("AAA", "BUY", 10.00, 100, T0)
    assert out["ok"], out
    e.on_depth("AAA", 0, UPDATE, ASK, 10.00, 500, "", T0 + 1)
    assert broker.position("AAA") == 100
    return e, tr, gate, broker, st


class TradeBotTests(unittest.TestCase):
    def test_takes_over_with_the_stop_at_max_pain(self):
        e, tr, gate, broker, st = setup()
        tr.bot.arm("AAA", True, now=T0 + 2)
        tr.watchdog(T0 + 3)
        t = tr.bot.trades["AAA"]
        self.assertEqual(t["mode"], EARLY)                      # no long Daily consolidation in the fixture
        self.assertEqual(t["pay_at"], 0.5)                      # a quarter of a $2 ATR
        self.assertAlmostEqual(t["stop"], 9.95)                  # the prior 5-minute low
        self.assertIn("took over 100 shares LONG", t["steps"][0]["text"])

    def test_pay_yourself_early_then_break_even_then_trail_on_5(self):
        e, tr, gate, broker, st = setup()
        tr.bot.arm("AAA", True, trail=5, now=T0 + 2)
        tr.watchdog(T0 + 3)
        tape(e, "AAA", T0 + 20, T0 + 300, lambda t: 10.30)
        tape(e, "AAA", T0 + 300, T0 + 330, lambda t: 10.55)       # $0.55 your way: pay yourself
        tr.watchdog(T0 + 331)
        t = tr.bot.trades["AAA"]
        self.assertTrue(t["paid"])
        e.on_depth("AAA", 0, UPDATE, BID, 10.56, 500, "", T0 + 332)  # the partial fills
        tr.watchdog(T0 + 333)
        self.assertEqual(broker.position("AAA"), 50)
        self.assertTrue(t["be"])
        self.assertTrue(any("break even: stop 10.00" in x["text"] for x in t["steps"]), t["steps"])
        self.assertGreaterEqual(t["stop"], 10.00)               # then straight up under the last finished 5-min low
        tape(e, "AAA", T0 + 340, T0 + 900, lambda t: 10.60 if t < T0 + 600 else 10.70)   # candles with lows 10.59 / 10.69
        tr.watchdog(T0 + 901)
        self.assertGreater(t["stop"], 10.00)                     # the runner's stop came up under a finished 5-min low
        self.assertLess(t["stop"], 10.70)
        before = t["stop"]
        tape(e, "AAA", T0 + 905, T0 + 925, lambda t: round(before - 0.02, 2))
        tr.watchdog(T0 + 926)
        self.assertEqual(broker.position("AAA"), 0)              # the stop took the runner out
        self.assertNotIn("AAA", tr.bot.trades)
        self.assertTrue(any("done" in s["text"] for s in tr.bot.done[-1]["steps"]))

    def test_give_it_room_waits_for_one_atr_and_pays_near_the_mp(self):
        e, tr, gate, broker, st = setup(atr=1.0, target=13.0)
        st.daily = {T0 - 86400 * (i + 1) - 36000: [10.0, 10.5, 9.5, 10.0, 1e6] for i in range(20)}   # 20 days in a $1 range
        tr.bot.arm("AAA", True, now=T0 + 2)
        tr.watchdog(T0 + 3)
        t = tr.bot.trades["AAA"]
        self.assertEqual(t["mode"], ROOM, t["mode_why"])
        tape(e, "AAA", T0 + 20, T0 + 120, lambda t: 10.70)        # +$0.70: no pay, no break even yet
        tr.watchdog(T0 + 121)
        self.assertFalse(t["paid"] or t["be"])
        tape(e, "AAA", T0 + 140, T0 + 200, lambda t: 11.05)       # +1 ATR: break even, no pay
        tr.watchdog(T0 + 201)
        self.assertTrue(t["be"]); self.assertFalse(t["paid"])
        tape(e, "AAA", T0 + 220, T0 + 260, lambda t: 12.75)       # in the last 10% to the MP 13.00: pay
        tr.watchdog(T0 + 261)
        self.assertTrue(t["paid"])

    def test_level_lost_gets_it_out_and_no_adding_back(self):
        e, tr, gate, broker, st = setup()
        st.play["auto"] = True
        tr.bot.arm("AAA", True, now=T0 + 2)
        tr.watchdog(T0 + 3)
        e.alerts.appendleft({"t": T0 + 10, "symbol": "AAA", "label": "BUYERS TOOK · LOST", "text": "lost it", "side": "bid", "role": "level"})
        tr.watchdog(T0 + 11)
        t = tr.bot.done[-1] if not tr.bot.trades else tr.bot.trades["AAA"]
        self.assertIn("LOST", t.get("out") or "")
        self.assertFalse(st.play["auto"])
        e.on_depth("AAA", 0, UPDATE, BID, 10.00, 500, "", T0 + 12)
        tr.watchdog(T0 + 13)
        self.assertEqual(broker.position("AAA"), 0)

    def test_close_back_under_the_pivot_gets_it_out(self):
        e, tr, gate, broker, st = setup(trigger=10.00)
        tr.bot.arm("AAA", True, now=T0 + 2)
        tr.watchdog(T0 + 3)
        tape(e, "AAA", T0 + 20, T0 + 300, lambda t: 9.97)         # a 5-minute candle closes under the pivot
        tr.watchdog(T0 + 301)
        self.assertIn("pivot", (tr.bot.trades.get("AAA") or tr.bot.done[-1]).get("out") or "")

    def test_take_back_stops_it_cold(self):
        e, tr, gate, broker, st = setup()
        tr.bot.arm("AAA", True, now=T0 + 2)
        tr.watchdog(T0 + 3)
        stop = tr.bot.trades["AAA"]["stop"]
        tr.bot.arm("AAA", False, now=T0 + 4)
        self.assertNotIn("AAA", tr.bot.trades)
        tape(e, "AAA", T0 + 20, T0 + 330, lambda t: 10.60)
        tr.watchdog(T0 + 331)
        self.assertEqual(broker.position("AAA"), 100)            # nothing paid, nothing moved
        self.assertEqual(tr._side_levels(st.play).get("stop"), stop)

    def test_switch_5_to_60_mid_trade_and_the_kind_by_hand(self):
        e, tr, gate, broker, st = setup()
        tr.bot.arm("AAA", True, now=T0 + 2)
        tr.watchdog(T0 + 3)
        tr.bot.arm("AAA", True, trail=60, mode=ROOM, now=T0 + 4)
        t = tr.bot.trades["AAA"]
        self.assertEqual((t["trail"], t["mode"], t["mode_by"]), (60, ROOM, "you"))

    def test_never_acts_on_a_live_account(self):
        e, tr, gate, broker, st = setup()
        gate.mode = "LIVE"
        tr.bot.arm("AAA", True, now=T0 + 2)
        tr.watchdog(T0 + 3)
        self.assertNotIn("AAA", tr.bot.trades)
        self.assertFalse(tr.bot.view(T0 + 3)["may_act"])

    def test_the_read_knows_the_plan_and_what_the_market_says(self):
        e, tr, gate, broker, st = setup(trigger=9.80, target=12.00)
        tr.bot.arm("AAA", True, now=T0 + 2)
        tr.watchdog(T0 + 3)
        t = tr.bot.trades["AAA"]
        rd = tr.bot.read(t, st, 10.20, T0 + 4)
        self.assertIn("LONG", rd["plan"]); self.assertIn("pivot 9.80", rd["plan"]); self.assertIn("MP 12.00", rd["plan"])
        self.assertIn("to 1", rd["plan"])
        self.assertIn("MP 12.00", rd["expect"])
        self.assertIn("reach the MP 12.00: +2.00 a share", rd["goal"])
        self.assertIn("+0.20 a share from the entry 10.00", rd["inside"])
        e.myread.set("AAA", "BEARISH", t=T0 + 4, price=10.2)
        st.storybook.__dict__["lean"] = {"side": "bear"}
        rd = tr.bot.read(t, st, 10.20, T0 + 5)
        self.assertEqual(rd["stance"], "CAREFUL", rd)
        self.assertIn("your read is BEARISH", rd["against"]); self.assertIn("sellers in control", rd["against"])
        # green and CAREFUL for two minutes: the stop tightens to the last finished 5-minute low
        tape(e, "AAA", T0 + 20, T0 + 600, lambda t: 10.40 if t < T0 + 580 else 10.55)
        before = t["stop"]
        tr.watchdog(T0 + 601)
        t["careful_since"] = T0 + 300; tr.watchdog(T0 + 602)
        self.assertGreater(t["stop"], before)
        self.assertTrue(any("tightened" in x["text"] for x in t["steps"]))

    def test_road_blocks_between_price_and_the_mp(self):
        e, tr, gate, broker, st = setup(trigger=9.80, target=12.00, sneaky_levels=[11.20])
        tr.bot.arm("AAA", True, now=T0 + 2)
        tr.watchdog(T0 + 3)
        t = tr.bot.trades["AAA"]
        rb = tr.bot.road_blocks(st, "long", 10.20, 12.00, T0 + 4)
        self.assertIn(11.20, [x["price"] for x in rb])
        self.assertTrue(all(10.20 < x["price"] < 12.00 for x in rb))
        rd = tr.bot.read(t, st, 10.20, T0 + 5)
        self.assertIn("SNEAKY PIVOT 11.20", rd["blocks"])
        # the 20 on the 60 ahead of a long: supply on the 60; one under price is not in the way
        st.__dict__["_story_mas"] = {"hpack": [("EMA 10", 10.50), ("EMA 20", 11.60), ("SMA 50", 9.00)]}
        rb = tr.bot.road_blocks(st, "long", 10.20, 12.00, T0 + 6)
        names = [x["name"] for x in rb]
        self.assertTrue(any("60-MIN EMA 20 (supply on the 60)" in n for n in names), names)
        self.assertFalse(any("EMA 10" in n or "SMA 50" in n for n in names), names)
        rbs = tr.bot.road_blocks(st, "short", 10.20, 8.50, T0 + 6)
        self.assertTrue(any("SMA 50 (demand on the 60)" in x["name"] for x in rbs), rbs)
        st.__dict__["_story_mas"] = {}
        # green and at the road block: the stop tightens once
        tape(e, "AAA", T0 + 20, T0 + 600, lambda t: 10.90 if t < T0 + 580 else 11.15)
        tr.watchdog(T0 + 601); tr.watchdog(T0 + 607)
        self.assertTrue(any("road block, SNEAKY PIVOT 11.20" in x["text"] for x in t["steps"]), t["steps"])

    def test_consolidation_count(self):
        from twiney.tradebot import TradeBot
        rows = [[i, 10, 11, 9, 10] for i in range(5)] + [[i, 10, 10.5, 9.5, 10] for i in range(5, 25)]
        self.assertEqual(TradeBot.consolidation_days(rows, 1.0, 2.5), 25)      # a $2 range < 2.5 ATR
        self.assertEqual(TradeBot.consolidation_days(rows, 1.0, 1.5), 20)      # only the tight part
        self.assertEqual(TradeBot.consolidation_days(rows, None, 2.5), 0)


if __name__ == "__main__":
    unittest.main()


class TradeBotOptionTests(unittest.TestCase):
    """The same management on a contract: the stop rides the STOCK price, pay yourself takes contracts off."""

    def test_calls_paid_break_even_and_stopped(self):
        import time
        from test_opt_watch import make
        from twiney import options as _o
        e, tr = make()
        T = (time.time() // 300) * 300 + 10
        st = e.syms["AAA"]
        st.play.update(atr=2.0, auto=False)

        def go(t1, t2, px):
            t = t1
            while t < t2:
                e.on_l1("AAA", "bid", round(px - 0.01, 2), t); e.on_l1("AAA", "ask", px, t); e.on_l1("AAA", "last", px, t)
                e.on_print("AAA", px, 100, "X", t)
                t += 20
        go(T - 600, T, 10.00)
        exp = e.option_chain("AAA", None, "C", T)["expiry"]
        key = _o.key_of("AAA", exp, 10, "C")
        self.assertTrue(tr.opt_open("AAA", exp, 10, "C", "BUY", 2, None, T)["ok"]); e.practice_opt_tick(T + 1)
        held = lambda: int((e.opt_positions.get(key) or {}).get("qty") or 0)
        self.assertEqual(held(), 2)
        tr.bot.arm("AAA", True, now=T + 2)
        tr.watchdog(T + 3)
        b = tr.bot.trades[key]
        self.assertEqual((b["kind"], b["side"]), ("option", "long"))
        go(T + 20, T + 60, 10.55)                                   # the stock $0.55 your way
        tr.watchdog(T + 61); e.practice_opt_tick(T + 62); tr.watchdog(T + 63)
        self.assertTrue(b["paid"]); self.assertEqual(held(), 1)
        self.assertTrue(b["be"])
        self.assertEqual((tr.opt_stops.get(key) or {}).get("on"), "stock")
        stop = tr.opt_stops[key]["price"]
        go(T + 80, T + 100, round(stop - 0.05, 2))                  # the stock trades under the stop
        tr.fast_stops(T + 101); tr.watchdog(T + 101); e.practice_opt_tick(T + 102); tr.watchdog(T + 103)
        self.assertEqual(held(), 0)
        self.assertNotIn(key, tr.bot.trades)

    def test_shares_and_calls_at_the_same_time_each_managed(self):
        import time
        from test_opt_watch import make
        from twiney import options as _o
        e, tr = make()
        T = (time.time() // 300) * 300 + 10
        st = e.syms["AAA"]
        st.play.update(atr=2.0, auto=False)

        def go(t1, t2, px):
            t = t1
            while t < t2:
                e.on_depth("AAA", 0, 1, 0, round(px - 0.01, 2), 500, "", t) if False else None
                e.on_l1("AAA", "bid", round(px - 0.01, 2), t); e.on_l1("AAA", "ask", px, t); e.on_l1("AAA", "last", px, t)
                e.on_print("AAA", px, 100, "X", t)
                t += 20
        go(T - 600, T, 10.00)
        self.assertTrue(tr.submit("AAA", "BUY", 10.05, 100, T)["ok"])
        e.sim_broker.on_market("AAA", T)
        exp = e.option_chain("AAA", None, "C", T)["expiry"]
        key = _o.key_of("AAA", exp, 10, "C")
        self.assertTrue(tr.opt_open("AAA", exp, 10, "C", "BUY", 2, None, T)["ok"]); e.practice_opt_tick(T + 1)
        self.assertEqual(int(tr.broker.position("AAA")), 100)
        self.assertTrue(tr.set_opt_stop(key, 0.05, on="option", now=T + 1)["ok"])       # your stop on the contract
        tr.bot.arm("AAA", True, now=T + 2)
        tr.watchdog(T + 3)
        self.assertEqual(sorted(t["kind"] for t in tr.bot.trades.values()), ["option", "stock"])
        self.assertEqual(tr.bot.trades[key].get("your_stop"), 0.05)
        self.assertEqual(tr.opt_stops[key]["on"], "option")                              # untouched
        tr.bot.arm("AAA", False, now=T + 4)                   # TAKE BACK takes both back
        self.assertEqual(tr.bot.trades, {})
