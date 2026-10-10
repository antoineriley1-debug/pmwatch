"""LEVEL FOLLOW-UP: after the back and forth at a level, what did it decide?

When a level gets a bunch of calls (coming into it, at it, bounced, rejected, taken ...), the desk keeps watching it and,
5 to 7 minutes after the fight started, says how it came out, in plain words:

  DEFENDED     price is back on the side it came from and never held on the other side
               (came down into it: the buyers defended it; came up into it: the sellers did)
  LOST / BROKE price went through, a candle CLOSED on the other side, and it is holding there
               (came down into it: support lost; came up into it: it broke through)
  RECLAIMED    it went through, held there a while, and price is back on the side it came from
  UNDECIDED    still sitting on it: checked once more a few minutes later, then said as it is

Each outcome has several ways of saying it, rotated, so it never sounds like the same canned line twice in a row.
Display and voice only: nothing here places or changes an order.
"""

from .levelwatch import MOVING

PHRASES = {
    "DEFENDED_BUYERS": [
        "{nm} held up. Buyers defended {lvl} after all that back and forth, price {px}, {dist} over it",
        "Buyers won that fight at {nm}. {lvl} held, we're at {px} now",
        "{nm} did its job, {lvl} held as demand. Buyers were there. Price {px}, sitting {dist} above it",
        "That was a defend at {nm}. Buyers kept {lvl}, price is {px}",
    ],
    "DEFENDED_SELLERS": [
        "{nm} held as supply. Sellers defended {lvl}, price {px}, {dist} under it",
        "Sellers won that one at {nm}. {lvl} held, we're at {px}",
        "{nm} turned it away. {lvl} held up top, price back to {px}",
        "That was a reject at {nm}. Sellers kept {lvl}, price is {px}",
    ],
    "LOST": [
        "{nm} is lost. Sellers took {lvl} and price is holding under it at {px}",
        "Demand gave out at {nm}. {lvl} broke, we're at {px}, {dist} below it",
        "{nm} didn't hold. {lvl} broke down, price {px}, now it's supply over us",
        "Buyers lost {nm} at {lvl}. Price {px}, living under it now",
    ],
    "BROKE": [
        "{nm} broke. Buyers took {lvl} and price is holding over it at {px}",
        "We're through {nm}. {lvl} gave way, price {px}, {dist} above it",
        "{nm} got taken out. {lvl} is behind us, price {px}, now it's demand under us",
        "Sellers lost {nm} at {lvl}. Price {px}, holding above it",
    ],
    "RECLAIMED_UP": [
        "{nm} reclaimed. Lost it for a bit, buyers took {lvl} back, price {px}",
        "Got {nm} back. Dipped under {lvl}, now back over at {px}",
        "That was a reclaim at {nm}. Back above {lvl}, price {px}",
        "Shakeout at {nm}. Went under {lvl}, buyers pulled it back, price {px}",
    ],
    "RECLAIMED_DOWN": [
        "{nm} reclaimed by sellers. It popped over {lvl}, now back under at {px}",
        "Failed breakout at {nm}. Back below {lvl}, price {px}",
        "That push over {nm} didn't stick. Back under {lvl}, price {px}",
        "Sellers took {nm} back. Over {lvl} for a bit, now {px}",
    ],
    "UNDECIDED": [
        "Still no decision at {nm}. Chopping right on {lvl}, price {px}",
        "{nm} is still a coin flip. Price {px}, sitting on {lvl}",
        "Nobody's winning at {nm} yet. Still going back and forth on {lvl}, price {px}",
        "Still a fight at {nm}. Price {px}, right on {lvl}, no side has it",
    ],
}


TURN = {}


def _ident(code, name, price):
    if code in MOVING:
        return (code,)
    return (code or "", name if code in (None, "", "YOURS") else "", round(float(price), 2))


class LevelFollowUp:
    def __init__(self):
        self.fights = {}       # level ident -> the fight
        self.turn = TURN       # outcome -> how many times said, across every stock (the phrase rotates desk-wide)
        self.done = {}         # level ident -> t of its last verdict

    def note(self, ev, t):
        """A level call just went out (levelwatch event): open or feed that level's fight."""
        k = _ident(ev.get("code"), ev.get("name"), ev["price"])
        f = self.fights.get(k)
        if f is None:
            f = self.fights[k] = {"t0": t, "last_alert": t, "n": 0, "from": None, "name": ev.get("name"), "say": ev.get("say") or ev.get("name"),
                                  "code": ev.get("code"), "price": float(ev["price"]), "zone": float(ev.get("zone") or 0.0),
                                  "other_since": None, "held_other": False, "rechecked": False}
        f["n"] += 1
        f["last_alert"] = t
        f["price"] = float(ev["price"])
        if ev.get("zone"):
            f["zone"] = float(ev["zone"])
        if f["from"] is None and ev.get("from") in ("above", "below"):
            f["from"] = ev["from"]

    def update(self, t, price, levels, cfg, tick, close=None):
        """Every read: watch the open fights. close: (t the candle ended, its close) for the last completed candle:
        a level is only lost / broken on a close through it. Returns the verdicts due now: [fight dict + "outcome"]."""
        if price is None:
            return []
        lo = float(cfg.get("followup_min_minutes", 5)) * 60.0
        hi = max(lo, float(cfg.get("followup_max_minutes", 7)) * 60.0)
        quiet = float(cfg.get("followup_quiet_seconds", 60))
        need = int(cfg.get("followup_min_alerts", 3))
        hold = float(cfg.get("hold_seconds", 60))
        again = float(cfg.get("followup_recheck_minutes", 4)) * 60.0
        now = {_ident(L.get("code"), L.get("name"), L["price"]): float(L["price"]) for L in (levels or [])}
        out = []
        for k, f in list(self.fights.items()):
            if k in now:
                f["price"] = now[k]                        # VWAP and friends move: judge against where it is now
            if f["from"] is None:
                if t - f["t0"] > hi:
                    self.fights.pop(k, None)
                continue
            zone = max(f["zone"], tick * 2)
            d = price - f["price"]
            side = "above" if d > zone else "below" if d < -zone else "at"
            if side not in ("at", f["from"]):              # through it: how long has it held over there?
                if f["other_since"] is None:
                    f["other_since"] = t
                if close is not None and close[0] > f["other_since"] and (close[1] > f["price"] if side == "above" else close[1] < f["price"]):
                    f["closed_other"] = True
                if t - f["other_since"] >= hold and (close is None or f.get("closed_other")):
                    f["held_other"] = True
            elif side == f["from"]:
                f["other_since"] = None
                f["closed_other"] = False
            age = t - f["t0"]
            if age < lo or (t - f["last_alert"] < quiet and age < hi):
                continue
            if f["n"] < need:                              # one call, no fight: nothing to follow up
                self.fights.pop(k, None)
                continue
            if side == "at" and not f["rechecked"]:
                f["rechecked"] = True; f["t0"] = t - lo + again   # look again in a few minutes
                continue
            if side == "at":
                outcome = "UNDECIDED"
            elif side == f["from"]:
                outcome = "RECLAIMED" if f["held_other"] else "DEFENDED"
            elif f["other_since"] is not None and t - f["other_since"] >= hold and (close is None or f.get("closed_other")):
                outcome = "LOST" if f["from"] == "above" else "BROKE"
            else:
                continue                                   # just went through: give it the hold time first
            self.fights.pop(k, None)
            self.done[k] = t
            out.append(dict(f, outcome=outcome, last=price, dist=abs(d)))
        return out

    def words(self, v, nm, lvl, px, dist):
        """The verdict in casual words, a different way of putting it each time."""
        o, frm = v["outcome"], v["from"]
        key = {"DEFENDED": "DEFENDED_BUYERS" if frm == "above" else "DEFENDED_SELLERS",
               "RECLAIMED": "RECLAIMED_UP" if frm == "above" else "RECLAIMED_DOWN"}.get(o, o)
        opts = PHRASES[key]
        n = self.turn.get(key, 0)
        self.turn[key] = n + 1
        w = opts[n % len(opts)].format(nm=nm, lvl=lvl, px=px, dist=dist)
        return w[:1].upper() + w[1:]


def label(v):
    """The short label on the alert list."""
    o, frm = v["outcome"], v["from"]
    if o == "DEFENDED":
        return "DEFENDED" if frm == "above" else "HELD AS SUPPLY"
    if o == "RECLAIMED":
        return "RECLAIMED" if frm == "above" else "FAILED BREAKOUT"
    return {"LOST": "LOST", "BROKE": "BROKE THROUGH", "UNDECIDED": "STILL UNDECIDED"}[o]
