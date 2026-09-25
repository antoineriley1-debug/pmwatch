import unittest

from helpers import ASK, BID, DELETE, INSERT, UPDATE, Book, cfg, ladder, seller_book
from twiney.levels import BUILDING, GONE_PENDING, INCONCLUSIVE, RELOAD, WATCHING, LevelTracker
from twiney.tape import BUY, SELL


class Harness:
    """Drives one ask-side tracker at 10.00 through a book + tape."""

    def __init__(self, side=ASK, **reload_overrides):
        self.rc = cfg(reload=reload_overrides)["reload"]
        self.side = side
        if side == ASK:
            self.book = seller_book()
            self.level = 10.00
        else:
            self.book = Book(10)
            ladder(self.book, BID, [(10.00, 1000), (9.99, 800)])
            ladder(self.book, ASK, [(10.01, 500), (10.02, 400)])
            self.level = 10.00
        self.tr = LevelTracker("AAA", self.level, side, "trigger", self.rc, 0.0)
        self.alerts = []

    def _note(self, label, t):
        if label:
            self.alerts.append((t, label))

    def show(self, size, t):
        self.book.apply(0, UPDATE, self.side, self.level, size)
        self._note(self.tr.on_book(self.book, t), t)

    def remove(self, t):
        self.book.apply(0, DELETE, self.side, self.level, 0)
        self._note(self.tr.on_book(self.book, t), t)

    def hit(self, size, t, price=None):
        aggressor = BUY if self.side == ASK else SELL
        self._note(self.tr.on_print(price or self.level, size, aggressor, t, self.book), t)

    def tick(self, t):
        self._note(self.tr.evaluate(t, self.book), t)

    def build_reload(self):
        """Two refills after executions, 1700 absorbed vs 1000 peak -> confirmed at t=6."""
        self.show(1000, 1.0)
        self.hit(600, 2.0)
        self.show(400, 2.1)
        self.show(1000, 3.0)
        self.hit(700, 4.0)
        self.show(300, 4.1)
        self.show(1000, 5.0)
        self.hit(400, 6.0)


class ReloadDetectionTests(unittest.TestCase):
    def test_reload_seller_detected_with_full_evidence(self):
        h = Harness()
        h.build_reload()
        self.assertEqual(h.alerts, [(6.0, "RELOAD SELLER DETECTED")])
        self.assertEqual(h.tr.state, RELOAD)
        self.assertEqual(h.tr.absorbed_total, 1700)

    def test_reload_buyer_detected_on_bid(self):
        h = Harness(side=BID)
        h.build_reload()
        self.assertEqual(h.alerts, [(6.0, "RELOAD BUYER DETECTED")])

    def test_no_call_without_enough_refreshes(self):
        h = Harness()
        h.show(1000, 1.0)
        h.hit(900, 2.0)
        h.hit(900, 2.5)          # heavy volume but the size never came back
        h.show(100, 2.6)
        self.assertEqual(h.alerts, [])
        self.assertEqual(h.tr.state, BUILDING)

    def test_no_call_when_absorbed_does_not_exceed_display(self):
        h = Harness()
        for i in range(4):  # refills, but 5000 shown and only ~1600 traded
            h.show(5000, i * 1.0)
            h.hit(400, i * 1.0 + 0.5)
            h.show(4600, i * 1.0 + 0.6)
        self.assertEqual(h.alerts, [])

    def test_evidence_outside_window_expires(self):
        h = Harness(window_seconds=10.0)
        h.show(1000, 1.0)
        h.hit(600, 2.0)
        h.show(400, 2.1)
        h.show(1000, 3.0)
        h.hit(700, 40.0)
        h.show(300, 40.1)
        h.show(1000, 41.0)
        h.hit(400, 42.0)
        self.assertEqual(h.alerts, [])

    def test_prints_on_the_other_side_do_not_count(self):
        h = Harness()
        h.show(1000, 1.0)
        h.tr.on_print(10.00, 5000, SELL, 2.0, h.book)
        self.assertEqual(h.tr.absorbed_total, 0)


class VerdictTests(unittest.TestCase):
    def test_cleaned_up_needs_executions_and_move_through(self):
        h = Harness()
        h.build_reload()
        h.show(1000, 7.0)
        h.hit(1000, 8.0)
        h.remove(8.05)
        self.assertEqual(h.tr.state, GONE_PENDING)
        h.hit(200, 8.2, price=10.01)  # price trades through the level
        self.assertEqual(h.alerts[-1], (8.2, "CLEANED UP"))
        self.assertEqual(h.tr.state, WATCHING)
        self.assertEqual(h.tr.last_verdict[0], "CLEANED UP")

    def test_cleaned_up_when_print_arrives_after_book_delete(self):
        h = Harness()
        h.build_reload()
        h.show(1000, 7.0)
        h.remove(8.0)            # book first...
        h.hit(1000, 8.05)        # ...tape lags
        h.hit(100, 8.1, price=10.01)
        self.assertEqual(h.alerts[-1], (8.1, "CLEANED UP"))

    def test_pulled_without_execution_evidence(self):
        h = Harness()
        h.build_reload()
        h.show(600, 6.1)
        h.show(1000, 7.0)        # refilled at 7.0: earlier prints are already accounted for
        h.remove(9.0)
        h.tick(9.5)
        self.assertEqual(h.alerts[-1][1], "RELOAD SELLER DETECTED")  # grace not over yet
        h.tick(10.6)
        self.assertEqual(h.alerts[-1], (10.6, "PULLED"))

    def test_pulled_even_if_price_then_moves_through(self):
        h = Harness()
        h.build_reload()
        h.show(1000, 7.0)
        h.remove(9.0)
        h.hit(100, 9.2, price=10.01)
        h.tick(11.0)
        self.assertEqual(h.alerts[-1][1], "PULLED")

    def test_consumed_but_no_follow_through_is_inconclusive_and_silent(self):
        h = Harness(through_timeout_seconds=3.0)
        h.build_reload()
        h.show(1000, 7.0)
        h.hit(1000, 8.0)
        h.remove(8.05)
        h.tick(12.0)
        self.assertEqual([a for a in h.alerts if a[1] != "RELOAD SELLER DETECTED"], [])
        self.assertEqual(h.tr.last_verdict[0], INCONCLUSIVE)

    def test_reappearing_level_cancels_pending_verdict(self):
        h = Harness()
        h.build_reload()
        h.remove(7.0)
        h.book.apply(0, INSERT, ASK, 10.00, 900)
        h.tr.on_book(h.book, 7.3)
        h.tick(20.0)
        self.assertEqual(h.tr.state, RELOAD)
        self.assertEqual(len(h.alerts), 1)

    def test_out_of_view_level_is_never_judged(self):
        rc = cfg()["reload"]
        book = Book(rows_requested=3)
        ladder(book, BID, [(9.99, 1)])
        ladder(book, ASK, [(10.00, 1), (10.01, 1), (10.02, 1)])
        tr = LevelTracker("AAA", 10.10, ASK, "trigger", rc, 0.0)
        tr.state = RELOAD
        tr.displayed = 500
        self.assertIsNone(tr.on_book(book, 1.0))
        self.assertTrue(tr.out_of_view)
        self.assertEqual(tr.state, RELOAD)

    def test_resync_blocks_verdicts(self):
        h = Harness()
        h.build_reload()
        h.book.reset()                      # error 317
        h.tr.on_resync()
        h._note(h.tr.on_book(h.book, 7.0, judge=False), 7.0)
        h.tick(30.0)
        self.assertEqual(h.tr.state, RELOAD)
        self.assertEqual(len(h.alerts), 1)

    def test_resync_during_pending_restores_reload(self):
        h = Harness()
        h.build_reload()
        h.remove(7.0)
        h.tr.on_resync()
        h.tick(20.0)
        self.assertEqual(h.tr.state, RELOAD)


if __name__ == "__main__":
    unittest.main()
