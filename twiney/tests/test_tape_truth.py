"""The tape never calls buyers in a sell-off: a print through the moved quote is read against the quote it traded in,
the price path decides who is in control, and a refused Level II says why."""

import unittest

from helpers import cfg, plays
from twiney import pace
from twiney.engine import Engine, SymbolState
from twiney.tape import BUY, SELL


class SellOffClassificationTests(unittest.TestCase):
    def _st(self):
        st = SymbolState(plays()[0], cfg())
        return st

    def test_a_hit_at_the_old_bid_is_a_sell_after_the_quote_dropped(self):
        st = self._st()
        # the market was 100.00 x 100.02; it is now 99.95 x 99.97 (the quote dropped first, the print arrives after)
        st.quotes.extend([(100.0, 100.00, 100.02), (100.4, 99.95, 99.97)])
        st.l1["bid"], st.l1["ask"] = 99.95, 99.97
        self.assertEqual(st.aggressor(100.00, 100.5), SELL)       # was: BUY (100.00 is over the new 99.97 offer)
        self.assertEqual(st.aggressor(100.02, 100.5), BUY)        # the lift at the old offer stays a buy
        self.assertEqual(st.aggressor(99.95, 100.5), SELL)        # at the bid now: plain
        self.assertEqual(st.aggressor(99.97, 100.5), BUY)

    def test_a_lift_at_the_old_offer_is_a_buy_after_the_quote_jumped(self):
        st = self._st()
        st.quotes.extend([(100.0, 100.00, 100.02), (100.4, 100.06, 100.08)])
        st.l1["bid"], st.l1["ask"] = 100.06, 100.08
        self.assertEqual(st.aggressor(100.02, 100.5), BUY)        # was: SELL (under the new bid)

    def test_no_quote_held_it_the_tick_rule_decides(self):
        st = self._st()
        st.quotes.extend([(100.0, 99.95, 99.97)])
        st.l1["bid"], st.l1["ask"] = 99.95, 99.97
        st.tape.add(100.1, 100.10, 100, 99.95, 99.97, "X", side=SELL)
        self.assertEqual(st.aggressor(100.05, 100.2), SELL)       # lower than the print before it: hit
        st.tape.add(100.2, 100.05, 100, 99.95, 99.97, "X", side=SELL)
        self.assertEqual(st.aggressor(100.05, 100.3), SELL)       # the same price: the side before it
        self.assertEqual(st.aggressor(100.30, 100.3), BUY)        # higher: lifted

    def test_old_quotes_do_not_count(self):
        st = self._st()
        st.quotes.extend([(90.0, 100.00, 100.02), (99.0, 99.95, 99.97)])
        st.l1["bid"], st.l1["ask"] = 99.95, 99.97
        st.tape.add(99.5, 99.96, 100, 99.95, 99.97, "X", side=BUY)
        self.assertEqual(st.aggressor(100.00, 100.5), BUY)        # the 100.00 x 100.02 market is ten seconds gone: tick rule, higher


class ControlTests(unittest.TestCase):
    def _book(self, path, side="buy"):
        b, t = _steady()
        for k, px in enumerate(path):
            b.add(t + k, px, 1000.0, side)
        return b, t + len(path)

    def test_sellers_in_control_while_buyers_lift(self):
        # fifteen seconds of prints at the offer (buy_pct 100) while price steps DOWN 20 cents: sellers' tape
        b, t = self._book([100.00 - 0.0133 * k for k in range(15)], "buy")
        p = pace.read(b, t, 99.80, [], 0.01, CFG)
        self.assertEqual(p["buy_pct"], 100)
        self.assertEqual(p["control"], "sellers")
        self.assertLess(p["drift"], -0.1)
        from twiney.story import tape_words
        self.assertIn("Sellers in control", tape_words(dict(p, state="FAST"), None))

    def test_buyers_in_control_while_sellers_hit(self):
        b, t = self._book([100.00 + 0.0133 * k for k in range(15)], "sell")
        p = pace.read(b, t, 100.20, [], 0.01, CFG)
        self.assertEqual(p["buy_pct"], 0)
        self.assertEqual(p["control"], "buyers")
        from twiney.story import tape_words
        self.assertIn("Buyers in control", tape_words(dict(p, state="FAST"), None))

    def test_flat_price_keeps_the_plain_read(self):
        b, t = self._book([100.00] * 15, "buy")
        p = pace.read(b, t, 100.00, [], 0.01, CFG)
        self.assertIsNone(p["control"])
        from twiney.story import tape_words
        self.assertEqual(tape_words(dict(p, state="FAST"), None), "Buyers stepping up")

    def test_level_context_and_play_by_play_follow_control(self):
        e = Engine(plays(), cfg(), None)
        st = e.syms["AAA"]
        st.pace = {"buy_pct": 80, "control": "sellers", "drift": -0.22, "state": "FAST", "ratio": 1.0}
        words, short = e._level_context(st, 10.0, 1000.0, True)
        self.assertIn("sellers in control", str(words))
        self.assertNotIn("buyers stepping up", str(words))


class RefusedBookTests(unittest.TestCase):
    def test_refusal_is_said_with_the_fix(self):
        e = Engine(plays(), cfg(), None)
        e.on_connection("CONNECTED", "", 1.0)
        e.on_depth_rejected("AAA", 10092, "Deep market data is not supported for this combination of security type/exchange", 2.0)
        m = [x for x in e.messages if x.get("symbol") == "AAA"]
        self.assertTrue(m and "Level II refused by IBKR [10092]" in m[0]["text"] and "TotalView" in m[0]["text"], m)
        h = e._health(e.syms["AAA"], 3.0)
        self.assertIn("TotalView", h["depth_refused"])
        self.assertIsNone(e._health(e.syms["AAA"], 3.0 + 3600)["depth_refused"])    # the cooldown is over: a fresh try
        self.assertIn("allows 3", Engine.depth_refusal(309, "max depth requests"))


def _steady(normal_sps=1000.0, minutes=20, end=10_000.0, price=100.0):
    b = pace.PaceBook()
    t = end - minutes * 60
    while t < end - 15:
        b.add(t, price, normal_sps, "buy" if int(t) % 2 else "sell")
        t += 1.0
    return b, t


from twiney.config import DEFAULTS as _D
CFG = dict(_D["pace"])


if __name__ == "__main__":
    unittest.main()


class UnderOverTests(unittest.TestCase):
    """The play-by-play never says 'sitting on' a level price is under: under it is UNDER, over it is OVER."""
    def test_under_the_prior_day_low_is_said_as_under(self):
        from twiney import story
        from twiney.config import DEFAULTS
        import copy
        C = copy.deepcopy(DEFAULTS)
        sb = story.Story()
        foc = {"on": True, "approach": True, "kind": "pdl", "name": "prior-day low", "p": 145.00, "lo": 145.00, "hi": 145.00, "dir": "down"}
        for last, want in ((144.94, "under"), (145.06, "over"), (145.00, "on")):
            out = story.play_by_play(sb, 1_700_000_000.0, foc, last, 0.3, {"state": "FAST", "buy_pct": 30, "ratio": 1.5}, None, [], [], C["story"])
            self.assertIsNotNone(out)
            head = out["text"].split(".")[0].lower()
            self.assertNotIn("sitting on", head) if want != "on" else None
            if want == "under":
                self.assertIn("under", head, out["text"])
            elif want == "over":
                self.assertIn("over", head, out["text"])
            else:
                self.assertTrue("on " in head or "at " in head, out["text"])


class LeanTests(unittest.TestCase):
    """WHO HAS THE TAPE: a side, held with reasons until the data turns; a counter-move is the other side TRYING."""
    def _cfg(self):
        import copy
        from twiney.config import DEFAULTS
        return copy.deepcopy(DEFAULTS)["story"]

    def _mins(self, t, path):
        """One-minute bars ending at t following a price path (closes), highs / lows a few cents around."""
        n = len(path)
        return [[t - 60 * (n - i), p, p + 0.03, p - 0.03, p, 1000] for i, p in enumerate(path)]

    def test_sellers_take_the_tape_and_a_bounce_is_buyers_trying(self):
        from twiney import story
        C = self._cfg()
        sb = story.Story(); t = 1_700_000_000.0
        sb.breaks["prior-day low"] = {"dir": "down", "t": t - 600, "lo": 100.0, "hi": 100.0, "state": "broke"}
        down = [101.0 - 0.02 * i for i in range(40)]          # lower highs and lower lows, a new low of day right now
        ln = story.tape_lean(sb, t, 99.2, self._mins(t, down), {"P": {"usd": 600000}, "C": {"usd": 100000}}, None, False, C)
        self.assertEqual(ln["side"], "bear")
        self.assertIn("prior-day low taken", ln["why"])
        self.assertTrue(any("puts" in w for w in ln["why"]), ln["why"])
        self.assertIn("Sellers have the tape", ln["changed"])
        # a bounce with the buy percentage up: TRYING, not stepping up, and the play-by-play does not turn bullish
        fast_buyers = {"state": "FAST", "buy_pct": 80, "ratio": 1.8, "control": "buyers", "drift": 0.2}
        self.assertIn("Buyers are trying", story.tape_words(fast_buyers, None, sb))
        self.assertIn("sellers still have the tape", story.tape_words(fast_buyers, None, sb))
        foc = {"on": True, "approach": True, "kind": "pdl", "name": "prior-day low", "p": 100.0, "lo": 100.0, "hi": 100.0, "dir": "down"}
        out = story.play_by_play(sb, t, foc, 100.05, 0.3, fast_buyers, None, [], [], C)
        self.assertIn("buyers are trying", out["text"].lower())
        self.assertNotIn("buyers stepping up", out["text"])
        self.assertNotEqual(out["tone"], "bull")
        # the lean holds: the same bounce a minute later with no level taken back does not turn it
        ln2 = story.tape_lean(sb, t + 60, 100.3, self._mins(t + 60, down[5:] + [99.3, 99.6, 99.9, 100.2, 100.3]), {"P": {"usd": 600000}, "C": {"usd": 100000}}, None, False, C)
        self.assertEqual(ln2["side"], "bear")
        self.assertIsNone(ln2["changed"])

    def test_the_lean_turns_only_when_the_data_turns(self):
        from twiney import story
        C = self._cfg(); C["lean_hold_minutes"] = 10; C["lean_neutral_minutes"] = 3
        sb = story.Story(); t = 1_700_000_000.0
        sb.breaks["prior-day low"] = {"dir": "down", "t": t - 600, "lo": 100.0, "hi": 100.0, "state": "broke"}
        down = [101.0 - 0.02 * i for i in range(40)]
        story.tape_lean(sb, t, 99.2, self._mins(t, down), {"P": {"usd": 600000}, "C": {"usd": 100000}}, None, False, C)
        self.assertEqual(sb.lean["side"], "bear")
        # the level is recovered on a close (the break failed) and the flow goes even: the reasons are gone
        sb.breaks["prior-day low"]["state"] = "failed"
        flat = [100.5] * 40
        ln = story.tape_lean(sb, t + 120, 100.5, self._mins(t + 120, flat), {}, None, False, C)
        self.assertEqual(ln["side"], "bear")                         # not yet: a short while to be sure
        ln = story.tape_lean(sb, t + 120 + 181, 100.5, self._mins(t + 301, flat), {}, None, False, C)
        self.assertIsNone(ln["side"])
        self.assertIn("No side has the tape", ln["changed"])
        # buyers take levels: the tape is theirs
        sb.breaks["prior-day high"] = {"dir": "up", "t": t + 400, "lo": 101.0, "hi": 101.0, "state": "broke"}
        up = [100.0 + 0.03 * i for i in range(40)]
        ln = story.tape_lean(sb, t + 500, 101.2, self._mins(t + 500, up), {"C": {"usd": 500000}, "P": {"usd": 50000}}, None, False, C)
        self.assertEqual(ln["side"], "bull")
        self.assertIn("Buyers have the tape", ln["changed"])
        self.assertIn("Sellers are trying", story.tape_words({"state": "FAST", "buy_pct": 20, "ratio": 1.8}, None, sb))

    def test_a_flip_needs_the_hold_time(self):
        from twiney import story
        C = self._cfg(); C["lean_hold_minutes"] = 10
        sb = story.Story(); t = 1_700_000_000.0
        sb.breaks["prior-day low"] = {"dir": "down", "t": t - 600, "lo": 100.0, "hi": 100.0, "state": "broke"}
        down = [101.0 - 0.02 * i for i in range(40)]
        story.tape_lean(sb, t, 99.2, self._mins(t, down), {"P": {"usd": 600000}, "C": {"usd": 100000}}, None, False, C)
        # two minutes later everything says buyers (a level up taken, higher highs, calls): still the sellers' tape
        sb.breaks["prior-day high"] = {"dir": "up", "t": t + 100, "lo": 101.0, "hi": 101.0, "state": "broke"}
        up = [100.0 + 0.03 * i for i in range(40)]
        ln = story.tape_lean(sb, t + 120, 101.2, self._mins(t + 120, up), {"C": {"usd": 500000}, "P": {"usd": 50000}}, None, False, C)
        self.assertEqual(ln["side"], "bear")
        ln = story.tape_lean(sb, t + 601, 101.2, self._mins(t + 601, up), {"C": {"usd": 500000}, "P": {"usd": 50000}}, None, False, C)
        self.assertEqual(ln["side"], "bull")

    def test_nothing_decisive_is_neutral(self):
        from twiney import story
        sb = story.Story(); t = 1_700_000_000.0
        ln = story.tape_lean(sb, t, 100.0, self._mins(t, [100.0] * 40), {}, None, False, self._cfg())
        self.assertIsNone(ln["side"])
        self.assertEqual(ln["text"], "NO SIDE HAS THE TAPE")
        self.assertEqual(story.tape_words({"state": "FAST", "buy_pct": 80, "ratio": 1.8}, None, sb), "Buyers stepping up")


class SuspectLiftTests(unittest.TestCase):
    def test_a_lift_count_against_the_path_is_never_quoted(self):
        from twiney import story
        import copy
        from twiney.config import DEFAULTS
        C = copy.deepcopy(DEFAULTS)["story"]
        b, t = _steady()
        for k in range(15):
            b.add(t + k, 100.00 - 0.02 * k, 1000.0, "buy")          # "100% lifting" while price prints lower
        p = pace.read(b, t + 15, 99.7, [], 0.01, CFG)
        self.assertEqual(p["buy_pct"], 100)
        self.assertTrue(p["bp_suspect"])
        sb = story.Story()
        foc = {"on": True, "approach": True, "kind": "pdl", "name": "prior-day low", "p": 99.7, "lo": 99.7, "hi": 99.7, "dir": "down"}
        out = story.play_by_play(sb, t + 15, foc, 99.7, 0.3, p, None, [], [], C)
        self.assertNotIn("100%", out["text"])
        self.assertNotIn("buyers stepping up", out["text"].lower())
        self.assertIn("sellers have it", out["text"].lower())
        self.assertEqual(out["tone"], "bear")


def _ny(h, m):
    """A New York time today-ish (a fixed trading day) in epoch seconds."""
    from twiney import studies
    import datetime as _dt
    from zoneinfo import ZoneInfo
    return _dt.datetime(2026, 10, 9, h, m, tzinfo=ZoneInfo("America/New_York")).timestamp()


def _day(path, start=(9, 30)):
    """One-minute bars from the open along a price path (closes), 3-cent wicks."""
    t0 = _ny(*start)
    return [[t0 + 60 * i, p, p + 0.03, p - 0.03, p, 1000] for i, p in enumerate(path)]


class RegimeTests(unittest.TestCase):
    def _cfg(self):
        import copy
        from twiney.config import DEFAULTS
        return copy.deepcopy(DEFAULTS)["story"]

    def test_a_trend_day_down_then_the_lean_counts_it(self):
        from twiney import story
        sb = story.Story(); C = self._cfg()
        path = [230.0 - 0.06 * i for i in range(90)]                   # 90 minutes stepping down, $5.3 of range on an $8 ATR
        mins = _day(path)
        rg = story.day_regime(sb, mins[-1][0] + 60, mins, 8.0, C)
        self.assertEqual(rg["kind"], "down")
        self.assertIn("Trend day down", rg["changed"])
        ln = story.tape_lean(sb, mins[-1][0] + 60, path[-1], mins, {}, None, False, C)
        self.assertIn("trend day down", ln["why"])

    def test_chop_and_too_early(self):
        from twiney import story
        sb = story.Story(); C = self._cfg()
        import math
        path = [230.0 + 0.4 * math.sin(i / 5.0) for i in range(90)]     # $0.8 of range on an $8 ATR, back and forth
        mins = _day(path)
        self.assertIsNone(story.day_regime(sb, mins[30][0] + 60, mins[:31], 8.0, C)["kind"])   # 31 minutes: too early
        rg = story.day_regime(sb, mins[-1][0] + 60, mins, 8.0, C)
        self.assertEqual(rg["kind"], "chop")
        self.assertIn("Chop", rg["changed"])
        self.assertIsNone(story.day_regime(sb, mins[-1][0] + 60, mins, 8.0, C)["changed"])     # the same minute: nothing new


class AttemptTests(unittest.TestCase):
    def _cfg(self):
        import copy
        from twiney.config import DEFAULTS
        return copy.deepcopy(DEFAULTS)["story"]

    def _bear(self, sb, C):
        from twiney import story
        path = [232.0 - 0.05 * i for i in range(60)]                   # down to 229.05, under the prior-day low 230
        mins = _day(path)
        t = mins[-1][0] + 60
        sb.breaks["prior-day low"] = {"dir": "down", "t": t - 1200, "lo": 230.0, "hi": 230.0, "state": "broke"}
        story.tape_lean(sb, t, 229.05, mins, {"P": {"usd": 600000}, "C": {"usd": 50000}}, None, False, C)
        self.assertEqual(sb.lean["side"], "bear")
        return mins, t

    def test_buyers_try_and_fail(self):
        from twiney import story
        sb = story.Story(); C = self._cfg(); C["attempt_minutes"] = 8
        mins, t = self._bear(sb, C)
        quiet = {"state": "NORMAL", "buy_pct": 50, "control": None}
        st = story.attempts(sb, t, 229.05, mins, quiet, 0.01, 8.0, C)
        self.assertIsNone(st["open"]); self.assertIsNone(st["said"])
        # buyers turn it up: an attempt starts, naming what they need (the prior-day low back on a close)
        st = story.attempts(sb, t + 30, 229.40, mins, {"state": "FAST", "buy_pct": 75, "control": "buyers", "drift": 0.3}, 0.01, 8.0, C)
        self.assertIsNotNone(st["open"])
        self.assertEqual(st["open"]["need"]["name"], "prior-day low")
        self.assertIn("Buyers are trying from 229.40", st["said"][0]); self.assertIn("230.00", st["said"][0]); self.assertIn("Wait", st["said"][0])
        # eight minutes later they never closed over it: failed, sellers still have it
        later = mins + [[t + 60 * i, 229.4, 229.6, 229.3, 229.5, 500] for i in range(9)]
        st = story.attempts(sb, t + 30 + 8 * 60 + 1, 229.5, later, quiet, 0.01, 8.0, C)
        self.assertIsNone(st["open"])
        self.assertEqual(st["done"][-1]["outcome"], "failed")
        self.assertIn("could not take back prior-day low 230.00", st["said"][0]); self.assertIn("Sellers still have the tape", st["said"][0])
        # a rest: the next lift right away is not a new attempt
        st = story.attempts(sb, t + 30 + 8 * 60 + 30, 229.6, later, {"state": "FAST", "buy_pct": 75, "control": "buyers"}, 0.01, 8.0, C)
        self.assertIsNone(st["open"])

    def test_buyers_try_and_a_new_low_ends_it(self):
        from twiney import story
        sb = story.Story(); C = self._cfg()
        mins, t = self._bear(sb, C)
        story.attempts(sb, t + 30, 229.40, mins, {"state": "FAST", "buy_pct": 75, "control": "buyers"}, 0.01, 8.0, C)
        later = mins + [[t + 60, 229.4, 229.45, 228.90, 228.95, 500]]
        st = story.attempts(sb, t + 121, 228.95, later, {"state": "FAST", "buy_pct": 20, "control": "sellers"}, 0.01, 8.0, C)
        self.assertEqual(st["done"][-1]["outcome"], "failed")
        self.assertIn("A new low instead", st["said"][0])

    def test_buyers_take_it_back(self):
        from twiney import story
        sb = story.Story(); C = self._cfg()
        mins, t = self._bear(sb, C)
        story.attempts(sb, t + 30, 229.40, mins, {"state": "FAST", "buy_pct": 75, "control": "buyers"}, 0.01, 8.0, C)
        later = mins + [[t + 60, 229.5, 230.3, 229.4, 230.2, 500]]     # a minute closed over 230
        st = story.attempts(sb, t + 125, 230.2, later, {"state": "FAST", "buy_pct": 70}, 0.01, 8.0, C)
        self.assertEqual(st["done"][-1]["outcome"], "took")
        self.assertIn("took back prior-day low 230.00 on a close", st["said"][0])
        self.assertIn("still have the tape until they hold it", st["said"][0])

    def test_no_attempt_without_a_lean(self):
        from twiney import story
        sb = story.Story(); C = self._cfg()
        mins = _day([230.0] * 40); t = mins[-1][0] + 60
        st = story.attempts(sb, t, 230.3, mins, {"state": "FAST", "buy_pct": 80, "control": "buyers"}, 0.01, 8.0, C)
        self.assertIsNone(st["open"])


class StorylineLogTests(unittest.TestCase):
    def test_lean_lines_go_to_the_storyline_file(self):
        import os, tempfile, json
        e = Engine(plays(), cfg(), None)
        d = tempfile.mkdtemp(); e.storyline_path = os.path.join(d, "storylines.jsonl")
        st = e.syms["AAA"]; st.l1["last"] = 10.0
        sc = e.cfg["story"]
        e._story_alert(st, {"topic": "lean", "text": "Sellers have the tape: x", "tone": "bear", "pri": 2}, 1_700_000_000.0, sc)
        e._story_alert(st, {"topic": "pbp", "text": "noise", "tone": "neutral", "pri": 4}, 1_700_000_001.0, sc)
        e._story_alert(st, {"topic": "attempt", "text": "Buyers are trying", "tone": "neutral", "pri": 3}, 1_700_000_002.0, sc)
        rows = [json.loads(l) for l in open(e.storyline_path)]
        self.assertEqual([r["topic"] for r in rows], ["lean", "attempt"])
        self.assertEqual(rows[0]["symbol"], "AAA")
        self.assertIn("day", rows[0])
