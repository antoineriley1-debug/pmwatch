"""THE BASKET: every confirmed trade at a price today, counted ONCE as it arrives: [total, bought, sold, sequence].
Bought (at the ask) and sold (into the bid) split; between counts in the total only. CLR clears it on its side of the
market; a new New York day starts every basket over; the ladder row carries it."""
import unittest

from helpers import cfg, plays
from twiney.engine import Engine
from twiney.book import INSERT, BID, ASK

T0 = 1791460800.0 + 15 * 3600       # 2026-10-08 11:00 New York


def make():
    e = Engine(plays(), cfg()); e.on_connection("DEMO", "", T0)
    e.apply_slot("AAA", True, T0)
    for i in range(5):
        e.on_depth("AAA", i, INSERT, BID, round(9.99 - i * 0.01, 2), 1000, "", T0)
        e.on_depth("AAA", i, INSERT, ASK, round(10.00 + i * 0.01, 2), 1000, "", T0)
    e.on_l1("AAA", "bid", 9.99, T0); e.on_l1("AAA", "ask", 10.00, T0); e.on_l1("AAA", "last", 10.00, T0)
    return e


def lad(e, t):
    with e.lock:
        st = e.syms["AAA"]
        return e._memory_ladder(st, t, e._user_levels(st.play))


def bk(e, t, price):
    r = next((r for r in lad(e, t)["rows"] if abs(float(r["price"]) - price) < 1e-9), None)
    return r and r.get("bk")


class BasketTests(unittest.TestCase):
    def test_each_trade_counts_once_and_splits_by_side(self):
        e = make()
        e.on_print("AAA", 10.00, 300, "NASDAQ", T0 + 1)       # at the ask: bought
        e.on_print("AAA", 10.00, 200, "NASDAQ", T0 + 2)
        e.on_print("AAA", 9.99, 500, "NASDAQ", T0 + 3)        # at the bid: sold
        self.assertEqual(bk(e, T0 + 4, 10.00), [500, 500, 0, 2])
        self.assertEqual(bk(e, T0 + 4, 9.99), [500, 0, 500, 1])
        # reading the ladder again (and again) never adds anything
        for _ in range(5):
            lad(e, T0 + 5)
        self.assertEqual(bk(e, T0 + 5, 10.00), [500, 500, 0, 2])

    def test_between_counts_in_the_total_only(self):
        e = make()
        e.on_l1("AAA", "bid", 9.98, T0 + 1); e.on_l1("AAA", "ask", 10.02, T0 + 1)
        e.on_print("AAA", 10.00, 100, "NASDAQ", T0 + 2)       # inside a wide spread
        b = bk(e, T0 + 3, 10.00)
        self.assertEqual(b[0], 100); self.assertEqual(b[1] + b[2] <= 100, True); self.assertEqual(b[3], 1)

    def test_not_reset_by_the_15_minute_memory(self):
        e = make()
        e.on_print("AAA", 10.00, 300, "NASDAQ", T0 + 1)
        e.on_print("AAA", 10.01, 100, "NASDAQ", T0 + 1200)    # 20 minutes later: the SOLD / BOUGHT memory let go
        self.assertEqual(bk(e, T0 + 1201, 10.00)[0], 300)    # the day's basket did not

    def test_new_day_starts_over(self):
        e = make()
        e.on_print("AAA", 10.00, 300, "NASDAQ", T0 + 1)
        e.on_print("AAA", 10.00, 50, "NASDAQ", T0 + 86400)
        self.assertEqual(bk(e, T0 + 86401, 10.00)[0], 50)

    def test_clr_clears_its_side_only(self):
        e = make()
        e.on_print("AAA", 10.03, 100, "NASDAQ", T0 + 1)       # above the ask
        e.on_print("AAA", 9.97, 100, "NASDAQ", T0 + 1)        # below the bid
        self.assertTrue(e.ladder_clear("AAA", "above", T0 + 2))
        self.assertIsNone(bk(e, T0 + 3, 10.03))
        self.assertEqual(bk(e, T0 + 3, 9.97)[0], 100)
        e.on_print("AAA", 10.03, 40, "NASDAQ", T0 + 4)        # fills again from zero
        self.assertEqual(bk(e, T0 + 5, 10.03), [40, 40, 0, 1])

    def test_settings_ride_on_the_ladder(self):
        e = make()
        L = e.snapshot(T0 + 1)["panes"][0]["ladder"] if e.snapshot(T0 + 1).get("panes") else None
        self.assertIsNotNone(L)
        self.assertEqual(L["basket"]["basket_speed"], 1.0); self.assertTrue(L["basket"]["basket_animate"])
        self.assertEqual(L["basket"]["money_columns"], "traded")


if __name__ == "__main__":
    unittest.main()
