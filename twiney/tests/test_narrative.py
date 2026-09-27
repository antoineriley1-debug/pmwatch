import unittest

from twiney import narrative

PLAY = {"side": "long", "trigger": 10.00, "second_entry": 9.90}


class NarrativeTests(unittest.TestCase):
    def test_proximity(self):
        self.assertEqual(narrative.proximity_line(PLAY, 10.00)[1], "at")
        text, where = narrative.proximity_line(PLAY, 10.04)
        self.assertEqual(where, "near")
        self.assertIn("coming into your trigger 10.00 — 4¢ above it", text)
        self.assertEqual(narrative.proximity_line(PLAY, 12.0)[1], "far")

    def test_reload_headline_and_play_context(self):
        levels = [{"price": 10.0, "side": "ask", "role": "trigger", "state": "RELOAD", "displayed": 1500,
                   "absorbed_total": 6200, "absorbed_window": 6200, "refreshes": 5,
                   "last_verdict": None, "last_verdict_age": None}]
        head, tone, lines = narrative.story(PLAY, 9.99, levels, [], None, 100.0, [])
        self.assertEqual(tone, "reload")
        self.assertIn("RELOAD SELLER at 10.00", head)
        self.assertIn("6,200", head)
        self.assertIn("resistance is holding", head)
        self.assertTrue(any("supply sitting on your trigger" in l for l in lines))

    def test_fresh_verdict_wins(self):
        alert = {"t": 95.0, "label": "PULLED", "side": "bid", "price": 9.9, "role": "second_entry", "absorbed": 0}
        head, tone, _ = narrative.story(PLAY, 9.95, [], [], None, 100.0, [alert])
        self.assertEqual(tone, "pulled")
        self.assertIn("PULLED — the BUYER at 9.90 (your 2nd entry) vanished", head)

    def test_level_holding(self):
        bars = [[i * 60, 9.95, 10.00, 9.94, 9.97, 100, 0, 0] for i in range(5)]
        _, _, lines = narrative.story(PLAY, 9.97, [], bars, None, 400.0, [])
        self.assertTrue(any("Resistance at your trigger 10.00 is holding: tested 5x" in l for l in lines), lines)


if __name__ == "__main__":
    unittest.main()


class TrapTests(unittest.TestCase):
    def test_trapped_longs_line_and_reloader_map(self):
        trap = {"longs": {"shares": 12400, "low": 10.05, "high": 10.12, "avg": 10.08, "heavy": True}, "shorts": None,
                "window_minutes": 10}
        reloaders = {"below": [], "above": [{"price": 10.10, "side": "ask", "kind": "confirmed", "role": "trigger",
                                             "refills": 5, "absorbed": 6200, "showing": 900}]}
        lines = narrative.trap_lines(trap, reloaders, {"side": "short"}, 10.0)
        self.assertEqual(len(lines), 1)
        self.assertIn("TRAPPED LONGS (heavy): 12,400 shares paid up between 10.05 and 10.12", lines[0])
        self.assertIn("seller reloading at 10.10 absorbed them", lines[0])
        self.assertIn("what your short wants", lines[0])
        self.assertEqual(narrative.reloader_line(reloaders), "Reloaders — above: SELLER 10.10 ×5, 6,200 hit")
        self.assertIsNone(narrative.reloader_line({"below": [], "above": []}))
        self.assertEqual(narrative.trap_lines(None, None, {"side": "long"}, 10.0), [])
