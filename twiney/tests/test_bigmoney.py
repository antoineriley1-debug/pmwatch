import datetime as dt
import os
import tempfile
import unittest

from twiney.bigmoney import BigMoney


def _p(t, cp="C", strike=130.0, exp="2026-10-16", size=1000, price=6.0, side="ask", spot=128.4):
    return {"t": t, "symbol": "NVDA", "cp": cp, "strike": strike, "expiry": exp, "size": size, "price": price,
            "premium": size * price * 100, "spot": spot, "side": side, "kind": "sweep", "vid": None}


NOW = dt.datetime(2026, 10, 1, 15, 0, tzinfo=dt.timezone.utc).timestamp()


class BigMoneyTests(unittest.TestCase):
    def test_only_big_prints_are_remembered_and_survive_a_restart(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "big.jsonl")
            bm = BigMoney({"big_money_min_premium": 500000}, path)
            self.assertTrue(bm.add(_p(NOW - 3 * 86400), NOW))            # $600K
            self.assertFalse(bm.add(_p(NOW, size=10), NOW))                 # $6K: too small
            self.assertFalse(bm.add(_p(NOW - 3 * 86400), NOW))            # same print twice
            bm2 = BigMoney({"big_money_min_premium": 500000}, path)
            self.assertEqual(len(bm2.items), 1)

    def test_open_calls_underwater_and_in_profit(self):
        p = _p(NOW - 3 * 86400)                                            # 1000 x 130C @ 6.00 = $600K, breakeven 136
        r = BigMoney.judge(p, 131.0, NOW)
        self.assertEqual(r["status"], "BUYERS UNDERWATER")
        self.assertEqual((r["breakeven"], r["value"], r["pnl"]), (136.0, 100000, -500000))
        self.assertIn("under the 136.00 breakeven", r["text"])
        r = BigMoney.judge(p, 140.0, NOW)
        self.assertEqual(r["status"], "BUYERS IN PROFIT")
        self.assertEqual(r["value"], 1000000)

    def test_expired_worthless_uses_the_expiry_close(self):
        p = _p(NOW - 20 * 86400, exp="2026-09-25")
        r = BigMoney.judge(p, 140.0, NOW, close_on=lambda d: 128.0)       # closed under the strike that day
        self.assertEqual(r["status"], "EXPIRED WORTHLESS")
        self.assertIn("the buyers lost all $600K", r["text"])

    def test_puts_and_sellers_side(self):
        p = _p(NOW - 86400, cp="P", strike=125.0, price=3.0, side="bid")  # 1000 x 125P sold at the bid, $300K
        r = BigMoney.judge(p, 120.0, NOW)                                 # stock under the 122 breakeven
        self.assertEqual(r["who"], "SELLERS")
        self.assertEqual(r["status"], "SELLERS UNDERWATER")
        self.assertFalse(r["good"])


if __name__ == "__main__":
    unittest.main()
