import unittest
from helpers import cfg, plays
from twiney.engine import Engine
from twiney.book import INSERT, UPDATE, DELETE, BID, ASK


def make():
    e = Engine(plays(), cfg()); e.on_connection("DEMO", "", 0.0)
    e.apply_slot("AAA", True, 0.0)
    for i in range(5):
        e.on_depth("AAA", i, INSERT, BID, round(9.99 - i * 0.01, 2), 1000, "", 1.0)
        e.on_depth("AAA", i, INSERT, ASK, round(10.00 + i * 0.01, 2), 1000, "", 1.0)
    e.on_l1("AAA", "bid", 9.99, 1.0); e.on_l1("AAA", "ask", 10.00, 1.0); e.on_l1("AAA", "last", 10.00, 1.0)
    return e


def lad(e, t):
    with e.lock:
        st = e.syms["AAA"]
        return e._memory_ladder(st, t, e._user_levels(st.play))


def row(L, price):
    return next(r for r in L["rows"] if abs(float(r["price"]) - price) < 1e-9)


class VisitTests(unittest.TestCase):
    """SOLD / BOUGHT THIS VISIT: a price's count starts over when price comes BACK after really leaving (3 ticks away);
    a cent of chop is the same visit. ×N = visits."""
    def test_visit_resets_only_after_price_really_left(self):
        e = make()
        e.on_print("AAA", 10.00, 300, "X", 2.0); e.on_print("AAA", 10.01, 100, "X", 2.1)    # chop: one tick away
        e.on_print("AAA", 10.00, 200, "X", 2.2)
        r = row(lad(e, 2.3), 10.00)
        self.assertEqual(r["vb"] + r["vs"], 500); self.assertEqual(r["vn"], 1); self.assertTrue(r["vopen"])
        e.on_print("AAA", 10.04, 100, "X", 3.0)                                           # left: 4 ticks away
        r = row(lad(e, 3.1), 10.00); self.assertFalse(r["vopen"]); self.assertEqual(r["vb"] + r["vs"], 500)
        e.on_print("AAA", 10.00, 50, "X", 4.0)                                            # back: a new visit
        r = row(lad(e, 4.1), 10.00)
        self.assertEqual(r["vb"] + r["vs"], 50); self.assertEqual(r["vn"], 2)


class PullStackTests(unittest.TestCase):
    """STACK: size added at a price (buyers / sellers stepping up) and size pulled without trading, last minute."""
    def test_stacked_and_pulled_sizes(self):
        e = make()
        e.tick(30.0, allocate_slots=False)                                # past the resync grace: the first read primes it
        e.on_depth("AAA", 1, UPDATE, BID, 9.98, 6000, "", 31.0)         # +5000 stacked on the bid
        e.tick(31.5, allocate_slots=False)
        e.on_depth("AAA", 0, UPDATE, ASK, 10.00, 200, "", 32.0)         # -800 off the offer, nothing traded
        e.tick(32.5, allocate_slots=False); e.tick(34.0, allocate_slots=False)   # past the re-quote window: a pull
        L = lad(e, 34.1)
        self.assertEqual(row(L, 9.98)["ps_b"][0], 5000)
        self.assertEqual(row(L, 10.00)["ps_a"][1], 800)
        self.assertNotIn("ps_b", row(lad(e, 200.0), 9.98))              # a minute later: gone


class ClearTests(unittest.TestCase):
    def test_clear_above_the_ask_keeps_below(self):
        e = make()
        e.on_print("AAA", 10.03, 400, "X", 2.0); e.on_print("AAA", 9.97, 300, "X", 2.1)
        e.on_print("AAA", 10.00, 100, "X", 2.2)
        self.assertTrue(e.ladder_clear("AAA", "above", 2.5))
        L = lad(e, 2.6)
        r_up, r_dn = row(L, 10.03), row(L, 9.97)
        self.assertEqual((r_up["sold"], r_up["bought"], r_up.get("vb", 0), r_up.get("vs", 0)), (0, 0, 0, 0))
        self.assertEqual(r_dn["sold"] + r_dn["bought"], 300)
        e.on_print("AAA", 10.03, 50, "X", 3.0)                           # new prints after the clear count again
        self.assertEqual(row(lad(e, 3.1), 10.03)["bought"] + row(lad(e, 3.1), 10.03)["sold"], 50)


class LevelMarksTests(unittest.TestCase):
    """Your chart on the ladder: the PS60 lines with their distance, a SNEAKY PIVOT you marked, and the option STRIKES
    getting the money."""
    def test_lines_sneaky_and_strikes(self):
        e = make()
        e.set_play_level("AAA", "target", 10.80, 1.5, source="chart"); e.set_play_level("AAA", "stop", 9.70, 1.5, source="chart")
        self.assertTrue(e.add_level("AAA", 9.96, 1.6, kind="sneaky"))
        self.assertIn(9.96, e.syms["AAA"].play["sneaky_levels"])
        e.syms["AAA"].flow_marks.append({"t": 1.7, "spot": 10.0, "strike": 10.5, "cp": "C", "exp": "2026-10-09", "dte": 3,
                                          "prem": 900000, "side": "ask", "kind": "SWEEP", "hot": True})
        L = lad(e, 2.0)
        roles = {m["role"]: m for m in L["marks"]}
        self.assertAlmostEqual(roles["target"]["dist"], 0.80, places=4)
        self.assertEqual(roles["strike"]["label"], "10.5C"); self.assertEqual(roles["strike"]["prem"], 900000)
        self.assertIn("sneaky", [m["role"] for m in row(L, 9.96).get("lv", [])])
        self.assertIn("second_entry", [m["role"] for m in row(L, 10.10).get("lv", [])])  # the play's 2nd entry, in reach: its own row
        self.assertTrue(e.remove_level("AAA", 9.96, 2.1, kind="sneaky"))
        self.assertEqual(e.syms["AAA"].play["sneaky_levels"], [])

    def test_only_hammered_otm_close_dated_strikes(self):
        e = make()
        fm = e.syms["AAA"].flow_marks
        base = {"t": 1.7, "spot": 10.0, "exp": "2026-10-09", "prem": 500000, "kind": "SWEEP", "hot": False}
        fm.append(dict(base, strike=10.5, cp="C", dte=3, side="ask"))      # OTM call bought, close: ON
        fm.append(dict(base, strike=9.5, cp="P", dte=2, side="ask"))       # OTM put bought, close: ON
        fm.append(dict(base, strike=11.0, cp="C", dte=3, side="bid"))      # sold at the bid: off
        fm.append(dict(base, strike=9.0, cp="C", dte=3, side="ask"))       # in the money: off
        fm.append(dict(base, strike=12.0, cp="C", dte=45, side="ask"))     # far dated: off
        got = sorted((m["label"], m["dte"]) for m in lad(e, 2.0)["marks"] if m["role"] == "strike")
        self.assertEqual(got, [("10.5C", 3.0), ("9.5P", 2.0)])


if __name__ == "__main__":
    unittest.main()
