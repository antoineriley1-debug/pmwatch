"""PACE OF TAPE: speed against the stock's own normal, and the calls at a level."""
import unittest

from twiney import pace
from twiney.config import DEFAULTS

CFG = dict(DEFAULTS["pace"])


def build(normal_sps=1000.0, minutes=20, end=10_000.0, price=100.0):
    """A book at a steady pace: one print a second, buyers and sellers even."""
    b = pace.PaceBook()
    t = end - minutes * 60
    while t < end - 15:
        b.add(t, price, normal_sps, "buy" if int(t) % 2 else "sell")
        t += 1.0
    return b, t


class PaceTests(unittest.TestCase):
    def test_normal_pace_reads_about_one(self):
        b, t = build()
        for k in range(15):
            b.add(t + k, 100.0, 1000.0, "buy" if k % 2 else "sell")
        p = pace.read(b, t + 15, 100.0, [], 0.01, CFG)
        self.assertEqual(p["state"], "NORMAL")
        self.assertAlmostEqual(p["ratio"], 1.0, delta=0.25)

    def test_breakout_with_speed_and_somebody_knows(self):
        b, t = build()
        # 30 s ago price was under 100.50; now it ran through on 4x the shares, buyers paying up
        for k in range(15):
            b.add(t + k, 100.40 + 0.02 * k, 4000.0, "buy")
        knows = {"C": {"knows": True, "cp": "C", "dollars": 640000, "prints": 6, "sweeps": 2, "top": {"strike": 105.0, "dte": 3}}, "P": {"knows": False}}
        p = pace.read(b, t + 15, 100.68, [(100.50, "PDH")], 0.01, CFG, knows=knows)
        self.assertEqual(p["call"], "BREAKOUT WITH SPEED")
        self.assertEqual(p["level"], [100.50, "PDH"])
        self.assertIn("SOMEBODY KNOWS SOMETHING $640K calls · 6 prints · 2 sweeps · 105 strike, 3d", p["flow"])
        self.assertIn(p["state"], ("FAST", "SURGE"))

    def test_break_without_speed(self):
        b, t = build()
        for k in range(15):
            b.add(t + k, 100.40 + 0.02 * k, 700.0, "buy")
        p = pace.read(b, t + 15, 100.68, [(100.50, "PDH")], 0.01, CFG)
        self.assertEqual(p["call"], "BREAKOUT WITHOUT SPEED")

    def test_stalling_into_a_level(self):
        b, t = build()
        for k in range(15):
            b.add(t + k, 100.47, 200.0, "buy")             # creeping up to 100.50 on a dried-up tape
        p = pace.read(b, t + 15, 100.47, [(100.50, "REJECT 20E")], 0.01, CFG)
        self.assertEqual(p["call"], "STALLING INTO")
        self.assertEqual(p["level"][1], "REJECT 20E")

    def test_speed_and_flow_anywhere(self):
        b, t = build()
        for k in range(15):
            b.add(t + k, 100.0, 4000.0, "buy")
        knows = {"C": {"knows": True, "cp": "C", "dollars": 300000, "prints": 4, "sweeps": 0, "top": {}}, "P": {"knows": False}}
        p = pace.read(b, t + 15, 100.0, [], 0.01, CFG, knows=knows)
        self.assertEqual(p["call"], "SPEED + FLOW")
        self.assertIn("calls hammered", p["level"][1])

    def test_warming_up(self):
        b = pace.PaceBook()
        b.add(100.0, 10.0, 100, "buy")
        self.assertEqual(pace.read(b, 101.0, 10.0, [], 0.01, CFG)["state"], "WARMING UP")


if __name__ == "__main__":
    unittest.main()


class PaceAuditTests(unittest.TestCase):
    def test_a_steady_tape_reads_normal_from_the_first_minutes(self):
        for minutes in (3, 5, 8):
            b = pace.PaceBook()
            end = 10_000.0
            t = end - minutes * 60
            while t < end:
                b.add(t, 100.0, 1000.0, "buy" if int(t) % 2 else "sell")
                t += 1.0
            p = pace.read(b, end, 100.0, [], 0.01, CFG)
            if p["state"] != "WARMING UP":
                self.assertEqual(p["state"], "NORMAL", minutes)
                self.assertAlmostEqual(p["ratio"], 1.0, delta=0.3)

    def test_quiet_tape_still_sees_a_level_below(self):
        b, t = build()
        # nothing printed 25-45 s ago (no price "30 s back"), price now just over support
        rows = [r for r in b.b if not (t - 60 <= r[0] <= t)]
        b.b.clear(); b.b.extend(rows)
        for k in range(15):
            b.add(t + k, 100.02, 200.0, "sell")
        p = pace.read(b, t + 15, 100.02, [(100.00, "PDL")], 0.01, CFG)
        self.assertEqual(p["level"], [100.00, "PDL"])


class NotDryingUpOnABreakout(unittest.TestCase):
    def test_buyers_lifting_into_a_level_is_not_stalling(self):
        b, t = build()
        for k in range(15):                                   # a little under normal, every print lifting the offer
            b.add(t + k, 100.40 + 0.005 * k, 700.0, "buy")
        p = pace.read(b, t + 15, 100.47, [(100.50, "HIGH OF DAY")], 0.01, CFG)
        self.assertNotEqual(p["call"], "STALLING INTO")

    def test_slowing_is_not_called_drying_up(self):
        b, t = build()
        for k in range(15):
            b.add(t + k, 100.47, 600.0, "buy" if k % 2 else "sell")
        p = pace.read(b, t + 15, 100.47, [(100.50, "REJECT 20E")], 0.01, CFG)
        self.assertEqual(p["call"], "STALLING INTO")
        self.assertIn("slowing", p["words"])
        self.assertNotIn("drying", p["words"])
