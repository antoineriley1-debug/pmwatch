import os
import tempfile
import unittest

from twiney.callbook import CallBook

CFG = {"callbook": {"enabled": True, "target_atr": 0.5, "stop_atr": 0.25}, "score": {"hit_atr": 0.1},
       "levels": {"took_hold_minutes": 5}, "flow": {"min_premium": 250000}}


def row(t, sym="AAA", kind="LEVEL BUYERS TOOK", d=1, p0=100.0, atr=2.0):
    return {"t": t, "symbol": sym, "kind": kind, "dir": d, "p0": p0, "atr": atr, "src": "live", "reads": {"money": "WITH"}}


CTX = {"tape": [{"t": 1, "price": 100.0, "size": 300, "side": "buy"}], "book": {"bids": [[99.99, 500, 1]], "asks": [[100.01, 400, 1]]},
       "control": "BUYERS IN CONTROL", "flow": [{"t": 1, "cp": "C", "strike": 105, "premium": 300000, "side": "ask"}],
       "candles": [[0, 99, 100, 98, 99.5, 10]], "levels": [{"name": "PRIOR DAY HIGH", "price": 100.0}], "plan": {},
       "replay": {"file": "rec.jsonl", "at": 1000.0}}


class CallBookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cb = CallBook(self.tmp.name, CFG)

    def tearDown(self):
        self.tmp.cleanup()

    def test_card_keeps_what_the_desk_saw(self):
        c = self.cb.add(row(1000.0), {"label": "BUYERS TOOK", "words": "Buyers took it", "lvl": 100.0}, CTX)
        self.assertEqual(c["control"], "BUYERS IN CONTROL")
        self.assertEqual(c["tape"][0]["side"], "buy")
        self.assertEqual(c["flow"][0]["premium"], 300000)
        self.assertEqual(c["reads"], {"money": "WITH"})
        self.assertEqual((c["target"], c["stop"], c["plan_src"]), (101.0, 99.5, "ATR"))
        self.assertEqual(c["settings"]["levels.took_hold_minutes"], 5)
        self.assertEqual(self.cb.wanted(1001.0), [{"id": c["id"], "symbol": "AAA"}])

    def test_outcomes_target_first_and_hold_grade(self):
        c = self.cb.add(row(1000.0), {"label": "BUYERS TOOK", "lvl": 100.0}, CTX)
        self.cb.tick(1100.0, {"AAA": 100.4})
        self.cb.tick(1300.0, {"AAA": 101.1})                   # target 101.00 reached before the stop
        self.assertEqual(c["first"], "TARGET")
        self.cb.grade("AAA", 100.0, "BUYERS TOOK", "STRONG")
        self.assertEqual(c["hold"], "STRONG")
        self.cb.tick(1900.0, {"AAA": 101.0})
        self.assertEqual(c["outcome"], "HIT")
        self.cb.tick(2800.0, {"AAA": 100.2})
        self.assertEqual(set(c["moves"]), {"300", "900", "1800"})
        self.assertNotIn(c["id"], self.cb.open)

    def test_stop_first_and_a_miss(self):
        c = self.cb.add(row(1000.0, d=-1), {"label": "SELLERS TOOK"}, CTX)
        self.cb.tick(1200.0, {"AAA": 100.6})                   # a short: the stop is 100.50
        self.assertEqual(c["first"], "STOP")
        self.cb.tick(1900.0, {"AAA": 100.6})
        self.assertEqual(c["outcome"], "MISS")

    def test_thumbs_note_and_read_back_from_disk(self):
        import time
        now = time.time()
        c = self.cb.add(row(now), {"label": "BUYERS TOOK"}, CTX)
        self.cb.rate(c["id"], thumb=-1, note="came back under in a minute")
        cb2 = CallBook(self.tmp.name, CFG)
        got = [x for x in cb2.read(1, now) if x["id"] == c["id"]][0]
        self.assertEqual((got["thumb"], got["note"]), (-1, "came back under in a minute"))

    def test_picture_saved_and_served(self):
        c = self.cb.add(row(1000.0), {"label": "BUYERS TOOK"}, CTX)
        name = self.cb.save_pic(c["id"], b"\xff\xd8\xff\xe0" + b"0" * 100)
        self.assertEqual(name, c["id"] + ".jpg")
        self.assertTrue(os.path.isfile(self.cb.pic_path(name)))
        self.assertIsNone(self.cb.save_pic(c["id"], b"<html>"))           # not a picture
        self.assertIsNone(self.cb.pic_path("../../etc/passwd"))
        self.assertEqual(self.cb.wanted(1001.0), [])

    def test_old_pictures_go_cards_stay(self):
        c = self.cb.add(row(1000.0), {"label": "BUYERS TOOK"}, CTX)
        name = self.cb.save_pic(c["id"], b"\xff\xd8" + b"0" * 10)
        p = self.cb.pic_path(name)
        os.utime(p, (0, 0))
        self.cb.prune(61 * 86400)
        self.assertIsNone(self.cb.pic_path(name))

    def test_weekly_review_worst_first_and_settings_before_after(self):
        cards = []
        for i, (kind, out, v) in enumerate([("A", "HIT", 5), ("A", "HIT", 5), ("A", "MISS", 3), ("B", "MISS", 5), ("B", "MISS", 5)]):
            cards.append({"id": str(i), "t": 1000.0 + i, "kind": kind, "outcome": out, "moves": {"900": 0.2 if out == "HIT" else -0.2},
                          "atr": 2.0, "thumb": 0, "first": None, "settings": {"levels.took_hold_minutes": v}})
        r = CallBook.review(cards)
        self.assertEqual([k["kind"] for k in r["kinds"]], ["B", "A"])      # worst first
        self.assertEqual(r["kinds"][1]["hit_pct"], 67)
        t = r["tuning"][0]
        self.assertEqual(t["setting"], "levels.took_hold_minutes")
        self.assertEqual([v["value"] for v in t["values"]], [5, 3])


if __name__ == "__main__":
    unittest.main()
