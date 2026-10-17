import os
import tempfile
import unittest

from twiney.phrases import KINDS, Phrases, check


F = {"who": "Buyers", "level": "the prior-day high", "price": "185.55", "ago": "five minutes ago", "last": "186.10"}


class PhraseTests(unittest.TestCase):
    def test_every_built_in_line_passes_its_own_check(self):
        for k, v in KINDS.items():
            self.assertIsNone(check(k, v["default"]), k)

    def test_a_version_must_keep_the_numbers_and_twineys_words(self):
        self.assertIn("leaves out", check("level.took", "{who} took {level} at {price}"))
        self.assertIn("does not have", check("level.took", "{who} took {level} at {price} {ago}, price {last}, {strike}"))
        self.assertIn("resistance", check("level.took", "{who} broke resistance {level} at {price} {ago}. Price {last}"))
        self.assertIn("have the tape", check("level.took", "{who} have the tape: took {level} at {price} {ago}. Price {last}"))
        self.assertIn("at the ask", check("level.took", "{who} took {level} at {price} {ago}, at the ask. Price {last}"))
        self.assertIsNone(check("level.took", "{who} grabbed {level} at {price} {ago} and are sitting on it. Price {last}"))

    def test_ai_versions_wait_for_approval_and_only_approved_are_spoken(self):
        ph = Phrases(None, {})
        added, refused = ph.add_ai("level.took", "1. {who} grabbed {level} at {price} {ago}, sitting on it. Price {last}\n"
                                                "- {who} took {level} at {price}\n"
                                                "Here are some versions:")
        self.assertEqual(len(added), 1)
        self.assertEqual(added[0]["status"], "pending")
        self.assertEqual(len(refused), 1)
        default = KINDS["level.took"]["default"].format(**F)
        said = {ph.pick("level.took", F, default) for _ in range(6)}
        self.assertEqual(said, {default})                         # pending: never spoken
        ph.set_status("level.took", added[0]["id"], "approved")
        said = [ph.pick("level.took", F, default) for _ in range(4)]
        self.assertIn("Buyers grabbed the prior-day high at 185.55 five minutes ago, sitting on it. Price 186.10", said)
        self.assertIn(default, said)                              # the desk's own line stays in the turn

    def test_twineys_own_line_is_approved_and_kept_on_disk(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "phrases.json")
            ph = Phrases(path, {})
            row, why = ph.add("flow.hit", "{premium} hit {symbol} {strike} {what}{expiring}, buyers paid up for it")
            self.assertIsNone(why)
            self.assertEqual(row["status"], "approved")
            self.assertEqual(Phrases(path, {}).approved("flow.hit"), [row["text"]])
            self.assertEqual(ph.add("flow.hit", row["text"])[1], "already on the list")

    def test_off_switch_speaks_the_built_in_line_only(self):
        ph = Phrases(None, {"phrases": {"use_approved": False}})
        ph.add("level.rejected", "Sellers pushed it back at {level}, {price}")
        self.assertEqual({ph.pick("level.rejected", {"level": "VWAP", "price": "10.00"}, "X") for _ in range(4)}, {"X"})


class EnginePhraseTests(unittest.TestCase):
    def test_level_call_uses_an_approved_version_in_turn(self):
        from twiney.engine import Engine
        e = Engine.__new__(Engine)
        e.phrases = Phrases(None, {})
        e.phrases.add("level.took", "{who} grabbed {level} at {price} {ago}, sitting on it. Price {last}")
        ev = {"kind": "BUYERS TOOK", "minutes": 5}
        said = [e._took_words(ev, "the prior-day high", 185.55, 186.10) for _ in range(2)]
        self.assertTrue(any(s.startswith("Buyers grabbed the prior-day high") for s in said), said)
        self.assertTrue(any(s.startswith("Buyers took the prior-day high at 185.55 five minutes ago") for s in said), said)


if __name__ == "__main__":
    unittest.main()
