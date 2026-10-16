"""DAN'S DAILY: the Market Notes email parsed with rules (watchlist rows, the flow lines, the date), read on a
schedule through Gmail, kept in the data folder, shown on the desk; off until a Gmail user + app password are set."""

import datetime as dt
import os
import tempfile
import time
import unittest
from zoneinfo import ZoneInfo

from helpers import cfg, plays
from twiney import danmail
from twiney.danmail import DanMail, parse, parse_message
from twiney.engine import Engine

NY = ZoneInfo("America/New_York")

SAMPLE = """\
https://example.com/

Hey Trader,

No video this evening.

Market Notes

CHIPS
Reports of a memory breakthrough hit the chip names overnight.

APPLE
Up on the day, record high.

Current Pivot Watchlist Oct 14, 2026

AAAA 76 Short 3⭐️
BBBB 229 3⭐️
CCCC 771.30 & 779.82 3⭐️
DDDD 156 Short 2⭐️
not a row at all

OPTION FLOW

BUYER 400 EEEE WKLY 1000C@15.00
BUYER 250 FFFF 11/20 270C
BUYER 2,700 GGGG 11/20 180C@5.40 1.4M
SELLER 100 HHHH 10/30 400P@6.50

*Setup Tier Rating System - 5 STARS Please see below.
*Watchlist Tier Ranking System 5 Star - A daily macro breakout.
"""


def at(y, m, d, hh, mm):
    return dt.datetime(y, m, d, hh, mm, tzinfo=NY).timestamp()


class ParseTests(unittest.TestCase):
    def test_rows_flow_date_and_notes(self):
        got = parse(SAMPLE)
        self.assertEqual(got["date"], "Oct 14, 2026")
        self.assertEqual([(r["symbol"], r["pivots"], r["side"], r["stars"]) for r in got["rows"]],
                         [("AAAA", [76.0], "short", 3), ("BBBB", [229.0], "long", 3), ("CCCC", [771.3, 779.82], "long", 3), ("DDDD", [156.0], "short", 2)])
        self.assertEqual(len(got["flow"]), 4)
        f = got["flow"]
        self.assertEqual((f[0]["who"], f[0]["size"], f[0]["symbol"], f[0]["expiry"], f[0]["strike"], f[0]["right"], f[0]["price"]), ("BUYER", 400, "EEEE", "WKLY", 1000.0, "C", 15.0))
        self.assertEqual((f[1]["price"], f[1]["premium"]), (None, None))
        self.assertEqual((f[2]["size"], f[2]["premium"]), (2700, "1.4M"))
        self.assertEqual((f[3]["who"], f[3]["right"]), ("SELLER", "P"))
        self.assertIn("CHIPS", got["notes"]); self.assertIn("record high", got["notes"])
        self.assertNotIn("Current Pivot", got["notes"])

    def test_nothing_is_guessed_from_an_email_without_a_list(self):
        got = parse("Hey, no notes tonight. See you tomorrow.\n")
        self.assertEqual((got["date"], got["rows"], got["flow"]), (None, [], []))

    def test_a_whole_message_plain_and_html(self):
        raw = ("From: Access A Trader <support@example.com>\r\nTo: you@example.com\r\nSubject: Market Notes - Watchlist 10/14\r\n"
               "Date: Tue, 13 Oct 2026 23:38:25 +0000\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n" + SAMPLE).encode("utf-8")
        got = parse_message(raw)
        self.assertEqual(got["subject"], "Market Notes - Watchlist 10/14"); self.assertEqual(len(got["rows"]), 4)
        html = "<html><body><p>Market Notes</p><p>Current Pivot Watchlist Oct 14, 2026</p><p>AAAA 76 Short 3⭐️</p><p>OPTION FLOW</p><p>BUYER 400 EEEE WKLY 1000C@15.00</p><p>*foot</p></body></html>"
        raw2 = ("From: a@b.c\r\nSubject: Watchlist\r\nContent-Type: text/html; charset=utf-8\r\n\r\n" + html).encode("utf-8")
        got2 = parse_message(raw2)
        self.assertEqual([r["symbol"] for r in got2["rows"]], ["AAAA"]); self.assertEqual(len(got2["flow"]), 1)


class DanMailTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.e = Engine(plays(), cfg())
        self.calls = []

    def tearDown(self):
        self.tmp.cleanup()

    def fetcher(self, user, pw, sender, subject):
        self.calls.append((user, pw, sender, subject))
        return dict(parse(SAMPLE), subject="Market Notes - Watchlist 10/14", **{"from": sender, "sent": "x"})

    def make(self, on=True, times=None):
        c = dict(self.e.cfg)
        c["gmail"] = {"enabled": on, "user": "me@gmail.com", "app_password": "abcd efgh ijkl mnop", "sender": "support@example.com", "subject": "Watchlist", "times": times or ["06:30", "19:45"]}
        return DanMail(self.e, c, self.tmp.name, fetcher=self.fetcher)

    def test_off_until_gmail_is_set(self):
        d = self.make(on=False)
        self.assertFalse(d.enabled())
        st = d.refresh(1.0, wait=True)
        self.assertIn("Gmail is off", st["error"]); self.assertEqual(self.calls, [])
        self.assertFalse(d.view()["enabled"])

    def test_refresh_reads_keeps_and_shows(self):
        d = self.make()
        d.refresh(100.0, wait=True)
        self.assertEqual(self.calls[-1], ("me@gmail.com", "abcd efgh ijkl mnop", "support@example.com", "Watchlist"))
        v = d.view()
        self.assertEqual(v["date"], "Oct 14, 2026"); self.assertEqual([r["symbol"] for r in v["rows"]], ["AAAA", "BBBB", "CCCC", "DDDD"])
        self.assertEqual(v["status"]["last_ok"], 100.0); self.assertIsNone(v["status"]["error"])
        self.assertTrue(os.path.exists(os.path.join(self.tmp.name, "dan-watchlist-latest.json")))
        again = DanMail(self.e, d.cfg, self.tmp.name, fetcher=self.fetcher)      # a restart shows the kept list at once
        self.assertEqual([r["symbol"] for r in again.view()["rows"]], ["AAAA", "BBBB", "CCCC", "DDDD"])
        self.assertTrue(any("DAN'S DAILY read from Gmail: 4 names" in m["text"] for m in self.e.messages))

    def test_a_gmail_problem_is_said_not_hidden(self):
        def boom(*a):
            raise RuntimeError("[AUTHENTICATIONFAILED] Invalid credentials")
        d = DanMail(self.e, self.make().cfg, self.tmp.name, fetcher=boom)
        d.refresh(5.0, wait=True)
        self.assertIn("Invalid credentials", d.view()["status"]["error"])
        self.assertTrue(any("Gmail did not answer" in m["text"] for m in self.e.messages))

    def test_the_schedule_once_at_start_then_at_the_times(self):
        d = self.make(times=["06:30", "19:45"])
        d.tick(at(2026, 10, 14, 5, 0))                       # startup: one read
        time.sleep(0.2); self.assertEqual(len(self.calls), 1)
        d.tick(at(2026, 10, 14, 6, 0)); time.sleep(0.1); self.assertEqual(len(self.calls), 1)     # not yet
        d.tick(at(2026, 10, 14, 6, 31)); time.sleep(0.2); self.assertEqual(len(self.calls), 2)    # 06:30 read
        d.tick(at(2026, 10, 14, 6, 45)); time.sleep(0.1); self.assertEqual(len(self.calls), 2)    # once a day
        d.tick(at(2026, 10, 14, 19, 50)); time.sleep(0.2); self.assertEqual(len(self.calls), 3)   # the evening read
        d.tick(at(2026, 10, 15, 6, 32)); time.sleep(0.2); self.assertEqual(len(self.calls), 4)    # the next day again

    def test_snapshot_carries_it(self):
        self.e.dan = self.make()
        self.e.dan.refresh(1.0, wait=True)
        s = self.e.snapshot(2.0)
        self.assertEqual(s["dan"]["date"], "Oct 14, 2026"); self.assertEqual(len(s["dan"]["flow"]), 4)


if __name__ == "__main__":
    unittest.main()
