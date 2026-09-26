import unittest

from twiney import narrative

PLAY = {"side": "long", "trigger": 10.00, "second_entry": 9.90}


class NarrativeTests(unittest.TestCase):
    def test_proximity(self):
        self.assertEqual(narrative.proximity_line(PLAY, 10.00)[1], "at")
        text, where = narrative.proximity_line(PLAY, 10.04)
        self.assertEqual(where, "near")
        self.assertIn("approaching your trigger 10.00 — 4¢ above it", text)
        self.assertEqual(narrative.proximity_line(PLAY, 12.0)[1], "far")

    def test_reload_headline_and_play_context(self):
        levels = [{"price": 10.0, "side": "ask", "role": "trigger", "state": "RELOAD", "displayed": 1500,
                   "absorbed_total": 6200, "absorbed_window": 6200, "refreshes": 5,
                   "last_verdict": None, "last_verdict_age": None}]
        head, tone, lines = narrative.story(PLAY, 9.99, levels, [], None, 100.0, [])
        self.assertEqual(tone, "reload")
        self.assertIn("SELLER keeps reloading at 10.00", head)
        self.assertIn("6,200", head)
        self.assertTrue(any("CLEANED UP here = the break is real" in l for l in lines))

    def test_fresh_verdict_wins(self):
        alert = {"t": 95.0, "label": "PULLED", "side": "bid", "price": 9.9, "role": "second_entry", "absorbed": 0}
        head, tone, _ = narrative.story(PLAY, 9.95, [], [], None, 100.0, [alert])
        self.assertEqual(tone, "pulled")
        self.assertIn("BUYER at 9.90 (your 2nd entry) PULLED", head)

    def test_level_holding(self):
        bars = [[i * 60, 9.95, 10.00, 9.94, 9.97, 100, 0, 0] for i in range(5)]
        _, _, lines = narrative.story(PLAY, 9.97, [], bars, None, 400.0, [])
        self.assertTrue(any("tested your trigger 10.00 5x" in l for l in lines))


if __name__ == "__main__":
    unittest.main()
