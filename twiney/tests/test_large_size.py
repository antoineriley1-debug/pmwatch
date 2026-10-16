"""LARGE SIZE: a print that traded more than the Level II showed at that price. Called once a minute per price,
marked on the ladder row for a while, said; small prints and prints the book did show are never called."""

import unittest

from helpers import ASK, BID, INSERT, cfg, plays
from twiney.engine import Engine


class LargeSizeTests(unittest.TestCase):
    def setUp(self):
        self.e = Engine(plays(), cfg(ladder={"big_shares": 5000}))
        self.e.on_connection("CONNECTED", "", 1.0)
        self.e.apply_slot("AAA", True, 1.0)
        self.e.on_depth("AAA", 0, INSERT, BID, 9.99, 800, "", 1.0)
        self.e.on_depth("AAA", 0, INSERT, ASK, 10.00, 600, "", 1.0)
        self.e.on_l1("AAA", "bid", 9.99, 1.0); self.e.on_l1("AAA", "ask", 10.00, 1.0)

    def large(self):
        return [a for a in self.e.alerts if a["label"] == "LARGE SIZE"]

    def rows(self, t):
        st = self.e.syms["AAA"]
        return self.e._memory_ladder(st, t, self.e._user_levels(st.play))["rows"]

    def test_a_print_bigger_than_the_bid_showed(self):
        self.e.on_print("AAA", 9.99, 5000, "NSDQ", 2.0)        # 5,000 sold into a bid showing 800
        al = self.large()
        self.assertEqual(len(al), 1)
        self.assertEqual((al[0]["shares"], al[0]["shown"], al[0]["side"]), (5000, 800, "bid"))
        self.assertIn("the book never showed it", al[0]["text"])
        self.assertIn("Large size at 9.99", al[0]["words"])
        row = next(r for r in self.rows(2.5) if float(r["price"]) == 9.99)
        self.assertEqual(row["large"][0]["size"], 5000); self.assertEqual(row["large"][0]["shown"], 800); self.assertEqual(row["large"][0]["side"], "sell")

    def test_small_prints_and_shown_size_are_not_called(self):
        self.e.on_print("AAA", 9.99, 300, "NSDQ", 2.0)         # a fifth of BIG is the floor
        self.e.on_depth("AAA", 0, INSERT, ASK, 10.00, 9000, "", 2.5)
        self.e.on_print("AAA", 10.00, 4000, "NSDQ", 3.0)       # the offer showed 9,000: nothing hidden about it
        self.assertEqual(self.large(), [])
        self.assertNotIn("large", next(r for r in self.rows(3.5) if float(r["price"]) == 10.0))

    def test_once_a_minute_per_price_but_every_one_marked(self):
        self.e.on_print("AAA", 9.99, 5000, "NSDQ", 2.0)
        self.e.on_print("AAA", 9.99, 6000, "NSDQ", 20.0)
        self.e.on_print("AAA", 9.99, 7000, "NSDQ", 70.0)
        self.assertEqual(len(self.large()), 2)
        row = next(r for r in self.rows(71.0) if float(r["price"]) == 9.99)
        self.assertEqual([x["size"] for x in row["large"]], [5000, 6000, 7000])
        row = next(r for r in self.rows(20.0 + 121) if float(r["price"]) == 9.99)
        self.assertEqual([x["size"] for x in row.get("large", [])], [7000])    # the mark ages out after large_size_seconds

    def test_voice_switch(self):
        self.e.cfg["ladder"]["voice_large_size"] = False
        self.e.on_print("AAA", 9.99, 5000, "NSDQ", 2.0)
        self.assertIsNone(self.large()[0]["words"])


if __name__ == "__main__":
    unittest.main()
