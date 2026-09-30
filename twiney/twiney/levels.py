"""Reload detection at watched price levels.

One LevelTracker follows one side (bid or ask) of one price. It only reports:

  RELOAD BUYER DETECTED / RELOAD SELLER DETECTED
      inside the evidence window the level refilled after executions at least
      ``min_refreshes`` times, executed shares there reached both
      ``min_absorbed_shares`` and ``absorbed_multiple`` x the largest displayed
      size, and size is still displayed.
  CLEANED UP
      a confirmed reload disappeared, executions at the level inside
      ``consumed_exec_window_seconds`` reached ``consumed_min_exec_fraction`` of
      its last displayed size, and price then traded through the level.
  PULLED
      a confirmed reload disappeared and, after ``pull_grace_seconds``, there
      was not enough recent execution evidence to call it consumed.

A disappearance that is consumed but never followed through is closed silently
as INCONCLUSIVE. Nothing here attributes liquidity to a single participant.
"""

from collections import deque

from .book import ASK, BID
from .conviction import ACTIVE, FADING, GONE, PULLED_STAGE, STALE
from .prices import price_key, tick_size
from .tape import BUY, SELL

WATCHING = "WATCHING"
BUILDING = "BUILDING"
RELOAD = "RELOAD"
GONE_PENDING = "GONE_PENDING"

CLEANED_UP = "CLEANED UP"
PULLED = "PULLED"
INCONCLUSIVE = "INCONCLUSIVE"


def reload_label(side):
    return "RELOAD SELLER DETECTED" if side == ASK else "RELOAD BUYER DETECTED"


class LevelTracker:
    def __init__(self, symbol, price, side, role, cfg, created=0.0):
        self.symbol = symbol
        self.price = price
        self.side = side
        self.role = role
        self.cfg = cfg
        self.tick = tick_size(price)
        self.key = price_key(price, self.tick)
        self.created = created
        self.last_active = created
        self.last_verdict = None  # (label, t)
        self.verdict_info = None
        # proven: confirmed as a reload once, and stays proven (lit on the ladder) until it is CLEANED UP,
        # PULLED, or price trades through the level with nothing sitting there. A brief flicker to zero,
        # or an inconclusive "gone" call, does not un-prove it.
        self.proven = False
        self.proven_refills = 0
        # conviction: how much to trust that a proven reloader is still there (see conviction.py)
        self.last_refill_t = None    # when size last came back after being hit (or when the reload was confirmed)
        self.refill_basis = 0.0      # the most that traded through before he replaced it: what he absorbs per refill
        self.vol_since_refill = 0.0  # shares that hit this side at the level since then: what he has NOT replaced
        self.gone_t = None           # when a proven level was finally lost (through with nothing there, or a verdict)
        self._reset_episode()

    def _reset_episode(self):
        self.state = WATCHING
        self.displayed = 0.0
        self.peak_displayed = 0.0
        self.episode_start = None
        self.absorbed_total = 0.0
        self.prints = deque()  # (t, size) executions against this side at the level
        self._psum = 0.0       # running total of self.prints (a busy level must not cost more with every print)
        self.refresh_times = deque()
        self.exec_since_refresh = 0.0
        self.confirmed_at = None
        self.gone_at = None
        self.size_before_gone = 0.0
        self.last_change_t = None
        self.gone_basis_t = None
        self.last_through = None
        self.out_of_view = False

    # ---- helpers -----------------------------------------------------------

    def matches(self, price):
        return abs(price_key(price, self.tick) - self.key) <= self.cfg["level_band_ticks"]

    def _through(self, price):
        """Price is beyond the level in the direction that consumes this side."""
        k = price_key(price, self.tick)
        band = self.cfg["level_band_ticks"]
        return k > self.key + band if self.side == ASK else k < self.key - band

    def _prune(self, now):
        w = self.cfg["window_seconds"]
        keep = max(w, self.cfg["consumed_exec_window_seconds"])
        while self.prints and now - self.prints[0][0] > keep:
            self._psum -= self.prints.popleft()[1]
        if not self.prints:
            self._psum = 0.0
        while self.refresh_times and now - self.refresh_times[0] > w:
            self.refresh_times.popleft()

    def absorbed_window(self, now):
        w = self.cfg["window_seconds"]
        if w >= self.cfg["consumed_exec_window_seconds"]:
            self._prune(now)             # the deque now holds exactly the window
            return max(0.0, self._psum)
        return sum(s for t, s in self.prints if now - t <= w)

    def refreshes_window(self, now):
        w = self.cfg["window_seconds"]
        return sum(1 for t in self.refresh_times if now - t <= w)

    # ---- inputs ------------------------------------------------------------

    def on_book(self, book, now, judge=True):
        """Feed the current book. ``judge`` is False while the book is resyncing."""
        displayed = book.size_at(self.side, self.price, self.cfg["level_band_ticks"])
        prev = self.displayed
        if displayed > 0:
            self.out_of_view = False
            self.last_active = now
            if self.state == WATCHING:
                self.state = BUILDING
                self.episode_start = now
            elif self.state == GONE_PENDING:
                # it came back before a verdict: still a live reload
                self.state = RELOAD
                self.gone_at = None
            if displayed > prev and self.exec_since_refresh > 0:
                # size came back after executions ate into it: a refresh
                self.refresh_times.append(now)
                if self.proven:
                    self.proven_refills += 1
                self.last_refill_t = now
                self.refill_basis = max(self.refill_basis, self.exec_since_refresh)
                self.exec_since_refresh = 0.0
                self.vol_since_refill = 0.0
            if displayed != prev:
                self.last_change_t = now
            self.displayed = displayed
            self.peak_displayed = max(self.peak_displayed, displayed)
        else:
            visible = book.in_view(self.side, self.price) or (
                book.best(self.side) is not None and self._level_inside_or_through(book))
            self.displayed = 0.0
            if not judge:
                return None
            if not visible:
                self.out_of_view = True
                return None
            self.out_of_view = False
            if self.state == RELOAD:
                self.state = GONE_PENDING
                self.gone_at = now
                self.size_before_gone = prev if prev > 0 else self.peak_displayed
                # only prints after the level took its final size can have consumed it
                self.gone_basis_t = self.last_change_t if self.last_change_t is not None else now
            elif self.state == BUILDING and prev > 0:
                # never confirmed: keep counters for the window, but note it's empty
                pass
        return self.evaluate(now, book)

    def _holding_through(self, book):
        """Right now nothing of this side is left at or before the level: the offer is above it (the bid below
        it). If price comes back, the offer is back at or under the level - that is not cleaned up, it is still
        being fought over."""
        if book is None:
            return True
        own = book.best(self.side)
        if own is None:
            return True
        k = price_key(own, self.tick)
        return k > self.key if self.side == ASK else k < self.key

    def _level_inside_or_through(self, book):
        best = book.best(self.side)
        k = price_key(best, self.tick)
        return k >= self.key if self.side == ASK else k <= self.key

    def on_print(self, price, size, aggressor, now, book=None):
        if self._through(price):
            self.last_through = now
            if self.proven and self.state not in (RELOAD, GONE_PENDING) and self.displayed <= 0:
                self.proven = False           # price went through a proven level that is no longer defended
                self.gone_t = now
            return self.evaluate(now, book) if self.state == GONE_PENDING else None
        if not self.matches(price):
            return None
        hits_side = (self.side == ASK and aggressor == BUY) or (self.side == BID and aggressor == SELL)
        if not hits_side:
            return None
        if self.state == WATCHING:
            self.state = BUILDING
            self.episode_start = now
        self.last_active = now
        self.prints.append((now, size))
        self._psum += size
        self.absorbed_total += size
        self.exec_since_refresh += size
        self.vol_since_refill += size
        return self.evaluate(now, book)

    def on_resync(self):
        """Book was reset (error 317 / reconnect): drop any pending disappearance."""
        if self.state == GONE_PENDING:
            self.state = RELOAD
            self.gone_at = None
        self.displayed = 0.0

    # ---- decision ----------------------------------------------------------

    def evaluate(self, now, book=None):
        """Advance the state machine. Returns an alert label or None."""
        self._prune(now)
        c = self.cfg
        if self.state == BUILDING:
            if self.episode_start is not None and now - self.episode_start > c["window_seconds"] \
                    and not self.prints and not self.refresh_times and self.displayed <= 0:
                self._reset_episode()
                return None
            absorbed = self.absorbed_window(now)
            if (self.refreshes_window(now) >= c["min_refreshes"]
                    and absorbed >= c["min_absorbed_shares"]
                    and absorbed >= c["absorbed_multiple"] * self.peak_displayed
                    and self.displayed >= c["min_display_shares"]):
                self.state = RELOAD
                self.confirmed_at = now
                self.proven = True
                self.gone_t = None
                # the print that confirmed him is evidence FOR him, not size he failed to replace: start fresh here
                self.last_refill_t = now
                self.vol_since_refill = 0.0
                self.proven_refills = self.refreshes_window(now)
                return reload_label(self.side)
            return None

        if self.state == GONE_PENDING:
            since = max(self.gone_at - c["consumed_exec_window_seconds"], self.gone_basis_t)
            if book is not None:
                # the opposite side quoting beyond the level also means price moved through
                opp_best = book.best(BID if self.side == ASK else ASK)
                if opp_best is not None and self._through(opp_best):
                    self.last_through = now
            moved_through = (self.last_through is not None
                             and self.last_through >= self.gone_at - c["consumed_exec_window_seconds"])
            recent = sum(s for t, s in self.prints if t >= since)
            consumed = recent > 0 and recent >= c["consumed_min_exec_fraction"] * self.size_before_gone
            # a level that flickers to zero for a moment (delete + re-insert, a locked book from another
            # venue) is not cleared: it has to stay gone for clear_confirm_seconds first
            gone_for = now - self.gone_at
            if consumed and moved_through and gone_for >= c.get("clear_confirm_seconds", 3.0) and self._holding_through(book):
                return self._verdict(CLEANED_UP, now)
            if not consumed and now - self.gone_at >= c["pull_grace_seconds"]:
                return self._verdict(PULLED, now)
            if consumed and now - self.gone_at >= c["through_timeout_seconds"]:
                self._verdict(INCONCLUSIVE, now)
                return None
        return None

    def _verdict(self, label, now):
        self.last_verdict = (label, now)
        if label in (CLEANED_UP, PULLED):
            self.proven = False
            self.gone_t = now
        self.verdict_info = {"absorbed": self.absorbed_total, "size_before_gone": self.size_before_gone,
                             "refreshes": self.refreshes_window(now)}
        self._reset_episode()
        return label

    # ---- conviction ----------------------------------------------------------

    def conviction(self, now):
        """0..1: how much to trust that a proven reloader is still there.

        Volume carries the weight: shares that traded through since his last refill, against the most he ever
        let trade before replacing it (never less than his biggest showing), scaled by ``stale_multiple``.
        Time is a slow second bleed to ``stale_seconds``; while size is still showing it never takes the
        reading under half on its own. Not proven = 0.
        """
        if not self.proven:
            return 0.0
        c = self.cfg
        ref = self.last_refill_t if self.last_refill_t is not None else self.confirmed_at
        if ref is None:
            return 0.0
        basis = max(self.refill_basis, self.peak_displayed, float(c["min_absorbed_shares"])) * float(c.get("stale_multiple", 1.5))
        conv_v = max(0.0, 1.0 - self.vol_since_refill / basis) if basis > 0 else 1.0
        stale = float(c.get("stale_seconds", 2400.0))
        conv_t = max(0.0, 1.0 - (now - ref) / stale) if stale > 0 else 1.0
        if self.displayed > 0:
            conv_t = max(conv_t, 0.5)
        return round(max(0.0, min(1.0, min(conv_v, conv_t))), 3)

    def stage(self, now):
        """RELOADING / STILL THERE / NOT RELOADING for a proven level; CLEANED UP or PULLED for a while after it
        is lost; else None. Dan's words: the desk never says fading, stale or gone."""
        c = self.cfg
        if self.proven:
            cv = self.conviction(now)
            if cv >= float(c.get("active_floor", 0.75)):
                return ACTIVE
            if cv >= float(c.get("fading_floor", 0.25)):
                return FADING
            return STALE
        if self.gone_t is not None and now - self.gone_t <= float(c.get("gone_show_seconds", 7200.0)):
            return PULLED_STAGE if self.last_verdict and self.last_verdict[0] == PULLED else GONE
        return None

    def _display_state(self, now):
        if self.state == BUILDING and not self.absorbed_window(now):
            return "RESTING"
        if self.state == GONE_PENDING:
            return "GONE — JUDGING"
        return self.state

    def snapshot(self, now):
        return {
            "price": self.price,
            "side": "ask" if self.side == ASK else "bid",
            "role": self.role,
            "state": self._display_state(now),
            "displayed": self.displayed,
            "peak_displayed": self.peak_displayed,
            "absorbed_window": self.absorbed_window(now),
            "absorbed_total": self.absorbed_total,
            "refreshes": self.refreshes_window(now),
            "out_of_view": self.out_of_view,
            "proven": self.proven,
            "conviction": self.conviction(now),
            "stage": self.stage(now),
            "since_refill": round(self.vol_since_refill) if self.proven else 0,
            "refill_age": round(now - self.last_refill_t, 1) if self.proven and self.last_refill_t is not None else None,
            # a verdict is history the moment size is sitting at the level again
            "last_verdict": self.last_verdict[0] if self.last_verdict and self.displayed <= 0 else None,
            "last_verdict_age": round(now - self.last_verdict[1], 1) if self.last_verdict and self.displayed <= 0 else None,
        }
