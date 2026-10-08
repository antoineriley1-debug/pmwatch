"""BREAK TRAPS: who got caught when price took out a key level and came back.

A break is price trading THROUGH a key level: the high / low of day (one that has stood a while, not every new tick of a
run), the premarket high / low, the prior day's high / low / close, the after-hours high / low, today's open.

From the break on, every print on the breakout side of the level is counted: for a break UP, the buy prints (paid the
offer) at or above the level: how many, how many shares, the dollars and their average price; and what was RESTING on
the offer at the level when it went (the sellers that got taken out). A break DOWN mirrors it: sell prints at or below
the level, the bid that was resting there. Only the crowd AT the break counts: within `zone_dollars` of the level and
`count_minutes` of the break (buyers hours later and dollars higher did not buy that break).

TRAPPED: price comes back through the level by `retrace_dollars` (well under a dollar by default) without ever making a
new extreme past the break: the breakout buyers (sellers) are underwater and the level stands as the high (low). Shown:
how many, which side, their average (where they get out), how far underwater, and the dollars at risk.

RECLAIMED: price makes a new extreme past the break: the breakout held, nobody is trapped. AT THEIR EXIT: price comes
back up (down) to the trapped crowd's average, where they sell (cover) to get out. A break is forgotten after
`memory_minutes`.

Gross figures: the tape shows who bought, not who has since sold. Read it as how much is caught, and where.
"""


class BreakTraps:
    def __init__(self):
        self.side = {}          # level key -> "above" / "below" / "at": where price last was against it
        self.hi = None          # [price, t]: the standing session high (regular hours)
        self.lo = None
        self.day = None
        self.breaks = []        # newest last
        self.events = []        # (kind, break) that happened on the last update: the engine calls them

    @staticmethod
    def _key(name, price):
        return f"{name}@{round(price, 4)}"

    def reset_day(self, day):
        self.day = day
        self.side.clear(); self.hi = self.lo = None; self.breaks = []

    def _open(self, t, name, say, price, up, resting, cfg):
        for b in self.breaks:
            # the same price under two names (the premarket high IS the high of day): one break with both names
            if b["state"] in ("BROKE", "TRAPPED", "AT EXIT") and b["up"] == up and abs(b["level"] - price) < 0.0051 and name not in b["name"].split(" / "):
                if b["t"] == t:
                    b["name"] += " / " + name; b["say"] += " and " + say
                return b
            if b["state"] in ("BROKE", "TRAPPED", "AT EXIT") and abs(b["level"] - price) < 1e-9:
                # one break per level while it lives: crossing back the other way IS that break failing (the trap),
                # not a new break the other way; crossing again the same way is the same break
                return None if b["up"] != up else b
        b = {"t": t, "name": name, "say": say, "level": price, "up": up, "state": "BROKE",
             "prints": 0, "shares": 0.0, "usd": 0.0, "resting": round(resting or 0), "extreme": price,
             "trap_t": None, "exit_said": False, "last": price}
        self.breaks.append(b)
        self.events.append(("BROKE", b))
        keep = int(cfg.get("max_breaks", 6))
        if len(self.breaks) > keep:
            self.breaks = self.breaks[-keep:]
        return b

    def update(self, t, price, size, side, tick, levels, rth, day, cfg, resting_at=None):
        """One print. ``levels``: [(name, say, price)] fixed key levels. ``side``: buy / sell / mid. ``rth``: inside
        regular hours (the high / low of day only count there). ``resting_at(up, level)``: size resting on the offer
        (up) / bid (down) at that price right now. Returns the events of this print."""
        self.events = []
        if price is None or price <= 0 or not size or size <= 0:
            return self.events
        if day != self.day:
            self.reset_day(day)
        through = max(tick * 0.5, 1e-9)
        # 1) the fixed key levels: a cross from one side to the other is a break
        for name, say, lv in levels:
            if lv is None or lv <= 0:
                continue
            k = self._key(name, lv)
            now = "above" if price > lv + through else "below" if price < lv - through else "at"
            was = self.side.get(k)
            if now != "at":
                if was == "below" and now == "above":
                    self._open(t, name, say, lv, True, resting_at(True, lv) if resting_at else 0, cfg)
                elif was == "above" and now == "below":
                    self._open(t, name, say, lv, False, resting_at(False, lv) if resting_at else 0, cfg)
                self.side[k] = now
        # 2) the high / low of day: a high that STOOD at least min_age seconds, then a print through it
        if rth:
            age = float(cfg.get("hod_min_age_seconds", 120))
            if self.hi is None:
                self.hi = [price, t]
            elif price > self.hi[0] + through:
                if t - self.hi[1] >= age:
                    self._open(t, "HIGH OF DAY", "the high of day", self.hi[0], True, resting_at(True, self.hi[0]) if resting_at else 0, cfg)
                self.hi = [price, t]
            if self.lo is None:
                self.lo = [price, t]
            elif price < self.lo[0] - through:
                if t - self.lo[1] >= age:
                    self._open(t, "LOW OF DAY", "the low of day", self.lo[0], False, resting_at(False, self.lo[0]) if resting_at else 0, cfg)
                self.lo = [price, t]
        # 3) every live break: count the breakout side, watch for the trap, the reclaim, the exit
        retrace = float(cfg.get("retrace_dollars", 0.30))
        mem = float(cfg.get("memory_minutes", 60)) * 60.0
        zone = float(cfg.get("zone_dollars", 0.50))              # "at that location": buys this close to the level ...
        window = float(cfg.get("count_minutes", 15)) * 60.0      # ... in this long after the break
        for b in self.breaks:
            if b["state"] in ("RECLAIMED", "EXPIRED"):
                continue
            if t - b["t"] > mem:
                b["state"] = "EXPIRED"
                continue
            up, lv = b["up"], b["level"]
            b["last"] = price
            if b["state"] == "BROKE":
                # the breakout crowd: buy prints at or above the level (sell prints at or below it for a break down)
                near = abs(price - lv) <= zone + 1e-9 and t - b["t"] <= window
                if near and ((up and side == "buy" and price >= lv - 1e-9) or (not up and side == "sell" and price <= lv + 1e-9)):
                    b["prints"] += 1; b["shares"] += size; b["usd"] += price * size
                if (up and price > b["extreme"]) or (not up and price < b["extreme"]):
                    b["extreme"] = price
                # TRAPPED: back through the level by the retrace, the extreme never exceeded since
                if b["shares"] > 0 and ((up and price <= lv - retrace + 1e-9) or (not up and price >= lv + retrace - 1e-9)):
                    b["state"] = "TRAPPED"; b["trap_t"] = t
                    self.events.append(("TRAPPED", b))
            elif b["state"] in ("TRAPPED", "AT EXIT"):
                if (up and price > b["extreme"] + through) or (not up and price < b["extreme"] - through):
                    b["state"] = "RECLAIMED"; b["reclaim_t"] = t       # a new extreme past the break: they are out of it
                    self.events.append(("RECLAIMED", b))
                    continue
                avg = b["usd"] / b["shares"] if b["shares"] else lv
                if not b["exit_said"] and ((up and price >= avg - through) or (not up and price <= avg + through)):
                    b["exit_said"] = True; b["state"] = "AT EXIT"
                    self.events.append(("AT EXIT", b))
                elif b["state"] == "AT EXIT" and ((up and price <= lv - retrace + 1e-9) or (not up and price >= lv + retrace - 1e-9)):
                    b["state"] = "TRAPPED"                              # turned back down from their exit: still caught
        return self.events

    def view(self, t, price, n=3, retrace=0.30):
        """What the floating TRAPS box shows: the live breaks, newest first."""
        out = []
        for b in reversed(self.breaks):
            if b["state"] == "EXPIRED":
                continue
            avg = b["usd"] / b["shares"] if b["shares"] else None
            under = None
            if avg is not None and price:
                under = (avg - price) if b["up"] else (price - avg)
            out.append({"name": b["name"], "level": round(b["level"], 4), "up": b["up"], "side": "long" if b["up"] else "short",
                        "state": b["state"], "age": round(t - b["t"]), "trap_age": round(t - b["trap_t"]) if b["trap_t"] else None,
                        "prints": b["prints"], "shares": round(b["shares"]), "usd": round(b["usd"]), "avg": round(avg, 4) if avg else None,
                        "resting": b["resting"], "extreme": round(b["extreme"], 4),
                        "trap_at": round(b["level"] - retrace if b["up"] else b["level"] + retrace, 4),
                        "under": round(under, 4) if under is not None else None,
                        "at_risk": round(under * b["shares"]) if under is not None and under > 0 else 0})
            if len(out) >= n:
                break
        return out
