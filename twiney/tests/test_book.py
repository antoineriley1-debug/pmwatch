import unittest

from helpers import ASK, BID, DELETE, INSERT, UPDATE, Book, ladder


class BookTests(unittest.TestCase):
    def test_insert_update_delete_positions(self):
        b = Book(10)
        b.apply(0, INSERT, ASK, 10.02, 300)
        b.apply(0, INSERT, ASK, 10.01, 200)   # new best pushes the old row down
        b.apply(1, UPDATE, ASK, 10.02, 350)
        self.assertEqual(b.levels(ASK), [(10.01, 200, 1), (10.02, 350, 1)])
        b.apply(0, DELETE, ASK, 10.01, 0)
        self.assertEqual(b.best(ASK), 10.02)
        self.assertEqual(b.anomalies, 0)

    def test_smart_depth_rows_aggregate_by_price(self):
        b = Book(10)
        b.apply(0, INSERT, BID, 9.99, 300, "NSDQ")
        b.apply(1, INSERT, BID, 9.99, 200, "ARCA")
        b.apply(2, INSERT, BID, 9.98, 100, "BATS")
        self.assertEqual(b.levels(BID), [(9.99, 500, 2), (9.98, 100, 1)])
        self.assertEqual(b.size_at(BID, 9.99), 500)
        self.assertEqual(b.size_at(BID, 9.985, band_ticks=1), 600)

    def test_anomalies_are_counted_not_fatal(self):
        b = Book(10)
        self.assertFalse(b.apply(3, DELETE, ASK, 1, 0))
        self.assertFalse(b.apply(2, UPDATE, ASK, 10.0, 100))  # update of unknown row -> appended
        self.assertEqual(b.size_at(ASK, 10.0), 100)
        self.assertEqual(b.anomalies, 2)

    def test_reset_and_synced(self):
        b = Book(10)
        ladder(b, BID, [(9.99, 1)])
        self.assertFalse(b.synced)
        ladder(b, ASK, [(10.0, 1)])
        self.assertTrue(b.synced)
        b.reset()
        self.assertFalse(b.synced)
        self.assertEqual(b.levels(ASK), [])

    def test_in_view(self):
        b = Book(rows_requested=3)
        ladder(b, ASK, [(10.00, 1), (10.01, 1), (10.02, 1)])
        self.assertTrue(b.in_view(ASK, 10.01))
        self.assertFalse(b.in_view(ASK, 10.02))   # the last row of a full window: more may sit past it
        self.assertFalse(b.in_view(ASK, 10.05))   # beyond a full ladder: unknown
        self.assertTrue(b.in_view(ASK, 9.95))     # better than best: would be visible
        smart = Book(rows_requested=3)            # SMART depth: 3 rows, one price (three venues)
        for i, mm in enumerate(("NSDQ", "ARCA", "BATS")):
            smart.apply(i, 0, ASK, 10.00, 100, mm)
        self.assertFalse(smart.in_view(ASK, 10.03))   # the window is full: 10.03 is out of sight, not empty
        partial = Book(rows_requested=10)
        ladder(partial, ASK, [(10.00, 1)])
        self.assertTrue(partial.in_view(ASK, 10.50))  # side not full: everything visible


if __name__ == "__main__":
    unittest.main()
