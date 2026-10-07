import unittest

from helpers import ASK, BID, DELETE, INSERT, UPDATE, cfg, plays
from twiney.engine import Engine


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


class SlotTests(unittest.TestCase):
    def test_three_closest_get_depth_and_rotate(self):
        e = connected_engine()
        price_all(e, 1.0, {"AAA": 10.01, "BBB": 50.02, "CCC": 20.50, "DDD": 5.30})
        cmds = e.tick(1.0)
        self.assertEqual(sorted(c[1] for c in cmds if c[0] == "depth_on"), ["AAA", "BBB", "CCC"])
        self.assertTrue(e.syms["AAA"].depth_active)
        self.assertEqual(len(e.syms["AAA"].trackers), 4)  # trigger + second entry, both sides
        # DDD moves onto its trigger; CCC is now far: rotate after min hold
        price_all(e, 5.0, {"DDD": 5.00, "CCC": 21.50})
        self.assertEqual(e.tick(5.0), [])  # min_hold_seconds not reached yet
        cmds = e.tick(30.0)
        self.assertIn(("depth_off", "CCC"), cmds)
        self.assertIn(("depth_on", "DDD"), cmds)
        self.assertIsNone(e.syms["CCC"].book)

    def test_no_allocation_while_disconnected(self):
        e = Engine(plays(), cfg())
        price_all(e, 1.0, {"AAA": 10.0})
        self.assertEqual(e.tick(1.0), [])

    def test_connection_loss_releases_all_depth(self):
        e = connected_engine()
        price_all(e, 1.0, {"AAA": 10.0})
        e.tick(1.0)
        e.on_connection("DISCONNECTED", "socket", 2.0)
        self.assertEqual(e.slots, {})
        self.assertIsNone(e.syms["AAA"].book)

    def test_depth_rejection_blocks_symbol_for_cooldown(self):
        e = connected_engine()
        price_all(e, 1.0, {"AAA": 10.0, "BBB": 50.0, "CCC": 20.0, "DDD": 5.0})
        e.tick(1.0)
        e.on_depth_rejected("AAA", 309, "max depth", 2.0)
        self.assertNotIn("AAA", e.slots)
        cmds = e.tick(3.0)
        self.assertIn(("depth_on", "DDD"), cmds)
        self.assertNotIn(("depth_on", "AAA"), cmds)
        self.assertIn("309", e.syms["AAA"].last_error)

    def test_depth_for_unslotted_symbol_is_ignored(self):
        e = connected_engine()
        e.on_depth("AAA", 0, INSERT, ASK, 10.0, 100, "", 1.0)
        self.assertIsNone(e.syms["AAA"].book)


class ScreenControlTests(unittest.TestCase):
    def setUp(self):
        self.e = connected_engine()
        price_all(self.e, 1.0, {"AAA": 10.01, "BBB": 50.02, "CCC": 20.50, "DDD": 5.30})
        self.e.tick(1.0)

    def positions(self):
        return list(self.e.slot_order)

    def test_ladders_keep_their_screen_position(self):
        before = self.positions()
        price_all(self.e, 30.0, {"DDD": 5.00, "CCC": 21.50})
        self.e.tick(30.0)
        after = self.positions()
        i = before.index("CCC")
        self.assertEqual(after[i], "DDD")  # the newcomer takes the same spot
        for j, sym in enumerate(before):
            if j != i:
                self.assertEqual(after[j], sym)
        snap = self.e.snapshot(31.0)
        self.assertEqual(snap["panes"][i]["symbol"], "DDD")
        self.assertEqual(snap["panes"][i]["changed"]["prev"], "CCC")

    def test_auto_rotate_off_never_swaps(self):
        self.e.set_auto_rotate(False)
        price_all(self.e, 30.0, {"DDD": 5.00, "CCC": 21.50})
        self.assertEqual(self.e.tick(30.0), [])

    def test_pin_forces_symbol_onto_a_ladder_and_holds_it(self):
        self.e.set_pinned("DDD", True)
        cmds = self.e.tick(2.0)  # ignores min hold: the trader asked for it
        self.assertIn(("depth_on", "DDD"), cmds)
        price_all(self.e, 60.0, {"DDD": 9.00, "CCC": 20.00})
        self.e.tick(60.0)
        self.assertIn("DDD", self.e.slots)

    def test_live_reload_is_never_rotated_away(self):
        st = self.e.syms["CCC"]
        next(iter(st.trackers.values())).state = "RELOAD"
        price_all(self.e, 30.0, {"DDD": 5.00, "CCC": 21.50})
        self.e.tick(30.0)
        self.assertIn("CCC", self.e.slots)

    def test_english_story_and_alert_text(self):
        snap = self.e.snapshot(2.0)
        pane = snap["panes"][self.positions().index("AAA")]
        self.assertIn("your pivot 10.00", pane["headline"])
        self.assertTrue(pane["ladder"]["rows"])
        self.assertTrue(any("PIVOT" in r["tags"] for r in pane["ladder"]["rows"]))
        self.assertIn("status", snap["ranking"][0])


class FlowTests(unittest.TestCase):
    def _slotted(self, **sections):
        e = connected_engine(**sections)
        e.apply_slot("AAA", True, 0.0)
        seed_book(e, "AAA", 0.0)
        return e

    def test_reload_then_cleaned_up_through_engine(self):
        e = self._slotted()
        got = []
        e.listeners.append(lambda a: got.append(a) if a.get("role") not in ("conviction", "story") else None)   # the board's / story's calls are not reload calls
        t = 3.0  # after resync grace
        for refill in range(3):
            e.on_print("AAA", 10.00, 700, "NSDQ", t)
            e.on_depth("AAA", 0, UPDATE, ASK, 10.00, 300, "", t + 0.1)
            e.on_depth("AAA", 0, UPDATE, ASK, 10.00, 1000, "", t + 1.0)
            t += 2.0
        self.assertEqual([a["label"] for a in got], ["RELOAD SELLER DETECTED"])
        self.assertEqual(got[0]["role"], "trigger")
        e.on_print("AAA", 10.00, 1000, "NSDQ", t)
        e.on_depth("AAA", 0, DELETE, ASK, 10.00, 0, "", t + 0.05)
        e.on_print("AAA", 10.01, 300, "ARCA", t + 0.1)
        self.assertEqual(got[-1]["label"], "RELOAD SELLER DETECTED")   # a flicker is not a clear yet
        e.tick(t + 1.2)
        self.assertEqual(got[-1]["label"], "RELOAD SELLER DETECTED")   # 1 s is not enough to call it cleared
        e.tick(t + 3.2)                                                  # still gone, price still through
        self.assertEqual(got[-1]["label"], "CLEANED UP")
        self.assertIn("CLEANED UP — the SELLER at 10.00 (your pivot) is gone", got[-1]["text"])
        self.assertIn("RELOAD SELLER at 10.00", got[0]["text"])
        self.assertEqual(got[-1]["size_before_gone"], 1000)
        pane = e.snapshot(t + 1)["panes"][0]
        self.assertTrue(pane["marks"])      # absorption bubbles for the chart
        self.assertTrue(pane["bars"])       # 1-minute candles built from prints
        row = [r for r in pane["ladder"]["rows"] if r["price"] == 10.0][0]
        self.assertGreater(row["bought"], 2000)  # the level memory kept what traded there
        self.assertGreater(got[-1]["absorbed"], 2000)

    def test_error_317_reset_never_produces_pulled(self):
        e = self._slotted()
        got = []
        e.listeners.append(lambda a: got.append(a) if a.get("role") != "story" else None)   # the PS60 story tells it too
        t = 3.0
        for refill in range(3):
            e.on_print("AAA", 10.00, 700, "NSDQ", t)
            e.on_depth("AAA", 0, UPDATE, ASK, 10.00, 300, "", t + 0.1)
            e.on_depth("AAA", 0, UPDATE, ASK, 10.00, 1000, "", t + 1.0)
            t += 2.0
        e.on_depth_reset("AAA", t)
        e.on_depth("AAA", 0, INSERT, ASK, 10.01, 800, "", t + 0.1)  # partial rebuild
        e.on_depth("AAA", 0, INSERT, BID, 9.99, 800, "", t + 0.2)
        for k in range(20):
            e.tick(t + 0.5 * k)
        self.assertEqual([a["label"] for a in got], ["RELOAD SELLER DETECTED"])
        self.assertEqual(e.syms["AAA"].resets, 1)

    def test_prints_classified_against_book_bbo(self):
        e = self._slotted()
        e.on_print("AAA", 10.00, 100, "X", 1.0)
        e.on_print("AAA", 9.99, 100, "X", 1.1)
        sides = [p["side"] for p in e.syms["AAA"].tape.prints]
        self.assertEqual(sides, ["buy", "sell"])

    def test_auto_levels_track_big_inside_size(self):
        e = connected_engine(reload={"auto_levels": True, "auto_min_display_shares": 2000})
        e.apply_slot("AAA", True, 0.0)
        seed_book(e, "AAA", 0.0, bid=10.49, ask=10.50, ask_size=5000)
        e.on_depth("AAA", 0, UPDATE, ASK, 10.50, 5000, "", 3.0)
        roles = {(tr.price, tr.side): tr.role for tr in e.syms["AAA"].trackers.values()}
        self.assertEqual(roles.get((10.50, ASK)), "auto")

    def test_trap_and_reloaders_from_prints(self):
        e = connected_engine(trap={"min_shares": 500, "heavy_shares": 2000})
        e.apply_slot("AAA", True, 0.0)
        seed_book(e, "AAA", 0.0, bid=10.09, ask=10.10)
        # impatient buyers pay 10.10 / 10.12, then the market drops to 10.00
        e.on_print("AAA", 10.10, 800, "X", 3.0)
        e.on_print("AAA", 10.12, 1500, "X", 4.0)
        e.on_depth("AAA", 0, UPDATE, BID, 9.99, 500, "", 5.0)
        e.on_depth("AAA", 0, UPDATE, ASK, 10.00, 500, "", 5.0)
        e.on_print("AAA", 9.99, 100, "X", 6.0)   # sets last = 9.99
        pane = e.snapshot(7.0)["panes"][0]
        self.assertEqual(pane["trap"]["longs"]["shares"], 2300)
        self.assertTrue(pane["trap"]["longs"]["heavy"])
        self.assertEqual((pane["trap"]["longs"]["low"], pane["trap"]["longs"]["high"]), (10.1, 10.12))
        self.assertIsNone(pane["trap"]["shorts"])
        self.assertTrue(any(l.startswith("TRAPPED LONGS") for l in pane["lines"]))
        self.assertEqual(pane["reloaders"], {"below": [], "above": []})
        # a confirmed reload seller above the market shows up in the map
        tr = [x for x in e.syms["AAA"].trackers.values() if x.price == 10.0 and x.side == ASK][0]
        tr.state = "RELOAD"
        rel = e.snapshot(8.0)["panes"][0]["reloaders"]
        self.assertEqual([r["price"] for r in rel["above"]], [10.0])

    def test_drawn_levels_are_watched_and_saved(self):
        import json, os, tempfile
        e = self._slotted()
        with tempfile.TemporaryDirectory() as d:
            e.plays_path = os.path.join(d, "plays.json")
            self.assertTrue(e.add_level("AAA", 10.05, 2.0))
            self.assertIn((ASK, 1005), e.syms["AAA"].trackers)
            self.assertEqual(e.syms["AAA"].trackers[(ASK, 1005)].role, "extra")
            saved = json.load(open(e.plays_path))
            self.assertEqual([p for p in saved["plays"] if p["symbol"] == "AAA"][0]["extra_levels"], [10.05])
            self.assertTrue(any(l["role"] == "extra" and l["price"] == 10.05 for l in e.snapshot(3.0)["panes"][0]["user_levels"]))
            e.remove_level("AAA", 10.05, 4.0)
            self.assertNotIn((ASK, 1005), e.syms["AAA"].trackers)
            self.assertEqual([p for p in json.load(open(e.plays_path))["plays"] if p["symbol"] == "AAA"][0]["extra_levels"], [])

    def test_second_entry_set_from_chart(self):
        import json, os, tempfile
        e = self._slotted()
        with tempfile.TemporaryDirectory() as d:
            e.plays_path = os.path.join(d, "plays.json")
            self.assertIn((BID, 1010), e.syms["AAA"].trackers)                # old 2nd entry 10.10
            self.assertTrue(e.set_play_level("AAA", "second_entry", 10.15, 2.0))
            self.assertNotIn((BID, 1010), e.syms["AAA"].trackers)
            self.assertEqual(e.syms["AAA"].trackers[(BID, 1015)].role, "second_entry")
            self.assertEqual(e.syms["AAA"].play["second_entry"], 10.15)
            saved = [p for p in json.load(open(e.plays_path))["plays"] if p["symbol"] == "AAA"][0]
            self.assertEqual((saved["second_entry"], saved["pivot"]), (10.15, 10.0))
            self.assertNotIn("trigger", saved)
            self.assertTrue(e.set_play_level("AAA", "stop", 9.50, 3.0))
            self.assertEqual(e.snapshot(4.0)["panes"][0]["play"]["stop"], 9.5)
            self.assertFalse(e.set_play_level("AAA", "trigger", None, 5.0))     # trigger can't be cleared
            self.assertTrue(e.set_play_level("AAA", "second_entry", None, 6.0))  # 2nd entry can
            self.assertNotIn((BID, 1015), e.syms["AAA"].trackers)

    def test_snapshot_shape(self):
        e = self._slotted()
        price_all(e, 1.0, {"AAA": 10.0})
        e.on_print("AAA", 10.00, 100, "X", 1.0)
        s = e.snapshot(2.0)
        self.assertEqual(s["mode"], "PAPER-ONLY ORDER ENTRY · LIVE LOCKED")
        self.assertEqual(s["depth"], ["AAA"]); d = [p for p in s["panes"] if p][0]
        self.assertEqual(d["symbol"], "AAA")
        self.assertEqual(len(d["book"]["asks"]), 3)
        self.assertEqual(d["book"]["asks"][0], [10.0, 1000, 1])
        self.assertIn("state", d["tape"])
        self.assertTrue(any(l["role"] == "trigger" for l in d["levels"]))
        self.assertEqual(s["ranking"][0]["symbol"], "AAA")
        self.assertIn(d["health"]["status"], ("OK", "SYNCING"))


if __name__ == "__main__":
    unittest.main()


class PlayLifecycleTests(unittest.TestCase):
    def test_stop_hit_retires_play_and_releases_its_ladder(self):
        e = connected_engine()
        e.syms["AAA"].play["stop"] = 9.50
        e.syms["AAA"].play["target"] = 10.80
        price_all(e, 1.0, {"AAA": 10.01, "BBB": 50.02, "CCC": 20.50, "DDD": 5.30})
        e.tick(1.0)
        self.assertTrue(e.syms["AAA"].depth_active)
        price_all(e, 40.0, {"AAA": 9.49})
        cmds = e.tick(40.0)
        self.assertIn(("depth_off", "AAA"), cmds)
        self.assertEqual(e.syms["AAA"].retired["reason"], "stopped out")
        self.assertNotIn("AAA", [s for s, _ in e.ranking(41.0)])
        snap = e.snapshot(41.0)
        row = next(r for r in snap["ranking"] if r["symbol"] == "AAA")
        self.assertEqual(row["retired"]["reason"], "stopped out")
        self.assertTrue(any("retired" in m["text"] for m in snap["messages"]))
        # reactivating while price is still under the stop must not retire it again at once
        self.assertTrue(e.reactivate_play("AAA", 42.0))
        e.tick(42.0)
        self.assertIsNone(e.syms["AAA"].retired)
        self.assertIn("AAA", [s for s, _ in e.ranking(43.0)])
        # once price is back above the stop, the stop is live again
        price_all(e, 44.0, {"AAA": 9.95}); e.tick(44.0)
        price_all(e, 45.0, {"AAA": 9.40}); e.tick(45.0)
        self.assertEqual(e.syms["AAA"].retired["reason"], "stopped out")

    def test_target_hit_on_short_play(self):
        e = connected_engine()
        e.syms["BBB"].play["side"] = "short"
        e.syms["BBB"].play["target"] = 49.00
        price_all(e, 1.0, {"BBB": 50.0})
        e.tick(1.0)
        price_all(e, 2.0, {"BBB": 48.99})
        e.tick(2.0)
        self.assertEqual(e.syms["BBB"].retired["reason"], "target hit")

    def test_grading_a_call_is_kept_and_shown(self):
        e = connected_engine()
        e.alerts.appendleft({"t": 1.0, "symbol": "AAA", "label": "RELOAD BUYER DETECTED", "price": 9.9, "key": "1.0|AAA|RELOAD BUYER DETECTED|9.9", "text": "x"})
        self.assertTrue(e.grade("1.0|AAA|RELOAD BUYER DETECTED|9.9", "good", 2.0))
        self.assertEqual(e.snapshot(2.0)["alerts"][0]["grade"], "good")
        self.assertFalse(e.grade("k", "meh", 2.0))
        e.grade("1.0|AAA|RELOAD BUYER DETECTED|9.9", None, 3.0)
        self.assertIsNone(e.snapshot(3.0)["alerts"][0]["grade"])


class VoiceTests(unittest.TestCase):
    def test_big_size_added_pulled_and_hit_are_called_out(self):
        e = connected_engine(voice={"min_shares": 5000, "repeat_seconds": 20})
        price_all(e, 1.0, {"AAA": 10.01})
        e.tick(1.0)
        seed_book(e, "AAA", 2.0)
        e.on_depth("AAA", 0, UPDATE, BID, 9.99, 18000, "", 3.0)
        self.assertEqual(e.voice[0]["text"], "AAA: 18k buyer at 9.99")
        # pulled: size vanishes with nothing trading there
        e.on_depth("AAA", 0, UPDATE, BID, 9.99, 200, "", 4.0)
        e.tick(5.6)                                    # decided once the tape has caught up
        self.assertEqual(e.voice[0]["text"], "AAA: buyer pulled 18k from 9.99")
        # hit: prints at that price account for the drop
        e.on_depth("AAA", 0, UPDATE, ASK, 10.00, 12000, "", 30.0)
        self.assertEqual(e.voice[0]["text"], "AAA: 12k seller at 10.00")
        for k in range(6):
            e.on_print("AAA", 10.00, 2000, "X", 31.0 + k * 0.1)
        e.on_depth("AAA", 0, UPDATE, ASK, 10.00, 100, "", 32.0)
        e.tick(33.6)
        self.assertEqual(e.voice[0]["text"], "AAA: seller at 10.00 got hit for 12k")
        self.assertEqual(len(e.snapshot(33.0)["voice"]), 4)


class TypedTickerTests(unittest.TestCase):
    def test_typed_ticker_becomes_a_watch_play_and_gets_the_ladder(self):
        e = connected_engine()
        seen = []
        e.play_listeners.append(lambda p: seen.append(p["symbol"]))
        play = e.add_play("msft", 1.0)
        self.assertEqual((play["symbol"], play["watch"], play["trigger"]), ("MSFT", True, None))
        self.assertEqual(seen, ["MSFT"])
        self.assertIs(e.add_play("MSFT"), play)            # typing it again is harmless
        self.assertIsNone(e.add_play("not a ticker!"))
        e.on_l1("MSFT", "last", 400.0, 2.0)
        snap = e.snapshot(2.0)                              # no pivot: no crash anywhere
        row = next(r for r in snap["ranking"] if r["symbol"] == "MSFT")
        self.assertIsNone(row["rank"])
        self.assertIn("no pivot", row["status"])
        self.assertEqual(row["ps60"]["grade"], "PASS")
        self.assertIn("MSFT", snap["symbols"])
        # the symbol on screen gets a ladder: focus pins it
        self.assertTrue(e.set_focus("MSFT", 3.0))
        self.assertIn("MSFT", e.pinned)
        e.tick(3.0)
        self.assertTrue(e.syms["MSFT"].depth_active)
        e.set_focus("AAA", 4.0)
        self.assertNotIn("MSFT", e.pinned)                  # the auto-pin moves with the focus
        # marking a pivot on the chart turns it into a real play
        e.set_play_level("MSFT", "trigger", 401.0, 5.0)
        self.assertFalse(e.syms["MSFT"].play["watch"])
        self.assertIsNotNone(next(r for r in e.snapshot(5.0)["ranking"] if r["symbol"] == "MSFT")["rank"])


class PlaySetupTests(unittest.TestCase):
    def test_trader_inputs_drive_everything(self):
        e = connected_engine()
        e.on_l1("AAA", "last", 10.01, 1.0); e.tick(1.0)
        ok, why = e.set_play_setup("AAA", {"side": "long", "trigger": 10.0, "stop": 9.7, "mp": 10.9, "second_entry": ""}, 2.0)
        self.assertTrue(ok, why)
        p = e.syms["AAA"].play
        self.assertEqual((p["stop"], p["target"], p["mp"], p["second_entry"]), (9.7, 10.9, 10.9, None))
        row = next(r for r in e.snapshot(2.0)["ranking"] if r["symbol"] == "AAA")
        self.assertEqual((row["ps60"]["mp"]["dollars"], row["ps60"]["mp"]["level"]), (0.9, 10.9))
        ok, why = e.set_play_setup("AAA", {"mp": 9.9}, 2.5)
        self.assertFalse(ok); self.assertIn("MP 9.9 must be above the pivot", why)
        # bad inputs are refused with a reason, nothing changes
        ok, why = e.set_play_setup("AAA", {"stop": 10.5}, 3.0)
        self.assertFalse(ok); self.assertIn("below the pivot", why); self.assertEqual(e.syms["AAA"].play["stop"], 9.7)
        ok, why = e.set_play_setup("AAA", {"mp": "abc"}, 3.0)
        self.assertFalse(ok); self.assertIn("mp must be a number", why)
        # a stop on a typed-in ticker with no pivot is fine
        e.add_play("ZZZ", 4.0); e.on_l1("ZZZ", "last", 50.0, 4.0)
        ok, why = e.set_play_setup("ZZZ", {"stop": 49.0, "mp": 52.0}, 4.0)
        self.assertTrue(ok, why)

    def test_short_stop_sits_above_the_second_entry_under_the_pivot(self):
        """AAPL short: pivot 120.50, 2nd entry 120.01, stop 120.18, target 117.24 — the stop is above the 2nd entry
        (the PS60 stop) even though it is under the pivot. That is a valid short and must save as one."""
        e = connected_engine()
        e.add_play("AAPL", 1.0); e.on_l1("AAPL", "last", 120.3, 1.0); e.tick(1.0)
        ok, why = e.set_play_setup("AAPL", {"side": "short", "trigger": 120.5, "second_entry": 120.01, "stop": 120.18, "target": 117.24}, 2.0)
        self.assertTrue(ok, why)
        p = e.syms["AAPL"].play
        self.assertEqual((p["side"], p["stop"], p["second_entry"]), ("short", 120.18, 120.01))
        # a stop UNDER a short's 2nd entry is still wrong, and the reason names the 2nd entry
        ok, why = e.set_play_setup("AAPL", {"stop": 119.9}, 3.0)
        self.assertFalse(ok); self.assertIn("above the 2nd entry 120.01 for a short", why)
        # same for a long: the stop goes under the 2nd entry, not just under the pivot
        ok, why = e.set_play_setup("AAPL", {"side": "long", "trigger": 119.0, "second_entry": 119.4, "stop": 119.6, "target": 121.0}, 4.0)
        self.assertFalse(ok); self.assertIn("below the 2nd entry 119.4 for a long", why)

    def test_side_applies_at_once_and_keeps_the_drawn_levels(self):
        """Picking SHORT in PLAY SETUP flips the play right away; the levels drawn on the chart stay put and the
        desk says which of them now sit on the wrong side (nothing is wiped, nothing waits for SAVE)."""
        e = connected_engine()
        e.add_play("AAPL", 1.0); e.on_l1("AAPL", "last", 120.3, 1.0); e.tick(1.0)
        for role, px in (("trigger", 120.5), ("second_entry", 120.01), ("stop", 120.18), ("target", 117.24)):
            e.set_play_level("AAPL", role, px, 1.5)
        self.assertEqual(e.syms["AAPL"].play["side"], "short")   # the stop above the target already said so
        e.syms["AAPL"].play["side"] = "long"                      # pretend the pick is what flips it
        ok, warn = e.set_side("AAPL", "short", 2.0)
        self.assertTrue(ok); self.assertEqual(warn, [])
        p = e.syms["AAPL"].play
        self.assertEqual((p["side"], p["trigger"], p["second_entry"], p["stop"], p["target"]), ("short", 120.5, 120.01, 120.18, 117.24))
        self.assertTrue(any("SIDE → SHORT" in n["text"] for n in e.symbol_log("AAPL")))
        # back to long: the same levels are now on the wrong side, and the desk says so instead of wiping them
        ok, warn = e.set_side("AAPL", "long", 3.0)
        self.assertTrue(ok); self.assertEqual(len(warn), 3)
        self.assertIn("2nd entry 120.01 must be above the pivot 120.5 for a long", warn[0])
        self.assertEqual(e.syms["AAPL"].play["second_entry"], 120.01)
        self.assertEqual(e.set_side("AAPL", "sideways", 3.5), (False, ["side must be long or short"]))

    def test_side_reads_off_the_stop_and_target(self):
        """Draw a stop above a target and the play is a short; stop under the target, a long. No SIDE pick needed."""
        e = connected_engine()
        e.add_play("AAPL", 1.0); e.on_l1("AAPL", "last", 120.3, 1.0); e.tick(1.0)
        e.set_play_level("AAPL", "trigger", 120.5, 1.5)
        e.set_play_level("AAPL", "stop", 120.18, 2.0)            # one level alone says nothing
        self.assertEqual(e.syms["AAPL"].play["side"], "long")
        e.set_play_level("AAPL", "target", 117.24, 2.5)
        self.assertEqual(e.syms["AAPL"].play["side"], "short")
        self.assertTrue(any("SIDE → SHORT (stop 120.18 above target 117.24)" in n["text"] for n in e.symbol_log("AAPL")))
        e.set_play_level("AAPL", "target", 123.0, 3.0); e.set_play_level("AAPL", "stop", 119.0, 3.0)
        self.assertEqual(e.syms["AAPL"].play["side"], "long")
        # the board and the auto entry read the side the trader picked
        e.set_side("AAPL", "short", 4.0)
        e.apply_slot("AAPL", True, 4.0)
        pane = next(x for x in e.snapshot(4.0)["panes"] if x and x["symbol"] == "AAPL")
        self.assertEqual(pane["play"]["side"], "short")
        self.assertTrue(pane["conviction"]["label"].startswith("SHORT"), pane["conviction"]["label"])


class BigSizeTests(unittest.TestCase):
    def test_big_size_is_highlighted_and_counted_each_time_it_shows(self):
        e = connected_engine()
        e.on_l1("AAA", "last", 10.01, 1.0); e.tick(1.0)
        e.on_depth("AAA", 0, INSERT, BID, 10.00, 400, "", 2.0)
        e.on_depth("AAA", 0, INSERT, ASK, 10.02, 400, "", 2.0)
        e.on_depth("AAA", 1, INSERT, ASK, 10.03, 8000, "", 2.1)
        row = lambda t, p: [r for r in e.snapshot(t)["panes"][0]["ladder"]["rows"] if r["price"] == p][0]
        self.assertEqual(row(2.2, 10.03)["ask_big"], {"times": 1, "huge": False})
        self.assertNotIn("ask_big", row(2.2, 10.02))
        e.on_depth("AAA", 1, UPDATE, ASK, 10.03, 300, "", 3.0)      # he leaves
        self.assertNotIn("ask_big", row(3.1, 10.03))
        e.on_depth("AAA", 1, UPDATE, ASK, 10.03, 9000, "", 3.5)     # a blip back half a second later is the same order
        self.assertEqual(row(3.6, 10.03)["ask_big"]["times"], 1)
        e.on_depth("AAA", 1, UPDATE, ASK, 10.03, 300, "", 4.0)
        e.on_depth("AAA", 1, UPDATE, ASK, 10.03, 20000, "", 10.0)   # gone for real, then back, huge this time
        self.assertEqual(row(10.1, 10.03)["ask_big"], {"times": 2, "huge": True})
        # adjustable per symbol from the desk
        self.assertTrue(e.set_big_shares("AAA", 30000, 11.0))
        self.assertNotIn("ask_big", row(11.1, 10.03))
        lad = e.snapshot(11.1)["panes"][0]["ladder"]
        self.assertEqual((lad["big_shares"], lad["big_default"]), (30000, False))
        e.set_big_shares("AAA", None, 12.0)
        self.assertEqual(row(12.1, 10.03)["ask_big"]["times"], 2)   # changing the bar is not a new appearance


class VerifyRound2Tests(unittest.TestCase):
    def test_locked_quote_reads_against_the_last_clean_one(self):
        from twiney.engine import SymbolState
        st = SymbolState(plays()[0], cfg())
        st.quotes.extend([(90, 10.01, 10.02), (105, 10.00, 10.02), (109.9, 10.02, 10.02)])
        st.l1["bid"], st.l1["ask"] = 10.02, 10.02
        self.assertEqual(st.aggressor(10.01, 110), "mid")
        self.assertEqual(st.aggressor(10.00, 110), "sell")

    def test_price_follows_the_quote_when_the_tape_goes_quiet(self):
        e = connected_engine()
        price_all(e, 1.0, {"AAA": 10.00}); e.tick(1.0)
        seed_book(e, "AAA", 1.5)
        e.on_print("AAA", 10.00, 100, "X", 2.0)
        e.on_l1("AAA", "last", 10.05, 5.0)
        self.assertEqual(e.syms["AAA"].price(), 10.00)      # the tape is live: it sets the price
        e.tick(13.0)
        self.assertEqual(e.syms["AAA"].price(), 10.05)      # tape quiet 10 s+: the quote's last takes over
        self.assertEqual(e.syms["AAA"].bar_list()[-1][4], 10.05)

    def test_flow_side_words(self):
        from twiney.flow import normalize
        base = {"ticker": "AAA", "strike": 10, "cp": "C", "size": 1, "price": 1}
        self.assertEqual(normalize(dict(base, side="At Bid"))["side"], "bid")
        self.assertEqual(normalize(dict(base, side="AT_ASK"))["side"], "ask")
        self.assertEqual(normalize(dict(base, side="Above Ask"))["side"], "ask")


class TapeSpeedTests(unittest.TestCase):
    def test_speed_reads_this_stock_against_its_own_last_minute(self):
        from twiney.tape import Tape
        tp = Tape(cfg()["tape"])
        for i in range(60):                      # a print a second for a minute
            tp.add(1000.0 + i, 10.0, 100, 9.99, 10.0)
        self.assertEqual(tp.speed(1060.0)["trend"], "STEADY")
        for i in range(40):                      # then 4 a second for 10 s: speeding up, all paid up
            tp.add(1060.0 + i * 0.25, 10.0, 200, 9.99, 10.0)
        sp = tp.speed(1069.9)
        self.assertEqual(sp["trend"], "SPEEDING UP")
        self.assertEqual(sp["pps"], 4.0)
        self.assertEqual(sp["sps"], 800)
        self.assertEqual(len(sp["series"]), 30)
        self.assertEqual(sum(r[0] for r in sp["series"]), 40 * 200 + 60 * 100)   # every buy inside the 90 s
        self.assertEqual(tp.speed(1095.0)["trend"], "SLOWING")                  # then nothing for 25 s
        self.assertEqual(Tape(cfg()["tape"]).speed(5.0)["trend"], "QUIET")


class StillLadderTests(unittest.TestCase):
    def test_rows_stay_put_while_price_moves_inside_them(self):
        from helpers import cfg, plays, INSERT, UPDATE, BID, ASK
        from twiney.engine import Engine
        e = Engine(plays(), cfg())
        e.on_connection("DEMO", "", 0.0)
        e.apply_slot("AAA", True, 0.0)
        def quote(bid, t):
            for i in range(3):
                e.on_depth("AAA", i, INSERT if t == 1.0 else UPDATE, BID, round(bid - i * 0.01, 2), 500, "", t)
                e.on_depth("AAA", i, INSERT if t == 1.0 else UPDATE, ASK, round(bid + 0.01 + i * 0.01, 2), 500, "", t)
        quote(10.00, 1.0)
        top = lambda t: e._memory_ladder(e.syms["AAA"], t, [])["rows"][0]["price"]
        first = top(1.1)
        quote(10.03, 2.0)                                    # a few ticks: the same rows
        self.assertEqual(top(2.1), first)
        quote(10.10, 3.0)                                    # near the top edge: re-centred
        self.assertNotEqual(top(3.1), first)


class BigTapeTests(unittest.TestCase):
    """The BIG TAPE: large prints, and the same side hitting the same price again and again (a builder)."""
    def test_blocks_and_builders(self):
        from twiney.tape import Tape
        tp = Tape({"window_seconds": 30.0, "min_prints_for_read": 5, "control_ratio": 0.65, "large_print_shares": 5000, "keep_prints": 200,
                   "big_tape_shares": 5000, "big_tape_dollars": 250000, "big_tape_minutes": 30, "build_window_seconds": 90, "build_prints": 3, "build_dollars": 500000,
                   "big_tape_x_average": 0})
        # a buyer working 10.05: six prints of 1,200 at the ask inside a minute
        for i in range(6):
            tp.add(100.0 + i * 10, 10.05, 1200, 10.04, 10.05)
        tp.add(170.0, 10.04, 300, 10.04, 10.05)           # a small sale, not a builder
        tp.add(180.0, 10.06, 9000, 10.05, 10.06)          # one block at the ask
        tp.add(190.0, 300.0, 1000, 299.9, 300.0)          # $300K in one print: a block by money
        b = tp.big(200.0)
        self.assertEqual([(p["size"], p["price"]) for p in b["prints"]], [(1000, 300.0), (9000, 10.06)])
        self.assertEqual(len(b["builders"]), 1)
        g = b["builders"][0]
        self.assertEqual((g["side"], g["price"], g["prints"], g["shares"], g["biggest"]), ("buy", 10.05, 6, 7200, 1200))
        self.assertTrue(g["still"]); self.assertEqual(g["last_age"], 50)
        # three minutes of silence: the builder went quiet; a new run at the same price is a new builder
        self.assertFalse(tp.big(400.0)["builders"][0]["still"])
        for i in range(3):
            tp.add(500.0 + i * 5, 10.05, 2000, 10.04, 10.05)
        bs = tp.big(520.0)["builders"]
        self.assertEqual([(x["prints"], x["still"]) for x in bs], [(3, True), (6, False)])

    def test_bar_scales_with_the_tickers_own_tape(self):
        """A $750 ETF prints $250K all day long: a print makes the big tape only when it is also many times the
        ticker's own average print, so the big tape stays the big players."""
        from twiney.tape import Tape
        tp = Tape({"window_seconds": 30.0, "min_prints_for_read": 5, "control_ratio": 0.65, "large_print_shares": 5000, "keep_prints": 500,
                   "big_tape_shares": 10000, "big_tape_dollars": 1000000, "big_tape_x_average": 20, "big_tape_minutes": 30,
                   "build_window_seconds": 90, "build_prints": 5, "build_dollars": 2000000})
        for i in range(100):
            tp.add(100.0 + i, 750.0, 2000, 749.99, 750.0)      # ordinary tape: $1.5M prints, 2,000 shares each
        b = tp.big(250.0)
        self.assertEqual(b["prints"], [])                          # money alone does not make it: not above 20x the average
        self.assertEqual(len(b["builders"]), 1)                    # the same side at the same price 100 times IS a builder
        tp.add(260.0, 750.0, 60000, 749.99, 750.0)               # 60,000 shares at once: 25x the average, $45M
        b = tp.big(270.0)
        self.assertEqual([p["size"] for p in b["prints"]], [60000])
        self.assertEqual(b["x_average"], 20); self.assertGreater(b["average"], 2000)

    def test_pane_carries_the_big_tape(self):
        e = connected_engine()
        e.apply_slot("AAA", True, 0.0)
        e.on_l1("AAA", "bid", 9.99, 1.0); e.on_l1("AAA", "ask", 10.0, 1.0)
        for i in range(40):                                   # the ordinary tape: 100-share prints
            e.on_print("AAA", 9.99, 100, "X", 1.0 + i * 0.02)
        for i in range(6):                                    # then the same buyer at 10.00 six times
            e.on_print("AAA", 10.0, 2000, "X", 2.0 + i)
        pane = next(x for x in e.snapshot(9.0)["panes"] if x and x["symbol"] == "AAA")
        bt = pane["bigtape"]
        self.assertEqual(bt["builders"][0]["side"], "buy"); self.assertEqual(bt["builders"][0]["shares"], 12000)
        self.assertEqual(bt["builders"][0]["price"], 10.0)


class ReloaderReturnTests(unittest.TestCase):
    """The same seller back at the same price inside the return window is the SAME seller: the desk says BACK,
    counts his visits and adds his absorbed shares across them. Gone longer than the window: a fresh story."""
    def _reload(self, e, got, t, price=10.00):
        for _ in range(3):
            e.on_print("AAA", price, 700, "NSDQ", t)
            e.on_depth("AAA", 0, UPDATE, ASK, price, 300, "", t + 0.1)
            e.on_depth("AAA", 0, UPDATE, ASK, price, 1000, "", t + 1.0)
            t += 2.0
        return t

    def _clean(self, e, t):
        e.on_print("AAA", 10.00, 1000, "NSDQ", t)
        e.on_depth("AAA", 0, DELETE, ASK, 10.00, 0, "", t + 0.05)
        e.on_print("AAA", 10.01, 300, "ARCA", t + 0.1)
        e.tick(t + 3.2)
        return t + 3.2

    def test_back_within_the_window_is_the_same_seller(self):
        e = connected_engine(reload={"return_window_seconds": 1200.0}); e.apply_slot("AAA", True, 0.0); seed_book(e, "AAA", 0.0)
        got = []; e.listeners.append(lambda a: got.append(a) if a.get("role") != "conviction" else None)
        t = self._reload(e, got, 3.0)
        self.assertEqual(got[-1]["label"], "RELOAD SELLER DETECTED")
        t = self._clean(e, t)
        self.assertEqual(got[-1]["label"], "CLEANED UP"); first = got[-1]["absorbed"]
        # six minutes later he is sitting on 10.00 again and refilling: BACK, 2nd visit
        t += 360.0
        e.on_depth("AAA", 0, INSERT, ASK, 10.00, 1000, "", t); e.on_depth("AAA", 1, UPDATE, ASK, 10.01, 400, "", t)
        t = self._reload(e, got, t + 1.0)
        self.assertEqual(got[-1]["label"], "RELOAD SELLER BACK", [g["label"] for g in got])
        a = got[-1]
        self.assertEqual(a["back"]["n"], 2); self.assertEqual(a["back"]["prior"], "CLEANED UP"); self.assertTrue(355 <= a["back"]["away"] <= 375)
        self.assertEqual(a["episodes"], 1); self.assertGreaterEqual(a["absorbed_all"], first + a["absorbed"])
        self.assertIn("RELOAD SELLER BACK at 10.00", a["text"]); self.assertIn("2nd visit", a["text"]); self.assertIn("6 min ago", a["text"])
        row = next(r for r in e._memory_ladder(e.syms["AAA"], t, {})["rows"] if r["price"] == 10.0)
        self.assertEqual(row["ask_back"]["n"], 2); self.assertEqual(row["ask_episodes"], 1)
        self.assertGreaterEqual(row["ask_absorbed_all"], first)

    def test_gone_too_long_is_a_fresh_reloader(self):
        e = connected_engine(reload={"return_window_seconds": 60.0}); e.apply_slot("AAA", True, 0.0); seed_book(e, "AAA", 0.0)
        got = []; e.listeners.append(lambda a: got.append(a) if a.get("role") != "conviction" else None)
        t = self._clean(e, self._reload(e, got, 3.0))
        t += 600.0
        e.on_depth("AAA", 0, INSERT, ASK, 10.00, 1000, "", t); e.on_depth("AAA", 1, UPDATE, ASK, 10.01, 400, "", t)
        self._reload(e, got, t + 1.0)
        self.assertEqual(got[-1]["label"], "RELOAD SELLER DETECTED"); self.assertEqual(got[-1]["episodes"], 0)
        self.assertNotIn("back", got[-1])


class BookCheckTests(unittest.TestCase):
    def test_a_wide_book_with_prints_in_its_gap_in_regular_hours_is_re_asked(self):
        import datetime as _dt
        from zoneinfo import ZoneInfo
        t0 = _dt.datetime(2026, 10, 6, 9, 47, tzinfo=ZoneInfo("America/New_York")).timestamp()
        e = connected_engine()
        e.apply_slot("AAA", True, t0)
        e.on_depth("AAA", 0, INSERT, BID, 10.01, 500, "", t0)
        e.on_depth("AAA", 0, INSERT, ASK, 10.11, 500, "", t0)        # 10 ticks wide: the inside levels are missing
        st = e.syms["AAA"]; st.resync_until = 0
        for k in range(25):
            e.on_print("AAA", 10.05 + (k % 3) * 0.01, 100, "ARCA", t0 + 1 + k * 0.5)
        self.assertTrue(st.resub_depth)
        self.assertTrue(any("ticks wide" in m["text"] for m in e.messages))

    def _nbbo_setup(self):
        import datetime as _dt
        from zoneinfo import ZoneInfo
        t0 = _dt.datetime(2026, 10, 6, 9, 47, tzinfo=ZoneInfo("America/New_York")).timestamp()
        e = connected_engine()
        e.apply_slot("AAA", True, t0)
        e.on_depth("AAA", 0, INSERT, BID, 10.00, 500, "", t0)
        e.on_depth("AAA", 0, INSERT, ASK, 10.10, 500, "", t0)        # the book: 10.00 x 10.10
        st = e.syms["AAA"]; st.resync_until = 0
        return e, st, t0

    def test_a_tighter_nbbo_is_the_inside_once_it_holds(self):
        e, st, t0 = self._nbbo_setup()
        e.on_l1("AAA", "bid", 10.04, t0 + 0.1)
        e.on_l1("AAA", "ask", 10.05, t0 + 0.1)                      # the quote: 10.04 x 10.05
        self.assertEqual(st.bbo(), (10.00, 10.10))                   # a moment: a quote can lag, the book stays
        e.on_l1("AAA", "bid", 10.04, t0 + 1.5)
        self.assertEqual(st.bbo(), (10.04, 10.05))                   # held over a second: the NBBO is the inside
        # a print at 10.05 is a BUY at the offer, not a mid print in a wide book
        from twiney.tape import BUY
        self.assertEqual(st.aggressor(10.05, t0 + 1.6), BUY)
        e.on_l1("AAA", "bid", 10.00, t0 + 2.0)
        e.on_l1("AAA", "ask", 10.10, t0 + 2.0)                      # quote back in line with the book
        self.assertEqual(st.bbo(), (10.00, 10.10))

    def test_nbbo_tighter_than_the_book_for_5s_in_rth_asks_again(self):
        e, st, t0 = self._nbbo_setup()
        for k in range(8):
            e.on_l1("AAA", "bid", 10.04, t0 + k)
            e.on_l1("AAA", "ask", 10.05, t0 + k)
        e.on_print("AAA", 10.05, 100, "ARCA", t0 + 7.5)
        self.assertTrue(st.resub_depth)
        self.assertTrue(any("wider than the quote" in m["text"] for m in e.messages))


class ContractAtLinesTests(unittest.TestCase):
    def test_percent_at_the_lines_from_delta_and_gamma(self):
        e = connected_engine()
        st = e.syms["AAA"]
        st.l1["last"] = 100.0; st.l1["bid"] = 99.99; st.l1["ask"] = 100.01
        st.play.update(side="long", second_entry=101.0, stop=99.0, target=104.0, trade_as="option", opt_key="AAA 20261009 100C")
        k = "AAA 20261009 100C"
        e.on_opt_quote(k, "bid", 1.95, 1.0); e.on_opt_quote(k, "ask", 2.05, 1.0)
        e.on_opt_greeks(k, {"delta": 0.5, "gamma": 0.1}, 1.0)
        est = e._opt_est(st, 1.0)
        # in at 101: 2 + 0.5 + 0.05 = 2.55; target 104: 2 + 2 + 0.8 = 4.80 (+88%); stop 99: 2 - 0.5 + 0.05 = 1.55 (-39%)
        self.assertEqual(est["entry"], 2.55)
        self.assertEqual(est["lines"]["target"]["v"], 4.8)
        self.assertEqual(est["lines"]["target"]["pct"], 88)
        self.assertEqual(est["lines"]["stop"]["pct"], -39)
        self.assertEqual(est["rr"], 2.3)

    def test_nothing_without_a_contract(self):
        e = connected_engine()
        self.assertIsNone(e._opt_est(e.syms["AAA"], 1.0))


class ExchangeTimeCandleTests(unittest.TestCase):
    def test_candle_follows_ibkr_time_not_arrival(self):
        e = connected_engine()
        m = 1_791_300_000 - 1_791_300_000 % 60            # a minute boundary
        e.on_print("AAA", 10.00, 100, "ARCA", m + 0.3, "", xt=m - 1)     # IBKR: 10:30:59, here at 10:31:00.3
        st = e.syms["AAA"]
        self.assertIn(m - 60, st.bars)
        self.assertNotIn(m, st.bars)
        e.on_print("AAA", 10.05, 100, "ARCA", m + 1.2, "", xt=m)         # IBKR: 10:31:00
        self.assertIn(m, st.bars)
        self.assertEqual(st.bars[m - 60][3], 10.00)

    def test_pc_clock_off_is_said(self):
        e = connected_engine()
        base = 1_791_300_000
        for i in range(60):
            e.on_print("AAA", 10.0, 100, "ARCA", base + i + 3.2, "", xt=base + i)   # PC 3 s ahead
        self.assertAlmostEqual(e.clock_offset, 3.2, places=1)
        self.assertTrue(any("clock is about 3.2 s ahead" in m["text"] for m in e.messages))


class DayRangeFromHistoryTests(unittest.TestCase):
    def test_low_of_day_counts_the_history_before_ted_watched(self):
        import datetime as _dt
        from zoneinfo import ZoneInfo
        ny = ZoneInfo("America/New_York")
        t_open = _dt.datetime(2026, 10, 7, 9, 30, tzinfo=ny).timestamp()
        t_now = _dt.datetime(2026, 10, 7, 14, 28, tzinfo=ny).timestamp()
        e = connected_engine()
        e._clock(t_now)
        e.on_hist_bar("AAA", t_open - 600, 772.0, 772.5, 771.0, 772.2, 1000)      # premarket: never the day's low
        e.on_hist_bar("AAA", t_open, 775.72, 775.9, 773.61, 774.0, 1000)
        e.on_hist_bar("AAA", t_open + 3600, 776.0, 777.7, 775.9, 777.5, 1000)
        e.on_print("AAA", 777.22, 100, "ARCA", t_now, "", xt=int(t_now))
        e.on_print("AAA", 777.45, 100, "ARCA", t_now + 1, "", xt=int(t_now) + 1)
        st = e.syms["AAA"]
        self.assertEqual(st.day_lo[0], 773.61)
        self.assertEqual(st.day_hi[0], 777.7)
        marks = {m["role"]: m["price"] for m in e._ladder_marks(st, t_now + 2, [], 777.45)}
        self.assertEqual((marks["hod"], marks["lod"]), (777.7, 773.61))
