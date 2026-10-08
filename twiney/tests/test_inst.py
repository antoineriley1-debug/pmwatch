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


class FundScoreTests(unittest.TestCase):
    def tr(self, price, side, sizes, absorbed, peak):
        return SimpleNamespace(price=price, side=side, refill_sizes=deque(sizes), absorbed_all=0.0, absorbed_total=absorbed,
                               peak_displayed=peak, displayed=200, proven=True, state="RELOAD")

    def test_all_the_tells_make_one_high_score(self):
        walk = {"side": "BUYER", "dir": "up", "steps": [25.40, 25.42, 25.45], "usd": 0}
        prog = {"side": "BUY"}
        lv = inst.fund_levels([self.tr(25.45, "bid", [200] * 8, 75000, 400)], walk, [{"price": 25.45, "usd": 900000}], prog, {"fund_show": 50})
        self.assertEqual(len(lv), 1); self.assertGreaterEqual(lv[0]["score"], 90)
        self.assertTrue(any("same size 200" in w for w in lv[0]["why"])); self.assertTrue(any("accumulation" in w for w in lv[0]["why"]))

    def test_seller_walking_it_down_is_distribution(self):
        walk = {"side": "SELLER", "dir": "down", "steps": [25.40, 25.30, 25.20, 25.00], "usd": 0}
        lv = inst.fund_levels([self.tr(25.20, "ask", [300] * 6, 40000, 600)], walk, [], {"side": "SELL"}, {"fund_show": 50})
        self.assertTrue(lv and any("distribution" in w for w in lv[0]["why"]))

    def test_a_plain_reload_is_not_tagged(self):
        self.assertEqual(inst.fund_levels([self.tr(25.0, "bid", [200, 900, 1500], 1200, 1500)], None, [], None, {"fund_show": 50}), [])


class GuideTests(unittest.TestCase):
    def test_buying_over_vwap_dips_are_bought(self):
        g = inst.guides({"side": "BUY"}, 25.50, 25.40, 37000, {})
        self.assertIn("dips to VWAP are likely bought", g[0])

    def test_selling_under_vwap_and_last_hour_push_down(self):
        g = inst.guides({"side": "SELL"}, 25.30, 25.40, 55000, {})
        self.assertIn("pops to VWAP are likely sold", g[0]); self.assertIn("push down into the close", g[1])

    def test_midday_slows(self):
        self.assertTrue(any("Midday" in x for x in inst.guides({"side": "BUY"}, 25.5, 25.4, 45000, {})))
