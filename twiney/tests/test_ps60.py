import unittest

from twiney import ps60
from twiney.config import DEFAULTS

CFG = DEFAULTS["ps60"]
# a Tuesday 9:30 New York, in summer (UTC-4)
OPEN = 1758029400.0  # 2025-09-16 13:30 UTC


def bars(seq, start=OPEN):
    """seq of (o, h, l, c) -> 1-minute bars."""
    return [[start + i * 60, o, h, l, c, 1000, 0, 0] for i, (o, h, l, c) in enumerate(seq)]


class SecondEntryTests(unittest.TestCase):
    play = {"symbol": "T", "side": "long", "trigger": 736.70, "target": 745.0, "stop": 733.0, "active": True}

    def test_cheat_sheet_example(self):
        # break 736.70 -> new high 738.90 -> retrace -> back through 738.90 on a new candle
        seq = [(736.0, 736.5, 735.8, 736.4), (736.4, 737.5, 736.3, 737.4), (737.4, 738.9, 737.2, 738.5),
               (738.5, 738.7, 737.6, 737.8), (737.8, 738.2, 737.5, 738.0)]
        se = ps60.second_entry(bars(seq), self.play, OPEN + 5 * 60, CFG)
        self.assertEqual(se["state"], ps60.RETRACE)
        self.assertEqual(se["extreme"], 738.9)
        self.assertIn("SECOND ENTRY = through 738.90", se["text"])
        seq.append((738.0, 739.2, 737.9, 739.1))
        se = ps60.second_entry(bars(seq), self.play, OPEN + 6 * 60, CFG)
        self.assertEqual(se["state"], ps60.SECOND_ENTRY)
        self.assertEqual(se["second_entry"], 738.9)
        self.assertEqual(se["build"], "building")
        g = ps60.grade(self.play, 739.1, se, ps60.measured_potential(self.play, 739.1, 5.0, CFG), 100, True,
                       DEFAULTS["trading"])
        self.assertEqual(g["grade"], "READY")

    def test_same_candle_never_counts_and_failure_resets(self):
        # the candle that makes the high can't also be the second entry
        seq = [(736.0, 737.0, 735.9, 736.9), (736.9, 738.0, 736.8, 737.9)]
        se = ps60.second_entry(bars(seq), self.play, OPEN + 2 * 60, CFG)
        self.assertEqual(se["state"], ps60.BROKE)
        # closes back under the pivot: back to waiting, one failure on the board
        seq.append((737.9, 737.9, 735.0, 735.5))
        se = ps60.second_entry(bars(seq), self.play, OPEN + 3 * 60, CFG)
        self.assertEqual((se["state"], se["fails"]), (ps60.IDLE, 1))

    def test_short_mirror_and_not_building(self):
        play = dict(self.play, side="short", trigger=241.20, target=236.5, stop=243.3)
        seq = [(241.5, 241.6, 240.9, 241.0), (241.0, 241.1, 240.2, 240.4), (240.4, 240.9, 240.3, 240.8),
               (240.8, 240.9, 240.1, 240.5), (240.5, 240.7, 240.4, 240.6), (240.6, 240.8, 240.3, 240.7)]
        se = ps60.second_entry(bars(seq), play, OPEN + 6 * 60 + 200, CFG)
        self.assertEqual(se["state"], ps60.SECOND_ENTRY)
        self.assertEqual(se["second_entry"], 240.2)
        self.assertEqual(se["build"], "not building")
        g = ps60.grade(play, 240.7, se, ps60.measured_potential(play, 240.7, 4.0, CFG), 100, True, DEFAULTS["trading"])
        self.assertEqual(g["grade"], "WATCH")


class MeasuredPotentialTests(unittest.TestCase):
    def test_mp_atr_and_pass(self):
        play = {"side": "long", "trigger": 100.0, "target": 101.0, "stop": 99.0}
        mp = ps60.measured_potential(play, 100.2, 4.0, CFG)
        self.assertEqual((mp["dollars"], mp["ratio"], mp["verdict"]), (0.8, 0.2, "THIN"))
        se = {"state": ps60.IDLE, "build": None, "extreme": None, "second_entry": None, "fails": 0}
        g = ps60.grade(play, 100.2, se, mp, 100, True, DEFAULTS["trading"])
        self.assertEqual(g["grade"], "PASS")
        self.assertIn("THIN", g["why"])
        self.assertEqual(ps60.measured_potential(dict(play, target=None), 100.2, 4.0, CFG)["verdict"], "NO TARGET")
        g = ps60.grade(dict(play, stop=None), 100.2, se, ps60.measured_potential(play, 100.2, 1.0, CFG), 100, False,
                       DEFAULTS["trading"])
        self.assertEqual(g["grade"], "PASS")
        self.assertIn("risk not known", g["why"])
        self.assertFalse(g["gates"][3]["ok"])

    def test_atr_from_daily(self):
        daily = [[0, 10, 11, 9, 10.5], [1, 10.5, 12, 10, 11.5], [2, 11.5, 12, 10.5, 11]]
        self.assertEqual(ps60.atr(daily), 1.75)
        self.assertIsNone(ps60.atr(daily[:1]))


class SneakyAndRemountTests(unittest.TestCase):
    def test_sneaky_supply_inside_macro(self):
        # 60m candles: macro 95–105, three candles rejected at 100.0 in the middle
        seq = []
        for h, l in [(105, 100), (101, 96), (98, 95), (100.0, 98.5), (99.9, 98.2), (100.0, 98.6), (99.0, 97.5)]:
            for m in range(60):
                seq.append((l + 0.5, h, l, l + 0.5))
        sp = ps60.sneaky_pivots(bars(seq), 2.0, CFG)
        sup = [s for s in sp if s["kind"] == "supply"]
        self.assertTrue(sup, sp)
        self.assertEqual((sup[0]["price"], sup[0]["touches"], sup[0]["mp"]), (100.0, 3, 5.0))
        self.assertIn("SNEAKY PIVOT · SUPPLY", sup[0]["label"])
        # macro edges never qualify: a lone candle at the top is not a sneaky pivot
        self.assertFalse([s for s in sp if s["price"] == 105])

    def test_remount_and_rejection(self):
        level = 50.0
        seq = [(50.2, 50.3, 50.1, 50.2), (50.1, 50.2, 49.6, 49.7), (49.7, 49.8, 49.5, 49.6), (49.6, 50.3, 49.6, 50.2)]
        ev = ps60.remount(bars(seq), level, OPEN + 4 * 60, CFG)
        self.assertEqual((ev["kind"], ev["extreme"]), ("remount", 49.5))
        seq2 = [(49.8, 49.9, 49.7, 49.8), (49.8, 50.4, 49.8, 50.3), (50.3, 50.5, 50.2, 50.4), (50.4, 50.4, 49.7, 49.8)]
        ev = ps60.remount(bars(seq2), level, OPEN + 4 * 60, CFG)
        self.assertEqual((ev["kind"], ev["extreme"]), ("rejection", 50.5))
        self.assertIsNone(ps60.remount(bars(seq[:2]), level, OPEN + 2 * 60, CFG))

    def test_cash_flow_legs(self):
        play = {"target": 12.0}
        legs = ps60.cash_flow_legs(play, "BUY", 100, 10.0, DEFAULTS["trading"]["scale_plan"]["cash_flow"])
        self.assertEqual([(l["role"], l["qty"], l["price"]) for l in legs],
                         [("cash_flow_1", 50, 10.5), ("cash_flow_2", 25, 11.5), ("runner", 25, 12.0)])


class LanguageLockTests(unittest.TestCase):
    def test_no_forbidden_words_in_ps60_text(self):
        import re
        src = open(ps60.__file__, encoding="utf-8").read()
        strings = re.findall(r'"([^"\n]*)"', src)
        for word in ("zone", "door", "ribbon", "box "):
            self.assertFalse([s for s in strings if word in s.lower()], word)


if __name__ == "__main__":
    unittest.main()
