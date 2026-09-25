import unittest

from helpers import plays
from twiney.ranking import allocate, distances, nearest, rank


class RankingTests(unittest.TestCase):
    def test_distance_uses_trigger_and_second_entry(self):
        p = {"trigger": 10.0, "second_entry": 9.0}
        d_t, d_s = distances(p, 9.10)
        self.assertAlmostEqual(d_t, 0.9 / 9.10)
        self.assertAlmostEqual(d_s, 0.1 / 9.10)
        self.assertAlmostEqual(nearest(p, 9.10), 0.1 / 9.10)
        self.assertEqual(distances(p, None), (None, None))
        self.assertAlmostEqual(nearest({"trigger": 10.0, "second_entry": None}, 11.0), 1 / 11.0)

    def test_rank_orders_by_nearest_and_skips_unpriced_blocked_inactive(self):
        ps = plays()
        ps[3]["active"] = False
        prices = {"AAA": 10.20, "BBB": 50.05, "CCC": None, "DDD": 5.0}
        self.assertEqual([s for s, _ in rank(ps, prices)], ["BBB", "AAA"])
        self.assertEqual([s for s, _ in rank(ps, prices, blocked={"BBB"})], ["AAA"])


class AllocateTests(unittest.TestCase):
    def test_fills_empty_slots_with_closest(self):
        got = allocate({}, [("A", .001), ("B", .002), ("C", .003), ("D", .004)], 3, 0, .15, 20)
        self.assertEqual(set(got), {"A", "B", "C"})

    def test_hysteresis_prevents_churn(self):
        cur = {"A": 0, "B": 0, "C": 0}
        ranked = [("D", .0095), ("A", .001), ("B", .002), ("C", .010)]
        self.assertEqual(set(allocate(cur, ranked, 3, 100, .15, 20)), {"A", "B", "C"})
        ranked = [("D", .008), ("A", .001), ("B", .002), ("C", .010)]
        self.assertEqual(set(allocate(cur, ranked, 3, 100, .15, 20)), {"A", "B", "D"})

    def test_min_hold_protects_new_incumbents(self):
        cur = {"A": 0, "B": 0, "C": 95}
        ranked = [("D", .001), ("A", .002), ("B", .003), ("C", .050)]
        got = allocate(cur, ranked, 3, 100, .15, 20)
        # C is worst but too new; B is the worst eligible and D beats it clearly
        self.assertEqual(set(got), {"A", "C", "D"})
        self.assertEqual(got["D"], 100)
        self.assertEqual(got["A"], 0)

    def test_multiple_rotations_in_one_pass(self):
        cur = {"A": 0, "B": 0, "C": 0}
        ranked = [("D", .001), ("E", .001), ("F", .001), ("A", .05), ("B", .05), ("C", .05)]
        self.assertEqual(set(allocate(cur, ranked, 3, 100, .15, 20)), {"D", "E", "F"})

    def test_unpriced_incumbent_releases_slot(self):
        got = allocate({"A": 0, "Z": 0}, [("A", .01), ("B", .02)], 2, 5, .15, 20)
        self.assertEqual(set(got), {"A", "B"})


if __name__ == "__main__":
    unittest.main()
