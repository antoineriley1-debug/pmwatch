"""Acceptance tests from the Conviction Board source of truth, §10."""
import unittest

import twiney.ps60 as ps60
from helpers import ASK, BID, INSERT, cfg, plays
from twiney import board
from twiney.engine import Engine

FC = {"of_premium_min": 100000, "of_dte_green": 10, "of_dte_max": 21, "of_otm_min_pct": 1.0, "of_repeat_min": 2,
      "of_fresh_minutes": 30, "of_hedge_updays": 3}
G, Y, R = "GREEN", "YELLOW", "RED"


def pr(t, cp="C", prem=150000.0, dte=4.0, otm=6.0, strike=11.0, exp="2026-10-03", kind="sweep", side="ask"):
    return {"t": t, "symbol": "AAA", "cp": cp, "premium": prem, "dte": dte, "otm_pct": otm, "strike": strike,
            "expiry": exp, "kind": kind, "side": side, "spot": 10.0, "size": 300, "price": 5.0}


def se_state(state, build=None):
    return {"state": state, "second_entry": 10.10 if state == ps60.SECOND_ENTRY else None, "build": build,
            "extreme": 10.10, "retrace": 10.02, "fails": 0, "se_t": 100.0}


MP_CLEAR = {"dollars": 0.50, "atr": 0.40, "ratio": 1.25, "verdict": "CLEAR", "level": 10.6}
PLAY = {"symbol": "AAA", "side": "long", "trigger": 10.0, "stop": 9.9, "target": 10.6}


class FlowGateTests(unittest.TestCase):
    def test_one_print_under_the_floor_is_not_green(self):            # §10.2
        fg = board.flow_gate([pr(1000, prem=60000)], "long", 10.05, [], 1100, FC)
        self.assertFalse(fg["gate"]); self.assertNotEqual(fg["lanes"]["L6_FLOW_QUALITY"][0], G)
        # stacked repeats that reach institutional size do count
        fg = board.flow_gate([pr(1000, prem=60000), pr(1200, prem=60000)], "long", 10.05, [], 1300, FC)
        self.assertTrue(fg["premium_ok"]); self.assertTrue(fg["gate"])

    def test_near_spot_puts_after_up_days_are_a_hedge_not_a_short(self):   # §10.3
        closes = [9.0, 9.3, 9.7, 10.0]
        fg = board.flow_gate([pr(1000, cp="P", otm=0.3, strike=10.0), pr(1100, cp="P", otm=0.4, strike=10.0)], "short", 10.0, closes, 1200, FC)
        self.assertTrue(fg["hedge"]); self.assertFalse(fg["gate"]); self.assertEqual(fg["state"], "FLOW_HEDGE")
        self.assertIn("R9", fg["rules"])

    def test_months_out_is_yellow_weeklies_green(self):                 # §10.4
        far = board.flow_gate([pr(1000, dte=60, exp="2026-12-18"), pr(1100, dte=60, exp="2026-12-18")], "long", 10.05, [], 1200, FC)
        self.assertEqual(far["dte_lane"], R); self.assertEqual(far["lanes"]["L6_FLOW_QUALITY"][0], Y); self.assertFalse(far["gate"])
        near = board.flow_gate([pr(1000), pr(1100)], "long", 10.05, [], 1200, FC)
        self.assertEqual(near["dte_lane"], G); self.assertEqual(near["lanes"]["L6_FLOW_QUALITY"][0], G); self.assertTrue(near["gate"])

    def test_opposing_flow_and_fading(self):
        opp = board.flow_gate([pr(1000, cp="P", prem=400000, otm=5, strike=9.0), pr(1100)], "long", 10.0, [], 1200, FC)
        self.assertEqual(opp["state"], "FLOW_OPPOSITE")
        old = board.flow_gate([pr(1000), pr(1100)], "long", 10.0, [], 1100 + 40 * 60, FC)
        self.assertEqual(old["state"], "FLOW_FADING"); self.assertFalse(old["gate"])


class BoardTests(unittest.TestCase):
    def _board(self, se, prints, prev=None, mp=MP_CLEAR, reloaders=None, now=1300.0):
        return board.build(PLAY, 10.12, se, mp, reloaders or {"below": [], "above": []}, {"buy_pct": 70.0, "prints": 20},
                           prints, [9.0, 9.5, 9.8], [], now, FC, prev)

    def test_ready_needs_both_gates(self):                              # §10.1
        good = [pr(1000), pr(1100)]
        b = self._board(se_state(ps60.SECOND_ENTRY, "building"), good)
        self.assertEqual(b["board_state"], "READY_TO_GO"); self.assertEqual(b["traffic_light"], G)
        self.assertTrue(b["anti_early_entry"]["both_true"])
        b = self._board(se_state(ps60.SECOND_ENTRY, "building"), [])            # chart only
        self.assertEqual(b["board_state"], "ARMED"); self.assertIn("WAITING FLOW GATE", b["label"])
        b = self._board(se_state(ps60.BROKE), good)                              # flow only, chart not confirmed into a 2nd entry
        self.assertNotEqual(b["board_state"], "READY_TO_GO"); self.assertIn(b["board_state"], ("ARMED", "WATCH"))

    def test_second_entry_false_caps_at_armed_even_with_monster_flow(self):   # §10.5
        monster = [pr(1000, prem=5e6), pr(1050, prem=5e6), pr(1100, prem=5e6)]
        b = self._board(se_state(ps60.RETRACE), monster)
        self.assertEqual(b["board_state"], "ARMED"); self.assertIn("WAITING CHART GATE", b["label"])
        self.assertLess(b["score"], 100)

    def test_score_weights(self):
        b = self._board(se_state(ps60.SECOND_ENTRY, "building"), [pr(1000), pr(1100)])
        self.assertEqual(b["score"], 100)                                           # §5.3: 105 with the sweep bonus, capped at 100

    def test_invalidated_by_a_reload_seller_or_opposing_puts(self):
        good = [pr(1000), pr(1100)]
        seller = {"below": [], "above": [{"price": 10.15, "side": "ask", "kind": "confirmed", "stage": "RELOADING", "absorbed": 12000}]}
        b = self._board(se_state(ps60.SECOND_ENTRY, "building"), good, prev="READY_TO_GO", reloaders=seller)
        self.assertEqual(b["board_state"], "INVALIDATED"); self.assertIn("reload seller in the way", b["reasons"])
        b = self._board(se_state(ps60.SECOND_ENTRY, "building"), good + [pr(1200, cp="P", prem=900000, otm=5, strike=9.0)], prev="ARMED")
        self.assertEqual(b["board_state"], "INVALIDATED"); self.assertIn("opposing put flow", b["reasons"])

    def test_alert_copy_and_rule_codes(self):                            # §10.7
        b = self._board(se_state(ps60.SECOND_ENTRY, "building"), [pr(1000), pr(1100)])
        text = board.alert_text(b, PLAY, MP_CLEAR, se_state(ps60.SECOND_ENTRY, "building"))
        self.assertTrue(text.startswith("[PS60 OF] AAA LONG READY TO GO — chart gate GREEN (2nd entry 10.10) AND flow gate GREEN"))
        self.assertIn("MP $0.50 / ATR $0.40", text)
        for code in b["rules"]:
            self.assertIn(code, board.RULES)
        self.assertIn("ready to go", board.words(b))

    def test_options_stop_is_the_prior_5m_low(self):                     # R11
        bars = [[600 + i * 60, 10.0, 10.2, 9.95 + 0.01 * i, 10.1, 100, 50, 50] for i in range(10)]   # 600..1140: two 5m candles
        self.assertEqual(board.prior_5m(bars, 1230.0, True), 10.0)    # the candle 900..1140 (i=5..9): low 10.00


class EngineBoardTests(unittest.TestCase):
    def test_board_rides_the_pane_and_speaks_ready_once(self):
        e = Engine(plays(), cfg())
        e.on_connection("DEMO", "", 0.0); e.apply_slot("AAA", True, 0.0)
        for i in range(3):
            e.on_depth("AAA", i, INSERT, BID, round(9.99 - i * 0.01, 2), 500, "", 1.0)
            e.on_depth("AAA", i, INSERT, ASK, round(10.00 + i * 0.01, 2), 500, "", 1.0)
        e.syms["AAA"].play.update(stop=9.90, target=10.60, atr=0.40)
        real = ps60.second_entry
        ps60.second_entry = lambda bars, play, t, pc: dict(se_state(ps60.SECOND_ENTRY, "building"), text="x", tf=1)
        try:
            e.on_print("AAA", 10.12, 100, "X", 5.0)
            pane = next(x for x in e.snapshot(6.0)["panes"] if x and x["symbol"] == "AAA")
            self.assertEqual(pane["conviction"]["board_state"], "ARMED")
            self.assertEqual(pane["ps60"]["grade"], "WATCH")                  # READY held: the flow gate is not green
            for i in range(2):
                e.on_flow(pr(10.0 + i * 61, strike=11.0), 10.0 + i * 61)
            pane = next(x for x in e.snapshot(140.0)["panes"] if x and x["symbol"] == "AAA")
            self.assertEqual(pane["conviction"]["board_state"], "READY_TO_GO")
            self.assertEqual(pane["ps60"]["grade"], "READY")
            said = [a for a in e.alerts if a["label"] == "READY TO GO"]
            self.assertEqual(len(said), 1); self.assertIn("ready to go", said[0]["words"])
            e.snapshot(141.0)
            self.assertEqual(len([a for a in e.alerts if a["label"] == "READY TO GO"]), 1)
        finally:
            ps60.second_entry = real


if __name__ == "__main__":
    unittest.main()


class MarketScanTests(unittest.TestCase):
    def test_any_ticker_gets_a_flow_watch_when_the_gate_passes(self):
        e = Engine(plays(), cfg())
        e.set_flow_alerts("all") if hasattr(e, "set_flow_alerts") else setattr(e, "flow_alerts", "all")
        def zz(t, prem=150000.0):
            return dict(pr(t, prem=prem), symbol="ZZZ")
        e.on_flow(zz(1000.0), 1000.0)
        self.assertEqual([a for a in e.alerts if a["label"] == "FLOW WATCH"], [])           # one print: not yet (R5)
        e.on_flow(zz(1100.0), 1100.0)
        got = [a for a in e.alerts if a["label"] == "FLOW WATCH"]
        self.assertEqual(len(got), 1)
        self.assertTrue(got[0]["text"].startswith("[PS60 OF] ZZZ LONG WATCH — short-dated OTM CALL flow ($300K, 4DTE"))
        self.assertIn("NOT READY from flow alone", got[0]["text"])
        e.on_flow(zz(1200.0), 1200.0)
        self.assertEqual(len([a for a in e.alerts if a["label"] == "FLOW WATCH"]), 1)      # cooldown

    def test_a_stray_print_never_makes_a_watch(self):
        fg = board.flow_gate([pr(1000, prem=4000, dte=45)], "long", 10.0, [], 1100, FC)
        self.assertFalse(board.watch_worthy(fg))


class NoSidePickedTests(unittest.TestCase):
    """Until the trader picks a side (L / S, SIDE) or draws levels that only fit one, the desk never says
    'with you' or 'against you': it reports which way the money leans."""
    def _prints(self, cp, n=3, usd=120000):
        now = 1000.0
        return [{"t": now - 60 * i, "cp": cp, "side": "ask", "premium": usd, "strike": 100 + (5 if cp == "C" else -5), "spot": 100.0,
                 "dte": 3, "otm_pct": 5.0, "expiry": "2026-10-03", "sweep": False} for i in range(n)]

    def test_board_reports_the_lean_not_a_side(self):
        play = {"symbol": "AAA", "side": "long", "trigger": 100.0}
        b = board.build(play, 100.0, None, None, None, None, self._prints("P"), [], [], 1000.0, {})
        self.assertFalse(b["side_picked"])
        self.assertNotIn(b["board_state"], ("ARMED", "READY_TO_GO", "INVALIDATED"))
        self.assertTrue(b["label"].startswith("NO SIDE YET"), b["label"])
        self.assertIn("PUTS", b["label"])
        lanes = {l["id"]: l["text"] for l in b["lanes"]}
        self.assertNotIn("against", lanes["L5_FLOW_SIDE"]); self.assertIn("no side picked", lanes["L5_FLOW_SIDE"])
        self.assertIsNone(board.words(b))
        # a stop and a target pick the side; now the same put flow IS against a long
        play.update(stop=99.0, target=104.0)
        b = board.build(play, 100.0, None, None, None, None, self._prints("P"), [], [], 1000.0, {})
        self.assertTrue(b["side_picked"]); self.assertEqual(b["side_bias"], "LONG")
        self.assertIn("against this long", {l["id"]: l["text"] for l in b["lanes"]}["L5_FLOW_SIDE"])

    def test_side_picked_rules(self):
        self.assertFalse(board.side_picked({"side": "long"}))
        self.assertFalse(board.side_picked({"side": "long", "trigger": 10.0, "stop": 9.5}))
        self.assertTrue(board.side_picked({"side": "long", "stop": 9.5, "target": 11.0}))
        self.assertTrue(board.side_picked({"side": "short", "trigger": 10.0, "second_entry": 9.8}))
        self.assertTrue(board.side_picked({"side": "short", "side_set": True}))

    def test_words_are_plain_english(self):
        self.assertEqual(board.say_money(308000), "308 thousand dollars")
        self.assertEqual(board.say_money(1200000), "1.2 million dollars")
        self.assertEqual(board.say_money(2000000), "2 million dollars")
        b = {"symbol": "TSLA", "board_state": "READY_TO_GO", "side_bias": "LONG", "side_picked": True, "chart_gate": {"ok": True},
             "flow_gate": {"cluster": {"dollars": 308000, "repeats": 4}}, "reasons": []}
        self.assertEqual(board.words(b), "TSLA long, ready to go. The chart is confirmed and the flow is confirmed: 308 thousand dollars went into short term calls, 4 times. They keep coming.")
