"""KEY LEVELS WATCH: what price DOES at the levels that matter (the daily chart's and the session's).

Every key level is watched the same way, the way a tape reader reads it:

    price comes INTO the level (within a few ticks / a slice of the ATR)
      -> goes back the way it came, far enough        REJECTED (came up into it: sellers defended it)
                                                      BOUNCED  (came down into it: buyers defended it)
      -> goes THROUGH and holds there for a minute     BUYERS TOOK it (from below) / SELLERS TOOK it (from above)

PUSHING INTO / STALLING INTO / BREAKOUT and BREAKDOWN with or without speed come from the PACE read against the very
same levels, so the ladder, the calls, the voice and the story all name the same prices the same way.
"""


class LevelWatch:
    def __init__(self):
        self.s = {}        # level key -> {"side": "above"/"below", "touch": {"t", "from"} | None, "cross": t | None}
        self.said = {}     # (kind, level key) -> t

    def update(self, t, price, levels, tick, atr, cfg):
        """levels: [{"price", "name", "say", "code"}]. Returns the events that happened on this read."""
        if price is None or not levels:
            return []
        atr = atr or 0.0
        zone = max(float(cfg.get("zone_ticks", 3)) * tick, atr * float(cfg.get("zone_atr_pct", 3)) / 100.0)
        away = max(float(cfg.get("away_ticks", 8)) * tick, atr * float(cfg.get("away_atr_pct", 10)) / 100.0)
        hold = float(cfg.get("hold_seconds", 60))
        quiet = float(cfg.get("repeat_seconds", 300))
        out, live = [], set()
        for L in levels:
            p = float(L["price"])
            k = round(p, 4)
            live.add(k)
            s = self.s.setdefault(k, {"side": None, "touch": None, "cross": None})
            d = price - p
            side_now = "above" if d > zone else "below" if d < -zone else "at"
            tch = s["touch"]
            if tch and t - tch["t"] > float(cfg.get("touch_minutes", 15)) * 60:
                tch = s["touch"] = None; s["cross"] = None
            ev = None
            if side_now == "at":
                if tch is None and s["side"] in ("above", "below"):
                    s["touch"] = {"t": t, "from": s["side"]}
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
                    key = (ev, k)
                    if t - self.said.get(key, -1e9) >= quiet:
                        self.said[key] = t
                        out.append({"kind": ev, "price": p, "name": L["name"], "say": L.get("say") or L["name"],
                                    "code": L.get("code"), "from": frm, "t": t})
            if side_now != "at" and s["touch"] is None:
                s["side"] = side_now
        for k in [k for k in self.s if k not in live]:      # levels that went away (a new day, a level you removed)
            del self.s[k]
        return out
