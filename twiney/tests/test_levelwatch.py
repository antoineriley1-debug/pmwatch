import unittest

from twiney.levelwatch import LevelWatch

CFG = {"zone_ticks": 3, "zone_atr_pct": 0, "away_ticks": 8, "away_atr_pct": 0, "hold_seconds": 60, "repeat_seconds": 300}
L = [{"price": 100.00, "name": "PRIOR DAY HIGH", "say": "yesterday's high", "code": "PDH"}]


def run(path, t0=0.0, step=1.0, lw=None):
    lw = lw or LevelWatch()
    out = []
    for i, p in enumerate(path):
        out += lw.update(t0 + i * step, p, L, 0.01, 2.0, CFG)
    return out, lw


class LevelWatchTests(unittest.TestCase):
    def test_rejected_from_below(self):
        ev, _ = run([99.80, 99.90, 99.99, 100.01, 99.95, 99.85])
        self.assertEqual([e["kind"] for e in ev], ["REJECTED"])
        self.assertEqual(ev[0]["say"], "yesterday's high")

    def test_bounced_from_above(self):
        ev, _ = run([100.20, 100.05, 100.00, 100.02, 100.10, 100.15])
        self.assertEqual([e["kind"] for e in ev], ["BOUNCED"])

    def test_buyers_took_it_after_holding(self):
        path = [99.80, 99.99] + [100.10] * 70
        ev, _ = run(path)
        self.assertEqual([e["kind"] for e in ev], ["BUYERS TOOK"])

    def test_a_poke_through_that_comes_back_is_not_taken(self):
        path = [99.80, 99.99] + [100.10] * 30 + [99.95, 99.85]
        ev, _ = run(path)
        self.assertEqual([e["kind"] for e in ev], ["REJECTED"])

    def test_sellers_took_it(self):
        path = [100.30, 100.01] + [99.90] * 70
        ev, _ = run(path)
        self.assertEqual([e["kind"] for e in ev], ["SELLERS TOOK"])

    def test_no_repeat_inside_the_quiet_time(self):
        once = [99.80, 99.99, 99.85]
        ev, lw = run(once * 3)
        self.assertEqual(len(ev), 1)

    def test_far_away_price_does_nothing(self):
        ev, _ = run([95.0, 95.5, 96.0, 95.2])
        self.assertEqual(ev, [])
