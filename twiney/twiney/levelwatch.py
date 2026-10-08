"""KEY LEVELS WATCH: what price DOES at the levels that matter (the daily chart's and the session's).

Every key level is watched the same way, the way a tape reader reads it:

    price comes INTO the level (within a few ticks / a slice of the ATR)
      -> goes back the way it came, far enough        REJECTED (came up into it: sellers defended it)
                                                      BOUNCED  (came down into it: buyers defended it)
      -> goes THROUGH and holds there for a minute     BUYERS TOOK it (from below) / SELLERS TOOK it (from above)

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

    def update(self, t, price, levels, tick, atr, cfg):
        """levels: [{"price", "name", "say", "code"}]. Returns the events that happened on this read."""
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
                    if t - s["cross"] >= hold:
                        ev = "BUYERS TOOK" if side_now == "above" else "SELLERS TOOK"
                if ev:
                    s["touch"] = None; s["cross"] = None; s["side"] = side_now
                    emit(ev, L, frm)
            if side_now != "at" and s["touch"] is None:
                s["side"] = side_now
        for k in [k for k in self.s if k not in live]:      # levels that went away (a new day, a level you removed)
            del self.s[k]
        return out
