"""KEY LEVELS WATCH: what price DOES at the levels that matter (the daily chart's and the session's).

Every key level is watched the same way, the way a tape reader reads it:

    price comes INTO the level (within a few ticks / a slice of the ATR)
      -> goes back the way it came, far enough        REJECTED (came up into it: sellers defended it)
                                                      BOUNCED  (came down into it: buyers defended it)
      -> goes THROUGH and a candle CLOSES through it, then price HOLDS on that side for 5 minutes straight
                                                      BUYERS TOOK it (from below) / SELLERS TOOK it (from above)
         (trading through it is not taking it: no close under / over it, no break; a dip back through by more than
          a hair restarts the 5 minutes)
      -> 10 minutes after it was taken, how it held   HELD: STRONG (never came back to it) / HOLDING (came back to
                                                      test it and held) / NOT STRONG (dipped back through N times,
                                                      still on the right side) / LOST (back through it)

PUSHING INTO / STALLING INTO / BREAKOUT and BREAKDOWN with or without speed come from the PACE read against the very
same levels, so the ladder, the calls, the voice and the story all name the same prices the same way.
"""


from collections import deque

# levels that drift a little all day (VWAP, the 50-day, AIRSPACE's reject / bounce): one level whatever their price
MOVING = {"VWAP", "D50", "HOD", "LOD", "DREJ", "DBNC", "WREJ", "WBNC", "MREJ", "MBNC", "REJ", "BNC"}


class LevelWatch:
    def __init__(self):
        self.s = {}        # level key -> {"side": "above"/"below", "touch": {"t", "from"} | None, "cross": t | None}
        self.said = {}     # (kind, level key) -> t
        self.path = deque()   # (t, price) for the last ~20 s: which way price is travelling
        self.pend = {}     # level key -> {"t0", "ev", "from", "L"}: closed through it, holding for the 5 minutes
        self.graded = {}   # level key -> {"t0", "ev", "L", "dips", "under", "tested"}: taken, watched to its 10 minutes

    def update(self, t, price, levels, tick, atr, cfg, close=None):
        """levels: [{"price", "name", "say", "code"}]. close: (t the candle ended, its close) for the last completed
        candle: a level is only taken when a candle closes through it. Returns the events that happened on this read."""
        if price is None or not levels:
            return []
        atr = atr or 0.0
        zone = max(float(cfg.get("zone_ticks", 3)) * tick, atr * float(cfg.get("zone_atr_pct", 3)) / 100.0)
        # TESTED: price came down into it (or up into it) close enough to count as a test, even if it never printed
        # right on it. A test that turns back is a BOUNCE (from above) or a REJECTION (from below); AT is only said
        # within `zone` (on it, exactly)
        test = max(zone, float(cfg.get("test_ticks", 4)) * tick, atr * float(cfg.get("test_atr_pct", 3)) / 100.0)
        away = max(float(cfg.get("away_ticks", 8)) * tick, atr * float(cfg.get("away_atr_pct", 10)) / 100.0)
        hold = float(cfg.get("hold_seconds", 60))
        # TOOK: after the close through it, price has to stay on that side this long; a dip back through by more than a
        # hair (2 cents or a sliver of the ATR) starts the clock again
        took_hold = float(cfg.get("took_hold_minutes", 5)) * 60
        grade_at = float(cfg.get("grade_minutes", 10)) * 60
        hair = max(float(cfg.get("dip_cents", 2)) / 100.0, atr * float(cfg.get("dip_atr_pct", 1)) / 100.0)
        quiet = float(cfg.get("repeat_seconds", 300))
        near = max(float(cfg.get("near_ticks", 6)) * tick, atr * float(cfg.get("near_atr_pct", 8)) / 100.0, zone * 1.5)
        self.path.append((t, price))
        while self.path and t - self.path[0][0] > 20.0:
            self.path.popleft()
        move = price - self.path[0][1] if len(self.path) > 1 else 0.0
        # the last 5 s: still heading that way (a dip that already turned around is not "coming into" anything)
        p5 = next((px for tt, px in self.path if t - tt <= 5.0), price)
        move5 = price - p5
        travel = max(3 * tick, zone)
        out, live = [], set()
        # a level is WHAT it is (VWAP, yesterday's high, your 2nd entry), not its exact price: VWAP and the daily
        # reject / bounce move a little every second and are still the same level
        ident = lambda L: ((L["code"],) if L.get("code") in MOVING else (L.get("code") or "", L["name"] if L.get("code") in (None, "", "YOURS") else "",
                                                                            round(float(L["price"]), 2)))

        def emit(kind, L, frm):
            key = (kind, ident(L))
            if t - self.said.get(key, -1e9) >= quiet:
                self.said[key] = t
                out.append({"kind": kind, "price": float(L["price"]), "name": L["name"], "say": L.get("say") or L["name"],
                            "code": L.get("code"), "from": frm, "t": t, "last": price, "zone": zone})
        for L in levels:
            p = float(L["price"])
            k = ident(L)
            live.add(k)
            # TAKEN, watched to its 10 minutes: every dip back through it is counted
            g = self.graded.get(k)
            if g:
                sg = 1 if g["ev"] == "BUYERS TOOK" else -1
                dd = (price - p) * sg
                under = dd < -hair
                if under and not g["under"]:
                    g["dips"] += 1
                g["under"] = under
                if dd <= test:
                    g["tested"] = True
                g["best"] = max(g.get("best", dd), dd)
                if t - g["t0"] >= grade_at:
                    grade = ("LOST" if under else "STRONG" if not g["dips"] and not g["tested"]
                             else "HOLDING" if not g["dips"] else "NOT STRONG")
                    out.append({"kind": "HELD", "grade": grade, "took": g["ev"], "price": p, "name": L["name"],
                                "say": L.get("say") or L["name"], "code": L.get("code"), "from": g["from"], "t": t,
                                "last": price, "zone": zone, "dips": g["dips"], "since": g["t0"],
                                "minutes": round((t - g["t0"]) / 60.0), "away": round(dd, 4)})
                    del self.graded[k]
            # CLOSED through it: holding for the 5 minutes before it is called taken
            pd = self.pend.get(k)
            if pd:
                sg = 1 if pd["ev"] == "BUYERS TOOK" else -1
                dd = (price - p) * sg
                if dd < -away or t - pd["t0"] > float(cfg.get("touch_minutes", 15)) * 60:
                    del self.pend[k]                     # back through and gone the other way: never taken
                    s = self.s.setdefault(k, {"side": None, "touch": None, "cross": None})
                    s.update(side=None, touch=None, cross=None)
                    continue
                if dd < -hair:
                    pd["t0"] = t                          # dipped back through: the 5 minutes start again
                elif t - pd["t0"] >= took_hold:
                    del self.pend[k]
                    key = (pd["ev"], k)
                    if t - self.said.get(key, -1e9) >= quiet:
                        self.said[key] = t
                        out.append({"kind": pd["ev"], "price": p, "name": L["name"], "say": L.get("say") or L["name"],
                                    "code": L.get("code"), "from": pd["from"], "t": t, "last": price, "zone": zone,
                                    "since": pd["t0"], "minutes": round((t - pd["t0"]) / 60.0), "away": round(dd, 4)})
                        self.graded[k] = {"t0": pd["t0"], "ev": pd["ev"], "from": pd["from"], "dips": 0, "under": False,
                                          "tested": False}
                continue
            s = self.s.setdefault(k, {"side": None, "touch": None, "cross": None})
            d = price - p
            side_now = "above" if d > zone else "below" if d < -zone else "at"
            tch = s["touch"]
            if tch and t - tch["t"] > float(cfg.get("touch_minutes", 15)) * 60:
                tch = s["touch"] = None; s["cross"] = None
            ev = None
            # COMING INTO it: a few ticks away and travelling toward it
            toward = abs(move) >= travel and (move > 0) == (d < 0) and (move5 * (1 if d < 0 else -1)) >= -tick * 0.5
            between = any(abs(float(o["price"]) - p) > tick * 0.5 and min(price, p) < float(o["price"]) < max(price, p) for o in levels)
            if side_now != "at" and tch is None and abs(d) <= near and toward and not between:
                emit("COMING INTO", L, "below" if d < 0 else "above")
            # a test without printing on it: within `test` of it, from the side it was on, still not through
            if tch is None and side_now != "at" and s["side"] == side_now and abs(d) <= test:
                s["touch"] = tch = {"t": t, "from": side_now, "near": True}
            if side_now == "at":
                if (tch is None or tch.get("near")) and s["side"] in ("above", "below"):
                    if tch is None:
                        s["touch"] = {"t": t, "from": s["side"]}
                    else:
                        tch.pop("near", None)
                    emit("AT", L, s["side"])
                s["cross"] = None if tch is None or s["cross"] is None else s["cross"]
            elif tch:
                frm = tch["from"]
                if side_now == frm:
                    s["cross"] = None
                    if abs(d) >= away:
                        ev = "REJECTED" if frm == "below" else "BOUNCED"
                else:
                    if s["cross"] is None:
                        s["cross"] = t
                    if close is None:
                        took = t - s["cross"] >= hold            # no candles to go by: through and holding
                    else:                                        # a candle that ended after the cross CLOSED through it
                        took = close[0] > s["cross"] and (close[1] > p if side_now == "above" else close[1] < p)
                    if took:
                        ev = "BUYERS TOOK" if side_now == "above" else "SELLERS TOOK"
                if ev:
                    s["touch"] = None; s["cross"] = None; s["side"] = side_now
                    if ev in ("BUYERS TOOK", "SELLERS TOOK") and took_hold > 0:
                        self.pend[k] = {"t0": t, "ev": ev, "from": frm}    # called once it has held
                    else:
                        emit(ev, L, frm)
            if side_now != "at" and s["touch"] is None:
                s["side"] = side_now
        for k in [k for k in self.s if k not in live]:      # levels that went away (a new day, a level you removed)
            del self.s[k]
        for m in (self.pend, self.graded):
            for k in [k for k in m if k not in live]:
                del m[k]
        return out
