import tempfile
import unittest

from twiney.callbook import CallBook
from twiney.myread import MyRead

# Monday 2026-10-12 10:00 New York (14:00 UTC)
MON10 = 1791813600.0


class MyReadTests(unittest.TestCase):
    def test_today_until_the_close_and_week_until_friday(self):
        mr = MyRead(None)
        r = mr.set("aapl", "BULLISH", "over the 50-day", t=MON10, price=180.0)
        self.assertEqual(r["until"] - MON10, 6 * 3600)                      # 16:00 the same day
        self.assertEqual(mr.get("AAPL", MON10 + 3600)["read"], "BULLISH")
        self.assertIsNone(mr.get("AAPL", MON10 + 7 * 3600))                 # past the close: off
        w = mr.set("AMD", "BEARISH", week=True, t=MON10, price=150.0)
        self.assertEqual(w["until"] - MON10, 4 * 86400 + 6 * 3600)         # Friday 16:00

    def test_only_the_four_reads_and_clear(self):
        mr = MyRead(None)
        with self.assertRaises(ValueError):
            mr.set("AAPL", "LONG", t=MON10)
        mr.set("AAPL", "HANDS OFF", t=MON10)
        self.assertIsNone(mr.set("AAPL", None, t=MON10))
        self.assertEqual(mr.view(MON10), {})

    def test_against(self):
        self.assertTrue(MyRead.against("BULLISH", -1))
        self.assertFalse(MyRead.against("BULLISH", 1))
        self.assertTrue(MyRead.against("BEARISH", 1))
        self.assertTrue(MyRead.against("HANDS OFF", 1))
        self.assertFalse(MyRead.against("NEUTRAL", -1))

    def test_how_your_reads_did_kept_on_disk(self):
        with tempfile.TemporaryDirectory() as d:
            mr = MyRead(d)
            mr.set("AAPL", "BULLISH", t=MON10, price=180.0)
            mr.set("AMD", "BEARISH", t=MON10, price=150.0)
            mr.tick(MON10 + 6 * 3600 + 30, {"AAPL": 182.0, "AMD": 151.5})   # the close: AAPL right, AMD wrong
            rv = {x["read"]: x for x in MyRead(d).review()}
            self.assertEqual((rv["BULLISH"]["n"], rv["BULLISH"]["right_pct"]), (1, 100))
            self.assertEqual((rv["BEARISH"]["n"], rv["BEARISH"]["right_pct"]), (1, 0))
            self.assertEqual(MyRead(d).view(MON10 + 7 * 3600), {})

    def test_call_book_review_with_and_against_your_read(self):
        cards = [{"id": str(i), "t": 1.0 + i, "kind": "K", "dir": d, "outcome": o, "moves": {}, "atr": 1.0, "myread": r}
                 for i, (d, o, r) in enumerate([(1, "HIT", "BULLISH"), (1, "HIT", "BULLISH"), (-1, "MISS", "BULLISH"),
                                                (-1, "HIT", "BEARISH"), (1, "MISS", None)])]
        m = CallBook.review(cards)["myread"]
        self.assertEqual((m["with"]["n"], m["with"]["hit_pct"]), (3, 100))
        self.assertEqual((m["against"]["n"], m["against"]["hit_pct"]), (1, 0))


if __name__ == "__main__":
    unittest.main()
