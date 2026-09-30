import unittest

from helpers import ASK, BID, DELETE, INSERT, UPDATE, Book, cfg, ladder, plays, seller_book
from twiney.conviction import ACTIVE, FADING, GONE, STALE, PullBook, real_label
from twiney.engine import Engine
from twiney.levels import LevelTracker
from twiney.tape import BUY, SELL


# ---- the reloader's conviction: ACTIVE -> FADING -> STALE, back on a refill, GONE when the level fails ----

class Harness:
    def __init__(self, **reload_overrides):
        self.rc = cfg(reload=reload_overrides)["reload"]
        self.book = seller_book()
        self.tr = LevelTracker("AAA", 10.00, ASK, "trigger", self.rc, 0.0)
        self.alerts = []

    def _note(self, label, t):
        if label:
            self.alerts.append((t, label))

    def show(self, size, t):
        self.book.apply(0, UPDATE, ASK, 10.00, size)
        self._note(self.tr.on_book(self.book, t), t)

    def remove(self, t):
        self.book.apply(0, DELETE, ASK, 10.00, 0)
        self._note(self.tr.on_book(self.book, t), t)

    def hit(self, size, t, price=10.00):
        self._note(self.tr.on_print(price, size, BUY, t, self.book), t)

    def tick(self, t):
        self._note(self.tr.evaluate(t, self.book), t)

    def build_reload(self):
        self.show(1000, 1.0)
        self.hit(600, 2.0)
        self.show(400, 2.1)
        self.show(1000, 3.0)
        self.hit(700, 4.0)
        self.show(300, 4.1)
        self.show(1000, 5.0)
        self.hit(400, 6.0)


class ConvictionTests(unittest.TestCase):
    def test_not_proven_reads_zero_and_no_stage(self):
        h = Harness()
        h.show(1000, 1.0)
        self.assertEqual(h.tr.conviction(1.0), 0.0)
        self.assertIsNone(h.tr.stage(1.0))

    def test_fresh_reload_is_active(self):
        h = Harness()
        h.build_reload()
        self.assertEqual(h.alerts, [(6.0, "RELOAD SELLER DETECTED")])
        self.assertEqual(h.tr.stage(6.0), ACTIVE)
        self.assertGreaterEqual(h.tr.conviction(6.0), 0.75)

    def test_volume_through_without_a_refill_fades_then_goes_stale(self):
        h = Harness()
        h.build_reload()
        # the most he ever let trade before replacing it was 700; peak showing 1000; stale at 1.5 x 1000 = 1500 through
        h.show(400, 7.0)                    # size still there, but he is not replacing what gets hit
        h.hit(600, 8.0)                     # 1000 through since the last refill (the 400 at t=6 + 600)
        h.show(100, 8.1)
        self.assertEqual(h.tr.stage(8.1), FADING)
        h.hit(900, 9.0)                     # 1500 through: 1.5 x the most he ever showed, with nothing replaced
        self.assertEqual(h.tr.conviction(9.0), 0.0)
        self.assertEqual(h.tr.stage(9.0), STALE)
        self.assertTrue(h.tr.proven)        # stale is not gone: nothing has been decided about him yet

    def test_a_refill_snaps_conviction_back(self):
        h = Harness()
        h.build_reload()
        h.show(400, 7.0)
        h.hit(600, 8.0)
        h.show(100, 8.1)
        self.assertEqual(h.tr.stage(8.1), FADING)
        h.show(1200, 9.0)                   # he came back with size after getting hit: a refill
        self.assertEqual(h.tr.conviction(9.0), 1.0)
        self.assertEqual(h.tr.stage(9.0), ACTIVE)
        self.assertEqual(h.tr.vol_since_refill, 0.0)

    def test_time_alone_bleeds_slowly_and_never_under_half_while_showing(self):
        h = Harness(stale_seconds=1000.0)
        h.build_reload()
        h.show(1000, 7.0)                   # 1000 showing, nothing trades for a long time
        self.assertGreaterEqual(h.tr.conviction(7.0), 0.99)
        self.assertAlmostEqual(h.tr.conviction(506.0), 0.5, places=2)
        self.assertEqual(h.tr.conviction(2007.0), 0.5)       # size still showing: time alone stops at half
        self.assertEqual(h.tr.stage(2007.0), FADING)

    def test_time_bleeds_to_stale_when_nothing_is_showing(self):
        h = Harness(stale_seconds=1000.0)
        h.build_reload()
        h.show(1000, 6.5)
        h.hit(800, 7.0)                     # eaten...
        h.remove(7.05)                      # ...and gone, but price never went through: inconclusive, still proven
        h.tr.evaluate(20.0, h.book)
        self.assertTrue(h.tr.proven)
        self.assertLess(h.tr.conviction(1500.0), 0.25)
        self.assertEqual(h.tr.stage(1500.0), STALE)

    def test_price_through_an_undefended_level_is_gone(self):
        h = Harness()
        h.build_reload()
        h.show(1000, 6.5)
        h.hit(800, 7.0)
        h.remove(7.05)
        h.tr.evaluate(20.0, h.book)         # inconclusive: proven, but empty
        self.assertTrue(h.tr.proven)
        h.hit(100, 21.0, price=10.02)       # price trades through with nothing sitting there
        self.assertFalse(h.tr.proven)
        self.assertEqual(h.tr.stage(21.0), GONE)
        self.assertEqual(h.tr.conviction(21.0), 0.0)
        self.assertIsNone(h.tr.stage(21.0 + 7200.0 + 1))     # the ghost fades after gone_show_seconds

    def test_cleaned_up_verdict_is_gone(self):
        h = Harness()
        h.build_reload()
        h.show(1000, 7.0)
        h.hit(1000, 8.0)                    # eaten
        h.remove(8.05)
        h.hit(200, 8.2, price=10.01)        # and price trades through
        h.tick(11.1)
        self.assertIn((11.1, "CLEANED UP"), h.alerts)
        self.assertEqual(h.tr.stage(11.1), GONE)

    def test_snapshot_carries_conviction(self):
        h = Harness()
        h.build_reload()
        snap = h.tr.snapshot(6.0)
        self.assertEqual(snap["stage"], ACTIVE)
        self.assertIn("conviction", snap)
        self.assertIn("since_refill", snap)
        self.assertIn("refill_age", snap)


# ---- REAL or FAKE: of the size that left a price, what traded vs vanished ----

class PullBookTests(unittest.TestCase):
    def setUp(self):
        self.pb = PullBook({"requote_seconds": 1.0, "real_min_shares": 100})
        self.book = Book(10)
        ladder(self.book, BID, [(9.99, 500), (9.98, 400), (9.97, 300)])
        ladder(self.book, ASK, [(10.00, 1000), (10.01, 800), (10.02, 900)])
        self.pb.on_book(self.book, ASK, 0.0)
        self.pb.on_book(self.book, BID, 0.0)

    def k(self, p):
        from twiney.prices import price_key
        return price_key(p)

    def test_first_read_counts_nothing(self):
        self.assertIsNone(self.pb.at(ASK, self.k(10.00)))

    def test_size_that_traded_is_filled(self):
        self.pb.on_print("buy", 10.00, 600)              # lifted the offer
        self.book.apply(0, UPDATE, ASK, 10.00, 400)
        self.pb.on_book(self.book, ASK, 1.0)
        r = self.pb.at(ASK, self.k(10.00))
        self.assertEqual((r["filled"], r["pulled"]), (600, 0))
        self.assertEqual(r["label"], "REAL")

    def test_size_that_vanished_is_pulled_after_the_requote_window(self):
        self.book.apply(0, UPDATE, ASK, 10.00, 200)      # 800 left, nothing printed
        self.pb.on_book(self.book, ASK, 1.0)
        self.assertIsNone(self.pb.at(ASK, self.k(10.00)))       # not yet: it may be a venue re-quoting
        self.pb.flush(2.5)
        r = self.pb.at(ASK, self.k(10.00))
        self.assertEqual((r["filled"], r["pulled"]), (0, 800))
        self.assertEqual(r["label"], "FAKE")

    def test_a_drop_that_comes_straight_back_is_a_requote_not_a_pull(self):
        self.book.apply(0, UPDATE, ASK, 10.00, 200)
        self.pb.on_book(self.book, ASK, 1.0)
        self.book.apply(0, UPDATE, ASK, 10.00, 1000)     # back inside a second
        self.pb.on_book(self.book, ASK, 1.4)
        self.pb.flush(5.0)
        self.assertIsNone(self.pb.at(ASK, self.k(10.00)))

    def test_mixed_reads_mixed(self):
        self.pb.on_print("buy", 10.00, 500)
        self.book.apply(0, UPDATE, ASK, 10.00, 0)        # 1000 left: 500 traded, 500 vanished
        self.pb.on_book(self.book, ASK, 1.0)
        self.pb.flush(3.0)
        r = self.pb.at(ASK, self.k(10.00))
        self.assertEqual((r["filled"], r["pulled"]), (500, 500))
        self.assertEqual(r["label"], "MIXED")

    def test_hit_and_refilled_inside_one_read_counts_as_traded(self):
        self.pb.on_print("buy", 10.00, 300)
        self.pb.on_book(self.book, ASK, 1.0)             # size unchanged: he replaced exactly what traded
        r = self.pb.at(ASK, self.k(10.00))
        self.assertEqual(r["filled"], 300)

    def test_a_bid_hit_takes_from_the_bid_side(self):
        self.pb.on_print("sell", 9.99, 500)
        self.book.apply(0, DELETE, BID, 9.99, 0)
        self.pb.on_book(self.book, BID, 1.0)
        r = self.pb.at(BID, self.k(9.99))
        self.assertEqual(r["label"], "REAL")

    def test_resync_counts_nothing(self):
        self.pb.on_book(self.book, ASK, 1.0, judge=False)
        self.book.apply(0, UPDATE, ASK, 10.00, 0)
        self.pb.on_book(self.book, ASK, 1.5, judge=False)
        self.pb.flush(5.0)
        self.assertIsNone(self.pb.at(ASK, self.k(10.00)))

    def test_prune_forgets_old_prices(self):
        self.pb.on_print("buy", 10.00, 600)
        self.book.apply(0, UPDATE, ASK, 10.00, 400)
        self.pb.on_book(self.book, ASK, 1.0)
        self.pb.prune(5000.0, 3600.0)
        self.assertIsNone(self.pb.at(ASK, self.k(10.00)))

    def test_labels(self):
        self.assertEqual(real_label(0.9), "REAL")
        self.assertEqual(real_label(0.5), "MIXED")
        self.assertEqual(real_label(0.1), "FAKE")
        self.assertIsNone(real_label(None))


# ---- through the engine: the ladder rows, the ghost marks, and rotation that leans toward a live reloader ----

def connected_engine(**sections):
    e = Engine(plays(), cfg(**sections))
    e.on_connection("CONNECTED", "", 0.0)
    return e


def price_all(e, t, prices):
    for sym, px in prices.items():
        e.on_l1(sym, "last", px, t)


def seed_book(e, sym, t, bid=9.99, ask=10.00, ask_size=1000):
    for i in range(3):
        e.on_depth(sym, i, INSERT, BID, round(bid - i * 0.01, 2), 500, "", t)
        e.on_depth(sym, i, INSERT, ASK, round(ask + i * 0.01, 2), ask_size if i == 0 else 800, "", t)


def prove_seller(e, sym="AAA", t0=10.0):
    """Drive AAA's trigger (10.00, ask side) to a confirmed reload seller, ticking the clock the way the live
    loop does (every quarter second) so the book is read between events."""
    e.on_l1(sym, "bid", 9.99, t0); e.on_l1(sym, "ask", 10.00, t0)
    e.tick(t0)
    e.on_print(sym, 10.00, 600, "X", t0 + 1)
    e.on_depth(sym, 0, UPDATE, ASK, 10.00, 400, "", t0 + 1.1)
    e.tick(t0 + 1.25)
    e.on_depth(sym, 0, UPDATE, ASK, 10.00, 1000, "", t0 + 2)
    e.tick(t0 + 2.25)
    e.on_print(sym, 10.00, 700, "X", t0 + 3)
    e.on_depth(sym, 0, UPDATE, ASK, 10.00, 300, "", t0 + 3.1)
    e.tick(t0 + 3.25)
    e.on_depth(sym, 0, UPDATE, ASK, 10.00, 1000, "", t0 + 4)
    e.tick(t0 + 4.25)
    e.on_print(sym, 10.00, 400, "X", t0 + 5)
    e.tick(t0 + 5.25)


class EngineConvictionTests(unittest.TestCase):
    def setUp(self):
        self.e = connected_engine(ladder={"real_min_shares": 1000})
        price_all(self.e, 1.0, {"AAA": 10.01, "BBB": 50.02, "CCC": 20.50, "DDD": 5.30})
        self.e.tick(1.0)
        seed_book(self.e, "AAA", 2.0)
        self.e.on_l1("AAA", "bid", 9.99, 2.0); self.e.on_l1("AAA", "ask", 10.00, 2.0)
        self.e.tick(3.5)                     # first tick after the resync grace: primes the book memory

    def ask_tracker(self):
        return next(tr for tr in self.e.syms["AAA"].trackers.values() if tr.side == ASK and abs(tr.price - 10.00) < 1e-9)

    def row(self, price, t):
        st = self.e.syms["AAA"]
        lad = self.e._memory_ladder(st, t, self.e._user_levels(st.play))
        return next(r for r in lad["rows"] if abs(float(r["price"]) - price) < 1e-9)

    def test_ladder_row_carries_stage_and_conviction(self):
        prove_seller(self.e)
        tr = self.ask_tracker()
        self.assertTrue(tr.proven)
        r = self.row(10.00, 15.0)
        self.assertEqual(r["ask_stage"], ACTIVE)
        self.assertGreaterEqual(r["ask_conv"], 0.75)
        self.assertIn("ask_since_refill", r)

    def test_ladder_row_carries_real_or_fake(self):
        prove_seller(self.e)                 # 1700 traded into 10.00 and the size dropped after each hit: REAL
        self.e.tick(16.0)
        r = self.row(10.00, 16.0)
        self.assertIn("ask_real", r)
        self.assertEqual(r["ask_real"]["label"], "REAL")

    def test_absorbed_here_survives_as_a_ghost_after_the_reloader_is_gone(self):
        prove_seller(self.e)
        self.e.on_print("AAA", 10.00, 1000, "X", 15.5)                 # eaten...
        self.e.on_depth("AAA", 0, DELETE, ASK, 10.00, 0, "", 15.6)     # ...the seller is gone...
        self.e.on_print("AAA", 10.01, 200, "X", 15.8)                  # ...and price trades through
        self.e.tick(16.0)
        self.e.tick(20.0)
        tr = self.ask_tracker()
        self.assertFalse(tr.proven)
        self.assertEqual(tr.stage(20.0), GONE)
        st = self.e.syms["AAA"]
        self.assertIn(("ask", tr.key), st.absorb_hist)
        self.assertGreaterEqual(st.absorb_hist[("ask", tr.key)][1], 1700)
        self.assertEqual(st.absorb_hist[("ask", tr.key)][3], "CLEANED UP")
        r = self.row(10.00, 3000.0)          # much later the row still shows the ghost...
        self.assertEqual(r["ask_stage"], GONE)
        # ...and after the ghost window the long memory is still there for the rest of the day, with the verdict
        r = self.row(10.00, 20.0 + 7200.0 + 5)
        self.assertIsNone(r.get("ask_stage"))
        self.assertEqual(r["ask_was"]["verdict"], "CLEANED UP")
        self.assertGreaterEqual(r["ask_was"]["shares"], 1700)

    def test_protected_includes_a_fading_reloader(self):
        prove_seller(self.e)
        self.assertIn("AAA", self.e._protected(15.0))
        # let a fair amount trade through with no refill: FADING, still protected
        self.e.on_depth("AAA", 0, UPDATE, ASK, 10.00, 400, "", 16.0)
        self.e.on_print("AAA", 10.00, 600, "X", 17.0)
        self.e.on_depth("AAA", 0, UPDATE, ASK, 10.00, 100, "", 17.1)
        self.assertEqual(self.ask_tracker().stage(17.1), FADING)
        self.assertIn("AAA", self.e._protected(17.1))

    def test_rotation_ranking_pulls_a_live_reloader_closer(self):
        prove_seller(self.e)
        self.e.on_l1("AAA", "last", 10.04, 15.0)    # a little off the pivot, so distance is not zero
        self.e.syms["AAA"].l1["last"] = 10.04
        plain = dict(self.e.ranking(15.0))
        weighted = dict(self._rotation(15.0))
        self.assertLess(weighted["AAA"], plain["AAA"])
        self.assertEqual(weighted["BBB"], plain["BBB"])     # no reloader on BBB: distance only

    def _rotation(self, t):
        return self.e._rotation_ranking(t)

    def test_conviction_weight_zero_is_distance_only(self):
        e = connected_engine(depth={"conviction_weight": 0.0})
        price_all(e, 1.0, {"AAA": 10.01, "BBB": 50.02, "CCC": 20.50, "DDD": 5.30})
        e.tick(1.0)
        seed_book(e, "AAA", 2.0)
        prove_seller(e)
        self.assertEqual(dict(e._rotation_ranking(15.0)), dict(e.ranking(15.0)))

    def test_reloaders_and_levels_carry_stage(self):
        prove_seller(self.e)
        rl = self.e._reloaders(self.e.syms["AAA"], 15.0, 9.995)
        self.assertEqual(rl["above"][0]["stage"], ACTIVE)
        pane = self.e._pane("AAA", 0, 15.0, [], full=False)
        lv = next(l for l in pane["levels"] if l["side"] == "ask" and abs(float(l["price"]) - 10.00) < 1e-9)
        self.assertEqual(lv["stage"], ACTIVE)
        self.assertTrue(lv["words"])
        self.assertIn("real", lv)


if __name__ == "__main__":
    unittest.main()


# ---- SOMEBODY KNOWS: short-dated out-of-the-money flow at the ask, agreeing with the level ----

class KnowsTests(unittest.TestCase):
    def setUp(self):
        self.e = connected_engine(ladder={"real_min_shares": 1000}, flow={"urgency_min_dollars": 100000, "urgency_max_dte": 7})
        price_all(self.e, 1.0, {"AAA": 10.01, "BBB": 50.02, "CCC": 20.50, "DDD": 5.30})
        self.e.tick(1.0)
        seed_book(self.e, "AAA", 2.0)
        self.e.on_l1("AAA", "bid", 9.99, 2.0); self.e.on_l1("AAA", "ask", 10.00, 2.0)
        self.e.tick(3.5)

    def put(self, t, strike=9.50, dte=3.0, prem=60000, side="ask", cp="P", kind="sweep", otm=None):
        spot = 10.0
        if otm is None:
            otm = (spot - strike) / spot * 100 if cp == "P" else (strike - spot) / spot * 100
        self.e.on_flow({"t": t, "symbol": "AAA", "strike": strike, "cp": cp, "expiry": "2026-10-03", "dte": dte, "size": 100,
                        "price": prem / 10000, "premium": prem, "spot": spot, "side": side, "kind": kind, "otm_pct": otm,
                        "oi": None, "iv": None}, t)

    def test_no_flow_is_not_knows(self):
        k = self.e._knows(self.e.syms["AAA"], ASK, 5.0)
        self.assertFalse(k["knows"])
        self.assertEqual(k["dollars"], 0)

    def test_short_dated_otm_puts_at_the_ask_confirm_a_reload_seller(self):
        prove_seller(self.e)
        self.put(15.5); self.put(15.6); self.put(15.7)          # $180K of 3-day 5%-OTM puts, at the ask
        k = self.e._knows(self.e.syms["AAA"], ASK, 16.0)
        self.assertTrue(k["knows"])
        self.assertEqual(k["prints"], 3)
        self.assertEqual(k["sweeps"], 3)
        self.assertEqual(k["top"]["strike"], 9.50)
        self.assertIn("SOMEBODY KNOWS", k["words"])
        r = next(r for r in self.e._memory_ladder(self.e.syms["AAA"], 16.0, self.e._user_levels(self.e.syms["AAA"].play))["rows"] if abs(float(r["price"]) - 10.00) < 1e-9)
        self.assertTrue(r["ask_knows"]["knows"])
        rl = self.e._reloaders(self.e.syms["AAA"], 16.0, 9.995)
        self.assertTrue(rl["above"][0]["knows"])

    def test_calls_do_not_confirm_a_seller(self):
        prove_seller(self.e)
        self.put(15.5, strike=10.50, cp="C"); self.put(15.6, strike=10.50, cp="C"); self.put(15.7, strike=10.50, cp="C")
        k = self.e._knows(self.e.syms["AAA"], ASK, 16.0)
        self.assertFalse(k["knows"])
        self.assertEqual(k["against"], 180000)
        kb = self.e._knows(self.e.syms["AAA"], BID, 16.0)      # ...they would confirm a buyer
        self.assertTrue(kb["knows"])

    def test_long_dated_or_at_the_bid_does_not_count(self):
        self.put(5.0, dte=30.0); self.put(5.1, dte=30.0); self.put(5.2, dte=30.0)
        self.assertEqual(self.e._knows(self.e.syms["AAA"], ASK, 6.0)["dollars"], 0)
        self.put(7.0, side="bid"); self.put(7.1, side="bid"); self.put(7.2, side="bid")
        self.assertEqual(self.e._knows(self.e.syms["AAA"], ASK, 8.0)["dollars"], 0)

    def test_the_other_side_outweighing_halves_the_score(self):
        self.put(5.0); self.put(5.1)                             # $120K puts
        self.put(5.2, strike=10.50, cp="C", prem=200000)         # $200K calls the other way
        k = self.e._knows(self.e.syms["AAA"], ASK, 6.0)
        self.assertFalse(k["knows"])
        self.assertAlmostEqual(k["score"], 0.3, places=2)        # 120K / 200K = 0.6, halved

    def test_rotation_leans_toward_somebody_knows(self):
        self.e.on_l1("AAA", "last", 10.04, 5.0); self.e.syms["AAA"].l1["last"] = 10.04
        plain = dict(self.e.ranking(6.0))
        self.put(5.5); self.put(5.6); self.put(5.7)
        weighted = dict(self.e._rotation_ranking(6.0))
        self.assertLess(weighted["AAA"], plain["AAA"])
        self.assertEqual(weighted["BBB"], plain["BBB"])

    def test_pane_levels_carry_knows(self):
        prove_seller(self.e)
        self.put(15.5); self.put(15.6); self.put(15.7)
        pane = self.e._pane("AAA", 0, 16.0, [], full=False)
        lv = next(l for l in pane["levels"] if l["side"] == "ask" and abs(float(l["price"]) - 10.00) < 1e-9)
        self.assertTrue(lv["knows"]["knows"])
        self.assertEqual(lv["knows"]["cp"], "P")


class KnowsCacheTests(unittest.TestCase):
    def test_one_read_per_symbol_until_a_print_lands_or_a_second_passes(self):
        e = connected_engine()
        st = e.syms["AAA"]
        calls = []
        real = e.flow.knows
        e.flow.knows = lambda *a, **k: (calls.append(a), real(*a, **k))[1]
        for _ in range(25):                      # twenty ladder rows, the reloaders list, the pane: one read
            e._knows(st, ASK, 10.2)
            e._knows(st, ASK, 10.4)
        self.assertEqual(len(calls), 1)
        e._knows(st, ASK, 11.0)                  # a second later: one more
        self.assertEqual(len(calls), 2)
        e.on_flow({"t": 11.1, "symbol": "AAA", "strike": 9.5, "cp": "P", "expiry": "2026-10-03", "dte": 3, "size": 100, "price": 6.0,
                   "premium": 60000, "spot": 10.0, "side": "ask", "kind": "sweep", "otm_pct": 5.0, "oi": None, "iv": None}, 11.1)
        e._knows(st, ASK, 11.2)                  # a new print on the name: read again at once
        self.assertEqual(len(calls), 3)
        e._knows(st, BID, 11.2)                  # the other side is its own read
        self.assertEqual(len(calls), 4)
