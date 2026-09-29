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
        e.listeners.append(got.append)
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
        e.listeners.append(got.append)
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
        d = s["depth"][0]
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
        self.assertEqual(e.voice[0]["text"], "AAA: buyer pulled 17k from 9.99")
        # hit: prints at that price account for the drop
        e.on_depth("AAA", 0, UPDATE, ASK, 10.00, 12000, "", 30.0)
        self.assertEqual(e.voice[0]["text"], "AAA: 12k seller at 10.00")
        for k in range(6):
            e.on_print("AAA", 10.00, 2000, "X", 31.0 + k * 0.1)
        e.on_depth("AAA", 0, UPDATE, ASK, 10.00, 100, "", 32.0)
        self.assertEqual(e.voice[0]["text"], "AAA: seller at 10.00 got hit for 11k")
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
        ok, why = e.set_play_setup("AAA", {"side": "long", "trigger": 10.0, "stop": 9.7, "target": 10.9, "mp": 0.9, "atr": 0.6, "second_entry": ""}, 2.0)
        self.assertTrue(ok, why)
        p = e.syms["AAA"].play
        self.assertEqual((p["stop"], p["target"], p["mp"], p["atr"], p["second_entry"]), (9.7, 10.9, 0.9, 0.6, None))
        row = next(r for r in e.snapshot(2.0)["ranking"] if r["symbol"] == "AAA")
        self.assertEqual((row["ps60"]["mp"]["dollars"], row["ps60"]["mp"]["verdict"]), (0.9, "CLEAR"))
        # bad inputs are refused with a reason, nothing changes
        ok, why = e.set_play_setup("AAA", {"stop": 10.5}, 3.0)
        self.assertFalse(ok); self.assertIn("below the pivot", why); self.assertEqual(e.syms["AAA"].play["stop"], 9.7)
        ok, why = e.set_play_setup("AAA", {"mp": "abc"}, 3.0)
        self.assertFalse(ok); self.assertIn("mp must be a number", why)
        # a stop on a typed-in ticker with no pivot is fine
        e.add_play("ZZZ", 4.0); e.on_l1("ZZZ", "last", 50.0, 4.0)
        ok, why = e.set_play_setup("ZZZ", {"stop": 49.0, "mp": 2.0, "atr": 1.5}, 4.0)
        self.assertTrue(ok, why)
