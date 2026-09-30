"""Conviction: how much to trust what the ladder is showing.

Two things live here.

1. The four stages of a proven reloader, and the words for them. The maths is on the LevelTracker
   (``conviction`` / ``stage``); this module only owns the names so the engine, the ladder and the tests
   all say the same thing:

     RELOADING      he reloaded just now, or size is sitting there with little traded through it since
     STILL THERE    no reload for a while, or a fair amount has traded through without him putting it back
     NOT RELOADING  more has traded through than he was ever putting back, or it has been a long time
     CLEANED UP     price came back and the level did not hold (he got eaten and price went through)
     PULLED         the size left without getting hit

   These are Dan's words. The desk never says "fading", "stale" or "gone".

   Conviction is a number 0..1 that drives those stages and the brightness of the row on the ladder.

2. ``PullBook``: for every price on each side of the book, of the size that LEFT the book, how much
   traded and how much simply vanished. A wall where most of the posted size ends up trading is real.
   A wall where most of it disappears before it trades was never there.

   IBKR gives displayed size per price, not order IDs, so this is INFERRED: size that dropped between two
   book reads, minus what printed against that side at that price in between, is called pulled. Two
   honest limits: (a) with SMART depth one venue re-quoting (delete + insert) looks like a drop then an
   add, so a drop that comes straight back inside ``requote_seconds`` is not counted; (b) an add and a
   cancel that net out between two reads are invisible. Read the number as a tilt, not a measurement.
"""

from .book import ASK, BID
from .prices import price_key

ACTIVE = "RELOADING"
FADING = "STILL THERE"
STALE = "NOT RELOADING"
GONE = "CLEANED UP"
PULLED_STAGE = "PULLED"

STAGES = (ACTIVE, FADING, STALE, GONE, PULLED_STAGE)

# a css-friendly word for each stage (the desk keys its colors on these)
SLUG = {ACTIVE: "active", FADING: "fading", STALE: "stale", GONE: "gone", PULLED_STAGE: "gone"}


def stage_words(stage, side_name):
    """One line, in plain words, for a hover or a call-out."""
    who = "buyer" if side_name == "bid" else "seller"
    if stage == ACTIVE:
        return f"the reload {who} is reloading: size came back after getting hit, little has traded through since"
    if stage == FADING:
        return f"the reload {who} is still there but has not reloaded in a bit"
    if stage == STALE:
        return f"the reload {who} is not reloading: more has traded through than he was putting back. Do not lean on him"
    if stage == GONE:
        return f"the reload {who} got cleaned up: price came back and the level did not hold"
    if stage == PULLED_STAGE:
        return f"the reload {who} pulled: the size left without getting hit"
    return ""


def real_label(pct):
    """REAL / MIXED / FAKE from the traded share of departed size."""
    if pct is None:
        return None
    if pct >= 0.70:
        return "REAL"
    if pct <= 0.30:
        return "FAKE"
    return "MIXED"


class PullBook:
    """Per price on each side: shares of departed size that traded (filled) vs vanished (pulled).

    Feed every print with ``on_print`` and every book read with ``on_book``. Call ``flush`` on the clock so
    a drop that never came back is finally counted as pulled, and ``prune`` so old prices age out.
    """

    def __init__(self, cfg):
        self.cfg = cfg            # the ladder section of the config
        self.reset()

    def reset(self):
        """A resynced book explains nothing about what left it: start over, count nothing until judged."""
        self.prev = {ASK: {}, BID: {}}       # price_key -> size at the last book read
        self.prices = {ASK: {}, BID: {}}     # price_key -> price (for the ladder)
        self.execs = {ASK: {}, BID: {}}      # price_key -> shares that hit this side here since the last read
        self.stats = {ASK: {}, BID: {}}      # price_key -> [filled, pulled, last change t]
        self.pending = {ASK: {}, BID: {}}    # price_key -> [t, shares]: a drop waiting to see if the venue re-quotes
        self.primed = {ASK: False, BID: False}

    # ---- inputs ------------------------------------------------------------

    def on_print(self, aggressor, price, size):
        """A print that hit the bid (aggressor sell) took from BID; one that lifted the offer took from ASK."""
        if aggressor == "sell":
            side = BID
        elif aggressor == "buy":
            side = ASK
        else:
            return
        k = price_key(price)
        self.execs[side][k] = self.execs[side].get(k, 0.0) + float(size)

    def on_book(self, book, side, now, judge=True):
        """Compare this side of the book with the last read and file what left it."""
        cur = {}
        for price, size, _n in book.levels(side):
            cur[price_key(price)] = float(size)
            self.prices[side][price_key(price)] = price
        if not judge:
            # resyncing: whatever changed is the rebuild, not an order leaving
            self.prev[side] = cur
            self.execs[side].clear()
            self.pending[side].clear()
            self.primed[side] = False
            return
        prev = self.prev[side]
        execs = self.execs[side]
        stats = self.stats[side]
        pending = self.pending[side]
        requote = float(self.cfg.get("requote_seconds", 1.0))
        if self.primed[side]:
            for k, prev_size in prev.items():
                cur_size = cur.get(k, 0.0)
                if cur_size < prev_size - 1e-9:
                    price = self.prices[side].get(k)
                    if cur_size <= 0 and price is not None and not book.in_view(side, price):
                        # scrolled out of the visible window, not gone: nothing to judge
                        execs.pop(k, None)
                        continue
                    drop = prev_size - cur_size
                    ex = execs.pop(k, 0.0)
                    filled = min(drop, ex)
                    rest = drop - filled
                    st = stats.setdefault(k, [0.0, 0.0, now])
                    if filled > 0:
                        st[0] += filled
                        st[2] = now
                    if rest > 1e-9:
                        p = pending.get(k)
                        if p is None:
                            pending[k] = [now, rest]
                        else:
                            p[1] += rest
                elif cur_size > prev_size + 1e-9:
                    # size came back: a drop this recent at this price was a venue re-quoting, not a pull
                    p = pending.get(k)
                    if p is not None and now - p[0] <= requote:
                        back = min(p[1], cur_size - prev_size)
                        p[1] -= back
                        if p[1] <= 1e-9:
                            del pending[k]
                    # whatever printed here since the last read was absorbed and replaced: that size traded
                    ex = execs.pop(k, 0.0)
                    if ex > 0:
                        st = stats.setdefault(k, [0.0, 0.0, now])
                        st[0] += ex
                        st[2] = now
            # prints at prices whose size did not change: hit and refilled inside one read, so it traded
            for k, ex in list(execs.items()):
                if ex > 0 and k in prev and abs(cur.get(k, 0.0) - prev[k]) <= 1e-9:
                    st = stats.setdefault(k, [0.0, 0.0, now])
                    st[0] += ex
                    st[2] = now
        execs.clear()
        self.prev[side] = cur
        self.primed[side] = True
        self.flush(now, side)

    def flush(self, now, side=None):
        """A drop that never came back inside ``requote_seconds`` is finally a pull."""
        requote = float(self.cfg.get("requote_seconds", 1.0))
        for s in ((side,) if side is not None else (ASK, BID)):
            pending = self.pending[s]
            for k in [k for k, (t0, _sh) in pending.items() if now - t0 > requote]:
                t0, sh = pending.pop(k)
                if sh > 1e-9:
                    st = self.stats[s].setdefault(k, [0.0, 0.0, now])
                    st[1] += sh
                    st[2] = now

    def prune(self, now, keep_seconds):
        for s in (ASK, BID):
            stats = self.stats[s]
            for k in [k for k, st in stats.items() if now - st[2] > keep_seconds]:
                del stats[k]

    # ---- reads -------------------------------------------------------------

    def at(self, side, k):
        """{filled, pulled, pct, label} for one price, or None until there is enough of a sample."""
        st = self.stats[side].get(k)
        if st is None:
            return None
        filled, pulled = st[0], st[1]
        total = filled + pulled
        if total < float(self.cfg.get("real_min_shares", 2000)):
            return None
        pct = filled / total
        return {"filled": round(filled), "pulled": round(pulled), "pct": round(pct, 3), "label": real_label(pct)}
