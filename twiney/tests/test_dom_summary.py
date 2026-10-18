"""The DOM's session summary line: bought (lifted the offer), sold (hit the bid), net, everything traded, the high /
low of day; a CLR on one side of the market takes those prices out of the totals."""

import unittest

from helpers import ASK, BID, INSERT, cfg, plays
from twiney.engine import Engine


class DomSummaryTests(unittest.TestCase):
    def setUp(self):
        self.e = Engine(plays(), cfg())
        self.e.on_connection("DEMO", "", 0.0)
        self.e.apply_slot("AAA", True, 0.0)
        self.e.on_depth("AAA", 0, INSERT, BID, 9.99, 1000, "", 1.0)
        self.e.on_depth("AAA", 0, INSERT, ASK, 10.00, 1000, "", 1.0)
        self.e.on_l1("AAA", "bid", 9.99, 1.0); self.e.on_l1("AAA", "ask", 10.00, 1.0)

    def lad(self, t):
        st = self.e.syms["AAA"]
        return self.e._memory_ladder(st, t, self.e._user_levels(st.play))

    def test_totals_add_up(self):
        self.e.on_print("AAA", 10.00, 700, "NSDQ", 2.0)      # lifted the offer
        self.e.on_print("AAA", 9.99, 300, "NSDQ", 3.0)       # hit the bid
        self.e.on_print("AAA", 10.00, 200, "NSDQ", 4.0)
        s = self.lad(5.0)["sum"]
        self.assertEqual((s["bought"], s["sold"], s["net"], s["traded"], s["prints"]), (900, 300, 600, 1200, 3))
        self.assertEqual((s["hod"], s["lod"]), (10.00, 9.99))

    def test_clear_below_the_bid_takes_those_prices_out(self):
        self.e.on_print("AAA", 10.00, 700, "NSDQ", 2.0)
        self.e.on_print("AAA", 9.98, 300, "NSDQ", 3.0)       # under the bid
        self.assertEqual(self.lad(4.0)["sum"]["traded"], 1000)
        self.assertTrue(self.e.ladder_clear("AAA", "below", 5.0))
        s = self.lad(7.0)["sum"]                               # the memo is a second old by now
        self.assertEqual((s["traded"], s["sold"], s["bought"]), (700, 0, 700))

    def test_nothing_traded_is_zero_not_missing(self):
        s = self.lad(2.0)["sum"]
        self.assertEqual((s["traded"], s["net"], s["hod"]), (0, 0, None))


if __name__ == "__main__":
    unittest.main()
