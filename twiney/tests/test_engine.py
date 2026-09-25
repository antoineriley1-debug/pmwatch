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
        self.assertEqual(got[-1]["size_before_gone"], 1000)
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

    def test_snapshot_shape(self):
        e = self._slotted()
        price_all(e, 1.0, {"AAA": 10.0})
        e.on_print("AAA", 10.00, 100, "X", 1.0)
        s = e.snapshot(2.0)
        self.assertEqual(s["mode"], "READ-ONLY · MARKET DATA ONLY")
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
