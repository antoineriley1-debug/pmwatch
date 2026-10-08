"""BREAK TRAPS: price takes out a key level and comes back. Counted: the breakout crowd's orders, shares, dollars,
average, what was resting at the level. TRAPPED when price is back through the level by the retrace with no new
extreme; RECLAIMED on a new extreme; AT EXIT when price comes back to their average."""
import unittest

from twiney.breaktrap import BreakTraps

CFG = {"retrace_dollars": 0.30, "hod_min_age_seconds": 120, "memory_minutes": 60, "max_breaks": 6}
PMH = [("PREMARKET HIGH", "the premarket high", 100.00)]


def run(bt, seq, levels=PMH, rth=False, t0=1000.0, day="d1", resting=None):
    evs = []
    for i, (p, sz, side) in enumerate(seq):
        evs += [(k, b["name"]) for k, b in bt.update(t0 + i, p, sz, side, 0.01, levels, rth, day, CFG, resting)]
    return evs


class BreakTrapTests(unittest.TestCase):
    def test_break_up_counts_buyers_then_trapped(self):
        bt = BreakTraps()
        evs = run(bt, [(99.95, 100, "buy"), (100.02, 500, "buy"), (100.05, 300, "buy"), (100.04, 200, "sell"),
                       (100.00, 400, "buy"), (99.90, 100, "sell"), (99.70, 100, "sell")],
                  resting=lambda up, lv: 2500)
        self.assertIn(("BROKE", "PREMARKET HIGH"), evs); self.assertIn(("TRAPPED", "PREMARKET HIGH"), evs)
        v = bt.view(2000, 99.70)[0]
        self.assertEqual(v["side"], "long"); self.assertEqual(v["state"], "TRAPPED")
        self.assertEqual(v["prints"], 3); self.assertEqual(v["shares"], 1200)          # the 3 buys at / over 100
        self.assertAlmostEqual(v["avg"], (100.02 * 500 + 100.05 * 300 + 100.00 * 400) / 1200, places=4)
        self.assertEqual(v["resting"], 2500); self.assertAlmostEqual(v["extreme"], 100.05)
        self.assertGreater(v["under"], 0.3); self.assertGreater(v["at_risk"], 0)

    def test_not_trapped_before_the_retrace(self):
        bt = BreakTraps()
        evs = run(bt, [(99.95, 100, "buy"), (100.05, 500, "buy"), (99.80, 100, "sell")])   # 20 cents under: not yet
        self.assertNotIn(("TRAPPED", "PREMARKET HIGH"), evs)
        self.assertEqual(bt.view(2000, 99.80)[0]["state"], "BROKE")

    def test_new_high_releases_them(self):
        bt = BreakTraps()
        evs = run(bt, [(99.95, 100, "buy"), (100.05, 500, "buy"), (99.60, 100, "sell"), (100.06, 100, "buy")])
        self.assertIn(("TRAPPED", "PREMARKET HIGH"), evs); self.assertIn(("RECLAIMED", "PREMARKET HIGH"), evs)
        self.assertEqual(bt.view(2000, 100.06)[0]["state"], "RECLAIMED")

    def test_back_at_their_exit(self):
        bt = BreakTraps()
        evs = run(bt, [(99.95, 100, "buy"), (100.10, 500, "buy"), (100.20, 100, "buy"), (99.60, 100, "sell"),
                       (100.12, 100, "buy"), (100.13, 100, "buy")])
        self.assertEqual([e for e in evs if e[0] == "AT EXIT"], [("AT EXIT", "PREMARKET HIGH")])   # said once

    def test_break_down_traps_shorts(self):
        bt = BreakTraps()
        lv = [("PRIOR DAY LOW", "the prior day low", 50.00)]
        evs = run(bt, [(50.05, 100, "sell"), (49.98, 800, "sell"), (49.95, 200, "sell"), (49.96, 100, "buy"), (50.35, 100, "buy")], levels=lv)
        self.assertIn(("TRAPPED", "PRIOR DAY LOW"), evs)
        v = bt.view(2000, 50.35)[0]
        self.assertEqual(v["side"], "short"); self.assertEqual(v["shares"], 1000); self.assertEqual(v["prints"], 2)

    def test_high_of_day_only_once_it_stood(self):
        bt = BreakTraps()
        seq = [(10.00 + i * 0.01, 100, "buy") for i in range(20)]          # a run: every print a new high, 1 s apart
        evs = run(bt, seq, levels=[], rth=True)
        self.assertFalse([e for e in evs if e[1] == "HIGH OF DAY"])     # never a 'break' of a high that never stood
        evs = run(bt, [(10.15, 100, "sell")] * 1 + [(10.20, 300, "buy")], levels=[], t0=1300.0, rth=True)   # the 10.19 high stood 280 s
        self.assertIn(("BROKE", "HIGH OF DAY"), evs)
        self.assertAlmostEqual(bt.view(1400, 10.20)[0]["level"], 10.19)

    def test_no_hod_outside_regular_hours(self):
        bt = BreakTraps()
        run(bt, [(10.0, 100, "buy")], levels=[], rth=False)
        evs = run(bt, [(10.5, 100, "buy")], levels=[], rth=False, t0=2000.0)
        self.assertFalse(evs)

    def test_first_print_never_a_break(self):
        bt = BreakTraps()
        self.assertFalse(run(bt, [(100.50, 100, "buy")]))              # starts above the level: no cross seen

    def test_chop_at_the_level_is_not_a_break(self):
        bt = BreakTraps()
        evs = run(bt, [(99.99, 100, "buy"), (100.00, 100, "buy"), (100.00, 100, "sell"), (99.995, 100, "buy")])
        self.assertFalse(evs)

    def test_rebreak_is_one_break(self):
        bt = BreakTraps()
        run(bt, [(99.95, 100, "buy"), (100.05, 500, "buy"), (99.95, 100, "sell"), (100.05, 300, "buy")])
        self.assertEqual(len([b for b in bt.breaks if b["up"]]), 1)
        self.assertEqual(bt.view(2000, 100.05)[0]["shares"], 800)

    def test_new_day_forgets(self):
        bt = BreakTraps()
        run(bt, [(99.95, 100, "buy"), (100.05, 500, "buy")])
        run(bt, [(99.00, 100, "buy")], day="d2", t0=90000.0)
        self.assertEqual(bt.view(90001, 99.0), [])

    def test_expires(self):
        bt = BreakTraps()
        run(bt, [(99.95, 100, "buy"), (100.05, 500, "buy")])
        run(bt, [(100.06, 100, "buy")], t0=1000.0 + 3700)
        self.assertEqual(bt.view(1000 + 3701, 100.06), [])

    def test_failed_breakout_is_not_a_breakdown(self):
        bt = BreakTraps()
        run(bt, [(99.95, 100, "buy"), (100.05, 500, "buy"), (99.60, 100, "sell"), (99.50, 900, "sell")])
        self.assertEqual([b["up"] for b in bt.breaks], [True])           # only the breakout: its failure is the trap
        self.assertEqual(bt.view(2000, 99.5)[0]["shares"], 500)

    def test_after_release_a_break_the_other_way_counts(self):
        bt = BreakTraps()
        run(bt, [(99.95, 100, "buy"), (100.05, 500, "buy"), (99.60, 100, "sell"), (100.10, 100, "buy"), (99.90, 400, "sell")])
        self.assertEqual([b["up"] for b in bt.breaks], [True, False])    # released, then a real break down

    def test_same_price_two_names_is_one_break(self):
        bt = BreakTraps()
        lv = [("PREMARKET HIGH", "the premarket high", 100.00), ("PRIOR DAY HIGH", "the prior day high", 100.00)]
        evs = run(bt, [(99.95, 100, "buy"), (100.05, 500, "buy")], levels=lv)
        self.assertEqual(len(bt.breaks), 1); self.assertEqual(bt.breaks[0]["name"], "PREMARKET HIGH / PRIOR DAY HIGH")
        self.assertEqual(len([e for e in evs if e[0] == "BROKE"]), 1)

    def test_bad_prints_ignored(self):
        bt = BreakTraps()
        self.assertEqual(bt.update(1.0, None, 100, "buy", 0.01, PMH, True, "d1", CFG), [])
        self.assertEqual(bt.update(1.0, 100.5, 0, "buy", 0.01, PMH, True, "d1", CFG), [])

    def test_trapped_needs_someone_caught(self):
        bt = BreakTraps()
        evs = run(bt, [(99.95, 100, "buy"), (100.05, 500, "sell"), (99.60, 100, "sell")])   # nobody bought the break
        self.assertNotIn(("TRAPPED", "PREMARKET HIGH"), evs)


if __name__ == "__main__":
    unittest.main()


class EngineBreakTrapTests(unittest.TestCase):
    """Through the engine: prints in, the TRAPS box data out, one TRAPPED call with the numbers, spoken."""
    def make(self):
        from helpers import cfg, plays
        from twiney.engine import Engine
        from twiney.book import INSERT, BID, ASK
        e = Engine(plays(), cfg()); e.on_connection("DEMO", "", 1000.0)
        e.apply_slot("AAA", True, 1000.0)
        for i in range(5):
            e.on_depth("AAA", i, INSERT, BID, round(9.99 - i * 0.01, 2), 1000, "", 1000.0)
            e.on_depth("AAA", i, INSERT, ASK, round(10.00 + i * 0.01, 2), 3000 if i == 0 else 1000, "", 1000.0)
        e.on_l1("AAA", "bid", 9.99, 1000.0); e.on_l1("AAA", "ask", 10.00, 1000.0)
        e.syms["AAA"]._bt_levels = [("PREMARKET HIGH", "the premarket high", 10.00)]
        return e

    def test_trap_through_the_engine(self):
        e = self.make()
        t = 1001.0
        e.on_print("AAA", 9.99, 100, "NASDAQ", t)
        e.on_l1("AAA", "bid", 10.00, t); e.on_l1("AAA", "ask", 10.01, t)
        for i in range(6):
            e.on_print("AAA", 10.01, 400, "NASDAQ", t + 1 + i)               # breakout buyers at the offer
        e.on_l1("AAA", "bid", 9.65, t + 10); e.on_l1("AAA", "ask", 9.66, t + 10)
        e.on_print("AAA", 9.65, 300, "NASDAQ", t + 10)                       # back 35 cents under the level
        pane = e.snapshot(t + 11)["panes"][0]
        bts = pane["breaktraps"]
        b = next(x for x in bts if x["name"].startswith("PREMARKET HIGH"))
        self.assertEqual(b["state"], "TRAPPED"); self.assertEqual(b["side"], "long")
        self.assertEqual(b["shares"], 2400); self.assertEqual(b["prints"], 6)
        self.assertEqual(b["resting"], 3000)                                 # the offer resting at 10.00
        calls = [a for a in e.alerts if a["label"].startswith("TRAPPED LONGS")]
        self.assertEqual(len(calls), 1)
        self.assertIn("2,400", calls[0]["text"]); self.assertIn("6 buy orders", calls[0]["text"])
        self.assertTrue(calls[0]["words"].startswith("AAA. Trapped longs at the premarket high"))
        self.assertEqual(calls[0]["role"], "breaktrap")

    def test_small_trap_is_shown_not_called(self):
        e = self.make()
        e.on_print("AAA", 9.99, 100, "NASDAQ", 1001.0)
        e.on_l1("AAA", "bid", 10.00, 1001.0); e.on_l1("AAA", "ask", 10.01, 1001.0)
        e.on_print("AAA", 10.01, 200, "NASDAQ", 1002.0)
        e.on_l1("AAA", "bid", 9.60, 1003.0); e.on_l1("AAA", "ask", 9.61, 1003.0)
        e.on_print("AAA", 9.60, 100, "NASDAQ", 1003.0)
        self.assertFalse([a for a in e.alerts if "TRAPPED" in a["label"]])
        self.assertEqual(e.snapshot(1004.0)["panes"][0]["breaktraps"][0]["state"], "TRAPPED")

    def test_switched_off(self):
        e = self.make()
        e.cfg["breaktrap"]["enabled"] = False
        e.on_print("AAA", 9.99, 100, "NASDAQ", 1001.0); e.on_print("AAA", 10.05, 5000, "NASDAQ", 1002.0)
        self.assertIsNone(e.snapshot(1003.0)["panes"][0]["breaktraps"])
