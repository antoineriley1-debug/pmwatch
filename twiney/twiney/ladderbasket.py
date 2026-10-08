"""THE BASKET LADDER's server side: the duplicate-print guard, the FLIP watch, and the PS60 SEQUENCE.

Display only: nothing here creates, stages or sends an order.

PRINT GUARD. A confirmed trade is a tape print (tick-by-tick AllLast), never a depth change. IBKR prints carry no
trade id, so a print is keyed by its time + price + size + exchange. IBKR's time is whole seconds, and two real
100-share prints at the same price on the same exchange in the same second are common: the key also carries which
identical print of that second it is (1st, 2nd ...) on this connection. Within one connection that keeps every real
print; a re-delivery after a reconnect (a new connection counts again from the 1st) repeats keys already seen and is
ignored. Never double counted, never a real print dropped.

FLIP at a level: the defending side's refill DIES (a reload buyer / seller NOT RELOADING, CLEANED UP or PULLED, or no
refill for ``flip_dead_seconds``) AND size from the OPPOSITE side shows at that same price (at least
``flip_min_shares``, held ``flip_hold_seconds``). Size resting on the book, not prints: a single thin print can never
flip a level. It ends when the defender refills again or the opposite size leaves.

PS60 SEQUENCE (no entry at the pivot):
  1 WAITING AT PIVOT    — before the break; a reload seller at the pivot (long) says whether the break is likely
  2 BROKE THROUGH       — through the pivot and a new high (new low for shorts)
  3 PULLBACK TO PIVOT   — the pullback, with the live verdict of the reload buyer defending the pivot
  4 SECOND ENTRY        — lit only when the pullback held (back through the new high) with that reload buyer still
                          RELOADING or STILL THERE
The steps are the desk's own PS60 second-entry engine (ps60.second_entry): IDLE, BROKE, RETRACE, SECOND_ENTRY.
"""

from .conviction import ACTIVE, FADING, GONE, PULLED_STAGE, STALE

DEFENDING = (ACTIVE, FADING)              # RELOADING / STILL THERE: still defending
DEAD = (STALE, GONE, PULLED_STAGE)        # NOT RELOADING / CLEANED UP / PULLED


class PrintGuard:
    def __init__(self, keep_seconds=900.0):
        self.keep = keep_seconds
        self.epoch = 0
        self.n = {}          # (epoch, base key) -> identical prints seen so far on this connection
        self.seen = {}       # full key -> arrival t
        self._count = 0

    def new_connection(self):
        """A new connection to the feed: identical prints are counted from the 1st again (a re-delivery repeats keys)."""
        self.epoch += 1
        self.n = {}

    def first_time(self, t, xt, price, size, exchange):
        """True for a print never seen before; False for a duplicate (ignore it)."""
        base = (int(xt) if xt else round(float(t), 3), round(float(price), 6), round(float(size), 4), str(exchange or ""))
        k = (self.epoch, base)
        nth = self.n.get(k, 0) + 1
        self.n[k] = nth
        key = base + (nth,)
        if key in self.seen:
            return False
        self.seen[key] = t
        self._count += 1
        if self._count % 2000 == 0:          # forget keys older than keep_seconds (a re-delivery comes quickly)
            cut = t - self.keep
            self.seen = {k2: v for k2, v in self.seen.items() if v >= cut}
            live = {(self.epoch, k2[:4]) for k2 in self.seen}
            self.n = {k2: v for k2, v in self.n.items() if k2 in live}
        return True


class FlipWatch:
    def __init__(self):
        self.opp_since = {}      # (defending side, price) -> t the opposite size first showed
        self.flips = {}          # (defending side, price) -> {"t", "price", "who", "seq"}
        self.said = {}           # (defending side, price) -> t of the last call
        self.ended = {}          # price -> (defending side, t it ended): no mirror flip at that price for a while

    def update(self, t, trackers, size_at, cfg):
        """``trackers``: [(side 'bid'/'ask', price, stage, last_refill_t, refill_seq, ever_proven)]; ``size_at(side,
        price)`` = size resting on that side at that price now. Returns the NEW flips: [(side, price)]."""
        dead_s = float(cfg.get("flip_dead_seconds", 20))
        min_sz = float(cfg.get("flip_min_shares", 1000))
        hold = float(cfg.get("flip_hold_seconds", 2))
        out, live = [], set()
        for side, price, stage, last_refill, seq, proven in trackers:
            key = (side, round(price, 4))
            live.add(key)
            if not proven and stage not in DEAD:
                self.opp_since.pop(key, None); self.flips.pop(key, None)
                continue
            dead = stage in DEAD or (stage in DEFENDING and last_refill is not None and t - last_refill >= dead_s)
            opp = size_at("ask" if side == "bid" else "bid", price) or 0
            f = self.flips.get(key)
            if f is not None:
                # it ends when the defender refills again, or the opposite size leaves
                if seq != f["seq"] or opp < min_sz:
                    self.flips.pop(key, None); self.opp_since.pop(key, None)
                    self.ended[key[1]] = (side, t)
                continue
            # one side's flip at a price is THE read there: the mirror flip waits until it has been over a while
            # (price chopping on a level both sides defended must not flicker FLIP one way and back)
            other = ("ask" if side == "bid" else "bid", key[1])
            en = self.ended.get(key[1])
            if other in self.flips or (en and en[0] != side and t - en[1] < float(cfg.get("flip_mirror_seconds", 60))):
                self.opp_since.pop(key, None)
                continue
            if dead and opp >= min_sz:
                since = self.opp_since.setdefault(key, t)
                if t - since >= hold:
                    self.flips[key] = {"t": t, "price": price, "who": "seller" if side == "ask" else "buyer", "seq": seq}
                    out.append(key)
            else:
                self.opp_since.pop(key, None)
        for key in [k for k in self.flips if k not in live]:
            self.flips.pop(key, None)
        return out

    def at(self, price):
        """The live flip at this price, if any: 'seller' (seller losing, buyers taking over) or 'buyer'."""
        for (side, p), f in self.flips.items():
            if abs(p - price) < 1e-6:
                return f["who"]
        return None


def flip_words(price_txt, who):
    if who == "seller":
        return f"{price_txt} FLIP, seller losing, buyers taking over"
    return f"{price_txt} FLIP, buyer losing, sellers taking over"


def sequence(play, se, stage_at, t=None):
    """The PS60 SEQUENCE at the top of the ladder. ``se`` = the desk's second-entry read (ps60.second_entry);
    ``stage_at(side)`` = (stage, size showing) of the tracker on that side AT THE PIVOT, or (None, 0)."""
    trig = play.get("trigger")
    if not trig or not se:
        return None
    long_ = play.get("side", "long") != "short"
    defender = "bid" if long_ else "ask"            # the pullback is defended by a reload buyer (long) / seller (short)
    blocker = "ask" if long_ else "bid"             # before the break: the reload seller (long) / buyer (short) at it
    d_stage, d_size = stage_at(defender)
    b_stage, b_size = stage_at(blocker)
    st = se.get("state")
    step = {"IDLE": 1, "BROKE": 2, "RETRACE": 3, "SECOND_ENTRY": 4}.get(st, 1)
    lit4 = st == "SECOND_ENTRY" and d_stage in DEFENDING
    if st == "SECOND_ENTRY" and not lit4:
        step = 3                                    # through again, but no reload buyer defending: not lit
    who_b = "reload seller" if long_ else "reload buyer"
    who_d = "reload buyer" if long_ else "reload seller"
    if step == 1:
        if b_stage in DEFENDING:
            note = f"{who_b} at the pivot: {b_stage} — the break is not likely yet"
        elif b_stage in DEAD:
            note = f"{who_b} at the pivot: {b_stage} — the break is likely"
        elif b_size:
            note = f"{int(b_size):,} showing at the pivot, not proven"
        else:
            note = "nothing defending the pivot"
    elif step == 2:
        note = f"through the pivot, new {'high' if long_ else 'low'} {se.get('extreme')} — wait for the pullback"
    elif step == 3:
        note = (f"pullback to the pivot — {who_d}: {d_stage}" if d_stage else f"pullback to the pivot — no {who_d} there yet")
        if st == "SECOND_ENTRY":
            note += " (back through, but no reload defending: second entry not lit)"
    else:
        note = f"second entry — the pullback held, {who_d} {d_stage}"
    return {"step": step, "side": "long" if long_ else "short", "trigger": trig, "extreme": se.get("extreme"),
            "retrace": se.get("retrace"), "verdict": d_stage if step >= 3 else b_stage,
            "verdict_side": defender if step >= 3 else blocker, "note": note, "lit4": lit4}
