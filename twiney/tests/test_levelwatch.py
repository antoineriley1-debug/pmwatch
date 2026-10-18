import unittest

from twiney.levelwatch import LevelWatch

CFG = {"took_hold_minutes": 0, "zone_ticks": 3, "zone_atr_pct": 0, "away_ticks": 8, "away_atr_pct": 0, "hold_seconds": 60, "repeat_seconds": 300}
L = [{"price": 100.00, "name": "PRIOR DAY HIGH", "say": "yesterday's high", "code": "PDH"}]


REACT = ("REJECTED", "BOUNCED", "BUYERS TOOK", "SELLERS TOOK")


def run(path, t0=0.0, step=1.0, lw=None, everything=False):
    lw = lw or LevelWatch()
    out = []
    for i, p in enumerate(path):
        out += lw.update(t0 + i * step, p, L, 0.01, 2.0, CFG)
    return (out if everything else [e for e in out if e["kind"] in REACT]), lw


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


class ApproachTests(unittest.TestCase):
    def test_coming_into_then_at_then_rejected(self):
        ev, _ = run([99.80, 99.88, 99.95, 99.99, 100.00, 99.92, 99.85], everything=True)
        self.assertEqual([e["kind"] for e in ev], ["COMING INTO", "AT", "REJECTED"])
        self.assertEqual(ev[0]["from"], "below")

    def test_moving_away_is_not_coming_into(self):
        ev, _ = run([99.95, 99.93, 99.91, 99.90], everything=True)
        self.assertNotIn("COMING INTO", [e["kind"] for e in ev])


class ComingIntoNeedsARealMove(unittest.TestCase):
    """The AMD video: VWAP 13 cents under, price dipped a tick and broke out. That is not coming into VWAP."""
    VW = [{"price": 33.11, "name": "VWAP", "say": "VWAP", "code": "VWAP"}]

    def go(self, path, levels=None):
        lw, out = LevelWatch(), []
        for i, p in enumerate(path):
            out += lw.update(float(i), p, levels or self.VW, 0.01, 0.8, CFG)
        return [e["kind"] for e in out]

    def test_one_tick_dip_is_not_coming_into(self):
        self.assertNotIn("COMING INTO", self.go([33.18, 33.18, 33.17, 33.17]))

    def test_a_real_move_down_into_it_is(self):
        self.assertIn("COMING INTO", self.go([33.22, 33.20, 33.18, 33.16]))

    def test_a_level_in_between_comes_first(self):
        lv = self.VW + [{"price": 33.14, "name": "PRIOR DAY HIGH", "say": "yesterday's high", "code": "PDH"}]
        lw, out = LevelWatch(), []
        for i, p in enumerate([33.22, 33.20, 33.18, 33.16]):
            out += lw.update(float(i), p, lv, 0.01, 0.8, CFG)
        self.assertEqual([e["name"] for e in out if e["kind"] == "COMING INTO"], ["PRIOR DAY HIGH"])


HOLD = dict(CFG, took_hold_minutes=5, grade_minutes=10, dip_cents=2, dip_atr_pct=0, touch_minutes=30)


def walk(path, cfg=HOLD):
    """path: [(seconds, price)] held until the next point, read once a second."""
    lw, out, t = LevelWatch(), [], 0.0
    for (t0, px), nxt in zip(path, path[1:] + [(path[-1][0] + 1, path[-1][1])]):
        t = float(t0)
        while t < nxt[0]:
            out += lw.update(t, px, L, 0.01, 2.0, cfg)
            t += 1.0
    return out


class TookHoldTests(unittest.TestCase):
    """TOOK only after a close through it and 5 minutes holding; 10 minutes after, how it held."""

    def kinds(self, out):
        return [(e["kind"], e.get("grade")) for e in out if e["kind"] in ("BUYERS TOOK", "SELLERS TOOK", "HELD")]

    def test_not_taken_before_five_minutes(self):
        out = walk([(0, 99.80), (1, 99.99), (2, 100.10), (200, 100.10)])
        self.assertEqual(self.kinds(out), [])

    def test_taken_after_five_minutes_then_strong(self):
        out = walk([(0, 99.80), (1, 99.99), (2, 100.40), (1000, 100.40)])
        took = [e for e in out if e["kind"] == "BUYERS TOOK"][0]
        self.assertEqual(took["minutes"], 5)
        self.assertGreaterEqual(took["t"] - took["since"], 300)
        self.assertEqual(self.kinds(out), [("BUYERS TOOK", None), ("HELD", "STRONG")])

    def test_a_dip_back_through_restarts_the_clock(self):
        out = walk([(0, 99.80), (1, 99.99), (2, 100.40), (200, 99.95), (205, 100.40), (480, 100.40)])
        self.assertEqual(self.kinds(out), [])                # 200 + 300 not reached by 480
        out = walk([(0, 99.80), (1, 99.99), (2, 100.40), (200, 99.95), (205, 100.40), (520, 100.40)])
        self.assertEqual(self.kinds(out), [("BUYERS TOOK", None)])

    def test_a_hair_under_does_not_restart(self):
        out = walk([(0, 99.80), (1, 99.99), (2, 100.40), (100, 99.99), (110, 100.40), (380, 100.40)])
        self.assertEqual(self.kinds(out), [("BUYERS TOOK", None)])

    def test_came_back_to_test_it_and_held(self):
        out = walk([(0, 99.80), (1, 99.99), (2, 100.40), (400, 100.02), (420, 100.40), (1000, 100.40)])
        self.assertEqual(self.kinds(out)[-1], ("HELD", "HOLDING"))

    def test_dipped_under_twice_is_not_strong(self):
        out = walk([(0, 99.80), (1, 99.99), (2, 100.40), (400, 99.95), (410, 100.40), (450, 99.95), (460, 100.40),
                    (1000, 100.40)])
        held = [e for e in out if e["kind"] == "HELD"][0]
        self.assertEqual((held["grade"], held["dips"]), ("NOT STRONG", 2))

    def test_back_under_at_ten_minutes_is_lost(self):
        out = walk([(0, 99.80), (1, 99.99), (2, 100.40), (550, 99.95), (1000, 99.95)])
        self.assertEqual(self.kinds(out)[-1], ("HELD", "LOST"))

    def test_sellers_mirrored(self):
        out = walk([(0, 100.20), (1, 100.01), (2, 99.60), (1000, 99.60)])
        self.assertEqual(self.kinds(out), [("SELLERS TOOK", None), ("HELD", "STRONG")])
