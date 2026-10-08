"""THE BASKET LADDER (handoff v3.3.0): the print guard (no double count live or in replay), FLIP needs both conditions,
the PS60 SEQUENCE steps in order, the row fields the page draws from. Display only: no order code involved."""
import json
import os
import tempfile
import unittest

from helpers import cfg, plays
from twiney.engine import Engine
from twiney.book import INSERT, UPDATE, DELETE, BID, ASK
from twiney.ladderbasket import PrintGuard, FlipWatch, sequence, flip_words
from twiney.prices import price_key

T0 = 1791460800.0 + 3 * 3600        # 2026-10-08 11:00 New York


def make():
    e = Engine(plays(), cfg()); e.on_connection("DEMO", "", T0); e.apply_slot("AAA", True, T0)
    for i in range(5):
        e.on_depth("AAA", i, INSERT, BID, round(9.99 - i * 0.01, 2), 1000, "", T0)
        e.on_depth("AAA", i, INSERT, ASK, round(10.00 + i * 0.01, 2), 1000, "", T0)
    e.on_l1("AAA", "bid", 9.99, T0); e.on_l1("AAA", "ask", 10.00, T0); e.on_l1("AAA", "last", 10.00, T0)
    return e


def row(e, t, price):
    with e.lock:
        st = e.syms["AAA"]
        L = e._memory_ladder(st, t, e._user_levels(st.play))
    return next((r for r in L["rows"] if abs(float(r["price"]) - price) < 1e-9), None), L


class PrintGuardTests(unittest.TestCase):
    def test_two_real_identical_prints_in_one_second_both_count(self):
        g = PrintGuard()
        self.assertTrue(g.first_time(1.0, 1000, 10.0, 100, "NASDAQ"))
        self.assertTrue(g.first_time(1.1, 1000, 10.0, 100, "NASDAQ"))      # a second real one, same second

    def test_redelivery_after_reconnect_is_ignored(self):
        g = PrintGuard()
        for _ in range(3):
            g.first_time(1.0, 1000, 10.0, 100, "NASDAQ")
        g.new_connection()
        self.assertEqual([g.first_time(5.0, 1000, 10.0, 100, "NASDAQ") for _ in range(4)], [False, False, False, True])

    def test_different_exchange_or_size_is_a_different_print(self):
        g = PrintGuard()
        g.first_time(1.0, 1000, 10.0, 100, "NASDAQ")
        g.new_connection()
        self.assertTrue(g.first_time(1.0, 1000, 10.0, 100, "ARCA"))
        self.assertTrue(g.first_time(1.0, 1000, 10.0, 200, "NASDAQ"))

    def test_engine_counts_once_through_a_reconnect(self):
        e = make()
        e.on_connection("CONNECTED", "", T0)
        for i in range(3):
            e.on_print("AAA", 10.00, 100, "NASDAQ", T0 + 1, xt=T0 + 1)
        e.on_connection("DISCONNECTED", "", T0 + 2); e.on_connection("CONNECTED", "", T0 + 3)
        for i in range(3):                                                    # the same three, delivered again
            e.on_print("AAA", 10.00, 100, "NASDAQ", T0 + 4, xt=T0 + 1)
        self.assertEqual(e.syms["AAA"].basket[1000][0], 300)
        self.assertEqual(e.dup_prints, 3)

    def test_replay_never_recounts(self):
        """A recorded busy practice session, replayed twice (seeking back = starting over): every price's basket equals
        a raw count of the recorded prints, exactly, both times; and equals the live run."""
        from twiney.recorder import Recorder, read_events
        from twiney.replay import replay, session_header
        from twiney.sim import DemoFeed
        with tempfile.TemporaryDirectory() as d:
            c, ps = cfg(), plays()
            rec = Recorder(d, "t.jsonl"); rec.write(session_header(ps, c, "test"))
            live = Engine(ps, c, rec); feed = DemoFeed(live, ps, seed=5)
            t = 1000.0; feed.start(t)
            for _ in range(4 * 300):
                t += 0.25; feed.step(t)
            rec.close()
            raw = {}
            for ev in read_events(rec.path):
                if ev.get("ev") == "print":
                    k = (ev["sym"], price_key(ev["px"]))           # the desk's own rule (sub-penny prints included)
                    raw[k] = raw.get(k, 0) + ev["sz"]
            self.assertGreater(len(raw), 10)
            got_live = {(s, k): v[0] for s, st in live.syms.items() for k, v in (st.__dict__.get("basket") or {}).items()}
            self.assertEqual(got_live, raw)
            for _ in range(2):
                eng, _rec = replay(rec.path)
                got = {(s, k): v[0] for s, st in eng.syms.items() for k, v in (st.__dict__.get("basket") or {}).items()}
                self.assertEqual(got, raw)


class FlipTests(unittest.TestCase):
    def test_needs_both_conditions(self):
        fw = FlipWatch(); c = {"flip_dead_seconds": 20, "flip_min_shares": 1000, "flip_hold_seconds": 2}
        book = {("bid", 10.0): 0}
        size_at = lambda side, p: book.get((side, round(p, 2)), 0)
        seller = lambda stage, last_refill, seq=5: [("ask", 10.0, stage, last_refill, seq, True)]
        # 1) refill dead, nothing on the other side: no flip
        self.assertEqual(fw.update(100, seller("NOT RELOADING", 50), size_at, c), [])
        # 2) bids show at 10.00 but the seller is still RELOADING (refilled 5 s ago): no flip
        book[("bid", 10.0)] = 3000
        self.assertEqual(fw.update(100, seller("RELOADING", 95), size_at, c), [])
        self.assertEqual(fw.update(103, seller("RELOADING", 98), size_at, c), [])
        # 3) both: dead AND the other side holding 2 s -> FLIP
        self.assertEqual(fw.update(110, seller("NOT RELOADING", 50), size_at, c), [])
        self.assertEqual(fw.update(112.5, seller("NOT RELOADING", 50), size_at, c), [("ask", 10.0)])
        self.assertEqual(fw.at(10.0), "seller")
        # it ends when the seller refills again
        fw.update(113, seller("RELOADING", 113, seq=6), size_at, c)
        self.assertIsNone(fw.at(10.0))

    def test_a_thin_print_never_flips(self):
        fw = FlipWatch(); c = {"flip_dead_seconds": 20, "flip_min_shares": 1000, "flip_hold_seconds": 2}
        sz = {"v": 100}                                                       # 100 shares bid at the price: thin
        for t in range(100, 120):
            self.assertEqual(fw.update(t, [("ask", 10.0, "CLEANED UP", 10, 3, True)], lambda s, p: sz["v"], c), [])

    def test_flash_size_does_not_flip(self):
        fw = FlipWatch(); c = {"flip_dead_seconds": 20, "flip_min_shares": 1000, "flip_hold_seconds": 2}
        seq = [5000, 0, 5000, 0, 5000, 0]                                     # flickers in and out: never held 2 s
        for i, v in enumerate(seq):
            self.assertEqual(fw.update(100 + i, [("ask", 10.0, "CLEANED UP", 10, 3, True)], lambda s, p, v=v: v, c), [])

    def test_no_mirror_flip_flicker(self):
        fw = FlipWatch(); c = {"flip_dead_seconds": 20, "flip_min_shares": 1000, "flip_hold_seconds": 2, "flip_mirror_seconds": 60}
        both = lambda: [("ask", 10.0, "CLEANED UP", 1, 3, True), ("bid", 10.0, "CLEANED UP", 1, 3, True)]
        bk = {"bid": 3000, "ask": 0}
        for t in (100, 103):
            fw.update(t, both(), lambda s, p: bk[s], c)
        self.assertEqual(fw.at(10.0), "seller")
        bk.update(bid=0, ask=3000)                                            # the other way a moment later
        for t in (104, 106, 108, 140):
            self.assertEqual(fw.update(t, both(), lambda s, p: bk[s], c), [])
        self.assertIsNone(fw.at(10.0))
        fw.update(170, both(), lambda s, p: bk[s], c); out = fw.update(173, both(), lambda s, p: bk[s], c)
        self.assertEqual(out, [("bid", 10.0)])                               # a minute later it may flip the other way

    def test_buyer_flip_words(self):
        self.assertEqual(flip_words("10.00", "seller"), "10.00 FLIP, seller losing, buyers taking over")
        self.assertEqual(flip_words("10.00", "buyer"), "10.00 FLIP, buyer losing, sellers taking over")

    def test_engine_flip_alert_once(self):
        e = make()
        st = e.syms["AAA"]
        e.set_play_level("AAA", "trigger", 10.00, T0)
        tr = st.trackers[(ASK, 1000)]
        tr.proven = True; tr.last_refill_t = T0; tr.confirmed_at = T0
        e.on_depth("AAA", 0, UPDATE, BID, 10.00, 4000, "", T0 + 30)      # bids take the price
        e.on_depth("AAA", 0, DELETE, ASK, 10.00, 0, "", T0 + 30)
        tr.displayed = 0
        for k in range(6):
            e.tick(T0 + 30 + k)
        flips = [a for a in e.alerts if a["label"] == "FLIP"]
        self.assertEqual(len(flips), 1); self.assertIn("seller losing, buyers taking over", flips[0]["text"])
        r, _ = row(e, T0 + 36, 10.00)
        self.assertEqual(r.get("flip"), "seller")


class SequenceTests(unittest.TestCase):
    def stage(self, d, b):
        return lambda side: d if side == "bid" else b

    def test_steps_in_order_long(self):
        pl = {"trigger": 10.00, "side": "long"}
        s = sequence(pl, {"state": "IDLE"}, self.stage((None, 0), ("RELOADING", 3000)))
        self.assertEqual(s["step"], 1); self.assertIn("reload seller at the pivot: RELOADING", s["note"])
        s = sequence(pl, {"state": "BROKE", "extreme": "10.25"}, self.stage((None, 0), ("CLEANED UP", 0)))
        self.assertEqual(s["step"], 2); self.assertIn("new high 10.25", s["note"])
        s = sequence(pl, {"state": "RETRACE", "extreme": "10.25"}, self.stage(("RELOADING", 2000), (None, 0)))
        self.assertEqual(s["step"], 3); self.assertEqual(s["verdict"], "RELOADING"); self.assertEqual(s["verdict_side"], "bid")
        s = sequence(pl, {"state": "SECOND_ENTRY", "extreme": "10.25"}, self.stage(("STILL THERE", 2000), (None, 0)))
        self.assertEqual(s["step"], 4); self.assertTrue(s["lit4"])

    def test_step4_not_lit_without_the_reload_buyer(self):
        pl = {"trigger": 10.00, "side": "long"}
        for d in ((None, 0), ("NOT RELOADING", 0), ("CLEANED UP", 0), ("PULLED", 0)):
            s = sequence(pl, {"state": "SECOND_ENTRY", "extreme": "10.25"}, self.stage(d, (None, 0)))
            self.assertEqual(s["step"], 3); self.assertFalse(s["lit4"])

    def test_short_mirror(self):
        pl = {"trigger": 10.00, "side": "short"}
        s = sequence(pl, {"state": "RETRACE", "extreme": "9.80"}, lambda side: ("RELOADING", 1000) if side == "ask" else (None, 0))
        self.assertEqual(s["verdict_side"], "ask"); self.assertIn("reload seller: RELOADING", s["note"])

    def test_no_trigger_no_sequence(self):
        self.assertIsNone(sequence({"side": "long"}, {"state": "IDLE"}, lambda s: (None, 0)))


class RowFieldTests(unittest.TestCase):
    def test_refill_seq_rate_and_absorbed_agree(self):
        e = make()
        e.set_play_level("AAA", "trigger", 9.99, T0)
        st = e.syms["AAA"]
        tr = st.trackers[(BID, 999)]
        tr.refill_seq = 7; tr.refresh_times.extend([T0 + 50, T0 + 55])
        st.absorb_hist[("bid", 999)] = [9.99, 4200.0, T0 + 55, None, True]
        r, L = row(e, T0 + 60, 9.99)
        self.assertEqual(r["bid_rseq"], 7); self.assertEqual(r["bid_rf"], 2); self.assertEqual(r["bid_abs"], 4200)
        self.assertIn("basket_drop_ms", L["basket"]); self.assertIn("norm", L["basket"])

    def test_settings_defaults(self):
        c = cfg()["ladder"]
        self.assertEqual((c["basket_drop_ms"], c["basket_merge_ms"], c["basket_max_drops"]), (250, 50, 12))
        for k in ("basket_animate", "basket_pulse", "basket_glow", "basket_flip_alerts", "basket_touch_counter", "basket_sequence", "basket_manual_pop"):
            self.assertTrue(c[k], k)


if __name__ == "__main__":
    unittest.main()


class TiedTogetherTests(unittest.TestCase):
    """One system: the same reload tracker feeds the ladder, the FLIP, the PS60 SEQUENCE and the STORY; a FLIP and a
    trapped break reach the CALLS and the PS60 STORY feed like every other call."""
    def test_flip_goes_to_calls_and_the_story(self):
        e = make()
        st = e.syms["AAA"]
        e.set_play_level("AAA", "trigger", 10.00, T0)
        tr = st.trackers[(ASK, 1000)]
        tr.proven = True; tr.last_refill_t = T0; tr.confirmed_at = T0
        e.on_depth("AAA", 0, UPDATE, BID, 10.00, 4000, "", T0 + 30)
        e.on_depth("AAA", 0, DELETE, ASK, 10.00, 0, "", T0 + 30)
        tr.displayed = 0
        for k in range(6):
            e.tick(T0 + 30 + k)
        self.assertTrue(any(a["role"] == "flip" for a in e.alerts))
        self.assertTrue(any("FLIP at 10.00" in f[1] for f in st.storybook.feed), list(st.storybook.feed)[:3])

    def test_the_same_tracker_feeds_ladder_sequence_and_flip(self):
        e = make()
        st = e.syms["AAA"]
        e.set_play_level("AAA", "trigger", 10.00, T0)
        tr = st.trackers[(ASK, 1000)]
        tr.proven = True; tr.last_refill_t = T0 + 1; tr.confirmed_at = T0; tr.refill_seq = 4
        r, _ = row(e, T0 + 2, 10.00)
        seq = e._sequence(st, T0 + 2, e._ps60(st, T0 + 2, st.bar_list(500), st.price()))
        self.assertEqual(r["ask_stage"], tr.stage(T0 + 2))                    # the ladder reads the tracker
        self.assertEqual(seq["verdict"], tr.stage(T0 + 2))                     # the PIVOT verdict is the same tracker
        self.assertEqual(seq["verdict_side"], "ask")                           # long: the reload seller at the pivot


class BreakTrapStoryTests(unittest.TestCase):
    def test_trapped_break_goes_to_the_story(self):
        e = make()
        st = e.syms["AAA"]; st._bt_levels = [("PREMARKET HIGH", "the premarket high", 10.00)]
        t = T0 + 1
        e.on_print("AAA", 9.99, 100, "NASDAQ", t)
        e.on_l1("AAA", "bid", 10.00, t); e.on_l1("AAA", "ask", 10.01, t)
        for i in range(6):
            e.on_print("AAA", 10.01, 400, "NASDAQ", t + 1 + i)
        e.on_l1("AAA", "bid", 9.65, t + 10); e.on_l1("AAA", "ask", 9.66, t + 10)
        e.on_print("AAA", 9.65, 300, "NASDAQ", t + 10)
        self.assertTrue(any("TRAPPED LONGS" in f[1] for f in st.storybook.feed))
