"""KEY LEVEL calls are exact: no premarket close before 9:30 (it would move with price), AT only within a couple of
ticks, and an AT a few cents off the level says how far under / over price really is."""
import unittest

from twiney.levelwatch import LevelWatch

CFG = {"zone_ticks": 2, "zone_atr_pct": 1, "near_ticks": 6, "near_atr_pct": 8, "away_ticks": 8, "away_atr_pct": 10,
       "hold_seconds": 60, "repeat_seconds": 300, "touch_minutes": 15}
PMC = [{"price": 337.19, "name": "PREMARKET CLOSE", "say": "the premarket close", "code": "PMC"}]


class ExactLevelTests(unittest.TestCase):
    def run_path(self, prices, atr=5.0):
        lw, out = LevelWatch(), []
        for i, p in enumerate(prices):
            out += lw.update(100.0 + i, p, PMC, 0.01, atr, CFG)
        return out

    def test_twenty_cents_under_is_not_at(self):
        ev = self.run_path([336.70, 336.80, 336.90, 336.95, 336.99, 336.99])     # 20 cents under, AAPL ATR 5
        self.assertNotIn("AT", [e["kind"] for e in ev])

    def test_at_carries_the_real_price(self):
        ev = [e for e in self.run_path([336.80, 336.95, 337.10, 337.15, 337.16]) if e["kind"] == "AT"]
        self.assertEqual(len(ev), 1)
        self.assertAlmostEqual(ev[0]["last"], 337.15); self.assertGreater(ev[0]["zone"], 0)

    def test_no_premarket_close_before_930(self):
        from twiney import studies

        class St:
            m5x = {}
            bars = {}
        # 9:00 New York on a weekday: premarket bars up to now
        import datetime, zoneinfo
        ny = zoneinfo.ZoneInfo("America/New_York")
        t0 = datetime.datetime(2026, 10, 8, 8, 0, tzinfo=ny).timestamp()
        st = St()
        for i in range(60):
            st.bars[int(t0) + 60 * i] = [100 + i * 0.01, 100.5, 99.5, 100 + i * 0.01, 1000]
        t = datetime.datetime(2026, 10, 8, 9, 0, 30, tzinfo=ny).timestamp()
        s = studies.session_levels(st, t)
        self.assertIsNone(s["pmc"]); self.assertFalse(s["pm_done"])
        t2 = datetime.datetime(2026, 10, 8, 9, 45, tzinfo=ny).timestamp()
        self.assertEqual(studies.session_levels(st, t2)["pmc"], 100.59)


if __name__ == "__main__":
    unittest.main()


class BounceRejectTests(unittest.TestCase):
    """Above the premarket high, down into it, does not go through, back up = BOUNCED. Below it, up into it, back
    down = REJECTED. Price does not have to print exactly on the level: a test that turns back counts."""
    L = [{"price": 100.00, "name": "PREMARKET HIGH", "say": "the premarket high", "code": "PMH"}]

    def run_path(self, prices):
        lw, out = LevelWatch(), []
        for i, p in enumerate(prices):
            out += lw.update(100.0 + i, p, self.L, 0.01, 2.0, CFG)
        return [e["kind"] for e in out]

    def test_bounce_off_it_from_above_without_touching(self):
        ev = self.run_path([100.60, 100.40, 100.20, 100.06, 100.05, 100.15, 100.25, 100.40])
        self.assertIn("BOUNCED", ev); self.assertNotIn("AT", ev)

    def test_reject_from_below(self):
        ev = self.run_path([99.40, 99.60, 99.80, 99.95, 100.00, 99.90, 99.80, 99.70])
        self.assertIn("REJECTED", ev); self.assertIn("AT", ev)

    def test_through_and_held_is_taken_not_rejected(self):
        ev = self.run_path([99.40, 99.70, 99.90, 100.00] + [100.20] * 70)
        self.assertIn("BUYERS TOOK", ev); self.assertNotIn("REJECTED", ev)
