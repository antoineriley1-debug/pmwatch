"""THE LEVEL FOLLOW-UP: after the back and forth at a level, one call 5-7 minutes later saying how it came out."""
import unittest

from twiney.levelverdict import LevelFollowUp, PHRASES, label
from twiney.levelwatch import LevelWatch

CFG = {"zone_ticks": 2, "zone_atr_pct": 1, "near_ticks": 6, "near_atr_pct": 8, "away_ticks": 8, "away_atr_pct": 10,
       "hold_seconds": 60, "repeat_seconds": 300, "touch_minutes": 15, "test_ticks": 4, "test_atr_pct": 3,
       "followup_min_minutes": 5, "followup_max_minutes": 7, "followup_min_alerts": 3, "followup_quiet_seconds": 60,
       "followup_recheck_minutes": 4}
L = [{"price": 100.00, "name": "PREMARKET HIGH", "say": "the premarket high", "code": "PMH"}]


def path(start, legs):
    """[(price, seconds)]: price walks to each target over that many seconds, one read a second."""
    out, p = [], start
    for target, secs in legs:
        for i in range(1, int(secs) + 1):
            out.append(round(p + (target - p) * i / secs, 2))
        p = target
    return out


def run(prices, atr=2.0):
    lw, fu, calls, verdicts = LevelWatch(), LevelFollowUp(), [], []
    for i, px in enumerate(prices):
        t = 1000.0 + i
        for ev in lw.update(t, px, L, 0.01, atr, CFG):
            calls.append((t, ev["kind"])); fu.note(ev, t)
        for v in fu.update(t, px, L, CFG, 0.01):
            verdicts.append((t, v, fu.words(v, v["say"], "100.00", f"{px:.2f}", "a few cents")))
    return calls, verdicts


CHOP_FROM_ABOVE = [(100.40, 5), (100.00, 20), (100.30, 20), (100.01, 20), (100.30, 20), (100.00, 20)]


class FollowUpTests(unittest.TestCase):
    def one(self, verdicts):
        self.assertEqual(len(verdicts), 1, [(t, v["outcome"]) for t, v, _w in verdicts])
        return verdicts[0]

    def timing(self, calls, t):
        mins = (t - calls[0][0]) / 60.0
        self.assertGreaterEqual(mins, 5.0); self.assertLessEqual(mins, 7.5)

    def test_defended(self):
        calls, vs = run(path(100.40, CHOP_FROM_ABOVE + [(100.35, 30), (100.35, 420)]))
        self.assertGreaterEqual(len(calls), 3)
        t, v, words = self.one(vs)
        self.assertEqual(v["outcome"], "DEFENDED"); self.assertEqual(label(v), "DEFENDED"); self.timing(calls, t)
        self.assertIn("uyers", words)

    def test_lost(self):
        calls, vs = run(path(100.40, CHOP_FROM_ABOVE + [(99.60, 30), (99.60, 420)]))
        t, v, words = self.one(vs)
        self.assertEqual(v["outcome"], "LOST"); self.assertEqual(label(v), "LOST"); self.timing(calls, t)

    def test_reclaimed(self):
        calls, vs = run(path(100.40, CHOP_FROM_ABOVE + [(99.60, 20), (99.60, 100), (100.40, 20), (100.40, 400)]))
        t, v, words = self.one(vs)
        self.assertEqual(v["outcome"], "RECLAIMED"); self.assertEqual(label(v), "RECLAIMED")

    def test_broke_through_from_below(self):
        legs = [(99.60, 5), (100.00, 20), (99.70, 20), (99.99, 20), (99.70, 20), (100.00, 20), (100.50, 30), (100.50, 420)]
        calls, vs = run(path(99.60, legs))
        t, v, words = self.one(vs)
        self.assertEqual(v["outcome"], "BROKE"); self.assertEqual(label(v), "BROKE THROUGH")

    def test_held_as_resistance(self):
        legs = [(99.60, 5), (100.00, 20), (99.70, 20), (99.99, 20), (99.70, 20), (100.00, 20), (99.65, 30), (99.65, 420)]
        calls, vs = run(path(99.60, legs))
        t, v, words = self.one(vs)
        self.assertEqual(v["outcome"], "DEFENDED"); self.assertEqual(label(v), "HELD AS RESISTANCE")
        self.assertIn("ellers", words)

    def test_still_on_it_looks_again_then_says_undecided(self):
        calls, vs = run(path(100.40, CHOP_FROM_ABOVE + [(100.00, 30), (100.00, 900)]))
        t, v, words = self.one(vs)
        self.assertEqual(v["outcome"], "UNDECIDED"); self.assertEqual(label(v), "STILL UNDECIDED")
        self.assertGreater((t - calls[0][0]) / 60.0, 8.0)       # the look again came first

    def test_one_or_two_calls_is_no_fight(self):
        calls, vs = run(path(100.40, [(100.30, 5), (100.30, 600)]))
        self.assertEqual(vs, [])

    def test_never_the_same_words_twice_running(self):
        fu = LevelFollowUp()
        v = {"outcome": "DEFENDED", "from": "above"}
        said = [fu.words(v, "the premarket high", "100.00", "100.30", "30 cents") for _ in range(len(PHRASES["DEFENDED_BUYERS"]) + 1)]
        for a, b in zip(said, said[1:]):
            self.assertNotEqual(a, b)
        self.assertEqual(len(set(said)), len(PHRASES["DEFENDED_BUYERS"]))

    def test_two_stocks_in_a_row_get_different_words(self):
        a, b = LevelFollowUp(), LevelFollowUp()
        v = {"outcome": "DEFENDED", "from": "below"}
        self.assertNotEqual(a.words(v, "VWAP", "1", "2", "3"), b.words(v, "VWAP", "1", "2", "3"))

    def test_no_banned_words(self):
        for opts in PHRASES.values():
            for w in opts:
                for bad in ("fading", "stale", "gone", "trigger", "dark", "iceberg"):
                    self.assertNotIn(bad, w.lower())


if __name__ == "__main__":
    unittest.main()


class CloseConfirmsLevelTests(unittest.TestCase):
    """SELLERS TOOK / LOST only on a candle CLOSE under the level (BUYERS TOOK / BROKE: a close over it)."""

    def run_closes(self, prices, closes_under):
        lw, fu, calls, verdicts = LevelWatch(), LevelFollowUp(), [], []
        for i, px in enumerate(prices):
            t = 1000.0 + i
            m = int(t // 60) * 60
            close = (m, closes_under(m - 60, prices[max(0, int(m - 1000) - 1)]))
            for ev in lw.update(t, px, L, 0.01, 2.0, CFG, close):
                calls.append((t, ev["kind"])); fu.note(ev, t)
            for v in fu.update(t, px, L, CFG, 0.01, close):
                verdicts.append(v["outcome"])
        return calls, verdicts

    def test_trading_under_without_a_close_under_is_not_taken(self):
        # every candle closes back over 100 (a wick under), price sits under it in between
        prices = path(100.40, CHOP_FROM_ABOVE + [(99.80, 30), (99.80, 400)])
        calls, vs = self.run_closes(prices, lambda t0, px: 100.05)
        self.assertNotIn("SELLERS TOOK", [k for _t, k in calls])
        self.assertNotIn("LOST", vs)

    def test_the_close_under_takes_it(self):
        prices = path(100.40, CHOP_FROM_ABOVE + [(99.80, 30), (99.80, 400)])
        calls, vs = self.run_closes(prices, lambda t0, px: px)
        self.assertIn("SELLERS TOOK", [k for _t, k in calls])
        self.assertIn("LOST", vs)
