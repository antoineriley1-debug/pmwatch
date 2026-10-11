"""MARKET ANALYSIS DETAILED REPORT: Twiney's boards rebuilt on daily closes. Every test here is a rule from his Pine
boards (Recession Steps v1.2, Market State v1.1, Relationships Board v1.5, Rate Baskets v1.3.0, Macro Vision's
who-is-carrying-it), checked bar for bar on closes built for the purpose; then the loader (IBKR, FRED, the cache),
the page and its routes, DESK AI's market report, and the language lock on every word the page can say."""

import csv
import json
import os
import re
import tempfile
import time
import unittest
import urllib.request

from helpers import cfg, plays
from twiney import macro
from twiney.dashboard import Dashboard
from twiney.engine import Engine
from twiney.macrofeed import MacroFeed, last_closed_day, load_members

N = 320


def axis(n=N, start=20250101):
    import datetime as dt
    d = dt.date(start // 10000, (start // 100) % 100, start % 100)
    out = []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.year * 10000 + d.month * 100 + d.day)
        d += dt.timedelta(days=1)
    return out


def flat(days, v):
    return [(d, float(v)) for d in days]


def base(n=N, **over):
    """Every feed present and calm: prices flat, a normal curve, unemployment and claims steady."""
    D = axis(n)
    S = {"SPY": flat(D, 100), "SPY.A": flat(D, 100), "HYG.A": flat(D, 80), "XLF.A": flat(D, 40), "RSP": flat(D, 50),
         "SMH": flat(D, 200), "COPPER": flat(D, 4), "F:Y10": flat(D, 4.2), "F:Y02": flat(D, 3.8), "F:UR": flat(D[::21], 4.1),
         "F:CLM": flat(D[::5], 220000), "F:WTI": flat(D, 70), "F:BRENT": flat(D, 74), "F:OAS": flat(D, 3.2)}
    for _nm, sym, _g, _w in macro.SECTORS:
        S[sym] = flat(D, 50)
    S.update(over)
    return D, S


def calm_breadth(n=N, short=60.0, long=65.0):
    return [short] * n, [long] * n


def series(D, values):
    return list(zip(D, [float(v) for v in values]))


class RecessionStepTests(unittest.TestCase):
    def test_step1_needs_five_straight_weak_days(self):
        D, S = base()
        for k, want in ((4, False), (5, True)):
            hyg = [80.0] * (N - k) + [76.0] * k          # under its 50-day AND under a month ago, k days
            S["HYG.A"] = series(D, hyg)
            r = macro.build_report(S, {}, {}, breadth=calm_breadth())
            self.assertEqual(r["recession"]["on"][1], want, k)
            self.assertEqual(r["numbers"]["credRun"], k)
        self.assertIn("ON since", r["recession"]["rows"][1]["text"])
        self.assertEqual(r["recession"]["step"], 1)
        self.assertIn("STEP 1 OF 5 IS ON", r["recession"]["where"]["text"])
        S["HYG.A"] = series(D, [80.0] * (N - 4) + [76.0] * 4)
        r = macro.build_report(S, {}, {}, breadth=calm_breadth())
        self.assertIn("weak 4 of the 5 straight days", r["recession"]["rows"][1]["text"])
        self.assertIn("1 more weak days turns this ON", r["recession"]["rows"][1]["text"])

    def test_step2_breadth_under_30_five_days_and_a_day_at_30_resets(self):
        D, S = base()
        fi = [50.0] * (N - 5) + [28, 27, 26, 25, 24]
        r = macro.build_report(S, {}, {}, breadth=(fi, [60.0] * N))
        self.assertTrue(r["recession"]["on"][2])
        self.assertIn("JUST TURNED ON", r["recession"]["rows"][2]["text"])
        fi = [50.0] * (N - 6) + [28, 27, 30, 26, 25, 24]   # one close at 30 starts the count over
        r = macro.build_report(S, {}, {}, breadth=(fi, [60.0] * N))
        self.assertFalse(r["recession"]["on"][2])
        self.assertEqual(r["numbers"]["thinRun"], 3)
        self.assertIn("2 more. One day at 30 or higher resets the count to zero", r["recession"]["rows"][2]["text"])

    def test_step3_two_of_three_bank_clues(self):
        D, S = base()
        # the bank fund under its 200-day, and junk bonds down 1%+ this week: two clues
        S["XLF.A"] = series(D, [40.0] * (N - 30) + [36.0] * 30)
        S["XLF"] = S["XLF.A"]
        S["HYG.A"] = series(D, [80.0] * (N - 3) + [78.5] * 3)
        r = macro.build_report(S, {}, {}, breadth=calm_breadth())
        self.assertEqual(r["numbers"]["bankN"], 2)
        self.assertTrue(r["recession"]["on"][3])
        self.assertIn("THE ONE STILL OFF: banks against the market", r["recession"]["rows"][3]["text"])
        self.assertIn("out of order", r["recession"]["rows"][3]["text"])   # steps 1 and 2 are not on

    def test_jobs_sahm_rule_steps_4_and_5(self):
        D, S = base(N + 300)
        D2 = D
        n = len(D2)
        ur = [4.0] * n
        for i in range(n - 90, n):
            ur[i] = 5.0                                     # the 3-month average climbs a full point off its low
        S["F:UR"] = series(D2, ur)
        r = macro.build_report(S, {}, {}, breadth=calm_breadth(n))
        self.assertGreaterEqual(r["numbers"]["sahm"], 0.5)
        self.assertTrue(r["recession"]["on"][5])
        self.assertTrue(r["recession"]["on"][4])            # jobs crossed counts 2 points and turns step 4 on by itself
        self.assertIn("Sahm rule", r["recession"]["rows"][5]["text"])

    def test_step4_counts_warning_points(self):
        D, S = base()
        S["F:Y02"] = flat(D, 4.6)                         # inverted curve: 1 point
        S["COPPER"] = series(D, [4.0] * (N - 30) + [3.0] * 30)   # copper under its 200-day: 1 point
        r = macro.build_report(S, {}, {}, breadth=(([60.0] * N), ([40.0] * N)))   # long-term breadth under 45: 1 point
        self.assertEqual(r["numbers"]["econN"], 3)
        self.assertTrue(r["recession"]["on"][4])


class MarketStateTests(unittest.TestCase):
    def test_state_climbs_one_at_a_time_after_confirm_days(self):
        D, S = base(N + 300)
        n = len(D)
        ur = [4.0] * n
        for i in range(n - 80, n):
            ur[i] = 6.0
        S["F:UR"] = series(D, ur)
        r = macro.build_report(S, {}, {"confirm_days": 2}, breadth=calm_breadth(n))
        st = r["chart"]["state"]
        # from CLEAR, raw 4 arrives: the page goes 2, then 3, then 4, each after two days; never skips
        seen = [s for i, s in enumerate(st) if i == 0 or s != st[i - 1]]
        self.assertEqual(seen, [1, 2, 3, 4])
        self.assertEqual(r["state"]["n"], 4)
        self.assertEqual(r["state"]["name"], "LATE")
        self.assertIn("Stop pressing shorts", r["state"]["do"])

    def test_caution_is_smaller_not_short(self):
        D, S = base()
        S["HYG.A"] = series(D, [80.0] * (N - 12) + [76.0] * 12)
        r = macro.build_report(S, {}, {}, breadth=calm_breadth())
        self.assertEqual(r["state"]["n"], 2)
        self.assertIn("smaller, not short", r["state"]["do"])
        self.assertIn("State 3 starts when step 2 turns on", r["state"]["flips"])


class HistoryTests(unittest.TestCase):
    def test_step1_episodes_heal_and_follow_counts(self):
        D, S = base(600)
        n = len(D)
        hyg = [80.0] * n
        fi = [60.0] * n
        # three step-1 runs; step 2 confirms inside the second one only
        for a, b in ((100, 115), (250, 275), (420, 432)):
            for i in range(a, b):
                hyg[i] = 76.0
        for i in range(258, 268):
            fi[i] = 25.0
        S["HYG.A"] = series(D, hyg)
        r = macro.build_report(S, {}, {}, breadth=(fi, [60.0] * n))
        h = r["history"]
        self.assertEqual(h["ep1"], 3)
        self.assertEqual(h["fol1"], 1)
        self.assertEqual(h["heal1"], 2)
        self.assertEqual(h["breadth_thin_runs"], 1)
        self.assertEqual(h["steps"][1]["turned_on"], 3)
        self.assertEqual(h["steps"][1]["next_followed"], 1)     # step 2 inside the 40-day window, once
        self.assertIn("step 1 switched on and then ended 3 times", r["recession"]["history_text"])
        self.assertIn("1 of those 3", r["recession"]["history_text"])
        self.assertEqual(sum(1 for x in r["state"]["ladder"] if x["entered"]), 3)  # CLEAR, CAUTION and CONFIRMED were all visited


class RelationshipTests(unittest.TestCase):
    def test_lines_bands_and_direction(self):
        D, S = base()
        spy = [100.0] * (N - 10) + [100.0 + 0.1 * i for i in range(10)]    # just over its 50-day: inside the 1% band
        S["SPY.A"] = series(D, spy)
        r = macro.build_report(S, {}, {}, breadth=calm_breadth())
        rows = {x["n"]: x for x in r["relationships"]["rows"]}
        self.assertEqual(len(rows), 16)
        self.assertEqual(rows[10]["state"], "WATCH")
        self.assertEqual(rows[10]["direction"], "away")
        self.assertEqual(rows[6]["state"], "CLEAR")
        self.assertEqual(rows[9]["state"], "CLEAR")                   # curve +0.40: past the 0.25 warning band
        S["SPY.A"] = series(D, [100.0] * (N - 10) + [90.0] * 10)
        r = macro.build_report(S, {}, {}, breadth=calm_breadth())
        rows = {x["n"]: x for x in r["relationships"]["rows"]}
        self.assertEqual(rows[10]["state"], "PAST THE LINE")
        self.assertEqual(r["relationships"]["rows"][0]["state"], "PAST THE LINE")   # the most urgent first
        self.assertNotIn("TRIGGERED", json.dumps(r["relationships"]))

    def test_missing_feed_is_a_data_check_not_a_reading(self):
        D, S = base()
        del S["F:OAS"]
        r = macro.build_report(S, {}, {}, breadth=calm_breadth())
        rows = {x["n"]: x for x in r["relationships"]["rows"]}
        self.assertEqual(rows[16]["state"], "DATA CHECK")
        self.assertIn("High-yield credit spread", r["feeds"]["text"])


class BasketTests(unittest.TestCase):
    def test_hiding_places_lead_and_regional_banks_crack(self):
        D, S = base()
        up = [50.0] * (N - 6) + [50.0 + 0.5 * i for i in range(1, 7)]
        dn = [50.0] * (N - 6) + [50.0 - 0.5 * i for i in range(1, 7)]
        S["XLP"], S["XLV"], S["KRE"] = series(D, up), series(D, up), series(D, dn)
        r = macro.build_report(S, {}, {}, breadth=calm_breadth())
        b = r["baskets"]
        self.assertEqual(b["lead_week"], 2)
        self.assertTrue(b["winner"].startswith("WHERE MONEY HIDES"))
        self.assertTrue(b["tell_flags"]["regional_cracking"])
        self.assertIn("REGIONAL BANKS CRACKING", b["tells"])
        self.assertIn("DEFENSIVE", b["rotation"]["state"])
        staples = [x for row in b["rows"] for x in row["sectors"] if x["name"] == "STAPLES"][0]
        self.assertGreater(staples["w"], 0)

    def test_tie_means_no_clear_winner(self):
        D, S = base()
        r = macro.build_report(S, {}, {}, breadth=calm_breadth())
        self.assertTrue(r["baskets"]["tie"])
        self.assertEqual(r["baskets"]["winner"], "no clear winner")
        self.assertEqual(r["baskets"]["scenario"], 0)

    def test_patterns_are_his_eight_shapes(self):
        self.assertIn("A leader", macro._pattern(1, 1, 1))
        self.assertIn("New leader forming", macro._pattern(1, 1, -1))
        self.assertIn("losing ground now", macro._pattern(-1, -1, 1))
        self.assertIn("Stay away", macro._pattern(-1, -1, -1))


class LeaderTests(unittest.TestCase):
    def test_members_counted_and_ranked(self):
        D, S = base()
        members = {}
        for i in range(40):
            sym = f"S{i:02d}"
            members[sym] = (f"Stock {i}", "Information Technology" if i % 2 else "Utilities")
            drift = 0.002 if i < 30 else -0.004
            S["M:" + sym] = series(D, [50.0 * (1 + drift) ** k for k in range(N)])
        r = macro.build_report(S, members, {"big_names": ["S00", "S39"]})
        ld = r["leaders"]
        self.assertAlmostEqual(r["numbers"]["s5fi"], 75.0, places=1)   # 30 of 40 above their 50-day
        self.assertEqual(ld["members_month_top"][0]["sym"][0], "S")
        self.assertTrue(all(x["m"] < 0 for x in ld["members_month_bottom"][:10]))
        self.assertEqual({b["sector"] for b in ld["sector_breadth"]}, {"Technology", "Utilities"})
        self.assertEqual(ld["big_names"][1]["sym"], "S00")
        self.assertIn("WHO IS CARRYING IT", ld["carry_text"])


FORBIDDEN = re.compile(r"\b(resistance|support(?!s? the\b)|trigger\w*|fading|stale|gone|zones?|box(es)?|stack\w*|doors?|ribbon|iceberg|dark pool)\b", re.I)


def strings(o):
    if isinstance(o, str):
        yield o
    elif isinstance(o, dict):
        for k, v in o.items():
            yield from strings(k)
            yield from strings(v)
    elif isinstance(o, (list, tuple)):
        for v in o:
            yield from strings(v)


class LanguageTests(unittest.TestCase):
    def test_every_word_the_report_can_say(self):
        members = load_members()
        for seed in (3, 11, 29):
            S = macro.practice_series(list(members)[:120], seed=seed)
            r = macro.build_report(S, members, {"big_names": ["AAPL"]})
            for s in strings(r):
                m = FORBIDDEN.search(s)
                self.assertIsNone(m, f"{m.group(0) if m else ''} in: {s[:160]}")
        for fn in (macro._pattern,):
            for w in (1, -1):
                for m_ in (1, -1):
                    for y in (1, -1):
                        self.assertIsNone(FORBIDDEN.search(fn(w, m_, y)))

    def test_the_page_says_no_forbidden_word(self):
        with open(os.path.join(os.path.dirname(__file__), "..", "page_src", "market.html"), encoding="utf-8") as fh:
            src = fh.read()
        visible = re.sub(r"box-(sizing|shadow)|border-box", "", src)      # CSS keywords, not words on screen
        m = FORBIDDEN.search(visible)
        self.assertIsNone(m, m.group(0) if m else "")


class FeedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_fred_parse_skips_blanks(self):
        rows = MacroFeed.parse_fred("observation_date,DGS10\n2026-10-08,4.12\n2026-10-09,.\n2026-10-10,4.20\n")
        self.assertEqual(rows, [(20261008, 4.12), (20261010, 4.20)])

    def test_last_closed_day(self):
        import datetime as dt
        from zoneinfo import ZoneInfo
        ny = ZoneInfo("America/New_York")
        sat = dt.datetime(2026, 10, 10, 12, 0, tzinfo=ny).timestamp()
        self.assertEqual(last_closed_day(sat), 20261009)
        mon_morning = dt.datetime(2026, 10, 12, 10, 0, tzinfo=ny).timestamp()
        self.assertEqual(last_closed_day(mon_morning), 20261009)
        mon_close = dt.datetime(2026, 10, 12, 16, 30, tzinfo=ny).timestamp()
        self.assertEqual(last_closed_day(mon_close), 20261012)

    def test_fred_load_and_cache_round_trip(self):
        pages = {sid: f"observation_date,{sid}\n2026-10-08,1.5\n2026-10-09,1.6\n" for sid in macro.FRED.values()}
        c = cfg(market={"members": False})
        f = MacroFeed(c, mode="live", cache_dir=self.tmp.name, fetch=lambda url: pages[url.split("=")[-1]])
        f.load_fred()
        self.assertEqual(f.fred_state["state"], "ok")
        self.assertEqual(f.series["F:Y10"][-1], (20261009, 1.6))
        g = MacroFeed(c, mode="live", cache_dir=self.tmp.name)
        self.assertGreaterEqual(g.load_cache(), len(macro.FRED))
        self.assertEqual(g.series["F:OAS"][-1], (20261009, 1.6))

    def test_fred_down_keeps_the_saved_numbers(self):
        def boom(url):
            raise OSError("offline")
        f = MacroFeed(cfg(market={"members": False}), mode="live", cache_dir=self.tmp.name, fetch=boom)
        f.series["F:Y10"] = [(20261008, 4.0)]
        f.load_fred()
        self.assertEqual(f.fred_state["state"], "failed")
        self.assertEqual(f.series["F:Y10"], [(20261008, 4.0)])

    def test_ibkr_load_a_few_at_a_time_then_build(self):
        c = cfg(market={"members": False, "in_flight": 2, "big_names": []})
        f = MacroFeed(c, mode="live", cache_dir=self.tmp.name, contract_factory=lambda spec: spec)
        D = axis(260)

        class App:
            def __init__(self):
                self.req, self.sent = {}, []

            def reqHistoricalData(self, rid, contract, end, dur, size, what, rth, fmt, keep, opts):
                self.sent.append((rid, contract["symbol"], dur, what))

        class Sess:
            def __init__(self):
                self.app, self.n = App(), 1000

            def _rid(self):
                self.n += 1
                return self.n

        class Bar:
            def __init__(self, d, c):
                self.date, self.close = str(d), c
        s = Sess()
        t = 1791741600.0          # a Sunday afternoon: Friday's close is the last closed day
        f.step(t, s)
        self.assertTrue(f.loading)
        self.assertEqual(len(s.app.sent), 1)          # one at a time, 0.35 s apart
        f.step(t + 0.4, s)
        self.assertEqual(len(f.inflight), 2)          # never more than in_flight
        f.step(t + 0.8, s)
        self.assertEqual(len(f.inflight), 2)
        names = {sym for _r, sym, _d, _w in s.app.sent}
        self.assertTrue({"SPY", "HYG"} <= names)
        self.assertTrue(all(d == "20 Y" for _r, _s, d, _w in s.app.sent))
        adj = [w for _r, sym, _d, w in s.app.sent if sym == "SPY"]
        self.assertIn("ADJUSTED_LAST", adj)
        # answer everything as it goes out
        for _ in range(200):
            for rid in list(f.inflight):
                key = f.inflight[rid]["key"]
                if key == "COPPER":
                    f.on_error(rid, 200, "No security definition has been found")
                    continue
                for d in D:
                    f.on_bar(rid, Bar(d, 100.0))
                f.on_end(rid)
            t += 0.4
            f.step(t, s)
            if not f.loading:
                break
        self.assertFalse(f.loading)
        self.assertIn("COPPER", f.failed)
        self.assertTrue(os.path.exists(os.path.join(self.tmp.name, "SPY-A.json")))
        for _ in range(50):
            if f.report is not None:
                break
            time.sleep(0.1)
        self.assertTrue(f.report and f.report["ok"])
        self.assertEqual(f.report["as_of"], D[-1])
        # the next day only the missing days are asked
        f.series["XLE"] = f.series["XLE"][:-3]
        need = f._need("XLE", {"adjusted": False}, D[-1])
        self.assertTrue(need.endswith(" D"))
        self.assertIsNone(f._need("SPY", {"adjusted": False}, D[-1]))

    def test_retry_then_give_up(self):
        f = MacroFeed(cfg(market={"members": False}), mode="live", cache_dir=self.tmp.name)
        f.inflight[5] = {"key": "XLE", "spec": {"dur": "20 Y"}, "t": 0, "bars": [], "tries": 0}
        f.on_error(5, 162, "pacing")
        self.assertEqual(f.queue[-1][0], "XLE")
        f.inflight[6] = {"key": "XLK", "spec": {"dur": "20 Y"}, "t": 0, "bars": [], "tries": 2}
        f.on_error(6, 162, "pacing")
        self.assertIn("XLK", f.failed)

    def test_members_list_shipped(self):
        m = load_members()
        self.assertGreater(len(m), 450)
        self.assertEqual(m["AAPL"][1], "Information Technology")
        self.assertIn("BRK.B", m)


def wait(fn, timeout=20.0):
    end = time.time() + timeout
    while time.time() < end:
        if fn():
            return True
        time.sleep(0.05)
    return False


class PageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = Engine(plays(), cfg(market={"practice_members": 60}))
        self.engine.macro = MacroFeed(self.engine.cfg, mode="practice", cache_dir=self.tmp.name).start()
        self.dash = Dashboard(self.engine, "127.0.0.1", 0, clock=lambda: 2.0).start()

    def tearDown(self):
        self.dash.stop()
        self.tmp.cleanup()

    def get(self, path):
        return urllib.request.urlopen(self.dash.url + path, timeout=10)

    def test_page_and_report(self):
        html = self.get("/market").read().decode()
        self.assertIn("MARKET ANALYSIS DETAILED REPORT", html)
        self.assertIn("/api/market", html)
        self.assertTrue(wait(lambda: self.engine.macro.report is not None))
        d = json.loads(self.get("/api/market").read())
        self.assertTrue(d["ok"])
        self.assertEqual(d["mode"], "practice")
        self.assertTrue(d["report"]["ok"])
        self.assertIn("PRACTICE", d["report"]["source"])
        self.assertEqual(len(d["report"]["relationships"]["rows"]), 16)
        lite = json.loads(self.get("/api/market?lite=1").read())
        self.assertIsNone(lite["report"])
        req = urllib.request.Request(self.dash.url + "/api/market/refresh", data=b"{}", method="POST", headers={"Content-Type": "application/json"})
        out = json.loads(urllib.request.urlopen(req, timeout=10).read())
        self.assertTrue(out["ok"])

    def test_desk_has_the_market_button(self):
        html = self.get("/").read().decode()
        self.assertIn('id="mktBtn"', html)
        self.assertIn("/market", html)


class MarketAITests(unittest.TestCase):
    def test_packet_and_job(self):
        import sys
        sys.path.insert(0, os.path.dirname(__file__))
        from test_ai import FakeOllama, wait_for
        from twiney.ai import DeskAI
        srv = FakeOllama(reply="1. THE CALL\nState 2, smaller not short. Resistance at the 50-day; the trigger is breadth.")
        tmp = tempfile.TemporaryDirectory()
        try:
            c = cfg(ai={"enabled": True, "model": "llama3.1:8b", "url": srv.url}, market={"practice_members": 60})
            eng = Engine(plays(), c)
            eng.macro = MacroFeed(c, mode="practice", cache_dir=tmp.name)
            eng.macro.start()
            self.assertTrue(wait(lambda: eng.macro.report is not None))
            a = DeskAI(eng, c, tmp.name)
            eng.ai = a
            p = a.packet_market()
            for word in ("MARKET STATE:", "STEP 1 · LENDERS NERVOUS", "RELATIONSHIPS:", "RATE BASKETS:", "SCENARIOS:", "WHO IS CARRYING IT", "STEP 2 HISTORY"):
                self.assertIn(word, p, word)
            r = a.run("market", t=time.time())
            self.assertTrue(r["ok"], r)
            self.assertTrue(wait_for(lambda: a.busy is None and a.result("market") is not None, 10))
            res = a.result("market")
            self.assertIsNone(res["error"])
            self.assertNotIn("Resistance", res["text"])
            self.assertNotIn("trigger", res["text"])
            sent = srv.prompts[-1]
            self.assertIn("THE MARKET BACKDROP", sent["system"])
            self.assertIn("SCENARIOS:", sent["prompt"])
            r = a.run("marketask", t=time.time(), text="how close is step 2?")
            self.assertTrue(r["ok"], r)
            self.assertTrue(wait_for(lambda: a.busy is None and a.result("marketask") is not None, 10))
            self.assertIn("how close is step 2?", srv.prompts[-1]["prompt"])
        finally:
            srv.stop()
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
