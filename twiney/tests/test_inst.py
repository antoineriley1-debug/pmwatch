"""INSTITUTIONAL FOOTPRINTS: program, fund-style reloads, walking."""
import unittest
from types import SimpleNamespace
from collections import deque

from twiney import inst

CFG = {"min_slots": 6, "window_slots": 18, "agree": 0.65, "min_part": 0.06, "steady": 0.45,
       "same_size_min_refills": 4, "same_size_share": 0.6, "walk_minutes": 20, "walk_steps": 3}


def slots(nets, vol=10000.0, price=100.0, start=120):
    out = []
    for i, n in enumerate(nets):
        buy = (vol + n) / 2.0; sell = vol - buy
        out.append([start + i, vol, buy, sell, price * vol])
    return out


class ProgramTests(unittest.TestCase):
    def test_steady_buying_slot_after_slot_is_a_buy_program(self):
        s = slots([1200, 1000, 1500, 900, 1300, 1100, 1400, 1000, -200, 1200])
        p = inst.program(s, s[-1][0] + 1, 99.98, CFG)
        self.assertIsNotNone(p); self.assertEqual(p["side"], "BUY")
        self.assertGreaterEqual(p["won"], 8); self.assertAlmostEqual(p["part"], 10.7, delta=1.5)

    def test_random_two_sided_tape_is_not_a_program(self):
        s = slots([1200, -1500, 800, -900, 1300, -1100, 600, -1400, 900, -700])
        self.assertIsNone(inst.program(s, s[-1][0] + 1, 100.0, CFG))

    def test_one_huge_slot_is_not_steady(self):
        s = slots([100, 50, 9000, 80, 60, 120, 90, 40])
        self.assertIsNone(inst.program(s, s[-1][0] + 1, 100.0, CFG))

    def test_too_early_in_the_day(self):
        s = slots([1200, 1000, 1500])
        self.assertIsNone(inst.program(s, s[-1][0] + 1, 100.0, CFG))


class FundReloadTests(unittest.TestCase):
    def tr(self, sizes, price=25.40, side="bid"):
        return SimpleNamespace(refill_sizes=deque(sizes), price=price, side=side, absorbed_all=0.0, absorbed_total=75000.0, displayed=200)

    def test_same_refill_size_again_and_again(self):
        f = inst.fund_reloads([self.tr([200, 200, 200, 300, 200, 200])], 0, CFG)
        self.assertEqual(len(f), 1); self.assertEqual(f[0]["size"], 200); self.assertEqual(f[0]["usd"], round(75000 * 25.40))

    def test_varied_refills_are_not_fund_style(self):
        self.assertEqual(inst.fund_reloads([self.tr([200, 900, 1500, 400, 700])], 0, CFG), [])


class WalkTests(unittest.TestCase):
    def test_buyer_walking_up(self):
        rows = [{"side": "bid", "price": p, "usd": 100000, "first": 1000 + i * 60} for i, p in enumerate((25.40, 25.42, 25.45))]
        w = inst.walking(rows, 1300, CFG)
        self.assertEqual((w["side"], w["dir"], w["steps"]), ("BUYER", "up", [25.40, 25.42, 25.45]))

    def test_no_walk_when_prices_do_not_step(self):
        rows = [{"side": "bid", "price": p, "usd": 100000, "first": 1000 + i * 60} for i, p in enumerate((25.45, 25.40, 25.43))]
        self.assertIsNone(inst.walking(rows, 1300, CFG))
