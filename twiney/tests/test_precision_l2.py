"""TWINEY'S PRECISION LEVEL 2: the truth layer. The ten replay scenarios of the handoff (SPEC §11), run against the
engine's own depth / print accounting that the DOM draws from. Nothing here draws: it proves what the rows SAY.

Row fields the DOM reads (engine._memory_ladder):
  bid / ask          waiting buyers / sellers (resting size now)
  bk                 [traded here today, bought (lifted the offer), sold (hit the bid), prints]   = TRADED AT PRICE
  vs / vb            sold into the bid / bought from the offer THIS VISIT                          = ACTUAL SELLING / BUYING
  ps_b / ps_a        (stacked, pulled) in the last minute                                          = drain without a trade
  bid_real / ask_real {filled, pulled, pct}: of the size that left, how much traded vs vanished
  bid_state / bid_refills / bid_stage ...  the reload buyer / seller cluster (the EXISTING detector)
  lv                 every level on the row (stacked, never dropped)
"""

import time as _time
import unittest

from helpers import cfg, plays
from twiney.book import ASK, BID, DELETE, INSERT, UPDATE
from twiney.engine import Engine


def make(**sections):
    e = Engine(plays(), cfg(**sections)); e.on_connection("DEMO", "", 0.0)
    e.apply_slot("AAA", True, 0.0)
    for i in range(5):
        e.on_depth("AAA", i, INSERT, BID, round(9.99 - i * 0.01, 2), 1000, "", 1.0)
        e.on_depth("AAA", i, INSERT, ASK, round(10.00 + i * 0.01, 2), 1000, "", 1.0)
    e.on_l1("AAA", "bid", 9.99, 1.0); e.on_l1("AAA", "ask", 10.00, 1.0); e.on_l1("AAA", "last", 10.00, 1.0)
    e.tick(30.0, allocate_slots=False)          # past the resync grace: the book is judged from here
    return e


def lad(e, t):
    with e.lock:
        st = e.syms["AAA"]
        return e._memory_ladder(st, t, e._user_levels(st.play))


def row(L, price):
    return next(r for r in L["rows"] if abs(float(r["price"]) - price) < 1e-9)


class Scenario1_HitThenRefill(unittest.TestCase):
    """Resting 5,000 at the bid; 3,000 confirmed aggressive sells; the size drops to 2,000; 4,000 new shares added;
    the row refills to 6,000. Every number is what happened, and the drop is a TRADE, not a pull."""
    def test_execution_then_refill(self):
        e = make()
        e.on_depth("AAA", 0, UPDATE, BID, 9.99, 5000, "", 31.0); e.tick(31.5, allocate_slots=False)
        self.assertEqual(row(lad(e, 31.6), 9.99)["bid"], 5000)
        for k in range(3):                                                 # 3 × 1,000 hit the bid at 9.99
            e.on_print("AAA", 9.99, 1000, "X", 32.0 + k * 0.1)
        e.on_depth("AAA", 0, UPDATE, BID, 9.99, 2000, "", 32.4); e.tick(32.5, allocate_slots=False)
        r = row(lad(e, 32.6), 9.99)
        self.assertEqual(r["bid"], 2000)
        self.assertEqual(r["bk"][:3], [3000, 0, 3000])                  # traded at price: 3,000, all sold into the bid
        self.assertEqual(r["vs"], 3000)                                   # actual selling this visit
        self.assertEqual(r["bid_real"]["filled"], 3000)                   # the 3,000 that left TRADED
        self.assertEqual(r["bid_real"]["pulled"], 0)
        before = row(lad(e, 32.7), 9.99)["ps_b"][0]                      # stacked so far (the first show counted too)
        e.on_depth("AAA", 0, UPDATE, BID, 9.99, 6000, "", 33.0); e.tick(33.5, allocate_slots=False)
        r = row(lad(e, 33.6), 9.99)
        self.assertEqual(r["bid"], 6000)
        self.assertEqual(r["ps_b"][0] - before, 4000)                     # 4,000 came in (stacked), nothing pulled
        self.assertEqual(r["ps_b"][1], 0)
        self.assertEqual(r["bk"][:3], [3000, 0, 3000])                  # a refill never changes what TRADED


class Scenario2_CancelIsNotATrade(unittest.TestCase):
    """5,000 resting drops to 2,000 by cancellation alone: no execution anywhere, the row's TRADED stays at zero,
    the drop files as PULLED once the re-quote window passes."""
    def test_cancel_only(self):
        e = make()
        e.on_depth("AAA", 0, UPDATE, BID, 9.99, 5000, "", 31.0); e.tick(31.5, allocate_slots=False)
        e.on_depth("AAA", 0, UPDATE, BID, 9.99, 2000, "", 32.0); e.tick(32.5, allocate_slots=False)
        e.tick(34.0, allocate_slots=False)                                # past requote_seconds: a pull
        r = row(lad(e, 34.1), 9.99)
        self.assertEqual(r["bid"], 2000)
        self.assertNotIn("bk", r)                                         # nothing traded here today
        self.assertNotIn("vs", r)
        self.assertEqual(r["ps_b"][1], 3000)                              # pulled without trading
        self.assertEqual(r["bid_real"], {"filled": 0, "pulled": 3000, "pct": 0.0, "label": r["bid_real"]["label"]})
        self.assertNotEqual(r["bid_real"]["label"], "REAL")


class Scenario3_ReloadClusters(unittest.TestCase):
    """Repeated reload buyer and seller events at separate prices: the existing detector calls them, and the rows
    carry the cluster (side, refills, absorbed) anchored to the right price. Replays reproduce it."""
    def _reload(self, e, side, price, pos, t0):
        hit = "sell" if side == BID else "buy"
        for k in range(4):                                                 # show 1,000 · 900 trades into it · back to 1,000
            e.on_depth("AAA", pos, UPDATE, side, price, 1000, "", t0 + k * 2.0); e.tick(t0 + k * 2.0 + 0.3, allocate_slots=False)
            e.on_print("AAA", price, 900, "X", t0 + k * 2.0 + 0.6)
            e.on_depth("AAA", pos, UPDATE, side, price, 100, "", t0 + k * 2.0 + 0.8); e.tick(t0 + k * 2.0 + 1.0, allocate_slots=False)
        e.on_depth("AAA", pos, UPDATE, side, price, 1000, "", t0 + 8.2); e.tick(t0 + 8.5, allocate_slots=False)

    def test_clusters_on_their_own_rows(self):
        e = make(reload={"auto_levels": True, "auto_min_display_shares": 500})
        self._reload(e, BID, 9.99, 0, 40.0)
        self._reload(e, ASK, 10.00, 0, 60.0)
        e.tick(70.0, allocate_slots=False)
        L = lad(e, 70.1)
        rb, ra = row(L, 9.99), row(L, 10.00)
        self.assertEqual(rb.get("bid_state"), "RELOAD", rb)
        self.assertEqual(ra.get("ask_state"), "RELOAD", ra)
        self.assertGreaterEqual(rb["bid_refills"], 2); self.assertGreaterEqual(ra["ask_refills"], 2)
        self.assertGreaterEqual(rb["bid_absorbed"], 2700); self.assertGreaterEqual(ra["ask_absorbed"], 2700)
        self.assertNotEqual(rb.get("ask_state"), "RELOAD"); self.assertNotEqual(ra.get("bid_state"), "RELOAD")   # each on its own side and price
        labels = [a["label"] for a in e.alerts]
        self.assertIn("RELOAD BUYER DETECTED", labels); self.assertIn("RELOAD SELLER DETECTED", labels)
        self.assertEqual(sum(1 for a in e.alerts if a["label"] == "RELOAD BUYER DETECTED"), 1)    # one call, not one per refill


class Scenario4_OutOfOrderAndDuplicates(unittest.TestCase):
    """Cancel, add and execute interleaved, prints arriving out of order, then a reconnect that re-delivers a print:
    no double counting, the traded total is exactly the sum of the distinct prints, and the book rebuild after the
    reconnect judges nothing."""
    def test_reconciles(self):
        e = make()
        e.on_depth("AAA", 0, UPDATE, BID, 9.99, 5000, "", 31.0); e.tick(31.5, allocate_slots=False)
        e.on_print("AAA", 9.99, 700, "X", 32.3, "", 32)          # IBKR time 32, arrives after the next one
        e.on_print("AAA", 9.99, 300, "X", 32.1, "", 32)
        e.on_depth("AAA", 0, UPDATE, BID, 9.99, 4000, "", 32.4); e.tick(32.5, allocate_slots=False)    # 1,000 traded off it (the desk reads the book every quarter second)
        e.on_depth("AAA", 0, UPDATE, BID, 9.99, 3000, "", 32.6); e.tick(32.75, allocate_slots=False)   # then 1,000 cancelled
        stacked0 = row(lad(e, 32.76), 9.99)["ps_b"][0]
        e.on_depth("AAA", 0, UPDATE, BID, 9.99, 4500, "", 32.8); e.tick(33.0, allocate_slots=False)    # then 1,500 added
        e.tick(34.5, allocate_slots=False)
        r = row(lad(e, 34.6), 9.99)
        self.assertEqual(r["bk"][:3], [1000, 0, 1000])
        self.assertEqual(r["bk"][3], 2)                                  # two distinct prints
        self.assertEqual(r["bid"], 4500)
        self.assertEqual(r["bid_story"]["traded"], 1000)                   # the 1,000 that left TRADED
        self.assertEqual(r["bid_story"]["pulled"], 0)                       # the cancel came back inside the re-quote window: not a pull
        self.assertEqual(r["ps_b"][0] - stacked0, 500)                    # of the 1,500 added, 1,000 was the re-quote; 500 is new
        # the feed drops and comes back: it re-sends the 700 print and rebuilds the book smaller
        e.on_connection("DISCONNECTED", "", 35.0); e.on_connection("CONNECTED", "", 35.1)
        e.on_print("AAA", 9.99, 700, "X", 35.2, "", 32)          # the same print again: ignored
        e.apply_slot("AAA", True, 35.25)                          # depth is subscribed again after a reconnect
        for i in range(5):
            e.on_depth("AAA", i, INSERT, BID, round(9.99 - i * 0.01, 2), 2000, "", 35.3)
            e.on_depth("AAA", i, INSERT, ASK, round(10.00 + i * 0.01, 2), 2000, "", 35.3)
        e.tick(35.5, allocate_slots=False); e.tick(38.5, allocate_slots=False)
        r = row(lad(e, 38.6), 9.99)
        self.assertEqual(r["bk"][:3], [1000, 0, 1000])                  # still two prints, 1,000 shares
        self.assertEqual(r["bk"][3], 2)
        self.assertEqual(r["bid"], 2000)
        self.assertEqual(e.dup_prints, 1)


class Scenario5_FastRun(unittest.TestCase):
    """Price runs up through five rows: every row keeps exactly its executed volume, the last-price flag is on one
    row, and the sequence is intact."""
    def test_each_row_keeps_its_volume(self):
        e = make()
        t = 31.0
        for i, p in enumerate((10.00, 10.01, 10.02, 10.03, 10.04)):
            for k in range(3):
                e.on_print("AAA", p, 200 * (i + 1), "X", t); t += 0.05
            e.on_l1("AAA", "last", p, t)
        L = lad(e, t + 0.1)
        for i, p in enumerate((10.00, 10.01, 10.02, 10.03, 10.04)):
            r = row(L, p)
            self.assertEqual(r["bk"][0], 600 * (i + 1), p)
            self.assertEqual(r["bk"][1], 600 * (i + 1))                    # every one lifted the offer
            self.assertEqual(r["vb"], 600 * (i + 1))
        self.assertEqual([float(r["price"]) for r in L["rows"] if r["last"]], [10.04])


class Scenario6_SessionLevels(unittest.TestCase):
    """Prior-day and session levels on the ladder are the chart's own numbers (one registry), with their codes."""
    def test_ladder_marks_equal_key_levels(self):
        e = make()
        st = e.syms["AAA"]
        t0 = 1_700_000_000.0
        st.daily = {t0 - 86400 * 2: [9.5, 10.4, 9.3, 10.1], t0 - 86400: [10.1, 10.6, 9.8, 10.2]}
        with e.lock:
            kl = e.key_levels(st, t0 + 3600)
            marks = e._ladder_marks(st, t0 + 3600, e._user_levels(st.play), 10.0)
        want = {L["code"]: L["price"] for L in kl if L["code"] not in ("VWAP", "D50", "HOD", "LOD")}
        got = {m["code"]: m["price"] for m in marks if m.get("role") == "key"}
        self.assertTrue(want, kl)
        self.assertEqual(got, want)
        self.assertIn("PDH", got); self.assertIn("PDL", got)


class Scenario7_OverlappingLevels(unittest.TestCase):
    """Several levels on one price: the row carries every one of them, none hidden."""
    def test_all_levels_kept_on_the_row(self):
        e = make()
        st = e.syms["AAA"]
        e.set_play_level("AAA", "trigger", 10.02, 31.0, source="chart")
        e.set_play_level("AAA", "target", 10.02, 31.0, source="chart")
        st.day_hi = (10.02, 31.0)
        r = row(lad(e, 32.0), 10.02)
        roles = sorted(m["role"] for m in r["lv"])
        self.assertEqual(roles, ["hod", "target", "trigger"])


class Scenario8_Degradation(unittest.TestCase):
    """No depth: the rows still carry the trades, the sizes read zero, the health says so. A reconnect rebuild
    never files as pulled. A stale feed is reported, never invented."""
    def test_no_book_still_counts_trades(self):
        e = Engine(plays(), cfg()); e.on_connection("DEMO", "", 0.0)
        e.on_l1("AAA", "last", 10.00, 1.0); e.on_l1("AAA", "bid", 9.99, 1.0); e.on_l1("AAA", "ask", 10.00, 1.0)
        e.on_print("AAA", 10.00, 500, "X", 2.0)
        r = row(lad(e, 2.1), 10.00)
        self.assertEqual((r["bid"], r["ask"]), (0, 0))
        self.assertEqual(r["bk"][0], 500)
        self.assertNotIn("bid_real", r)

    def test_reconnect_rebuild_is_not_a_pull(self):
        e = make()
        e.on_depth("AAA", 0, UPDATE, BID, 9.99, 5000, "", 31.0); e.tick(31.5, allocate_slots=False)
        e.on_depth_reset("AAA", 32.0)
        for i in range(5):                                                 # the book comes back smaller
            e.on_depth("AAA", i, INSERT, BID, round(9.99 - i * 0.01, 2), 800, "", 32.1)
            e.on_depth("AAA", i, INSERT, ASK, round(10.00 + i * 0.01, 2), 800, "", 32.1)
        e.tick(32.5, allocate_slots=False); e.tick(35.0, allocate_slots=False); e.tick(37.0, allocate_slots=False)
        r = row(lad(e, 37.1), 9.99)
        self.assertNotIn("bid_real", r)                                   # nothing judged from the rebuild
        self.assertNotIn("ps_b", r)
        self.assertEqual(r["bid"], 800)
        self.assertGreaterEqual(e.syms["AAA"].resets, 1)

    def test_stale_feed_is_reported(self):
        e = make()
        e.on_print("AAA", 10.00, 100, "X", 31.0)
        h = e._health(e.syms["AAA"], 31.0 + 3600)
        self.assertEqual(h["status"], "STALE")
        self.assertTrue(h["tape_stale"])
        self.assertGreater(h["l1_age"], 3000)


class Scenario9_HeavyBurst(unittest.TestCase):
    """5,000 prints in a burst: the accounting is exact (every share counted once) and a row build stays fast."""
    def test_burst_exact_and_fast(self):
        e = make()
        total = 0
        t = 31.0
        for i in range(5000):
            p = round(9.98 + 0.01 * (i % 5), 2)
            sz = 100 + (i % 7) * 10
            e.on_print("AAA", p, sz, "X", t, "", int(t)); t += 0.001
            total += sz
        t0 = _time.perf_counter()
        L = lad(e, t + 0.1)
        ms = (_time.perf_counter() - t0) * 1000
        self.assertEqual(sum(r["bk"][0] for r in L["rows"] if r.get("bk")), total)
        self.assertEqual(sum(r["bk"][3] for r in L["rows"] if r.get("bk")), 5000)
        self.assertLess(ms, 250, f"ladder build took {ms:.0f} ms")


if __name__ == "__main__":
    unittest.main()
