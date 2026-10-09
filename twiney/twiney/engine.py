"""TWINEY engine: pure market-data state machine.

Every input carries its own timestamp, so the same engine drives live data,
JSONL replay and tests identically. The engine never talks to IBKR; it returns
slot commands ("depth_on"/"depth_off") which the market-data adapter executes.
"""

from . import board, options, orderflow
import logging
import threading
import time
from collections import deque

from . import narrative, ps60
from .studies import is_rth

from .book import ASK, BID, Book
from .conviction import ACTIVE, FADING, GONE, SLUG, STALE, PullBook, stage_words
from .flow import FLOW_LABELS, FlowBook
from .levels import BUILDING, GONE_PENDING, RELOAD, LevelTracker, WATCHING
from .prices import fmt_price, price_key, tick_size
from .ranking import allocate, distances, rank
from .tape import MID, Tape, classify, BUY, SELL
from .dark import DarkBook, is_dark

log = logging.getLogger("twiney.engine")

L1_FIELDS = ("bid", "ask", "last", "bid_size", "ask_size", "last_size", "volume",
             "high", "low", "close", "open")

ALERT_LABELS = ("RELOAD BUYER DETECTED", "RELOAD SELLER DETECTED", "RELOAD BUYER BACK", "RELOAD SELLER BACK", "CLEANED UP", "PULLED")
PS60_LABELS = ("REMOUNT", "REJECTION")

BAR_SECONDS = 60
def _k(n):
    """The ladder's own rounding, spoken: 800 -> '800', 5,900 -> '5.9k', 12,600 -> '13k'."""
    n = int(round(n))
    if n < 1000:
        return str(n)
    if n < 10000:
        v = round(n / 1000, 1)
        return f"{v:g}k"
    return f"{int(round(n / 1000))}k"


MAX_BARS = 2400  # ~6 trading days of 1-minute bars, enough for 60-minute candles
MEMORY_SECONDS = 900   # how long the price-level memory (traded volume by price) looks back
MARK_MINUTES = 400     # absorption bubbles kept for the chart



def options_ny_off(t):
    """Seconds to add to a UTC time to get New York wall time."""
    from .ps60 import ny_offset
    return ny_offset(t)


class _StudyView:
    """What the chart studies read of a symbol, copied: the maths runs on this, never on the live state."""
    def price(self):
        return self._px


class SymbolState:
    def __init__(self, play, cfg):
        self.play = play
        self.symbol = play["symbol"]
        self.hist_ver = 0       # bumps when history arrives, so the page knows to fetch it again (coalesced: see Engine._hist_bump)
        self.hist_dirty = False
        self.hist_bump_t = -1e9
        self.daily_vol = {}     # day start -> shares traded (daily bars from IBKR carry volume)
        self.l1 = {k: None for k in L1_FIELDS}
        self.l1_t = None
        self.q_t = None          # last time IBKR's quote stream moved the bid / ask
        self.sv = 0              # STREAM: bumps on every print / book change / quote: the page's live channel sends then
        self.tight_since = None  # since when the NBBO has been tighter than the depth book's inside (None = it isn't)
        self.tight_last = 0.0
        self.depth_active = False
        self.contract = None     # IBKR contract details once resolved: min_tick, con_id, long_name
        self.depth_since = None
        self.depth_t = None
        self.tape_t = None
        self.book = None
        self.tape = Tape(cfg["tape"])
        self.trackers = {}
        self.resync_until = 0.0
        self.resets = 0
        self.rejected_until = 0.0
        self.last_error = None
        self.retired = None     # {"reason", "t", "price"} once the play's stop or target is hit
        self.invalidation_armed = True  # after Reactivate, wait for price to get back inside stop/target first
        self.bars = {}          # minute start -> [o, h, l, c, v, buy_v, sell_v]
        self.daily = {}         # day start -> [o, h, l, c] from IBKR daily bars (ATR)
        # the chart studies' own IBKR histories (Gas + ATR, Airspace, Unvisited highs / lows): native bars so the
        # 30 / 60 minute moving averages and samples match TradingView's (60-minute candles = two 30s from 9:30). bar start -> [o, h, l, c, v]
        self.m30 = {}           # 30 minutes, regular session, 1 year (the CONT odds sample)
        self.m5x = {}           # 5 minutes WITH extended hours, 3 days, kept up to date (premarket / after hours / 9:30 open)
        self.m5 = {}            # 5 minutes, the chart's session, 2 months: the 5 / 15 minute charts' long MAs
        self.study_ver = 0
        self.remounts = set()   # (level, kind, t) already called
        self.sizes = {ASK: {}, BID: {}}   # last aggregated size per price on each side (voice call-outs)
        self.big = {ASK: {}, BID: {}}     # price_key -> [times big size has shown up here, peak, showing now]
        self.big_shares = None            # per-symbol override of ladder.big_shares
        self.foot = {}          # minute -> {price_key: [bought at ask, sold into bid]} (footprint chart)
        self.voice_last = {}    # (side, price_key, kind) -> t of the last call-out
        self.remount_last = {}  # (level, kind) -> t of the last call (cooldown)
        self.remount_check_t = 0.0
        self.memory = deque()   # (t, price_key, price, aggressor side, size) for the level memory
        self.mem_sums = {}      # (price_key, side) -> shares in the memory window, kept as prints come and go
        self.trap_mem = deque() # the same prints for the trapped-traders window
        self.trap_sums = {}     # (price_key, side) -> [shares, price x shares, price]
        # the whole session: who paid up / hit at every price since the open (for TRAPPED LONGS / SHORTS on the day),
        # and the session's high / low with the time they printed
        self.day_sums = {}      # (price_key, side) -> [shares, price x shares, price]
        self.day_key = None
        self.day_hi = None      # (price, t)
        self.day_lo = None
        self.marks = {}         # (minute, price_key, side) -> [price, absorbed shares]
        self.quotes = deque(maxlen=64)   # (t, bid, ask) as the best bid / offer changed: prints are read against it
        self.voice_pending = {}          # (side, price_key) -> size that left, waiting to see if it traded
        self.flow_marks = deque()        # big option prints on this name: where the stock was when each one hit
        from .pace import PaceBook
        self.pacebook = PaceBook()       # PACE OF TAPE: 5-second buckets of the tape (speed against its own normal)
        self.pace = None
        from .story import Story
        self.storybook = Story()         # PS60 STORY: the running story, newest first
        self.story = None
        self.consumed = deque(maxlen=20) # (t, price, side): reloaders that got cleaned up (the story's "consumed")
        self.pulled = deque(maxlen=20)   # (t, price, side): reloaders that PULLED (left, not cleaned up)
        self.dark = DarkBook()           # DARK POOL prints: large off-exchange trades and where dark volume keeps printing
        self.rflow_said = {}             # (strike, cp, expiry) -> when REPEAT FLOW was last called on it
        self.l1_volume = None            # IBKR's cumulative day volume (symbols without a tape)
        self.l1_last_raw = None          # IBKR's quote-stream last, kept even while the tape sets the price
        self.pulls = PullBook(cfg.get("ladder", {}))   # per price: of the size that left, what traded vs vanished
        self.absorb_hist = {}            # (side, price_key) -> [price, shares absorbed at a watched level today, last t, verdict, was proven]

    def bar_update(self, t, price, size=0.0, side=None):
        m = int(t // BAR_SECONDS) * BAR_SECONDS
        if self.bars and m < max(self.bars):
            self._late = getattr(self, "_late", 0) + 1      # a late print into a finished minute: rebuild the cache
        b = self.bars.get(m)
        if b is None:
            b = self.bars[m] = [price, price, price, price, 0.0, 0.0, 0.0]
            if len(self.bars) > MAX_BARS:
                for k in sorted(self.bars)[:len(self.bars) - MAX_BARS]:
                    del self.bars[k]
        else:
            b[1] = max(b[1], price)
            b[2] = min(b[2], price)
            b[3] = price
        b[4] += size
        if side == "buy":
            b[5] += size
        elif side == "sell":
            b[6] += size

    def bar_list(self, limit=None):
        """Bars as lists. The finished minutes are built once and kept (they don't change unless history lands:
        hist_ver); only the minute still forming is rebuilt on every call."""
        keys = sorted(self.bars)
        if not keys:
            return []
        done_key = (len(keys), keys[-2] if len(keys) > 1 else None, self.hist_ver, getattr(self, "_late", 0))
        if getattr(self, "_done_key", None) != done_key:
            self._done = [[k] + [round(x, 4) for x in self.bars[k]] for k in keys[:-1]]
            self._done_key = done_key
        out = self._done + [[keys[-1]] + [round(x, 4) for x in self.bars[keys[-1]]]]
        return out[-limit:] if limit else out

    def price(self):
        last = self.l1["last"]
        if last:
            return last
        bid, ask = self.l1["bid"], self.l1["ask"]
        if bid and ask:
            return (bid + ask) / 2.0
        return None

    def bbo(self):
        if self.book is not None and self.book.synced:
            b, a = self.book.best(BID), self.book.best(ASK)
            # a depth book that went quiet while the quote stream moved on is a frozen book: the quote is the truth
            # (otherwise every print after a silent depth stall is read on the wrong side)
            lb, la = self.l1["bid"], self.l1["ask"]
            if (lb and la and lb < la and self.q_t is not None and self.depth_t is not None
                    and self.q_t - self.depth_t > 5.0 and (b, a) != (lb, la)):
                return lb, la
            # IBKR's consolidated quote (the NBBO) tighter than the depth book for more than a second: the book is
            # missing the venue that holds the inside. The NBBO is the inside, the book still gives the rest
            if self.tight_since is not None and self.tight_last - self.tight_since >= 1.0 and lb and la:
                return max(b, lb), min(a, la)
            return b, a
        return self.l1["bid"], self.l1["ask"]

    def inside_check(self, t):
        """Is the NBBO tighter than the depth book's inside, and since when (a lagging quote is not: one second)."""
        bk, lb, la = self.book, self.l1["bid"], self.l1["ask"]
        tight = False
        if bk is not None and bk.synced and lb and la and lb < la and self.q_t is not None and t - self.q_t < 30.0:
            b, a = bk.best(BID), bk.best(ASK)
            if b is not None and a is not None and lb < a and la > b:      # never a quote crossing the book
                tight = lb > b + 1e-9 or la < a - 1e-9
        if tight:
            if self.tight_since is None:
                self.tight_since = t
            self.tight_last = t
        else:
            self.tight_since = None

    def note_quote(self, t):
        self.inside_check(t)
        b, a = self.bbo()
        if not self.quotes or self.quotes[-1][1:] != (b, a):
            self.quotes.append((t, b, a))

    def aggressor(self, price, t, window=0.3):
        """Who was in a rush. The tape and the book are separate IBKR streams: the book can already show the level
        gone when the print that took it arrives. So a print that reads 'mid' against the quote now is read against
        the quotes of the last moment; a locked / crossed quote is skipped for the last clean one."""
        bid, ask = self.bbo()
        locked = lambda b, a: b is not None and a is not None and b >= a
        if locked(bid, ask):
            # a locked / crossed quote says nothing: read the print against the last CLEAN quote of the last 10 s
            # (older is not the market any more), skipping half-updated quotes that lived under 50 ms
            q = list(self.quotes)
            for i in range(len(q) - 1, -1, -1):
                qt, b, a = q[i]
                if t - qt > 10.0:
                    break
                lived = (q[i + 1][0] if i + 1 < len(q) else t) - qt
                if lived < 0.05 or locked(b, a):
                    continue
                return classify(price, b, a)
            return MID
        side = classify(price, bid, ask)
        through = (ask is not None and price > ask + 1e-9) or (bid is not None and price < bid - 1e-9)
        if side != MID and not through:
            return side                           # at the offer or at the bid of the market right now: plain
        if through:
            # the print is OUTSIDE the market now: the quote moved before the print reached us (the tape and the
            # book are separate streams; in a sell-off the quote is already lower). Read it against the quote it
            # traded IN, the last one of the past second that held it: a sell at the old bid is a sell, never a
            # buy over the new offer
            for qt, b, a in reversed(self.quotes):
                if t - qt > max(window, 1.0):
                    break
                if locked(b, a) or b is None or a is None:
                    continue
                if b - 1e-9 <= price <= a + 1e-9:
                    return classify(price, b, a)
            # no quote held it: the tick rule, against the print before it (lower = hit, higher = lifted)
            prev = self.tape.last() if getattr(self, "tape", None) is not None else None
            if prev is not None:
                if price < prev["price"] - 1e-9:
                    return SELL
                if price > prev["price"] + 1e-9:
                    return BUY
                if prev["side"] in (BUY, SELL):
                    return prev["side"]
            return side if side != MID else MID
        for qt, b, a in reversed(self.quotes):   # the quote may have just moved: the last moment's quotes only
            if t - qt > window:
                break
            if locked(b, a):
                continue
            s2 = classify(price, b, a)
            if s2 != MID:
                return s2
        return MID


class Engine:
    def __init__(self, plays, cfg, recorder=None):
        self.cfg = cfg
        self.plays = [p for p in plays]
        self.recorder = recorder
        self.lock = threading.RLock()
        self.price_evt = threading.Event()     # set on every price update: the desk's own stops check at once
        self.och_seen = {}                # underlying -> (the contract on the OPTION CHART, when the page last asked)
        self.study_async = False          # True on the desk (live / practice / replay): studies worked out off the lock
        self._study_thread = None
        self._study_stop = threading.Event()
        self.syms = {p["symbol"]: SymbolState(p, cfg) for p in plays}
        self.slots = {}  # symbol -> time the slot was assigned
        n = cfg["depth"]["slots"]
        self.slot_order = [None] * n      # fixed screen position of each depth symbol
        self.slot_changes = [None] * n    # last change per position, for the "replaced" banner
        self._slot_last = [None] * n
        self.pinned = set()
        self.auto_rotate = True
        self._slot_cmds = []
        # read-only view of the account (orders are placed in TWS, never here)
        self.orders = {}        # key -> order dict (pending + recently finished)
        self.positions = {}
        self.opt_fills = []
        self.opt_chain = {}       # symbol -> {expiries, strikes, mult, con_id, source, t}
        self.opt_quotes = {}      # option key -> {bid, ask, last, t} (chain rows on watch + positions)
        self.opt_bars = {}        # option key -> {minute: [o, h, l, c, v, buy_v, sell_v]} (the OPTION CHART: the contract's mid)
        self.opt_prints = {}      # option key -> deque of [t, price, contracts, "buy" / "sell" / None] (OPTION T&S)
        self.opt_vol = {}         # option key -> IBKR's cumulative day volume (volume bars from its changes)
        self.opt_watch = {}       # symbol -> {expiry, right, keys[]}: the chain rows the page is looking at
        self.jlog_path = None     # recordings/desk.log: one JSON line per connection / order / fill / error event
        from .scorecard import Scorecard
        self.score = Scorecard(None, cfg.get("score") or {})   # THE DESK SCORE: every directional call, judged 5 / 15 min later
        self._jlog = None
        self.opt_positions = {}   # option key -> {symbol, expiry, strike, right, mult, qty, avg_cost, bid, ask, last}     # (account, symbol) -> {"qty", "avg_cost"}
        self.fills = {}         # exec id -> fill dict
        self.commissions = {}   # exec id -> commission ($)
        self.pos_t = {}         # symbol -> when the broker last reported its position
        self.fill_t = {}        # symbol -> when its last fill arrived
        self.start_pos = {}     # symbol -> shares held at the start of the day (from a settled position report)
        self.mdt_by_sym = {}    # symbol -> IBKR market data type (1 live, 3 delayed...)
        self.account_seen = False
        self.trader = None      # set by run_twiney when order entry is enabled
        self.bigmoney = None    # 30-day memory of big option prints (run_twiney gives it a file)
        self.sim_broker = None  # demo-mode fill simulator, if any
        self.plays_path = None  # where to save levels added from the chart
        self.replay = None      # replay control block when replaying a recording
        self.trainer = None     # REPLAY TRAINING (twiney.training.Trainer) while replaying with the desk up
        self.calib_path = None  # live only: recordings/inst_calib.jsonl, every CHILD ORDERS detection on the real tape
        self.storyline_path = None   # recordings/storylines.jsonl: every turn of the storyline (the lean, attempts, the day's regime)
        self.grades = {}        # alert key -> "good" | "bad" (trader's verdict on a call)
        self.voice = deque(maxlen=60)   # spoken call-outs: big size added / pulled / hit
        self.desk = None        # recording desk (REC / markers / screenshots), set by run_twiney
        self.flow = FlowBook(cfg.get("flow", {"min_premium": 250000, "min_prints": 2, "otm_pct": 3.0, "max_dte": 30,
                                              "window_minutes": 10, "repeat_minutes": 20}))
        self.flow_scope = cfg.get("quantdata", {}).get("scope", "all")
        self.flow_alerts = cfg.get("flow", {}).get("alerts", "watchlist")
        # your alerts: a price to hit, option flow arriving, a big equity print - on any ticker you watch
        self.user_alerts = []
        self.alerts_path = None
        self._alert_seq = 0
        self.remove_listeners = []
        self.equity = deque(maxlen=400)              # big equity prints (lit / dark), newest first
        self.urg = {}                                # (symbol, strike, cp, expiry) -> prints bought at the ask, recent
        self.urg_said = {}
        self.urgent_keys = set()
        self.urg_hist = deque(maxlen=6000)          # every urgent-type print of the session (the ticker search)
        self.scan_said = {}                         # (symbol, side) -> when the market-wide FLOW WATCH last called it
        self.equity_status = {"last_ok": None, "last_print": None, "detail": ""}
        self.marks_list = []    # markers seen while replaying a recording
        self.notes_list = []    # journal notes seen while replaying
        self.grades_path = None
        self.alerts = deque(maxlen=300)
        self.messages = deque(maxlen=80)
        self.listeners = []
        self.play_listeners = []   # called with a new play (typed-in ticker) so the feed subscribes it
        self.focus = None
        self.focus_pinned = False
        self.connection = {"state": "DISCONNECTED", "since": None, "detail": "",
                           "market_data_type": None}
        self.data_t = None      # last market data tick of any kind (the MKT light)
        self.data_problem = ""  # IBKR's reason for no data (subscriptions), shown on the MKT light
        self.flow_status = {"source": "off", "state": "off", "detail": "", "last_ok": None, "last_print": None}   # the OPT light
        self.started = None
        self.last_t = 0.0

    # ---- plumbing ------------------------------------------------------------

    def dump_state(self, rec, t):
        from .desk import dump_state
        dump_state(self, rec, t)

    LOGGED_EVENTS = ("conn", "order", "order_modify", "order_cancel", "fill", "error", "contract", "flip", "setup", "reverse")

    def _rec(self, event):
        if self.recorder is not None:
            self.recorder.write(event)
        if event.get("ev") == "alert" and (self.cfg.get("score") or {}).get("enabled", True):
            try:
                st = self.syms.get(event.get("symbol"))
                if st is not None:
                    atr = (st.__dict__.get("_story_atr") or {}).get("v") or st.play.get("atr")
                    self.score.note(event, event.get("t") or self.last_t, st.price(), atr)
            except Exception:
                log.exception("scorecard note")
        if self.jlog_path and event.get("ev") in self.LOGGED_EVENTS:
            # a structured log line per operational event (never credentials: none pass through here)
            try:
                import json as _json
                if self._jlog is None:
                    self._jlog = open(self.jlog_path, "a", encoding="utf-8")
                self._jlog.write(_json.dumps(event, default=str) + "\n")
                self._jlog.flush()
            except Exception:
                pass

    def _clock(self, t):
        if self.started is None:
            self.started = t
        if t > self.last_t:
            self.last_t = t

    def _st(self, symbol):
        return self.syms.get(symbol)

    def _spoken_names(self):
        """What the voice calls each stock on the desk: your names (SETTINGS > Voice), the name directory, else IBKR's company name."""
        from .names import parse_user, spoken
        user = parse_user((self.cfg.get("speech") or {}).get("names", ""))
        return {sym: spoken(sym, (st.contract or {}).get("long_name", ""), user) for sym, st in list(self.syms.items())}

    def _emit(self, st, tracker, label, t):
        final = label in ("CLEANED UP", "PULLED") and tracker.verdict_info
        if label.startswith("RELOAD") and tracker.back:
            label = "RELOAD BUYER BACK" if tracker.side == BID else "RELOAD SELLER BACK"
        alert = {
            "t": t,
            "symbol": st.symbol,
            "label": label,
            "price": fmt_price(tracker.price),
            "side": "ask" if tracker.side == ASK else "bid",
            "role": tracker.role,
            # a RELOAD call carries the evidence that confirmed it (the window); a verdict the whole episode
            "absorbed": round(final["absorbed"] if final else tracker.absorbed_window(t)),
            "refreshes": final["refreshes"] if final else tracker.refreshes_window(t),
            # exactly what the ladder row shows at that price right now
            "showing": round(st.book.size_at(tracker.side, tracker.price)) if st.book is not None else round(tracker.displayed),
            # the most the screen ever showed at that price: what you could see, against what really traded there
            "peak_shown": round(tracker.peak_displayed),
        }
        alert["dollars"] = round(alert["absorbed"] * float(tracker.price))
        alert["episodes"] = len(tracker.episodes)
        alert["absorbed_all"] = round(tracker.absorbed_all + tracker.absorbed_total)
        if tracker.back and label.startswith("RELOAD"):
            alert["back"] = dict(tracker.back)
        if label == "CLEANED UP":
            st.consumed.append((t, float(tracker.price), alert["side"], alert["absorbed_all"]))
        elif label == "PULLED":
            st.pulled.append((t, float(tracker.price), alert["side"]))
        if final:
            alert["size_before_gone"] = round(final["size_before_gone"])
            ah = st.absorb_hist.get((alert["side"], tracker.key))
            if ah is not None:
                ah[3] = label
        elif label.startswith("RELOAD"):
            # a proven reloader earns the row its long memory (an auto level that was only "likely" does not)
            ah = st.absorb_hist.setdefault((alert["side"], tracker.key), [tracker.price, 0.0, t, None, False])
            ah[4] = True
        alert["text"] = narrative.alert_text(alert, st.play)
        alert["key"] = f"{round(t, 2)}|{st.symbol}|{label}|{alert['price']}"
        self.alerts.appendleft(alert)
        self._rec(dict(alert, ev="alert"))
        for fn in self.listeners:
            try:
                fn(alert)
            except Exception:  # a broken listener must never stop the feed
                pass

    def _judge(self, st, t):
        return st.book is not None and st.book.synced and t >= st.resync_until

    # ---- inputs --------------------------------------------------------------

    def on_l1(self, symbol, field, value, t):
        try:
            return self._on_l1(symbol, field, value, t)
        finally:
            self.price_evt.set()          # after the update is in (the lock is released): stops on it are checked now

    def _on_l1(self, symbol, field, value, t):
        with self.lock:
            st = self._st(symbol)
            if st is None or field not in st.l1:
                return
            self._clock(t)
            self._rec({"ev": "l1", "t": t, "sym": symbol, "f": field, "v": value})
            self.data_t = t
            if field == "last":
                st.l1_last_raw = value
            if field == "last" and st.depth_active and st.tape_t is not None and t - st.tape_t < 10:
                # this symbol has a tape: the price IS the last print, the same print the candle is built from.
                # IBKR's separate quote stream can lag or lead the tape by a moment; it never moves the price here,
                # so the candle and the price can't disagree
                st.l1_t = t
                return
            st.l1[field] = value      # None = IBKR says there is no bid / offer right now
            st.l1_t = t
            st.sv += 1
            if field == "last" and value:
                self._check_price_alerts(symbol, value, t)
            if field in ("bid", "ask"):
                st.q_t = t
                st.note_quote(t)
            tape_dead = st.tape_t is None or t - st.tape_t >= 10
            if field == "last" and value and (not st.depth_active or tape_dead):
                st.bar_update(t, value)  # no tape (or it went quiet): the quote's last price keeps the chart moving
            if field == "volume" and value is not None:
                # no tape on this symbol: the day volume's increase is this minute's volume (charts, VWAP, daily)
                if st.l1_volume is not None and value > st.l1_volume and not st.depth_active and st.l1["last"]:
                    st.bar_update(t, st.l1["last"], value - st.l1_volume)
                st.l1_volume = value

    def on_depth(self, symbol, position, operation, side, price, size, market_maker, t):
        with self.lock:
            st = self._st(symbol)
            if st is None:
                return
            self._clock(t)
            self._rec({"ev": "depth", "t": t, "sym": symbol, "pos": position, "op": operation,
                       "side": side, "px": price, "sz": size, "mm": market_maker})
            if st.book is None:
                return  # stale update for a slot that was already released
            st.book.apply(position, operation, side, price, size, market_maker)
            st.sv += 1
            st.depth_t = t
            st.note_quote(t)
            self._voice_sizes(st, side, t)
            self._track_big(st, side, t)
            if self.sim_broker is not None:
                self.sim_broker.on_market(symbol, t)
            judge = self._judge(st, t)
            for tr in list(st.trackers.values()):
                if tr.side != side:
                    continue  # the other side is re-checked on the next tick()
                label = tr.on_book(st.book, t, judge=judge)
                if label:
                    self._emit(st, tr, label, t)
            if judge:
                self._auto_levels(st, t)

    def _clock_check(self, t, xt):
        """This PC's clock against IBKR's: over the last ~300 prints the smallest (arrival - IBKR time) is the clock
        difference (plus a little network time). More than 1.5 s either way is said once every 10 minutes: candles
        still follow IBKR's time, but the chart's clock, countdowns and 'ago' read this PC's."""
        win = self.__dict__.setdefault("_skew", deque(maxlen=300))
        win.append(t - xt)
        if len(win) < 50:
            return
        off = min(win)                     # IBKR time is whole seconds: the smallest gap is the true difference
        self.clock_offset = round(off, 2)
        if (off > 1.5 or off < -1.5) and t - getattr(self, "_skew_said", -1e9) > 600:
            self._skew_said = t
            self._message("warn", f"This PC's clock is about {abs(off):.1f} s {'ahead of' if off > 0 else 'behind'} IBKR's — "
                                  f"candles follow IBKR's time; sync the PC clock (Windows: Settings, Time & language, Sync now)", t)

    OFF_EXCHANGE = ("FINRA", "ADF", "TRF", "OTC")      # dark pools / internalisers: they print between the quotes by design

    def _book_check(self, st, price, t, exchange=""):
        """BOOK CHECK: the tape is the truth. Prints landing OUTSIDE the depth book's best bid / ask (more than a tick
        through it), print after print, mean the book is missing levels or out of step (a missed delete, a lost
        update): the LEVEL II would be showing a market that is not there. Then it is said once and IBKR is asked for
        the book again (the adapter re-subscribes when st.resub_depth is set)."""
        book = st.book
        if book is None or not book.synced or t < st.resync_until:
            return
        if str(exchange or "").upper() in self.OFF_EXCHANGE:
            return
        b, a = book.best(BID), book.best(ASK)
        if b is None or a is None:
            return
        tk = tick_size(price, st.symbol)
        win = st.__dict__.setdefault("_bookchk", deque())
        outside = price > a + tk + 1e-9 or price < b - tk - 1e-9
        # in regular hours a liquid name trades AT its bid / ask: a book many ticks wide with the prints landing in
        # the gap is a book missing its inside levels (after hours a wide market is normal: not judged)
        gap = (a - b) > 3 * tk + 1e-9 and b + tk / 2 < price < a - tk / 2 and is_rth(t)
        # running counts: a busy tape puts thousands of prints in 30 s, so nothing here walks the window
        cnt = st.__dict__.setdefault("_bookcnt", [0, 0])
        win.append((t, outside, gap))
        cnt[0] += outside; cnt[1] += gap
        while win and t - win[0][0] > 30.0:
            _t0, o0, g0 = win.popleft()
            cnt[0] -= o0; cnt[1] -= g0
        out, ins = cnt
        prints_bad = len(win) >= 20 and (out >= 0.3 * len(win) or ins >= 0.8 * len(win))
        # the quote tighter than the book: asked again ONCE. If it stays that way the depth feed simply lacks the venue
        # at the inside (a subscription), and the quote stands in for the inside (bbo) without asking again and again
        nb = (st.tight_since is not None and st.tight_last - st.tight_since >= 5.0 and is_rth(t)
              and not st.__dict__.get("_nb_asked"))
        if (prints_bad or nb) and t - getattr(st, "book_bad_t", -1e9) > 60.0:
            st.book_bad_t = t
            n = st.__dict__.get("_book_asks", 0)
            if n >= 3:                      # asked three times: it is the feed, not a glitch. Say so once, stop asking
                if not st.__dict__.get("_book_gave_up"):
                    st._book_gave_up = True
                    self._message("warn", f"{st.symbol}: IBKR's depth keeps missing levels at the inside — the quote is used for the best "
                                          f"bid / offer; check your depth subscriptions (Nasdaq TotalView, NYSE / Cboe depth)", t, st.symbol)
                win.clear(); cnt[0] = cnt[1] = 0
                return
            st._book_asks = n + 1
            if nb and not prints_bad:
                st._nb_asked = True
            st.resub_depth = True
            lb, la = st.l1["bid"], st.l1["ask"]
            why = (f"{out} of the last {len(win)} prints outside its {fmt_price(b)} x {fmt_price(a)}" if len(win) >= 20 and out >= 0.3 * len(win) else
                   f"its {fmt_price(b)} x {fmt_price(a)} is {round((a - b) / tk)} ticks wide and {ins} of the last {len(win)} prints traded inside it"
                   if len(win) >= 20 and ins >= 0.8 * len(win) else
                   f"its {fmt_price(b)} x {fmt_price(a)} is wider than the quote {fmt_price(lb)} x {fmt_price(la)} for {round(st.tight_last - st.tight_since)} s")
            self._message("warn", f"{st.symbol}: LEVEL II out of step with the tape ({why}) — asking IBKR for the book again", t, st.symbol)
            win.clear(); cnt[0] = cnt[1] = 0

    def on_depth_reset(self, symbol, t, reason="317"):
        with self.lock:
            st = self._st(symbol)
            if st is None:
                return
            st.sizes = {ASK: {}, BID: {}}
            self._clock(t)
            self._rec({"ev": "reset", "t": t, "sym": symbol, "reason": reason})
            st.resets += 1
            st.resync_until = t + self.cfg["reload"]["resync_grace_seconds"]
            if st.book is not None:
                st.book.reset()
            st.pulls.reset()
            for side in (ASK, BID):          # nothing is "showing" until the book is rebuilt: not a new appearance
                for rec in st.big[side].values():
                    if rec[2]:
                        rec[2] = False; rec[3] = None
            st.voice_pending.clear()
            for tr in st.trackers.values():
                tr.on_resync()
            self._message("warn", f"{symbol}: depth book reset ({reason}); resyncing", t, symbol)

    def on_print(self, symbol, price, size, exchange, t, conditions="", xt=None):
        try:
            return self._on_print(symbol, price, size, exchange, t, conditions, xt)
        finally:
            self.price_evt.set()          # after the update is in (the lock is released): stops on it are checked now

    def _on_print(self, symbol, price, size, exchange, t, conditions="", xt=None):
        """One trade from IBKR's tape. ``t`` is when it reached this PC; ``xt`` is IBKR's own time for it (whole
        seconds). The candles are cut on IBKR's time, so a minute's candle holds exactly IBKR's minute even when this
        PC's clock is a little off or the print arrives a moment after the minute turned."""
        with self.lock:
            st = self._st(symbol)
            if st is None or price is None or price <= 0 or not size or size <= 0:
                return
            # a confirmed trade counts ONCE: a print re-delivered (a reconnect, a restarted feed) is ignored
            pg = st.__dict__.get("_pguard")
            if pg is None:
                from .ladderbasket import PrintGuard
                pg = st._pguard = PrintGuard()
            if not pg.first_time(t, xt, price, size, exchange):
                self.dup_prints = getattr(self, "dup_prints", 0) + 1
                return
            self._clock(t)
            self._rec({"ev": "print", "t": t, "sym": symbol, "px": price, "sz": size,
                       "ex": exchange, "cond": conditions, "xt": xt})
            bt = t
            if xt and abs(t - xt) < 120.0:
                bt = xt + 0.5                       # IBKR's second (the middle of it): the candle IBKR puts it in
                self._clock_check(t, xt)
            self.data_t = t
            bid, ask = st.bbo()
            self._book_check(st, price, t, exchange)
            rec = st.tape.add(t, price, size, bid, ask, exchange, side=st.aggressor(price, t))
            self._dark_print(st, t, price, size, exchange, bid, ask)
            st.sv += 1
            st.pacebook.add(t, price, size, rec["side"])
            st.tape_t = t
            st.l1["last"] = price
            st.pulls.on_print(rec["side"], price, size)
            st.bar_update(bt, price, size, rec["side"])
            self._check_price_alerts(symbol, price, t)
            k = price_key(price)
            if rec["side"] in ("buy", "sell"):
                fmin = int(bt // BAR_SECONDS) * BAR_SECONDS
                st.__dict__.get("_foot_cache", {}).pop(fmin, None)   # a print into a minute rebuilds its footprint
                fm = st.foot.setdefault(fmin, {})
                cell = fm.setdefault(k, [price, 0.0, 0.0])
                cell[1 if rec["side"] == "buy" else 2] += size
                if len(st.foot) > 240:
                    del st.foot[min(st.foot)]
            self._visit(st, k, rec["side"], size, t)
            # THE BASKET: every confirmed trade at this price today, added ONCE, here, as it arrives:
            # [total, bought, sold, sequence]. The page shows these numbers (never its own count) and animates the new part
            bday = ps60.ny_day(t)
            if st.__dict__.get("basket_day") != bday:
                st.basket_day, st.basket = bday, {}
            bk = st.__dict__.setdefault("basket", {}).get(k)
            if bk is None:
                bk = st.basket[k] = [0.0, 0.0, 0.0, 0]
            bk[0] += size; bk[3] += 1
            if rec["side"] == "buy":
                bk[1] += size
            elif rec["side"] == "sell":
                bk[2] += size
            item = (t, k, price, rec["side"], size)
            st.memory.append(item)
            key = (k, rec["side"])
            st.mem_sums[key] = st.mem_sums.get(key, 0.0) + size
            st.trap_mem.append(item)
            dk = ps60.ny_day(t)
            if st.day_key != dk:                      # a new session: the day's story starts over
                st.day_key, st.day_sums, st.day_hi, st.day_lo = dk, {}, None, None
            if rec["side"] in ("buy", "sell"):
                ds = st.day_sums.get(key)
                if ds is None:
                    st.day_sums[key] = [size, price * size, price]
                else:
                    ds[0] += size; ds[1] += price * size
            self._break_trap(st, t, price, size, rec["side"], dk)
            # high / low of day = the REGULAR session only (9:30-4:00 New York), like the daily candle on every
            # chart package: a premarket print never sets the day's low
            if self.connection["state"] == "DEMO" or ps60.is_rth(t):
                if st.day_hi is None or price > st.day_hi[0]:
                    st.day_hi = (price, t)
                if st.day_lo is None or price < st.day_lo[0]:
                    st.day_lo = (price, t)
            ts = st.trap_sums.get(key)
            if ts is None:
                st.trap_sums[key] = [size, price * size, price]
            else:
                ts[0] += size; ts[1] += price * size
            self._prune_memory(st, t)
            if self.sim_broker is not None:
                self.sim_broker.on_market(symbol, t)
            marked = False
            for tr in list(st.trackers.values()):
                before = tr.absorbed_total
                label = tr.on_print(price, size, rec["side"], t, st.book)
                if not marked and tr.absorbed_total > before:
                    marked = True  # this print traded into a watched level's resting size
                    side = "ask" if tr.side == ASK else "bid"
                    mk = (int(t // BAR_SECONDS) * BAR_SECONDS, k, side)
                    st.marks.setdefault(mk, [price, 0.0])[1] += size
                    # the ladder's long memory: what was absorbed at this price today, however long ago
                    ah = st.absorb_hist.get((side, tr.key))
                    if ah is None:
                        st.absorb_hist[(side, tr.key)] = [tr.price, size, t, None, tr.proven]
                    else:
                        ah[1] += size; ah[2] = t; ah[3] = None; ah[4] = ah[4] or tr.proven
                    if len(st.marks) > 3000:          # a day of bubbles at most (MARK_MINUTES)
                        cut = t - MARK_MINUTES * 60
                        for key in [key for key in st.marks if key[0] < cut]:
                            del st.marks[key]
                if label:
                    self._emit(st, tr, label, t)

    # ---- the history cache: what the live desk saw, kept for the practice desk --------------------------------------

    def save_history(self, folder, t=None, only=None):
        """Write each stock's real histories (daily, the last five days of minutes, the extended-hours and 5-minute
        bars) to folder/SYM.json. The practice feed seeds from them, so practice AAPL trades at AAPL's price, ATR and
        levels. Live sessions only: the practice feed's own bars are never saved."""
        import json
        import os
        if self.connection.get("state") != "CONNECTED":
            return 0
        t = t if t is not None else (self.last_t or time.time())
        n = 0
        with self.lock:
            items = [(sym, st) for sym, st in self.syms.items() if only is None or sym in only]
        for sym, st in items:
            if len(st.daily) < 20:
                continue
            cut = t - 6 * 86400
            data = {"symbol": sym, "saved": t, "last": st.price(),
                    "daily": [[k] + list(st.daily[k][:4]) + [st.daily_vol.get(k) or 0] for k in sorted(st.daily)[-400:]],
                    "bars": [[k] + [round(x, 4) for x in st.bars[k][:5]] for k in sorted(st.bars) if k >= cut],
                    "m5x": [[k] + list(st.m5x[k][:5]) for k in sorted(st.m5x) if k >= cut],
                    "m5": [[k] + list(st.m5[k][:5]) for k in sorted(st.m5)[-2400:]]}
            try:
                tmp = os.path.join(folder, f"{sym}.json.tmp")
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(data, f)
                os.replace(tmp, os.path.join(folder, f"{sym}.json"))
                n += 1
            except OSError as exc:
                log.warning("history cache %s: %s", sym, exc)
        return n

    @staticmethod
    def load_history(folder, sym):
        """The cached real history for one stock, or None."""
        import json
        import os
        path = os.path.join(folder, f"{sym}.json")
        if not os.path.isfile(path):
            return None
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            return d if d.get("daily") else None
        except (OSError, ValueError):
            return None

    HIST_BUMP_SECONDS = 2.0

    def _hist_bump(self, st):
        """History arrived. The page refetches a symbol's whole history whenever hist_ver changes, so one bump per
        bar (a 5-day minute history is 1,950 bars, ten years of daily 2,500) had the page re-downloading megabytes
        every poll for minutes while the chart showed one bar. The version moves at most once every couple of
        seconds; the snapshot flushes the last change (Engine._hist_flush)."""
        now = self.last_t or time.time()
        st.hist_dirty = True
        if now - st.hist_bump_t >= self.HIST_BUMP_SECONDS:
            st.hist_ver += 1
            st.hist_bump_t = now
            st.hist_dirty = False

    def _hist_flush(self, st, t):
        if st.hist_dirty and t - st.hist_bump_t >= self.HIST_BUMP_SECONDS:
            st.hist_ver += 1
            st.hist_bump_t = t
            st.hist_dirty = False

    def on_daily_bar(self, symbol, t0, o, h, l, c, v=None):
        """Historical daily bar (ATR / measured potential)."""
        with self.lock:
            st = self._st(symbol)
            if st is None or None in (o, h, l, c):
                return
            self._rec({"ev": "dbar", "t": self.last_t or t0, "sym": symbol, "t0": t0, "o": o, "h": h, "l": l, "c": c, "v": v})
            st.daily[t0] = [o, h, l, c]
            if v is not None:
                st.daily_vol[t0] = float(v)
            self._hist_bump(st)
            if len(st.daily) > 3000:          # ~12 years: the Daily / Weekly 200s settle exactly like TradingView's
                for k in sorted(st.daily)[:len(st.daily) - 3000]:
                    del st.daily[k]
                    st.daily_vol.pop(k, None)

    STUDY_CAPS = {"m30": 4400, "m5x": 900, "m5": 4200}

    def on_study_bar(self, symbol, kind, t0, o, h, l, c, v=None):
        """A native IBKR bar for the chart studies: kind "m30" / "m5x" / "m5" (see SymbolState)."""
        if kind not in self.STUDY_CAPS:
            return
        with self.lock:
            st = self._st(symbol)
            if st is None or None in (o, h, l, c):
                return
            self._rec({"ev": "sbar", "t": self.last_t or t0, "sym": symbol, "k": kind, "t0": t0, "o": o, "h": h, "l": l, "c": c, "v": v})
            store = getattr(st, kind)
            store[t0] = [o, h, l, c, float(v or 0.0)]
            cap = self.STUDY_CAPS[kind]
            if len(store) > cap:
                for k in sorted(store)[:len(store) - cap]:
                    del store[k]
            st.study_ver += 1
            if kind != "m5x":            # the chart's longer history changed: the page fetches it again
                self._hist_bump(st)

    def _pace_levels(self, st, sc_v, t=None):
        """The prices the PACE reads against: your lines on the chart and the KEY LEVELS (the same list the ladder,
        the level watch, the voice and the story use: one system, one name per price)."""
        out = [(float(lv["price"]), lv["label"]) for lv in st._user_levels_cache if lv.get("price")]
        for L in self.key_levels(st, t if t is not None else self.last_t):
            if L["code"] not in ("HOD", "LOD"):           # today's high / low move with price: not a level to break
                out.append((L["price"], L["name"]))
        return out

    # the KEY LEVELS: short tag for the ladder, the name on the screen, the words the voice says
    KEY_NAMES = {"PDH": ("PDH", "PRIOR DAY HIGH", "yesterday's high"), "PDL": ("PDL", "PRIOR DAY LOW", "yesterday's low"),
                 "PDC": ("PDC", "PRIOR DAY CLOSE", "yesterday's close"), "PDO": ("PDO", "PRIOR DAY OPEN", "yesterday's open"),
                 "PMH": ("PMH", "PREMARKET HIGH", "the premarket high"), "PML": ("PML", "PREMARKET LOW", "the premarket low"),
                 "PMC": ("PMC", "PREMARKET CLOSE", "the premarket close"), "AHH": ("AHH", "AFTER-HOURS HIGH", "the after hours high"),
                 "AHL": ("AHL", "AFTER-HOURS LOW", "the after hours low"), "AHC": ("AHC", "AFTER-HOURS CLOSE", "the after hours close"),
                 "OPEN": ("OPN", "TODAY'S OPEN", "today's open"), "VWAP": ("VW", "VWAP", "VWAP"), "D50": ("50D", "50-DAY", "the 50 day"),
                 "HOD": ("HOD", "HIGH OF DAY", "the high of day"), "LOD": ("LOD", "LOW OF DAY", "the low of day")}

    # the colour each level has ON THE CHART (SETTINGS > Chart studies), so the ladder reads like the chart
    KEY_COLOR_KEYS = {"PDH": "col_pd", "PDL": "col_pd", "PDO": "col_pd", "PDC": "col_pdc", "PMH": "col_pm", "PML": "col_pm",
                      "PMC": "col_pm", "AHH": "col_ah", "AHL": "col_ah", "AHC": "col_ah", "OPEN": "col_open", "HOD": "col_hl",
                      "LOD": "col_hl", "OSUP": "col_old_supply", "ODEM": "col_old_demand", "EARNH": "col_earnings",
                      "EARNL": "col_earnings", "BOX": "col_box", "PH": "col_uv_high", "PL": "col_uv_low"}
    KEY_FIXED = {"VWAP": "#e8a0ff", "D50": "#1fc6fc", "ZONE": "#e8b931"}       # the chart's VWAP line, its 50 SMA, your zones

    def _key_color(self, code, sc):
        from . import studies
        if code in self.KEY_FIXED:
            return self.KEY_FIXED[code]
        if code in self.KEY_COLOR_KEYS:
            return studies.K(sc, self.KEY_COLOR_KEYS[code])
        if code.endswith("REJ"):
            return studies.K(sc, "col_reject")
        if code.endswith("BNC"):
            return studies.K(sc, "col_bounce")
        return "#9aa4b4"

    def key_levels(self, st, t):
        """The levels that matter today, from the DAILY chart and the session, worked out once a second:
        prior day open / high / low / close, the premarket and after-hours high / low / close (1-minute bars, locked),
        today's open, VWAP, the 50-day, high / low of day, the DAILY reject and bounce (AIRSPACE) and the prior daily
        highs and lows price has not been back to (prior resistance / support). Levels a tick apart are one level."""
        memo = st.__dict__.setdefault("_keylv", {})
        if memo.get("t") is not None and t - memo["t"] < 1.0:
            return memo["v"]
        from . import studies
        out = []

        sc = self.cfg.get("studies") or {}

        def add(code, price, name=None, say=None, short=None):
            if price is None or price <= 0:
                return
            sh, nm, sy = self.KEY_NAMES.get(code, (short or code, name or code, say or (name or code).lower()))
            out.append({"price": round(float(price), 4), "code": code, "short": short or sh, "name": name or nm, "say": say or sy,
                        "color": self._key_color(code, sc)})
        try:
            done = [k for k in sorted(st.daily) if studies.day_key(k + 43200) < studies.day_key(t)]
            if done:
                o, h, l, c = st.daily[done[-1]][:4]
                add("PDO", o); add("PDH", h); add("PDL", l); add("PDC", c)
            sess = studies.session_levels(st, t)
            add("PMH", sess.get("pmh")); add("PML", sess.get("pml")); add("PMC", sess.get("pmc"))
            add("AHH", sess.get("ahh")); add("AHL", sess.get("ahl")); add("AHC", sess.get("ahc"))
            add("OPEN", sess.get("open"))
            refs = self._refs(st, t)
            add("VWAP", refs.get("vwap")); add("D50", refs.get("sma50"))
            if st.day_hi:
                add("HOD", st.day_hi[0])
            if st.day_lo:
                add("LOD", st.day_lo[0])
            sv = ((st.__dict__.get("_studies") or {}).get("v")) or {}
            for L in (sv.get("air") or {}).get("lines") or []:
                lab = str(L.get("l") or "")
                if L.get("p") is not None and lab.startswith(("REJECT ", "BOUNCE ")):
                    rej = lab.startswith("REJECT")
                    tf = lab.split(" ")[1] if len(lab.split(" ")) > 1 else ""
                    tf = tf if tf in ("Daily", "Weekly", "Monthly") else ""
                    w = (tf + " " if tf else "") + ("reject" if rej else "bounce")
                    add(("D" if tf == "Daily" else tf[:1].upper() if tf else "") + ("REJ" if rej else "BNC"), L["p"], name=w.upper(),
                        say="the " + w.lower(), short=(tf[:1].upper() if tf else "") + ("R" if rej else "B"))
            for L in (sv.get("gas") or {}).get("lines") or []:
                lab = str(L.get("l") or "")
                if L.get("p") is None:
                    continue
                if lab.startswith(("EARN H", "EARN L")):
                    hi = lab.startswith("EARN H")
                    add("EARNH" if hi else "EARNL", L["p"], name="EARNINGS HIGH" if hi else "EARNINGS LOW",
                        say="the earnings high" if hi else "the earnings low", short="EH" if hi else "EL")
                elif lab.startswith(("BOX EDGE", "TIGHT BOX EDGE")):
                    add("BOX", L["p"], name="BOX EDGE", say="the box edge", short="BX")
            for z in (st.play or {}).get("zones") or []:
                try:
                    zl, zh = sorted((float(z[0]), float(z[1])))
                except (TypeError, ValueError, IndexError):
                    continue
                add("ZONE", zh, name=f"YOUR ZONE TOP {zl:.2f}-{zh:.2f}", say="the top of your zone", short="Z▲")
                add("ZONE", zl, name=f"YOUR ZONE BOTTOM {zl:.2f}-{zh:.2f}", say="the bottom of your zone", short="Z▼")
            for L in (sv.get("uv") or {}).get("lines") or []:
                lab = str(L.get("l") or "")
                if L.get("p") is None or " @ " not in lab:
                    continue
                hi = " high @" in lab
                day = lab.split(" ")[0]
                add("PH" if hi else "PL", L["p"], name=f"PRIOR {'HIGH' if hi else 'LOW'} {day}",
                    say=f"the prior {'high' if hi else 'low'} from {day}", short="PH" if hi else "PL")
            for L in (sv.get("gas") or {}).get("lines") or []:
                lab = str(L.get("l") or "")
                if L.get("p") is not None and lab.startswith(("old supply", "old demand")):
                    sup = lab.startswith("old supply")
                    add("OSUP" if sup else "ODEM", L["p"], name="LAST MONTH HIGH" if sup else "LAST MONTH LOW",
                        say="last month's high" if sup else "last month's low", short="MH" if sup else "ML")
        except Exception:
            log.exception("key levels %s", st.symbol)
        # one level per price (a tick apart): the names join, the first (most important) leads
        tk = tick_size(st.price() or 1.0, st.symbol)
        merged = []
        for L in out:
            same = next((m for m in merged if abs(m["price"] - L["price"]) < tk * 1.01), None)
            if same:
                if L["short"] not in same["short"].split("/"):
                    same["short"] += "/" + L["short"]; same["name"] += " / " + L["name"]; same["say"] += " and " + L["say"]
                    same["code"] = f"{same['code']}/{L['code']}"      # every level on the row keeps its code (PDH/PMH)
            else:
                merged.append(dict(L))
        memo.update(t=t, v=merged)
        return merged

    def _level_watch(self, st, t, last, tick):
        """REJECTED / BOUNCED / BUYERS TOOK / SELLERS TOOK at the key levels and your lines: a call, the voice, the
        story feed and the log, all with the tape and the reloaders read at that same level."""
        lc = self.cfg.get("levels") or {}
        if not lc.get("enabled", True):
            return
        from .levelwatch import LevelWatch
        lw = st.__dict__.get("_lw") or LevelWatch()
        st._lw = lw
        from . import studies as _stu
        pm_live = _stu.ny_secs(t) < 34200            # premarket still running: its high / low move with price, not levels yet
        lv = [{"price": L["price"], "name": L["name"], "say": L["say"], "code": L["code"]} for L in self.key_levels(st, t)
              if L["code"] not in ("HOD", "LOD") and not (pm_live and any(c in ("PMH", "PML", "PMC") for c in str(L["code"]).split("/")))]
        lv += [{"price": float(u["price"]), "name": u["label"], "say": "your " + u["label"].lower(), "code": "YOURS"}
               for u in (st._user_levels_cache or []) if u.get("price")]
        sv = ((st.__dict__.get("_studies") or {}).get("v")) or {}
        atr = ((sv.get("gas") or {}).get("y_atr")) or None
        close = self._last_close(st, t)
        for ev in lw.update(t, last, lv, tick, atr, lc, close):
            self._level_alert(st, ev, t)
        # THE FOLLOW-UP: 5-7 minutes after a level's back and forth, how it came out (defended / lost / reclaimed)
        if lc.get("followup", True):
            from .levelverdict import LevelFollowUp
            fu = st.__dict__.get("_lfu") or LevelFollowUp()
            st._lfu = fu
            for v in fu.update(t, last, lv, lc, tick, close):
                self._level_verdict(st, fu, v, t)

    @staticmethod
    def _last_close(st, t):
        """(t the candle ended, its close) for the last completed 1-minute candle: a level is taken on a close."""
        cur = int(t // BAR_SECONDS) * BAR_SECONDS
        ks = [k for k in st.bars if k < cur]
        if not ks:
            return None
        k = max(ks)
        return (k + BAR_SECONDS, st.bars[k][3])

    def _level_context(self, st, p, t, from_below):
        """What the rest of the desk sees at a level, in a few words each: the TAPE (who is stepping up, how fast),
        the BOOK at that price (size stacking or pulled, a reload buyer / seller), and the OPTION FLOW (short-dated
        calls / puts being hit, SOMEBODY KNOWS SOMETHING). Returns (spoken words, short text)."""
        words, short = [], []
        pc = st.pace or {}
        bp = pc.get("buy_pct")
        ctl, drift = pc.get("control"), pc.get("drift")
        from . import story as story_mod
        ln = story_mod.lean_side(st.storybook) if getattr(st, "storybook", None) is not None else 0
        if bp is not None and pc.get("bp_suspect"):
            who = "sellers" if ctl == "sellers" else "buyers"
            words.append(f"price printing {'lower' if ctl == 'sellers' else 'higher'}, {self._cents(abs(drift))} in fifteen seconds; {who} have it"); short.append(f"{who} have it · path")
        elif bp is not None and ln < 0 and ((bp >= 60 and ctl != "sellers") or ctl == "buyers"):
            words.append(story_mod.trying(st.storybook, "buyers")); short.append("buyers trying")
        elif bp is not None and ln > 0 and ((bp <= 40 and ctl != "buyers") or ctl == "sellers"):
            words.append(story_mod.trying(st.storybook, "sellers")); short.append("sellers trying")
        elif bp is not None:
            # the price path decides who is in control: a tape that keeps printing lower is sellers' whatever the
            # buy percentage says (buyers lifting offers that keep stepping down are getting run over)
            if ctl == "sellers" and bp >= 60:
                words.append(f"sellers in control, price down {self._cents(abs(drift))} in fifteen seconds; buyers lifting and getting run over"); short.append(f"sellers in control · −{abs(drift):.2f}")
            elif ctl == "buyers" and bp <= 40:
                words.append(f"buyers in control, price up {self._cents(abs(drift))} in fifteen seconds; sellers hitting and getting absorbed"); short.append(f"buyers in control · +{abs(drift):.2f}")
            elif bp >= 60:
                words.append(f"buyers stepping up, {bp} percent at the offer"); short.append(f"buyers {bp}%")
            elif bp <= 40:
                words.append(f"sellers stepping up, {100 - bp} percent at the bid"); short.append(f"sellers {100 - bp}%")
            else:
                words.append("two sided tape"); short.append(f"two-sided {bp}%")
        if pc.get("ratio"):
            # ONE speed read (PACE): "speeding up" only when it IS accelerating right now; fast but easing off says so
            acc = pc.get("accel")
            fast = pc["ratio"] >= 1.5 or (acc == "SPEEDING UP" and pc["ratio"] >= 1.2)
            if fast:
                words.append(f"tape speeding up, {pc['ratio']:.1f} times normal" if acc == "SPEEDING UP"
                             else f"tape fast but slowing, {pc['ratio']:.1f} times normal" if acc == "SLOWING"
                             else f"tape running fast, {pc['ratio']:.1f} times normal")
            elif pc.get("state") == "DRYING UP":            # really dry: a third of its normal pace or less
                words.append("tape drying up")
            elif pc.get("state") == "SLOW":
                words.append("tape slowing")
            short.append(f"pace x{pc['ratio']}")
        # the book at that price: the side price runs into (an offer over a level it comes up to, a bid under one it
        # comes down to)
        tk = tick_size(p, st.symbol)
        side = ASK if from_below else BID
        who = "seller" if side == ASK else "buyer"
        size = st.book.size_at(side, p, band_ticks=1) if st.book else 0
        ps = st.pulls.pullstack(side, price_key(p), t, float(self.cfg.get("ladder", {}).get("stack_seconds", 60)))
        rl = next((tr for tr in st.trackers.values() if tr.side == side and (tr.state == RELOAD or tr.proven) and abs(tr.price - p) <= 3 * tk), None)
        if rl:
            words.append(f"a reload {who} at {fmt_price(rl.price)}, refilled {rl.refreshes_window(t)} times")
            short.append(f"reload {who} {fmt_price(rl.price)}")
        elif ps and ps[0] >= max(ps[1], 1) and ps[0] >= 300:
            words.append(f"{who}s stacking {narrative.shares(ps[0])} shares there"); short.append(f"{who}s stacking {ps[0]:,}")
        elif ps and ps[1] > ps[0] and ps[1] >= 300:
            words.append(f"the {who}s pulled {narrative.shares(ps[1])} shares there"); short.append(f"{who}s pulled {ps[1]:,}")
        elif size:
            short.append(f"{size:,.0f} showing")
        # the option flow behind it
        kc, kp = self._knows(st, BID, t), self._knows(st, ASK, t)
        k = kc if kc.get("knows") else kp if kp.get("knows") else None
        st._ctx_flow = None                       # the receipt for any flow this context mentions (the level call carries it)
        if k:
            words.append(f"and somebody knows something: {'calls' if k is kc else 'puts'} being hit, {narrative.say_dollars(k.get('dollars') or 0)}")
            short.append(f"KNOWS {'calls' if k is kc else 'puts'} {narrative.say_dollars(k.get('dollars') or 0)}")
            st._ctx_flow = self._receipt(st.symbol, "C" if k is kc else "P", k.get("ids"),
                                         f"{k.get('max_dte')} days or less, out of the money, bought at the ask, last {k.get('window_minutes')} min")
        else:
            mx = float((self.cfg.get("story") or {}).get("flow_max_dte", 7))
            cutoff = t - 15 * 60
            pick = lambda cp: [m for m in st.flow_marks if m["t"] >= cutoff and m.get("side") == "ask" and m.get("cp") == cp
                               and m.get("dte") is not None and m["dte"] <= mx]
            cm, pm = pick("C"), pick("P")
            calls, puts = sum(m.get("prem") or 0 for m in cm), sum(m.get("prem") or 0 for m in pm)
            if max(calls, puts) >= 100000:
                big = "calls" if calls >= puts else "puts"
                st._ctx_flow = self._receipt(st.symbol, "C" if calls >= puts else "P", [m.get("id") for m in (cm if calls >= puts else pm)],
                                             f"{mx:g} days or less, bought at the ask, last 15 min")
                words.append(f"{big} flow behind it, {narrative.say_dollars(max(calls, puts))} in 15 minutes")
                short.append(f"{big} {narrative.say_dollars(max(calls, puts))}")
        return ", ".join(words), " · ".join(short)

    def _safe_view(self, fn, st, t, what):
        """A read-only panel that fails shows nothing for that refresh (logged once a minute) — it never takes the whole
        desk down with it (positions, orders and the ladder keep updating)."""
        try:
            return fn(st, t)
        except Exception as exc:
            last = self.__dict__.setdefault("_view_err_t", {})
            if t - last.get(what, -1e9) > 60:
                last[what] = t
                log.exception("%s view failed on %s", what, st.symbol)
                self._message("warn", f"{st.symbol}: the {what} read failed ({exc}) — skipped, everything else keeps running", t, st.symbol)
            return None

    def _inst_view(self, st, t):
        """INSTITUTIONAL FOOTPRINTS (inst.py): the program read, this slot's volume against its normal for the time of
        day, fund-style reloaders (same refill size) and a side walking the price. Once every few seconds; the new
        ones are called."""
        ic = self.cfg.get("inst") or {}
        if not ic.get("enabled", True):
            return None
        memo = st.__dict__.setdefault("_inst", {})
        if memo.get("t") is not None and t - memo["t"] < float(ic.get("every_seconds", 5)):
            return memo.get("v")
        memo["t"] = t
        from . import inst
        from .ps60 import ny_offset
        try:
            off = ny_offset(t)
            dk = int((t + off) // 86400)
            if memo.get("curve_k") != (dk, len(getattr(st, "m5", {}) or {})):
                memo["curve_k"] = (dk, len(getattr(st, "m5", {}) or {}))
                memo["curve"] = inst.volume_curve(getattr(st, "m5", {}) or {}, t, off)
            curve = memo.get("curve") or {}
            slots = inst.today_slots(st.bars, t, off, getattr(st, "_any_session", False))
            cur = inst.slot_of(t, off)
            memo["slots"] = slots
            vw = ((st.__dict__.get("_refs") or {}).get("v") or {}).get("vwap")
            # the market's own one-sided flow (QQQ / SPY when on the desk, else the other stocks): taken out first
            idx = [o for s2, o in self.syms.items() if s2 in ("QQQ", "SPY") and s2 != st.symbol]
            pool = idx or [o for s2, o in self.syms.items() if s2 != st.symbol]
            mkt = inst.market_shares([(o.__dict__.get("_inst") or {}).get("slots") or [] for o in pool])
            prog = inst.program(slots, cur, vw, ic, mkt)
            tod = None
            done = [r for r in slots if r[0] < cur]
            if done and curve.get(done[-1][0]):
                tod = {"x": round(done[-1][1] / curve[done[-1][0]], 2), "at": inst.hm(done[-1][0])}
            fund = inst.fund_reloads(list(st.trackers.values()), t, ic)
            bk = (st.__dict__.get("_rl_basket") or {}).get("rows") or {}
            walk = inst.walking([{"side": r["side"], "price": r["price"], "usd": round(r["shares"] * r["price"]), "first": r["first"]}
                                 for r in bk.values()], t, ic)
            flev = inst.fund_levels(list(st.trackers.values()), walk, list(st.dark.levels.values()), prog, ic)
            gd = inst.guides(prog, st.price(), vw, (t + off) % 86400, ic)
            # CHILD ORDERS: the same size again and again on one side at a steady clock, an algo working an order
            kids = inst.children(list(st.tape.prints), t, ic)
            if kids:
                kids["since"] = self._hm_t(kids["t0"])
                kids["sizes_set"] = set(kids.get("sizes") or [])
                self._calib(st, kids, t, memo)
            memo["kids"] = kids
            # a program on the other side of YOUR trade (shares, or a call = long / a put = short)
            mine = None
            try:
                q = int((self._position_view(st.symbol, st.price()) or {}).get("qty") or 0)
                if q:
                    mine = "long" if q > 0 else "short"
                else:
                    for p in self.opt_positions.values():
                        if p.get("symbol") == st.symbol and int(p.get("qty") or 0):
                            mine = "long" if (p.get("right") == "C") == (int(p["qty"]) > 0) else "short"
                            break
            except Exception:
                mine = None
            against = None
            if prog and mine and ((prog["side"] == "BUY") != (mine == "long")):
                against = (f"STEADY {'SELLING' if prog['side'] == 'SELL' else 'BUYING'} AGAINST YOUR {mine.upper()}: "
                           f"~{prog['part']}% of volume since {prog['since']}")
            if kids and mine and ((kids["side"] == "BUY") != (mine == "long")) and not against:
                against = (f"CHILD ORDERS AGAINST YOUR {mine.upper()}: {kids['n']} prints of {kids['size']} {'at the ask' if kids['side'] == 'BUY' else 'at the bid'} "
                           f"every {kids['every']}s since {kids['since']}")
            v = {"program": prog, "tod": tod, "fund": fund[:6], "walk": walk, "levels": flev[:8], "guides": gd, "against": against, "mine": mine,
                 "kids": {k: v_ for k, v_ in kids.items() if k != "sizes_set"} if kids else None}
        except Exception:
            log.exception("inst %s", st.symbol)
            v = None
        memo["v"] = v
        if v:
            self._inst_calls(st, v, t, ic)
        return v

    @staticmethod
    def _hm_t(t):
        from .ps60 import ny_offset
        sec = int((t + ny_offset(t)) % 86400)
        h, m = sec // 3600, (sec % 3600) // 60
        return f"{(h - 1) % 12 + 1}:{m:02d}"

    def _calib(self, st, kids, t, memo):
        """The CHILD ORDERS calibration log (live tape only): one line per detection as it grows, so the thresholds
        (size, clock, one-way share) can be tuned against what the real tape did."""
        if not self.calib_path or self.connection.get("state") != "CONNECTED":
            return
        key = (kids.get("side"), kids.get("size"), kids.get("t0"), kids.get("n"))
        if memo.get("calib_key") == key:
            return
        memo["calib_key"] = key
        row = {"t": round(t, 2), "symbol": st.symbol, "price": st.price()}
        row.update({k: v for k, v in kids.items() if k != "sizes_set" and isinstance(v, (int, float, str, list, type(None)))})
        try:
            import json as _json
            with open(self.calib_path, "a", encoding="utf-8") as f:
                f.write(_json.dumps(row, default=str) + "\n")
        except OSError:
            pass

    def _inst_calls(self, st, v, t, ic):
        said = st.__dict__.setdefault("_inst_said", {})
        rep = float(ic.get("repeat_seconds", 1200))
        calls = []
        kd = v.get("kids")
        if kd:
            who = "buyer" if kd["side"] == "BUY" else "seller"
            at = "at the ask" if kd["side"] == "BUY" else "at the bid"
            what = "CHILD ORDERS · BUY PROGRAM" if kd["side"] == "BUY" else "CHILD ORDERS · SELL PROGRAM"
            calls.append(((("KIDS", kd["side"])), what,
                          f"{what}: {kd['n']} prints of {kd['size']:,} {at} in {kd['minutes']:g} min, one every {kd['every']:g} s, "
                          f"{kd['one_way']}% one way · {kd['shares']:,} shares ≈${kd['usd']:,} since {kd['since']} · an algo working a {who}'s order",
                          f"Child orders. A {who} is working an order: {kd['n']} prints of {kd['size']} shares {at}, one every {kd['every']:g} seconds, "
                          f"since {kd['since']}. {kd['shares']:,} shares so far. Those prints look like nothing one at a time. That's the algo"))
        pg = v.get("program")
        if pg and pg["score"] >= float(ic.get("call_score", 70)):
            vv = pg.get("vs_vwap")
            vw = "" if vv is None else (f", {'buying' if pg['side'] == 'BUY' else 'selling'} {abs(vv) * 100:.0f} cents {'under' if vv < 0 else 'over'} VWAP" if abs(vv) >= 0.005 else ", at VWAP")
            what = "STEADY BUYING" if pg["side"] == "BUY" else "STEADY SELLING"
            calls.append((("PROG", pg["side"]), what,
                          f"{what} (program-like) · net {'buying' if pg['side'] == 'BUY' else 'selling'} in {pg['won']} of {pg['slots']} 5-min slots · ~{pg['part']}% of volume · since {pg['since']} · net {'bought' if pg['side'] == 'BUY' else 'sold'} ≈${pg['usd']:,}",
                          f"{st.symbol}. Steady {'buying' if pg['side'] == 'BUY' else 'selling'} against the market: {pg['won']} of the last {pg['slots']} five minute slots, about {pg['part']:.0f} percent of volume{vw}."))
        for f in v.get("levels") or []:
            if f["score"] < float(ic.get("fund_call", 70)):
                continue
            who = "BUYER" if f["side"] == "bid" else "SELLER"
            calls.append((("FUND", f["side"], round(f["price"], 2)), f"FUND {who}",
                          f"FUND {who} {fmt_price(f['price'])} · score {f['score']} · " + " · ".join(f["why"]),
                          f"{st.symbol}. Fund {who.lower()} at {fmt_price(f['price'])}, score {f['score']}. " + ", ".join(f["why"][:2]) + "."))
        wk = v.get("walk")
        if wk:
            dist = wk["dir"] == "down"
            calls.append((("WALK", wk["side"], wk["steps"][-1]), f"{wk['side']} WALKING {wk['dir'].upper()}",
                          f"{wk['side']} WALKING {'IT DOWN (distribution)' if dist else 'IT UP (accumulation)'} · " + " → ".join(str(fmt_price(p)) for p in wk["steps"]),
                          f"{st.symbol}. {'Seller walking it down' if dist else 'Buyer walking it up'}: {'selling' if dist else 'buying'} at " + ", then ".join(str(fmt_price(p)) for p in wk["steps"][-4:]) + (". Distribution." if dist else ". Accumulation.")))
        if v.get("against"):
            calls.append((("AGAINST", v["against"][:30]), "PROGRAM AGAINST YOU", v["against"], f"{st.symbol}. Warning. " + v["against"].lower().replace("~", "about ") + "."))
        gd = [g for g in (v.get("guides") or []) if g.startswith("Last hour")]
        if gd:
            calls.append((("LASTHOUR",), "INTO THE CLOSE", gd[0], f"{st.symbol}. {gd[0]}."))
        for key, label, text, words in calls:
            if t - said.get(key, -1e9) < (600.0 if key[0] == "AGAINST" else rep):
                continue
            said[key] = t
            alert = {"t": t, "symbol": st.symbol, "label": label, "price": fmt_price(st.price() or 0), "side": "bid" if "BUY" in label else "ask",
                     "role": "inst", "text": text, "words": words if ic.get("voice", True) else None}
            alert["key"] = f"{round(t, 2)}|{st.symbol}|{label}"
            self.alerts.appendleft(alert)
            self._rec(dict(alert, ev="alert"))
            self.log(st.symbol, text, t, kind="level")
            for fn in self.listeners:
                try:
                    fn(alert)
                except Exception:
                    pass

    def _dark_print(self, st, t, price, size, exchange, bid, ask):
        """DARK POOL: every print counts toward the day's volume; an off-exchange one goes into the dark book, and a
        very large one is called (the tab you are on says it)."""
        dc = self.cfg.get("dark") or {}
        if not dc.get("enabled", True):
            return
        db = st.dark
        if db.day is None or t - st.__dict__.get("_dark_dk_t", -1e9) > 60.0:
            st.__dict__["_dark_dk_t"] = t
            from . import studies
            dk = studies.day_key(t)
            if dk != db.day:
                db.reset(dk)
        db.count(size)
        if not is_dark(exchange):
            return
        vw = ((st.__dict__.get("_refs") or {}).get("v") or {}).get("vwap")
        rec = db.add(t, price, size, exchange, bid, ask, vw, dc)
        if rec is None or rec["usd"] < float(dc.get("alert_usd", 2000000)):
            return
        # not a stream of calls: one every couple of minutes per stock, unless this one is at least twice the last called
        lastc = st.__dict__.get("_dark_called")
        if lastc and t - lastc[0] < float(dc.get("call_gap_seconds", 120)) and rec["usd"] < 2 * lastc[1]:
            return
        st.__dict__["_dark_called"] = (t, rec["usd"])
        vv = rec["vs_vwap"]
        amt = (lambda x: f"${x:.2f}" if x >= 1 else f"{x * 100:.0f}¢")(abs(vv)) if vv is not None else ""
        vtxt = "" if vv is None else f" · {amt} {'over' if vv > 0 else 'under'} VWAP" if abs(vv) >= 0.005 else " · at VWAP"
        usd = rec["usd"]; m = f"${usd / 1e6:.1f}M" if usd >= 1e6 else f"${usd / 1e3:.0f}K"
        text = f"LARGE ORDER {m} · {int(size):,} @ {fmt_price(price)}" + (f" · {rec['at']}" if rec["at"] else "") + vtxt
        words = (f"{st.symbol}. Large order, {usd / 1e6:.1f} million dollars, {int(size):,} shares at {fmt_price(price)}"
                 + ("" if vv is None else f", {abs(vv) * 100:.0f} cents {'over' if vv > 0 else 'under'} VWAP" if abs(vv) >= 0.005 else ", at VWAP"))
        alert = {"t": t, "symbol": st.symbol, "label": "LARGE ORDER", "price": fmt_price(price), "side": "mid", "role": "dark",
                 "text": text, "words": words if dc.get("voice", True) else None, "usd": round(usd), "shares": int(size)}
        alert["key"] = f"{round(t, 2)}|{st.symbol}|DARK|{price}|{int(size)}"
        self.alerts.appendleft(alert)
        self._rec(dict(alert, ev="alert"))
        self.log(st.symbol, text, t, kind="level")
        for fn in self.listeners:
            try:
                fn(alert)
            except Exception:
                pass

    @staticmethod
    def _cents(d):
        c = int(round(d * 100))
        return f"{c} cents" if c < 100 else f"{d:.2f} dollars"

    def _level_alert(self, st, ev, t):
        kind, p = ev["kind"], ev["price"]
        from_below = ev.get("from") == "below"
        up = kind in ("BOUNCED", "BUYERS TOOK") or (kind in ("COMING INTO", "AT") and from_below)
        ctx_w, ctx_s = self._level_context(st, p, t, from_below)
        nm = ev["say"]
        last = ev.get("last")
        tk = tick_size(p, st.symbol)
        gap = (last - p) if last is not None else 0.0
        # AT: said exactly — on it, or how far under / over it price really is
        at_words = (f"At {nm}, {fmt_price(p)}" if abs(gap) < tk * 0.5
                    else f"Testing {nm}, {fmt_price(p)}. Price {fmt_price(last)}, {self._cents(abs(gap))} {'under' if gap < 0 else 'over'} it")
        head = {"COMING INTO": f"Coming into {nm}, {fmt_price(p)}, from {'below' if from_below else 'above'}" + (f". Price {fmt_price(last)}" if last is not None else ""),
                "AT": at_words,
                "REJECTED": f"Rejected at {nm}, {fmt_price(p)}. Sellers defending it, pulling off",
                "BOUNCED": f"Bounced off {nm}, {fmt_price(p)}. Buyers defending it, pulling off",
                "BUYERS TOOK": f"Closed over {nm}, {fmt_price(p)}. Buyers took it",
                "SELLERS TOOK": f"Closed under {nm}, {fmt_price(p)}. Sellers took it"}[kind]
        words = head + (". " + ctx_w[0].upper() + ctx_w[1:] if ctx_w else "")
        text = f"{kind} {ev['name']} {fmt_price(p)}" + (f" · price {fmt_price(last)}" if last is not None and abs(gap) >= tk * 0.5 else "") + (f" · {ctx_s}" if ctx_s else "")
        voice = (self.cfg.get("levels") or {}).get("voice", True)
        alert = {"t": t, "symbol": st.symbol, "label": kind, "price": fmt_price(p), "side": "bid" if not up else "ask",
                 "role": "level", "text": text, "words": f"{st.symbol}. {words}" if voice else None, "code": ev.get("code"),
                 "zone": ev.get("zone"), "last": last}
        if ctx_w and st.__dict__.get("_ctx_flow") and ("knows" in ctx_w or "flow behind" in ctx_w):
            alert["flow"] = st._ctx_flow
        alert["key"] = f"{round(t, 2)}|{st.symbol}|{kind}|{p}"
        self.alerts.appendleft(alert)
        self._rec(dict(alert, ev="alert"))
        self.log(st.symbol, text, t, kind="level")
        if st.__dict__.get("_lfu") is None:
            from .levelverdict import LevelFollowUp
            st._lfu = LevelFollowUp()
        st._lfu.note(ev, t)
        try:
            tone = "good" if kind in ("BOUNCED", "BUYERS TOOK") else "bad" if kind in ("REJECTED", "SELLERS TOOK") else "info"
            st.storybook.say("level", (kind, round(p, 4)), words + ".", tone, t, repeat=300.0)
        except Exception:
            pass
        for fn in self.listeners:
            try:
                fn(alert)
            except Exception:
                pass

    def _level_verdict(self, st, fu, v, t):
        """The follow-up call: how the back and forth at a level came out, in casual words (levelverdict)."""
        from .levelverdict import label
        tk = tick_size(v["price"], st.symbol)
        dist = self._cents(v["dist"]) if v["dist"] >= tk * 0.5 else "right on it"
        words = fu.words(v, v["say"], fmt_price(v["price"]), fmt_price(v["last"]), dist)
        lab = label(v)
        mins = max(1, round((t - v["t0"]) / 60.0)) if not v.get("rechecked") else None
        text = f"{lab} {v['name']} {fmt_price(v['price'])} · price {fmt_price(v['last'])} · after {v['n']} calls"
        voice = (self.cfg.get("levels") or {}).get("voice", True)
        good = (v["outcome"] in ("DEFENDED", "RECLAIMED") and v["from"] == "above") or v["outcome"] == "BROKE"
        bad = (v["outcome"] in ("DEFENDED", "RECLAIMED") and v["from"] == "below") or v["outcome"] == "LOST"
        alert = {"t": t, "symbol": st.symbol, "label": lab, "price": fmt_price(v["price"]), "side": "ask" if good else "bid",
                 "role": "level", "text": text, "words": f"{st.symbol}. {words}" if voice else None, "code": v.get("code"),
                 "zone": v.get("zone"), "last": v["last"], "followup": True}
        alert["key"] = f"{round(t, 2)}|{st.symbol}|FOLLOWUP|{v['price']}"
        self.alerts.appendleft(alert)
        self._rec(dict(alert, ev="alert"))
        self.log(st.symbol, text, t, kind="level")
        try:
            st.storybook.say("level", ("FOLLOWUP", round(v["price"], 4)), words + ".", "good" if good else "bad" if bad else "info", t, repeat=120.0)
        except Exception:
            pass
        for fn in self.listeners:
            try:
                fn(alert)
            except Exception:
                pass

    def _levels_tick(self, t):
        """The KEY LEVELS clock, twice a second, on its own (not tied to PACE: switching pace off never silences the
        level calls or the break traps): the levels a break is watched at, and REJECTED / BOUNCED / TOOK."""
        if t - getattr(self, "_levels_t", -1e9) < 0.5:
            return
        self._levels_t = t
        for sym, st in self.syms.items():
            last = st.price()
            if last is None:
                continue
            st._user_levels_cache = self._user_levels(st.play)
            try:
                self._break_trap_levels(st, t)
            except Exception:
                log.exception("break trap levels %s", sym)
            try:
                self._level_watch(st, t, last, tick_size(last, sym))
            except Exception:
                log.exception("level watch %s", sym)
            try:
                self._flip_watch(st, t)
            except Exception:
                log.exception("flip watch %s", sym)

    def _flip_watch(self, st, t):
        """FLIP (ladderbasket.FlipWatch): a defender's refill died and the other side's size took the price."""
        lc = self.cfg.get("ladder") or {}
        if st.book is None:
            return
        from .ladderbasket import FlipWatch, flip_words
        fw = st.__dict__.get("_flipw")
        if fw is None:
            fw = st._flipw = FlipWatch()
        trs = [("bid" if tr.side == BID else "ask", tr.price, tr.stage(t), tr.last_refill_t, tr.refill_seq,
                tr.proven or tr.gone_t is not None) for tr in st.trackers.values()]
        new = fw.update(t, trs, lambda side, p: st.book.size_at(BID if side == "bid" else ASK, p), lc)
        if not lc.get("basket_flip_alerts", True):
            return
        for side, price in new:
            if t - fw.said.get((side, price), -1e9) < 300:
                continue
            fw.said[(side, price)] = t
            who = "seller" if side == "ask" else "buyer"
            text = flip_words(fmt_price(price), who)
            alert = {"t": t, "symbol": st.symbol, "label": "FLIP", "price": fmt_price(price), "side": side,
                     "role": "flip", "text": f"FLIP at {narrative.px(price)}: {who} losing, {'buyers' if who == 'seller' else 'sellers'} taking over",
                     "words": f"{st.symbol}. Flip at {narrative.px(price)}. {'Seller' if who == 'seller' else 'Buyer'} losing, {'buyers' if who == 'seller' else 'sellers'} taking over.",
                     "key": f"{round(t, 2)}|{st.symbol}|FLIP|{price}"}
            self.alerts.appendleft(alert); self._rec(dict(alert, ev="alert")); self.log(st.symbol, text, t, kind="level")
            try:        # the PS60 STORY: the next chapter after a reloader is exhausted
                st.storybook.say("flip", (side, round(price, 4)), alert["text"] + ".", "good" if who == "seller" else "bad", t, repeat=300.0)
            except Exception:
                pass
            for fn in self.listeners:
                try:
                    fn(alert)
                except Exception:
                    pass

    def _pace_tick(self, t):
        """PACE OF TAPE for every stock, twice a second, browser open or not: speed against its own normal, and the
        calls at your levels (STALLING INTO / PRESSING / BREAKOUT WITH SPEED / BREAK WITHOUT SPEED, + FLOW)."""
        pc = self.cfg.get("pace") or {}
        if not pc.get("enabled", True) or t - getattr(self, "_pace_t", -1e9) < 0.5:
            return
        self._pace_t = t
        from . import pace as pace_mod
        for sym, st in self.syms.items():
            last = st.price()
            if last is None or not st.pacebook.b:
                st.pace = None
                continue
            st._user_levels_cache = self._user_levels(st.play)
            memo = st.__dict__.get("_studies") or {}
            levels = self._pace_levels(st, memo.get("v"), t) if pc.get("use_levels", True) else []
            # "+ FLOW" behind a break: the same prints as everywhere else: short-dated (story.flow_max_dte) and out of
            # the money. Far-dated or in-the-money size is not the bet on this move
            mx = float((self.cfg.get("story") or {}).get("flow_max_dte", 7))
            flow = [(m["t"], m["cp"], m.get("side"), m.get("prem") or 0.0, m.get("id")) for m in st.flow_marks
                    if m.get("dte") is not None and m["dte"] <= mx and m.get("spot")
                    and ((m["strike"] - m["spot"]) if m["cp"] == "C" else (m["spot"] - m["strike"])) / m["spot"] * 100.0 >= 0.5]
            try:
                knows = {"C": self._knows(st, BID, t), "P": self._knows(st, ASK, t)}    # SOMEBODY KNOWS SOMETHING: calls / puts
                p = pace_mod.read(st.pacebook, t, last, levels, tick_size(last, sym), pc, flow, knows)
            except Exception:
                log.exception("pace %s", sym)
                continue
            st.pace = p
            call = p.get("call")
            if call and p.get("level") and pc.get("alerts", True):
                rep_s = float(pc.get("repeat_seconds", 120))
                said = st.__dict__.setdefault("_pace_said", {})
                if call.startswith(("BREAKOUT", "BREAKDOWN")):
                    # one call per break of a level; the only second call allowed is the upgrade to WITH SPEED
                    # one call per break of a level PER DIRECTION (a breakout that comes straight back down is a new
                    # call: the failed break); the only second call allowed is WITHOUT -> WITH speed, same direction
                    # a level is its NAME (VWAP moves a cent every few seconds and is still VWAP)
                    nm = p["level"][1]
                    key = ("BREAK", "up" if call.startswith("BREAKOUT") else "down", nm)
                    prev = said.get(key)
                    fresh = prev is None or t - prev[0] >= rep_s
                    upgrade = prev is not None and not fresh and "WITHOUT" in prev[1] and "WITHOUT" not in call
                    # chop: price see-sawing over a level is one "broke without speed", not one every few seconds
                    chop = "WITHOUT" in call and t - (said.get(("CHOP", nm)) or (-1e9,))[0] < rep_s
                    if (fresh or upgrade) and not chop:
                        if "WITHOUT" in call:
                            said[("CHOP", nm)] = (t, call)
                        said[key] = (t, call)
                        self._pace_alert(st, p, t)
                else:
                    key = (call, p["level"][1])
                    if t - (said.get(key) or (-1e9,))[0] >= rep_s:
                        said[key] = (t, call)
                        self._pace_alert(st, p, t)

    def _pace_alert(self, st, p, t):
        lvl = p["level"]
        call = p["call"]
        good = "WITH SPEED" in call
        text = (f"{call}: {lvl[1]} at {fmt_price(lvl[0])}" if call == "SPEED + FLOW" else f"{call} {lvl[1]} {fmt_price(lvl[0])}") \
            + f" · tape ×{p['ratio']} its normal pace" + (f" · {p['flow']}" if p.get("flow") else "") \
            + (f" · buyers {p['buy_pct']}%" if p.get("buy_pct") is not None else "") \
            + (f" · not confirmed until a candle closes {p['needs_close']} it" if p.get("needs_close") else "")
        flow_on = bool(p.get("flow")) and p["flow"].startswith("+") and "WITHOUT" not in call and call != "SPEED + FLOW"
        alert = {"t": t, "symbol": st.symbol, "label": call + (" + FLOW" if flow_on else ""),
                 "price": fmt_price(lvl[0]), "side": "ask" if call.startswith(("BREAKOUT", "PRESSING")) or (call == "SPEED + FLOW" and "calls" in lvl[1]) else "bid",
                 "role": "pace", "text": text, "words": f"{st.symbol}. {p['words']}" if (self.cfg.get("pace") or {}).get("voice", True) else None}
        fr = p.get("flow_ref")
        if fr and p.get("flow") and fr.get("ids"):
            alert["flow"] = self._receipt(st.symbol, fr["cp"], fr["ids"], "short-dated, out of the money, bought at the ask")
        alert["key"] = f"{round(t, 2)}|{st.symbol}|{call}|{lvl[0]}"
        self.alerts.appendleft(alert)
        self._rec(dict(alert, ev="alert"))
        self.log(st.symbol, text, t, kind="level")
        for fn in self.listeners:
            try:
                fn(alert)
            except Exception:
                pass

    def _ps60_reload(self, price, sym=None):
        """Does a reload at this price count for PS60? Every real reload does (repeated execution at one price, how much
        traded, whether price goes through once it is gone). SETTINGS > PS60 story can limit it to whole / half dollars."""
        if not (self.cfg.get("story") or {}).get("whole_half_reloads_only", True):
            return True
        from .story import qualifies
        return qualifies(price, tick_size(price, sym) if price else 0.01)

    def _refs(self, st, t):
        """The two lines every desk watches, for the LEVEL II and the T&S (updated once a second):
        VWAP the way prop desks run it: the regular session's volume-weighted average price, starting fresh at 9:30
        (typical price (high + low + close) / 3 of each minute x its volume, the same as the chart's VWAP line).
        Before the open it is the premarket's (PM VWAP) until 9:30 starts the real one.
        The daily 50-day SMA (today's bar included, like the daily chart draws it)."""
        memo = st.__dict__.setdefault("_refs", {})
        if memo.get("t") is not None and t - memo["t"] < 1.0:
            return memo["v"]
        from . import studies
        st._any_session = self.connection["state"] == "DEMO"
        v = {}
        try:
            mins = studies.rth_minutes_today(st, t)
            kind = "VWAP"
            if not mins:                      # before the open: today's premarket minutes
                dk = studies.day_key(t)
                mins = [[m] + list(st.bars[m][:5]) for m in sorted(st.bars) if studies.day_key(m) == dk]
                kind = "PM VWAP"
            pv = vol = 0.0
            for b in mins:
                if b[5]:
                    pv += (b[2] + b[3] + b[4]) / 3.0 * b[5]
                    vol += b[5]
            if vol > 0:
                v["vwap"] = round(pv / vol, 4)
                v["vwap_label"] = kind
            dc = st.__dict__.get("_story_daily") or {}
            rows = dc.get("rows")
            if rows is None:
                rows, _live = studies.daily_series(st, t)
            closes = [r[4] for r in rows]
            px_now = st.price()
            if closes and px_now and studies.day_key(rows[-1][0] + 43200) == studies.day_key(t):
                closes[-1] = px_now                    # today's close IS the price now (the cached rows are up to 15 s old)
            if len(closes) >= 50:
                v["sma50"] = round(sum(closes[-50:]) / 50.0, 4)
        except Exception:
            log.exception("refs %s", st.symbol)
        last = st.price()
        for k in ("vwap", "sma50"):
            if v.get(k) and last:
                v[k + "_dist"] = round(last - v[k], 4)
        memo.update(t=t, v=v)
        return v

    def _story_tick(self, t):
        """The PS60 STORY for every stock with a price, once a second, browser open or not."""
        sc = self.cfg.get("story") or {}
        if not sc.get("enabled", True) or t - getattr(self, "_story_t", -1e9) < 1.0:
            return
        self._story_t = t
        for sym, st in self.syms.items():
            if st.price() is None:
                st.story = None
                continue
            try:
                st.story = self._story(st, t, sc)
            except Exception:
                log.exception("story %s", sym)
                continue
            if sc.get("alerts", True):
                for s_ in st.story.get("said") or []:
                    self._story_alert(st, s_, t, sc)

    def _story(self, st, t, sc):
        from . import story as story_mod
        from . import studies
        last = st.price()
        tick = tick_size(last, st.symbol)
        st._any_session = self.connection["state"] == "DEMO"
        dc = st.__dict__.setdefault("_story_daily", {})
        if dc.get("k") != (int(t // 15), st.hist_ver):       # the daily bars and their highs / lows: every 15 s
            dc["k"] = (int(t // 15), st.hist_ver)
            dc["rows"], dc["live"] = studies.daily_series(st, t)
            dc["pts"] = story_mod.structure_points(dc["rows"], dc["live"], t)
            try:                                                   # the premarket / after-hours highs and lows, today's open
                dc["sess"] = studies.session_levels(st, t)
                dc["pts"] += story_mod.session_points(dc["sess"])
            except Exception:
                log.exception("story session levels %s", st.symbol)
                dc["sess"] = None
        drows, live = dc["rows"], dc["live"]
        ac = st.__dict__.setdefault("_story_atr", {})
        if ac.get("k") != (int(t // 60), st.hist_ver, st.play.get("atr")):     # the daily ATR: once a minute
            ac["k"] = (int(t // 60), st.hist_ver, st.play.get("atr"))
            ac["v"] = st.play.get("atr") or self._atr(st, st.bar_list(MAX_BARS))
        atr = ac["v"]
        ctx = story_mod.daily_context(drows, live, last)
        # Dan's MA pack on the daily and the 60-minute (the chart's numbers): once a minute is plenty, they barely move
        mc = st.__dict__.setdefault("_story_mas", {})
        if mc.get("k") != (int(t // 60), st.hist_ver, st.study_ver):
            mc["k"] = (int(t // 60), st.hist_ver, st.study_ver)
            try:
                h60 = studies.h60_series(st, t, self.cfg.get("studies") or {})
                dcl, hcl = [r[4] for r in drows], [r[4] for r in h60]
                dpack = studies.ma_pack(dcl, use_bb=False)
                hpack = studies.ma_pack(hcl, use_bb=False) if len(h60) >= 5 else []
                mc["v"] = story_mod.ma_stack_points(dpack, hpack)
                # the framework reads the slope: the packs one bar back (the 60m 5 / 10 rising or falling)
                mc["dprev"] = studies.ma_pack(dcl[:-1], use_bb=False) if len(dcl) > 6 else []
                mc["hprev"] = studies.ma_pack(hcl[:-1], use_bb=False) if len(hcl) > 6 else []
                mc["dpack"], mc["hpack"] = dpack, hpack
                mc["mas"] = story_mod.key_mas(dpack, hpack, sc)
                mc["h60"] = h60[-3:]
            except Exception:
                log.exception("story MAs %s", st.symbol)
                mc["v"], mc["mas"], mc["dpack"], mc["hpack"], mc["dprev"], mc["hprev"], mc["h60"] = [], [], [], [], [], [], []
        points = story_mod.ps60_points(st.play, getattr(st, "sneaky_auto", None)) + dc["pts"] + story_mod.ma_points(ctx) + mc["v"]
        zones = story_mod.user_zones(st.play)                 # your zones only: no automatic support / resistance
        conf = story_mod.confluence(points, zones, last, atr, tick, sc)
        prints = list(self.flow.by_symbol.get(st.symbol, ()))
        fr = story_mod.flow_read(prints, t, sc, [r[4] for r in drows[-5:]])
        reloads = []
        for tr in st.trackers.values():
            if not (tr.state == RELOAD or tr.proven) or not self._ps60_reload(tr.price, st.symbol):
                continue
            stage = tr.stage(t)
            if stage not in (ACTIVE, FADING):
                continue
            reloads.append({"price": float(tr.price), "side": "bid" if tr.side == BID else "ask", "stage": stage,
                            "absorbed": round(tr.absorbed_all + tr.absorbed_total)})
        consumed = [{"price": c[1], "side": c[2], "absorbed": c[3] if len(c) > 3 else 0} for c in st.consumed
                    if t - c[0] <= 60 and self._ps60_reload(c[1], st.symbol)]
        cur = int(t // BAR_SECONDS) * BAR_SECONDS
        mins = [[k] + list(st.bars[k][:5]) for k in sorted(st.bars)[-12:] if k <= cur]
        se_state = ((getattr(st, "_ps60_cache", None) or (0, {}))[1] or {}).get("state")
        try:
            traps = self._break_trap_pane(st, t)
        except Exception:
            traps = None
        out = story_mod.build(st.storybook, t, last, tick, atr, st.play, se_state, ctx, points, zones, conf, fr, st.pace,
                              reloads, consumed, mins, sc, traps=traps, market=self._market_read(st, t),
                              pulled={(c[1], c[2]): c[0] for c in getattr(st, "pulled", ()) if t - c[0] <= 60},
                              fw=story_mod.ma_framework(mc.get("dpack"), mc.get("dprev"), mc.get("hpack"), mc.get("hprev"), last, sc),
                              mas=mc.get("mas"), trade=self._trade_read(st, last), h60=mc.get("h60"), drows=drows, live=live, sess=dc.get("sess"))
        out["feed"] = list(st.storybook.feed)[:30]
        out["near"] = round(story_mod.near_dist(last, atr, tick, sc), 4)
        out["atr"] = atr
        out["draw_zones"] = bool(sc.get("draw_zones", True))
        return out

    def _trade_read(self, st, last):
        """The trade you're in on this stock, for the story: the shares and / or its options, which way, the entry,
        the working stop / target, the open P&L."""
        try:
            pos = self._position_view(st.symbol, last)
            opts = [self._opt_view(p) for p in list(self.opt_positions.values()) if p.get("symbol") == st.symbol and p.get("qty")]
        except Exception:
            return None
        if not pos and not opts:
            return None
        pend = self._pending(st.symbol)
        stop = next((o.get("aux") or o.get("lmt") for o in pend if o.get("role") == "stop"), None) or st.play.get("stop")
        tgt = next((o.get("lmt") for o in pend if o.get("role") in ("target", "partial")), None) or st.play.get("target")
        bits, pnl, dir_ = [], 0.0, None
        if pos:
            dir_ = "long" if pos["qty"] > 0 else "short"
            bits.append(f"{'long' if pos['qty'] > 0 else 'short'} {abs(pos['qty']):,} {st.symbol} from {fmt_price(pos['avg_cost'])}")
            pnl += pos.get("pnl") or 0.0
        for o in opts:
            d_ = "long" if (o["right"] == "C") == (o["qty"] > 0) else "short"
            dir_ = dir_ or d_
            bits.append(f"{abs(o['qty'])} {o['label']} at {o['per_contract']:.2f}")
            pnl += o.get("pnl") or 0.0
        return {"dir": dir_, "what": " and ".join(bits), "pnl": round(pnl, 2), "entry": pos["avg_cost"] if pos else None,
                "stop": float(stop) if stop else None, "target": float(tgt) if tgt else None,
                "qty": pos["qty"] if pos else sum(o["qty"] for o in opts),
                "key": (dir_, pos["qty"] if pos else 0, tuple(sorted((o["key"], o["qty"]) for o in opts)))}

    def _market_read(self, st, t):
        """What the market is doing, for the coach: SPY / QQQ when on the desk (up or down on the day, over or under
        VWAP), else the desk itself (how many of the other stocks are green). Once every 5 s."""
        memo = self.__dict__.setdefault("_mkt_memo", {})
        if memo.get("t", -1e9) > t - 5 and st.symbol in memo.get("v", {}):
            return memo["v"][st.symbol]
        if memo.get("t", -1e9) <= t - 5:
            memo["t"], memo["v"] = t, {}

        def chg(o):
            p, c = o.price(), (o.l1 or {}).get("close")
            return (p - c) / c * 100.0 if p and c else None
        idx = [(s2, o) for s2, o in self.syms.items() if s2 in ("SPY", "QQQ") and s2 != st.symbol]
        out = None
        if idx:
            bits, ups, downs = [], 0, 0
            for s2, o in idx:
                ch = chg(o)
                if ch is None:
                    continue
                vw = ((o.__dict__.get("_refs") or {}).get("v") or {}).get("vwap")
                over = None if not vw else o.price() > vw
                bits.append(f"{s2} {'up' if ch >= 0 else 'down'} {abs(ch):.1f}%" + ("" if over is None else f", {'over' if over else 'under'} VWAP"))
                ups += ch > 0.15 and over is not False
                downs += ch < -0.15 and over is not True
            if bits:
                d = "up" if ups and not downs else "down" if downs and not ups else None
                out = {"dir": d, "text": "; ".join(bits) + "."}
        else:
            chs = [chg(o) for s2, o in self.syms.items() if s2 != st.symbol]
            chs = [c for c in chs if c is not None]
            if len(chs) >= 4:
                g = sum(1 for c in chs if c > 0)
                d = "up" if g >= 0.7 * len(chs) else "down" if g <= 0.3 * len(chs) else None
                out = {"dir": d, "text": f"{g} of {len(chs)} stocks on the desk are green."}
        memo["v"][st.symbol] = out
        return out

    @staticmethod
    def _story_pane(st):
        s_ = st.story
        if not s_:
            return None
        return {k: v for k, v in s_.items() if k != "said"}

    @staticmethod
    def _story_voiced(s_, sc):
        """Which story moments the voice says (SETTINGS > PS60 story): your trade and second entry always; the
        play-by-play, the coach and the excitement by their own switches; the rest by story.voice."""
        k = (s_.get("topic") or "").split(":")[0]
        if k in ("trade", "se"):
            return True
        if k == "pbp":
            return bool(sc.get("voice_play_by_play", True))
        if k.startswith("coach"):
            return bool(sc.get("voice_coach", True))
        if k == "hype":
            return bool(sc.get("voice_hype", True))
        return bool(sc.get("voice", True))

    def _story_alert(self, st, s_, t, sc):
        tone = s_.get("tone")
        alert = {"t": t, "symbol": st.symbol, "label": "PS60 STORY", "price": fmt_price(st.price()),
                 "side": "bid" if tone == "bear" else "ask", "role": "story", "text": s_["text"],
                 "pri": int(s_.get("pri") or 3),
                 "words": f"{st.symbol}. {s_['text']}" if self._story_voiced(s_, sc) else None}
        alert["key"] = f"{round(t, 2)}|{st.symbol}|STORY|{s_['topic']}"
        self.alerts.appendleft(alert)
        self._rec(dict(alert, ev="alert"))
        if self.storyline_path and str(s_["topic"]).split(":")[0] in ("lean", "attempt", "regime", "openread", "struct"):
            try:                                      # the storyline, one line per turn of it: the cross-day study reads this
                import json as _json
                from . import studies as _studies
                with open(self.storyline_path, "a", encoding="utf-8") as f:
                    f.write(_json.dumps({"t": round(t, 2), "day": _studies.day_key(t), "symbol": st.symbol, "topic": s_["topic"],
                                         "text": s_["text"], "price": alert["price"], "live": self.connection.get("state") == "CONNECTED"}) + "\n")
            except Exception:
                pass
        self.log(st.symbol, "STORY: " + s_["text"], t, kind="level")
        for fn in self.listeners:
            try:
                fn(alert)
            except Exception:
                pass

    def studies_for(self, st, t):
        """The chart studies for one symbol (GAS + ATR, AIRSPACE, UNVISITED HIGHS / LOWS), at most once a second."""
        sc = self.cfg.get("studies") or {}
        if not (sc.get("gas") or sc.get("airspace") or sc.get("unvisited")):
            return None
        memo = st.__dict__.setdefault("_studies", {})
        memo["want"] = t
        if memo.get("v") is not None and t - memo.get("t", -1e9) < 1.0 and memo.get("ver") == (st.study_ver, st.hist_ver):
            return memo["v"]
        if self.study_async and memo.get("v") is not None:
            # live: the studies worker keeps them fresh (about once a second) off the engine lock. The page gets the
            # last one at once: a refresh never holds the lock for the maths while IBKR's book and prints wait
            self._study_worker_start()
            return memo["v"]
        from . import studies
        st._any_session = self.connection["state"] == "DEMO"     # practice: today is whatever the practice market traded
        try:
            v = studies.compute(st, t, sc)
        except Exception as exc:                 # a study must never take the chart down
            log.exception("studies %s", st.symbol)
            v = {"error": str(exc)}
        memo.update(v=v, t=t, ver=(st.study_ver, st.hist_ver))
        return v

    def _study_worker_start(self):
        if self._study_thread is None or not self._study_thread.is_alive():
            self._study_thread = threading.Thread(target=self._study_loop, name="twiney-studies", daemon=True)
            self._study_thread.start()

    def _study_loop(self):
        """The chart studies, worked out away from the engine lock: under the lock only a quick copy of the bars is
        taken (a view), the maths runs on the copy, the answer is swapped in for the next refresh."""
        from . import studies
        while not self._study_stop.wait(0.25):
            t = self.last_t
            if not t:
                continue
            sc = self.cfg.get("studies") or {}
            for sym in list(self.syms):
                try:
                    st = self.syms.get(sym)
                    memo = st.__dict__.get("_studies") if st else None
                    if not memo or t - memo.get("want", -1e9) > 10.0:
                        continue                      # nobody is looking at this chart
                    ver = (st.study_ver, st.hist_ver)
                    if t - memo.get("t", -1e9) < 1.0 and memo.get("ver") == ver:
                        continue
                    with self.lock:
                        view = self._study_view(st)
                    try:
                        v = studies.compute(view, t, sc)
                    except Exception as exc:
                        log.exception("studies %s", sym)
                        v = {"error": str(exc)}
                    memo.update(v=v, t=t, ver=ver)
                except Exception:                     # one symbol never stops the worker
                    log.exception("studies worker %s", sym)

    def _study_view(self, st):
        """A copy of what the studies read, taken under the lock (dict copies: well under a millisecond)."""
        view = st.__dict__.get("_study_view")
        if view is None:
            view = st._study_view = _StudyView()
        view.symbol = st.symbol
        view.play = dict(st.play)
        view.bars = {k: list(b) for k, b in st.bars.items()}
        view.daily = dict(st.daily)
        view.daily_vol = dict(st.daily_vol)
        view.m30 = dict(getattr(st, "m30", {}) or {})
        view.m5x = {k: list(b) for k, b in (getattr(st, "m5x", {}) or {}).items()}
        view._px = st.price()
        view._any_session = self.connection["state"] == "DEMO"
        return view

    def _day_range_from_history(self, st, t0, h, l):
        """HIGH / LOW OF DAY with the whole day in it: IBKR's minute history for today's regular session counts, not
        only the prints since TED started watching this ticker (opened at 2 pm, the low is still the day's low)."""
        now = self.last_t or t0
        dk = ps60.ny_day(t0)
        if dk != ps60.ny_day(now) or not (self.connection["state"] == "DEMO" or ps60.is_rth(t0)):
            return
        if st.day_key != dk:
            st.day_key, st.day_sums, st.day_hi, st.day_lo = dk, {}, None, None
        if h and (st.day_hi is None or h > st.day_hi[0]):
            st.day_hi = (h, t0 + 30)
        if l and l > 0 and (st.day_lo is None or l < st.day_lo[0]):
            st.day_lo = (l, t0 + 30)

    def on_hist_bar(self, symbol, t0, o, h, l, c, v):
        """Historical 1-minute bar (reqHistoricalData) so the chart has context at startup."""
        with self.lock:
            st = self._st(symbol)
            if st is None:
                return
            self._rec({"ev": "hbar", "t": self.last_t or t0, "sym": symbol, "t0": t0, "o": o, "h": h, "l": l, "c": c, "v": v})
            self._day_range_from_history(st, t0, h, l)
            m = int(t0 // BAR_SECONDS) * BAR_SECONDS
            live = st.bars.get(m)
            if live is not None:
                # the minute was already started live (first ticks came in before the history): the history has
                # the whole minute up to now, so it sets the open and widens the range; the live close stays
                live[0] = o
                live[1] = max(live[1], h)
                live[2] = min(live[2], l)
                live[4] = max(live[4], v or 0.0)
            else:
                st.bars[m] = [o, h, l, c, v or 0.0, 0.0, 0.0]
            self._hist_bump(st)

    # ---- account view (read-only) --------------------------------------------

    DONE_STATUSES = ("Filled", "Cancelled", "ApiCancelled", "Inactive")

    def on_order(self, key, t, **fields):
        """Order info from IBKR (openOrder / orderStatus). Display only."""
        with self.lock:
            self.account_seen = True
            o = self.orders.setdefault(key, {"key": key, "first_seen": t})
            o.update({k: v for k, v in fields.items() if v is not None})
            o["t"] = t

    def rename_order(self, old_key, new_key):
        """TWS assigns a permanent id after we sent the order under our own id."""
        with self.lock:
            if old_key in self.orders and new_key not in self.orders:
                o = self.orders.pop(old_key)
                o["key"] = new_key
                self.orders[new_key] = o

    def on_orders_snapshot_end(self, seen_keys, t):
        """After a full open-order refresh, orders not listed are no longer working."""
        with self.lock:
            for key, o in list(self.orders.items()):
                if key not in seen_keys and o.get("status") not in self.DONE_STATUSES:
                    o["status"] = "Done"
                    o["t"] = t
            for key, o in list(self.orders.items()):
                if o.get("status") in self.DONE_STATUSES + ("Done",) and t - o["t"] > 600:
                    del self.orders[key]

    @staticmethod
    def _opt_view(p):
        """An option position for the page: contract, side, size, cost, quotes and the open P&L in dollars
        (IBKR's avg cost is per contract: multiplier already in)."""
        # an option is marked at the middle of its bid / ask (a last trade can be minutes old on a quiet contract)
        mark = (p["bid"] + p["ask"]) / 2 if p.get("bid") and p.get("ask") else (p.get("last") or None)
        mult = p.get("mult") or 100
        pnl = None if mark is None else (mark * mult - p["avg_cost"]) * p["qty"]
        exp = p.get("expiry") or ""
        label = f"{p.get('symbol')} {exp[4:6]}/{exp[6:8]} {p.get('strike'):g}{p.get('right')}" if len(exp) >= 8 else p["key"]
        return {"key": p["key"], "label": label, "symbol": p.get("symbol"), "expiry": exp, "strike": p.get("strike"),
                "right": p.get("right"), "mult": mult, "qty": p["qty"], "avg_cost": p["avg_cost"],
                "per_contract": p["avg_cost"] / mult if mult else p["avg_cost"],
                "bid": p.get("bid"), "ask": p.get("ask"), "last": p.get("last"), "mark": mark, "pnl": None if pnl is None else round(pnl, 2),
                "delta": p.get("delta")}

    def on_opt_position(self, account, key, fields, qty, avg_cost, t):
        """An option position from IBKR (contracts; avg_cost is per contract, IBKR style). Shown in POSITIONS with
        its own quotes so it can be scaled in and out of from the desk."""
        with self.lock:
            self.account_seen = True
            if qty:
                q = self.opt_quotes.get(key) or {}
                cur = self.opt_positions.get(key) or {"bid": q.get("bid"), "ask": q.get("ask"), "last": q.get("last"), "delta": q.get("delta")}
                cur.update(fields, key=key, account=account, qty=qty, avg_cost=avg_cost, t=t)
                self.opt_positions[key] = cur
            else:
                self.opt_positions.pop(key, None)

    def on_opt_quote(self, key, field, price, t):
        try:
            return self._on_opt_quote(key, field, price, t)
        finally:
            self.price_evt.set()          # after the update is in (the lock is released): stops on it are checked now

    def _on_opt_quote(self, key, field, price, t):
        with self.lock:
            if field not in ("bid", "ask", "last"):
                return
            q = self.opt_quotes.setdefault(key, {"bid": None, "ask": None, "last": None})
            q[field] = price
            q["t"] = t
            if field == "last" and price:      # the chart draws TRADES, the same prices as the T&S and the ladder
                self._opt_bar(key, t, round(price, 4))
            p = self.opt_positions.get(key)
            if p is not None:
                p[field] = price
                p["quote_t"] = t
            sim = getattr(self, "sim_broker", None)
            if sim is not None and hasattr(sim, "on_opt_market"):
                sim.on_opt_market(key, t)

    def _opt_bar(self, key, t, price, hist=None):
        bars = self.opt_bars.setdefault(key, {})
        m = int(t // BAR_SECONDS) * BAR_SECONDS
        if hist is not None:            # a finished minute from history: (o, h, l, c); a live minute keeps its close
            o, h, l, c = hist
            b = bars.get(m)
            bars[m] = [o, max(h, b[1]), min(l, b[2]), b[3], b[4], b[5], b[6]] if b else [o, h, l, c, 0.0, 0.0, 0.0]
            wait = (getattr(self, "_opt_vol_wait", None) or {}).get(key)
            if wait and m in wait:
                bars[m][4] = wait.pop(m)
        else:
            b = bars.get(m)
            if b is None:
                bars[m] = [price, price, price, price, 0.0, 0.0, 0.0]
            else:
                b[1] = max(b[1], price); b[2] = min(b[2], price); b[3] = price
        if len(bars) > MAX_BARS:
            for k in sorted(bars)[:len(bars) - MAX_BARS]:
                del bars[k]

    # ---- the charted contract's own book (IBKR market depth on the option: each exchange's quote) -------------------
    def opt_depth_wanted(self, t=None):
        """The contract that should have a book: the one on the OPTION CHART (asked for in the last minute), live only,
        SETTINGS on, not refused by IBKR in the last 5 minutes."""
        t = t if t is not None else self.last_t
        if self.connection.get("state") not in ("CONNECTED",) or not self.cfg["depth"].get("option_depth", True):
            return None
        live = getattr(self, "opt_live", None) or {}
        if not live:
            return None
        key, at = max(live.items(), key=lambda kv: kv[1])
        if t - at > 60 or t - (getattr(self, "opt_depth_refused", {}) or {}).get(key, -1e9) < 300:
            return None
        return key

    def on_opt_depth(self, key, position, operation, side, price, size, market_maker, t):
        from .book import Book
        from .conviction import PullBook
        with self.lock:
            books = self.__dict__.setdefault("opt_dbook", {})
            bk = books.get(key)
            if bk is None:
                bk = books[key] = Book(rows_requested=10)
                self.__dict__.setdefault("opt_dpulls", {})[key] = PullBook(self.cfg.get("ladder", {}))
            bk.apply(position, operation, side, price, size, market_maker)
            self.__dict__.setdefault("opt_depth_t", {})[key] = t

    def on_opt_depth_reset(self, key):
        with self.lock:
            bk = (getattr(self, "opt_dbook", None) or {}).get(key)
            if bk is not None:
                bk.reset()
            pb = (getattr(self, "opt_dpulls", None) or {}).get(key)
            if pb is not None:
                pb.reset()

    def on_opt_depth_refused(self, key, code, msg, t):
        with self.lock:
            self.__dict__.setdefault("opt_depth_refused", {})[key] = t
            (getattr(self, "opt_dbook", None) or {}).pop(key, None)
            self._message("warn", f"{key}: IBKR has no option book for it ({code}: {msg}) — the option LEVEL II shows the top of "
                                  f"book (best bid / ask). Needs OPRA market data, and a free depth line", t, key.split(" ")[0])

    def _opt_dbook(self, key, t):
        """The contract's live book, when IBKR is sending one (updated in the last 30 s and has both sides)."""
        bk = (getattr(self, "opt_dbook", None) or {}).get(key)
        if bk is None or t - (getattr(self, "opt_depth_t", {}) or {}).get(key, -1e9) > 30 or not (bk.levels(BID) and bk.levels(ASK)):
            return None
        return bk

    def on_opt_size(self, key, field, size, t):
        """Bid / ask size, last trade size and day volume of an option contract (IBKR tickSize)."""
        with self.lock:
            q = self.opt_quotes.setdefault(key, {"bid": None, "ask": None, "last": None})
            if field in ("bid_size", "ask_size"):
                # PULL / STACK at the touch (IBKR sends options top of book only): the same price, more size = stacked;
                # less size with no prints there to explain it = pulled
                side = "bid" if field == "bid_size" else "ask"
                px_ = q.get(side)
                old, oldpx = q.get(field), q.get("_" + side + "_px")
                if px_ and old is not None and size is not None and oldpx is not None and abs(oldpx - px_) < 1e-9 and size != old:
                    d = float(size) - float(old)
                    if d < 0:
                        traded = sum(p_[2] for p_ in list(self.opt_prints.get(key) or [])[:20]
                                     if abs(p_[1] - px_) < 1e-9 and t - p_[0] <= 1.5)
                        d = -max(0.0, -d - traded)
                    if abs(d) > 1e-9:
                        self.__dict__.setdefault("opt_ps", {}).setdefault(key, deque(maxlen=600)).append(
                            (t, side, int(round(px_ * 100)), d))
                q[field] = size
                q["_" + side + "_px"] = px_
            elif field == "last_size":
                lp = q.get("last_trade") or q.get("last")
                if lp and size and size > 0:
                    self.on_opt_print(key, lp, size, t, from_volume=False)
            elif field == "volume" and size is not None:
                prev = self.opt_vol.get(key)
                self.opt_vol[key] = size
                if prev is not None and size > prev:
                    m = int(t // BAR_SECONDS) * BAR_SECONDS
                    b = (self.opt_bars.get(key) or {}).get(m)
                    if b is not None:
                        b[4] += size - prev

    def on_opt_print(self, key, price, size, t, side=None, from_volume=True):
        """One trade in an option contract: OPTION T&S, BIG prints, and the chart's volume (buyers at the ask,
        sellers at the bid). ``from_volume`` False: IBKR's day volume already counts it in the bar."""
        from collections import deque as _dq
        with self.lock:
            q = self.opt_quotes.get(key) or {}
            if side is None:
                b_, a_ = q.get("bid"), q.get("ask")
                side = "buy" if a_ and price >= a_ - 1e-9 else "sell" if b_ and price <= b_ + 1e-9 else None
            self.opt_prints.setdefault(key, _dq(maxlen=400)).appendleft([t, round(price, 2), int(size), side])
            pb = (getattr(self, "opt_dpulls", None) or {}).get(key)
            if pb is not None and side in ("buy", "sell"):
                pb.on_print(side, price, size)
            m = int(t // BAR_SECONDS) * BAR_SECONDS
            bars = self.opt_bars.setdefault(key, {})
            b = bars.get(m)
            if b is None:
                b = bars[m] = [price, price, price, price, 0.0, 0.0, 0.0]
            if from_volume or key not in self.opt_vol:
                b[4] += size
            if side == "buy":
                b[5] += size
            elif side == "sell":
                b[6] += size

    def on_opt_hist_vol(self, key, t0, v):
        """Volume of one past minute of an option contract (IBKR TRADES history)."""
        with self.lock:
            m = int(t0 // BAR_SECONDS) * BAR_SECONDS
            if v is None or v < 0:
                return
            b = (self.opt_bars.get(key) or {}).get(m)
            if b is not None:
                b[4] = float(v)
            else:                       # the price minute has not landed yet: it picks this up when it does
                self.__dict__.setdefault("_opt_vol_wait", {}).setdefault(key, {})[m] = float(v)

    def option_tape(self, key, t, big_ct=100, big_usd=50000.0):
        """OPTION T&S, OPTION LEVEL II and OPTION BIG TAPE for one contract. IBKR sends the best bid / ask (with
        size) for options, no deeper book: the ladder shows that touch and what has traded at each price today."""
        try:
            sym, exp, strike, right = options.parse_key(key)
        except (ValueError, IndexError):
            return {}
        with self.lock:
            q = self.opt_quotes.get(key) or {}
            prints = list(self.opt_prints.get(key) or [])
            bid, ask = q.get("bid"), q.get("ask")
            # the ladder: nickels (or pennies under $3 when the quote is on pennies) around the touch
            ref = (bid + ask) / 2 if bid and ask else (ask or bid or q.get("last"))
            rows = []
            if ref:
                pennies = any(abs(round(x * 100) % 5) for x in (bid, ask) if x)
                pbk = (getattr(self, "opt_pbook", {}) or {}).get(key)
                step = (pbk.g / 100.0) if pbk is not None else (0.01 if pennies and ref < 3 else 0.05)
                traded = {}
                for tp, pp, sz, sd in prints:
                    k = round(pp, 2); tr = traded.setdefault(k, [0, 0]); tr[0 if sd == "buy" else 1 if sd == "sell" else 0] += sz
                dbk = self._opt_dbook(key, t)
                # PULL / STACK per price, last 60 s: the practice book's own adds / pulls, or the touch's size changes live
                pstack = {}
                evs = list(getattr(pbk, "ev", ()) or ()) if pbk is not None else list((getattr(self, "opt_ps", {}) or {}).get(key) or ())
                for et, eside, ec, d in evs:
                    if t - et <= 60:
                        a = pstack.setdefault((eside, ec), [0.0, 0.0])
                        a[0 if d > 0 else 1] += abs(d)
                half = max(10, int(((ask or ref) - (bid or ref)) / step / 2) + 8)     # both sides of the spread, 8 rows past each
                top = round(round(ref / step) * step + half * step, 2)
                for i in range(2 * half + 1):
                    px_ = round(top - i * step, 2)
                    if px_ <= 0:
                        break
                    row = {"price": px_, "bid": 0, "ask": 0, "bought": traded.get(px_, [0, 0])[0], "sold": traded.get(px_, [0, 0])[1],
                           "best_bid": bid is not None and abs(px_ - bid) < step / 2, "best_ask": ask is not None and abs(px_ - ask) < step / 2}
                    if row["best_bid"]:
                        row["bid"] = int(q.get("bid_size") or 0)
                    if row["best_ask"]:
                        row["ask"] = int(q.get("ask_size") or 0)
                    ps_, pa_ = pstack.get(("bid", int(round(px_ * 100)))), pstack.get(("ask", int(round(px_ * 100))))
                    if ps_:
                        row["ps_b"] = [round(ps_[0]), round(ps_[1])]
                    if pa_:
                        row["ps_a"] = [round(pa_[0]), round(pa_[1])]
                    if dbk is not None:                          # IBKR's book on the contract: every level's size
                        row["bid"] = int(dbk.size_at(BID, px_) or 0); row["ask"] = int(dbk.size_at(ASK, px_) or 0)
                        dps = self.opt_dpulls.get(key)
                        if dps is not None:
                            for sd_, nm in ((BID, "ps_b"), (ASK, "ps_a")):
                                v_ = dps.pullstack(sd_, price_key(px_), t, 60.0)
                                if v_:
                                    row[nm] = [v_[0], v_[1]]
                    pb = (getattr(self, "opt_pbook", {}) or {}).get(key)
                    if pb is not None and self._sim_like(t):   # the practice book: every level's size
                        row["bid"] = int(pb.size_at("bid", px_)); row["ask"] = int(pb.size_at("ask", px_))
                        row["reload_bid"] = ("bid", int(round(px_ * 100))) in pb.reload
                        row["reload_ask"] = ("ask", int(round(px_ * 100))) in pb.reload
                    rows.append(row)
            big = [{"t": tp, "price": pp, "size": sz, "side": sd, "premium": round(pp * sz * 100), "src": "tape"}
                   for tp, pp, sz, sd in prints if sz >= big_ct or pp * sz * 100 >= big_usd][:40]
            # Quant Data flow on this very contract (sweeps, blocks): the dough behind it
            exp_dash = f"{exp[:4]}-{exp[4:6]}-{exp[6:8]}"
            for f in list(self.flow.by_symbol.get(sym) or []):
                if f.get("cp") == right and abs((f.get("strike") or 0) - strike) < 1e-6 and str(f.get("expiry", ""))[:10] == exp_dash:
                    big.append({"t": f["t"], "price": f.get("price"), "size": f.get("size"), "side": f.get("side"),
                                "premium": f.get("premium"), "src": "flow", "kind": f.get("kind")})
            big.sort(key=lambda x: -(x["t"] or 0))
            vol = self.opt_vol.get(key)
            if vol is None:
                vol = sum(p[2] for p in prints)
            return {"book": rows, "prints": prints[:80], "big": big[:40], "bid_size": q.get("bid_size"), "ask_size": q.get("ask_size"),
                    "volume": vol, "bought": sum(p[2] for p in prints if p[3] == "buy"), "sold": sum(p[2] for p in prints if p[3] == "sell"),
                    "deep_book": self._sim_like(t) or self._opt_dbook(key, t) is not None, "sim": self.opt_sim(t)}

    def on_opt_hist_bar(self, key, t0, o, h, l, c):
        """A 1-minute TRADES bar of an option contract from IBKR history (the OPTION CHART's context)."""
        with self.lock:
            if None not in (o, h, l, c):
                self._opt_bar(key, t0, c, hist=(o, h, l, c))

    def _chart_stop_for(self, sym, right):
        """The stock chart's STOP line a NEW contract would ride: a call the long side's, a put the short side's."""
        st = self.syms.get(sym)
        if st is None:
            return None
        own_long = st.play.get("side", "long") == "long"
        lines = st.play if (right == "C") == own_long else (st.play.get("alt") or {})
        return lines.get("stop")

    SIM_WHY = ("options market closed: option prices are SIMULATED from the stock (paper only) — "
               "option orders are held until the 9:30 ET open")

    def opt_sim(self, t=None):
        """After hours on a PAPER account: the options market is closed (IBKR has no live option quotes), so the
        option chain, chart, LEVEL II and T&S run on the practice model priced from the stock, and the OPT light
        goes yellow SIM. Never on a LIVE account; off with SETTINGS > Trading > Simulated options after hours."""
        t = t if t is not None else self.last_t
        if self.connection["state"] != "CONNECTED" or not self.cfg.get("trading", {}).get("sim_options_after_hours", True):
            return False
        tr = self.trader
        if tr is None or getattr(getattr(tr, "gate", None), "mode", None) != "PAPER":
            return False
        if self.cfg.get("trading", {}).get("sim_options_force", False):
            return True
        from .ps60 import ny_seconds, ny_day
        return ny_day(t).weekday() >= 5 or not (9 * 3600 + 30 * 60 <= ny_seconds(t) < 16 * 3600)

    def _sim_like(self, t):
        """The practice option model runs: the practice desk, or after-hours SIM on paper."""
        return self.connection["state"] == "DEMO" or self.opt_sim(t)

    def practice_opt_tick(self, t, every=0.5):
        """The practice desk: every contract you hold, have a working order on, chart or picked is re-priced from the
        stock's price right now (calls gain as the stock rises, puts as it falls), so positions mark and orders
        fill like the real market even with the OPTION CHAIN closed."""
        if t - getattr(self, "_opt_tick_t", 0.0) < every or not self._sim_like(t):
            return
        self._opt_tick_t = t
        with self.lock:
            live = self.__dict__.setdefault("opt_live", {})      # key -> last time a chart / ticket asked for it
            keys = set(self.opt_positions) | {o["symbol"] for o in self._pending() if o.get("opt")} | \
                {k for k, at in live.items() if t - at < 120}
            from .optbook import PracticeOptBook
            books = self.__dict__.setdefault("opt_pbook", {})
            for key in keys:
                try:
                    sym, exp, strike, right = options.parse_key(key)
                except (ValueError, IndexError):
                    continue
                st = self.syms.get(sym)
                spot = st.price() if st else None
                fair = options.practice_quote(spot, strike, exp, right, t) if spot else None
                if not fair or not fair.get("ask"):
                    continue
                bk = books.get(key)
                if bk is None:
                    bk = books[key] = PracticeOptBook(seed=hash(key) & 0xffff)
                # which way the contract is being pushed: the stock's move since the last tick, signed for a put
                prev = getattr(bk, "spot", None); bk.spot = spot
                lean = 0.0 if prev is None else max(-0.3, min(0.3, (spot - prev) / max(1e-9, spot) * 400 * (1 if right == "C" else -1)))
                prints = bk.step(max(0.01, fair["bid"]), fair["ask"], t, lean)
                qt = bk.quote()
                for fld in ("bid", "ask"):
                    if qt[fld]:
                        self.on_opt_quote(key, fld, qt[fld], t)
                q = self.opt_quotes.get(key) or {}
                q["bid_size"], q["ask_size"] = qt["bid_size"], qt["ask_size"]
                for price, n, side, tt in prints:
                    self.on_opt_quote(key, "last", price, t)
                    self.on_opt_print(key, price, n, t, side)
                self.on_opt_greeks(key, options.bs_greeks(spot, strike, options.dte(exp, t) or 0, right), t)

    def practice_quote_key(self, key, t):
        """Price one contract from the stock right now (practice desk / after-hours SIM). True when it got a quote."""
        if not self._sim_like(t):
            return False
        try:
            sym, exp, strike, right = options.parse_key(key)
        except (ValueError, IndexError):
            return False
        with self.lock:
            st = self.syms.get(sym)
            spot = st.price() if st else None
            q = options.practice_quote(spot, strike, exp, right, t) if spot else None
            if not q:
                return False
            for fld in ("bid", "ask", "last"):
                self.on_opt_quote(key, fld, q[fld], t)
            self.on_opt_greeks(key, options.bs_greeks(spot, strike, options.dte(exp, t) or 0, right), t)
            return True

    def option_bars(self, key, t=None):
        """Everything the OPTION CHART draws for one contract: its 1-minute bars (trades), quote, your position in it
        and your working orders on it. The practice desk models the contract's day from the stock's own minutes."""
        t = t if t is not None else self.last_t
        try:
            sym, exp, strike, right = options.parse_key(key)
        except (ValueError, IndexError):
            return {"key": key, "available": False, "note": "not an option contract"}
        with self.lock:
            self.__dict__.setdefault("opt_live", {})[key] = t
            st = self.syms.get(sym)
            spot = st.price() if st else None
            sim = self._sim_like(t)
            if sim and spot:
                done = self.__dict__.setdefault("opt_hist_done", set())
                # practice desk: the contract's day modelled from the stock's minutes; after-hours SIM only when IBKR
                # gave no real history for it (a few SIM bars from before the chart opened don't count)
                if key not in done and st.bars and (self.connection["state"] == "DEMO" or len(self.opt_bars.get(key) or ()) < 5):
                    done.add(key)
                    for m in sorted(st.bars)[-780:]:
                        o, h, l, c = st.bars[m][:4]
                        def f(x, m=m):          # the model's price on the contract's own tick grid (pennies under $3, else nickels)
                            v = (options.practice_quote(x, strike, exp, right, m + BAR_SECONDS) or {}).get("last")
                            return None if v is None else round(round(v / (0.01 if v < 3 else 0.05)) * (0.01 if v < 3 else 0.05), 2)
                        fo, fh, fl, fc = f(o), f(h), f(l), f(c)
                        if None in (fo, fh, fl, fc):
                            continue
                        self._opt_bar(key, m, fc, hist=(fo, max(fh, fl, fo, fc), min(fh, fl, fo, fc), fc))
                        bb = self.opt_bars[key][m]
                        v = round(max(0.0, st.bars[m][4]) / 400.0 * (1.0 if strike and abs(strike - c) / c < 0.03 else 0.3))
                        bb[4] = float(v); bb[5] = float(round(v * 0.5)); bb[6] = float(v - round(v * 0.5))
                if key not in (getattr(self, "opt_pbook", {}) or {}):   # the contract's own book sets its quote
                    q = options.practice_quote(spot, strike, exp, right, t)
                    if q:
                        for fld in ("bid", "ask", "last"):
                            self.on_opt_quote(key, fld, q[fld], t)
            bars = self.opt_bars.get(key) or {}
            out = [[m] + [round(x, 4) for x in bars[m]] for m in sorted(bars)]
            q = self.opt_quotes.get(key) or {}
            pos = self.opt_positions.get(key)
            self.och_seen[sym] = (key, t)          # the contract on the OPTION CHART: the stock chart shows it at your lines
            return {"key": key, "available": True, "symbol": key, "underlying": sym, "expiry": exp, "strike": strike,
                    "right": right, "label": f"{sym} {exp[4:6]}/{exp[6:8]} {strike:g}{right}", "spot": spot,
                    "bars": out, "bid": q.get("bid"), "ask": q.get("ask"), "last": q.get("last"),
                    "position": self._opt_view(pos) if pos else None,
                    "orders": [o for o in self._pending() if o.get("symbol") == key],
                    "source": "PRACTICE" if self.connection["state"] == "DEMO" else "SIM" if sim else "IBKR",
                    "sim": sim and self.connection["state"] != "DEMO",
                    "delta": q.get("delta"), "iv": q.get("iv"),
                    "expires_today": exp == time.strftime("%Y%m%d", time.gmtime(t + options_ny_off(t))),
                    "dte": options.dte(exp, t),
                    "chart_stop": self._chart_stop_for(sym, right),
                    "tape": self.option_tape(key, t)}

    def on_opt_greeks(self, key, greeks, t):
        """Delta / gamma / theta / vega / implied vol for a contract (IBKR's tickOptionComputation, or the practice model)."""
        with self.lock:
            q = self.opt_quotes.setdefault(key, {"bid": None, "ask": None, "last": None})
            for k in ("delta", "gamma", "theta", "vega", "iv"):
                if greeks.get(k) is not None:
                    q[k] = greeks[k]
            q["greeks_t"] = t
            p = self.opt_positions.get(key)
            if p is not None:
                p["delta"] = q.get("delta")

    def on_opt_chain(self, symbol, expiries, strikes, mult, con_id, t, source="IBKR"):
        """The option chain for a symbol: expiries and strikes (from IBKR's secDefOptParams, or made up by the
        practice desk). Quotes come separately, for the rows the page watches."""
        with self.lock:
            self.opt_chain[str(symbol).upper()] = {"expiries": sorted(set(expiries)), "strikes": sorted(set(float(x) for x in strikes)),
                                                   "mult": float(mult or 100), "con_id": con_id, "source": source, "t": t}

    def _opt_est(self, st, t):
        """THE CONTRACT AT YOUR LINES, in %: what the contract you trade should be worth when the stock is at your 2nd
        entry, stop and target (today's delta and gamma: mid + delta x move + half gamma x move squared), and the % it
        makes or loses from your entry (your fill when you hold it, else the 2nd entry's estimate, else the mid now).
        The contract: the one the stock chart's lines trade, else the one on the OPTION CHART for this stock."""
        play = st.play or {}
        key = play.get("opt_key") if play.get("trade_as") == "option" else None
        seen = self.och_seen.get(st.symbol)
        if not key and seen and t - seen[1] < 30.0:
            key = seen[0]
        if not key:                     # the contract you are IN on this stock (the last one bought when several)
            held = [(k, p) for k, p in self.opt_positions.items() if p.get("symbol") == st.symbol and (p.get("qty") or 0) > 0]
            if held:
                key = max(held, key=lambda kp: kp[1].get("t") or kp[1].get("opened") or 0)[0]
        if not key:
            return None
        try:
            usym, exp, strike, right = options.parse_key(key)
        except (ValueError, IndexError):
            return None
        q = self.opt_quotes.get(key) or {}
        b, a = q.get("bid"), q.get("ask")
        mid = (b + a) / 2 if b and a and a >= b else q.get("last")
        delta, gamma, spot = q.get("delta"), q.get("gamma") or 0.0, st.price()
        label = f"{exp[4:6]}/{exp[6:8]} {strike:g}{right}"
        if not mid or delta is None or not spot:
            return {"key": key, "label": label, "wait": True}
        val = lambda S: max(0.01, mid + delta * (S - spot) + 0.5 * gamma * (S - spot) ** 2)
        own_long = play.get("side", "long") == "long"
        lines = play if (right == "C") == own_long else (play.get("alt") or {})
        pos = self.opt_positions.get(key)
        held = int((pos or {}).get("qty") or 0)
        if held > 0 and pos.get("avg_cost"):
            entry, basis = pos["avg_cost"] / (pos.get("mult") or 100), "your fill"
        elif lines.get("second_entry"):
            entry, basis = val(lines["second_entry"]), "at the 2nd entry"
        else:
            entry, basis = mid, "now"
        out = {"key": key, "label": label, "held": held, "entry": round(entry, 2), "basis": basis, "lines": {},
               "mid": round(mid, 4), "delta": delta, "gamma": gamma, "spot": spot,     # the page prices a right-click with these
               "alt": lines is not play}          # the contract rides the OTHER side's lines (a put on a long play)
        for role in ("second_entry", "stop", "target"):
            S = lines.get(role)
            if S:
                v = val(S)
                out["lines"][role] = {"at": S, "v": round(v, 2), "pct": round((v - entry) / entry * 100, 0)}
        tg, sp = out["lines"].get("target"), out["lines"].get("stop")
        if tg and sp and sp["pct"] < 0:
            out["rr"] = round(tg["pct"] / -sp["pct"], 1)
        return out

    def option_chain(self, symbol, expiry=None, right="C", t=None, width=10):
        """What the OPTION CHAIN panel shows: the chain, the watched expiry / right, the strikes around the spot
        with their quotes. On the practice desk the chain and the quotes are generated here."""
        t = t if t is not None else self.last_t
        symbol = str(symbol).upper()
        with self.lock:
            st = self.syms.get(symbol)
            spot = st.price() if st else None
            sim = self.opt_sim(t)
            if self.connection["state"] == "DEMO" and spot:
                if symbol not in self.opt_chain or t - self.opt_chain[symbol]["t"] > 3600:
                    self.on_opt_chain(symbol, options.practice_expiries(t), options.practice_strikes(spot), 100, None, t, source="PRACTICE")
            elif sim and spot and symbol not in self.opt_chain:      # after hours, no chain from IBKR yet: the model's
                self.on_opt_chain(symbol, options.practice_expiries(t), options.practice_strikes(spot), 100, None, t, source="SIM")
            ch = self.opt_chain.get(symbol)
            if not ch:
                return {"symbol": symbol, "spot": spot, "available": False, "source": None, "expiries": [], "rows": [],
                        "note": "no chain yet" if self.connection["state"] != "DEMO" else "waiting for a price"}
            expiry = expiry if expiry in ch["expiries"] else (ch["expiries"][0] if ch["expiries"] else None)
            right = "P" if str(right).upper().startswith("P") else "C"
            strikes = ch["strikes"]
            if spot and strikes:
                i = min(range(len(strikes)), key=lambda k: abs(strikes[k] - spot))
                strikes = strikes[max(0, i - width): i + width + 1]
            keys = [options.key_of(symbol, expiry, k, right) for k in strikes] if expiry else []
            self.opt_watch[symbol] = {"expiry": expiry, "right": right, "keys": keys, "t": t}
            if (ch["source"] == "PRACTICE" or sim) and spot and expiry:
                days = options.dte(expiry, t) if expiry else 0
                booked = getattr(self, "opt_pbook", {})
                for k, strike in zip(keys, strikes):
                    q = None if k in booked else options.practice_quote(spot, strike, expiry, right, t)
                    if q:
                        for f in ("bid", "ask", "last"):
                            self.on_opt_quote(k, f, q[f], t)
                        self.on_opt_greeks(k, options.bs_greeks(spot, strike, days or 0, right), t)
            rows = []
            for k, strike in zip(keys, strikes):
                q = self.opt_quotes.get(k) or {}
                pos = self.opt_positions.get(k)
                rows.append({"key": k, "strike": strike, "bid": q.get("bid"), "ask": q.get("ask"), "last": q.get("last"),
                             "delta": q.get("delta"), "gamma": q.get("gamma"), "theta": q.get("theta"), "vega": q.get("vega"), "iv": q.get("iv"),
                             "qty": pos["qty"] if pos else 0, "dte": options.dte(expiry, t) if expiry else None,
                             "otm_pct": round((strike - spot) / spot * 100 * (1 if right == "C" else -1), 1) if spot else None})
            return {"symbol": symbol, "spot": spot, "available": True, "source": "SIM" if sim else ch["source"], "sim": sim,
                    "sim_why": self.SIM_WHY if sim else None, "expiries": ch["expiries"],
                    "expiry": expiry, "right": right, "mult": ch["mult"], "rows": rows,
                    "orders": [o for o in self._pending() if o.get("opt") and str(o.get("symbol", "")).startswith(symbol + " ")]}

    def on_opt_fill(self, exec_id, key, side, qty, price, t):
        """An option execution: journaled and listed with the fills, kept OUT of the stock fills so the stock's
        day P&L (average cost over its own fills) is never touched by a contract."""
        with self.lock:
            self.account_seen = True
            if exec_id and any(f.get("exec_id") == exec_id for f in self.opt_fills):
                return
            self.opt_fills.append({"exec_id": exec_id, "symbol": key, "side": side, "shares": qty, "price": price,
                                   "t": t, "seq": 10**6 + len(self.opt_fills), "opt": True})
            self.opt_fills = self.opt_fills[-60:]
        self.log(key.split(" ")[0], f"OPTION FILL {side} {qty:g} {key} @ {price:.2f}", t, kind="fill")
        if self.desk is not None:                      # the journal builds the option trade too (in contracts, × 100)
            mult = float(((self.opt_chain.get(key.split(" ")[0]) or {}).get("mult")) or 100)
            self.desk.on_fill({"exec_id": exec_id, "symbol": key, "side": "BOT" if str(side).upper() in ("BOT", "BUY") else "SLD",
                               "shares": qty, "price": price, "opt": True, "mult": mult}, t)

    def on_position(self, account, symbol, qty, avg_cost, t):
        with self.lock:
            self.account_seen = True
            self.pos_t[symbol] = t
            if qty:
                self.positions[(account, symbol)] = {"account": account, "symbol": symbol,
                                                     "qty": qty, "avg_cost": avg_cost}
            else:
                self.positions.pop((account, symbol), None)

    def _feeds(self, t):
        """The two lights in the corner. green = live and flowing, amber = connected but not live
        (delayed, practice, replay, quiet), red = not connected."""
        c = self.connection
        stale = self.cfg["health"]["l1_stale_seconds"]
        age = None if self.data_t is None else max(0.0, t - self.data_t)
        mdt = c.get("market_data_type")
        if c["state"] == "CONNECTED":
            if mdt in (3, 4):
                mkt = ("amber", "DELAYED", "IBKR connected, but market data is DELAYED 15 minutes and there is no Level II: order flow reads are not valid. "
                       + (self.data_problem or "your data subscriptions"))
            elif (age is None or age > stale) and self.data_problem:
                mkt = ("red", "NO DATA", self.data_problem)
            elif age is None or age > stale:
                mkt = ("amber", "QUIET", f"IBKR connected, no ticks for {int(age)}s (market closed, or no subscription)" if age is not None
                       else "IBKR connected, waiting for the first tick")
            else:
                mkt = ("green", "LIVE", f"live IBKR market data · last tick {age:.0f}s ago")
        elif c["state"] == "DEMO":
            mkt = ("amber", "PRACTICE", "practice feed: synthetic, not market data")
        elif c["state"] == "REPLAY":
            mkt = ("amber", "REPLAY", "replaying a recording")
        else:
            mkt = ("red", c["state"], f"no market data: {c['state'].lower()}" + (f" · {c['detail']}" if c.get("detail") else ""))
        fs = self.flow_status
        if fs["source"] == "practice":
            opt = ("amber", "PRACTICE", "practice option flow: synthetic")
        elif fs["source"] == "quantdata":
            poll = float(self.cfg.get("quantdata", {}).get("poll_seconds", 5))
            ok_age = None if fs["last_ok"] is None else t - fs["last_ok"]
            last = "" if fs["last_print"] is None else f" · last print {int(t - fs['last_print'])}s ago"
            if fs["state"] == "error" and (ok_age is None or ok_age > 3 * poll + 5):
                opt = ("red", "ERROR", f"Quant Data: {fs['detail']}")
            elif ok_age is None:
                opt = ("amber", "CONNECTING", "Quant Data: waiting for the first answer")
            elif ok_age > 3 * poll + 5:
                opt = ("amber", "LATE", f"Quant Data: no answer for {int(ok_age)}s{last}")
            elif fs["last_print"] is None and fs.get("detail"):
                opt = ("amber", "NO PRINTS", f"Quant Data: {fs['detail']}")
            else:
                opt = ("green", "LIVE", f"Quant Data option flow · polled {int(ok_age)}s ago{last}")
        else:
            opt = ("red", "OFF", "no option data: add your Quant Data key in SETTINGS, then RESTART NOW")
        if self.opt_sim(t):          # after hours on paper: yellow, whatever the flow feed says
            opt = ("amber", "SIM", self.SIM_WHY + ". Option flow shows today's real prints (no new ones until the open).")
        return {"market": dict(zip(("color", "label", "detail"), mkt)), "options": dict(zip(("color", "label", "detail"), opt))}

    def set_flow_alerts(self, who, t=None):
        """UNUSUAL alerts for the watchlist only, or for every ticker in the feed."""
        who = "all" if who == "all" else "watchlist"
        with self.lock:
            self.flow_alerts = who
            self._rec({"ev": "flow_alerts", "t": t or self.last_t, "who": who})
        return who

    def set_flow_scope(self, scope, t=None):
        """WHOLE MARKET on ("all") or off ("watchlist"): what the flow feed pulls in."""
        scope = "watchlist" if scope == "watchlist" else "all"
        with self.lock:
            self.flow_scope = scope
            self._rec({"ev": "flow_scope", "t": t or self.last_t, "scope": scope})
        return scope

    def on_flow(self, p, t=None):
        """One option print. Every ticker goes into the feed; only watchlist symbols run the unusual detector."""
        with self.lock:
            t = t if t is not None else p.get("t", self.last_t)
            st = self._st(p["symbol"])
            if p.get("spot") is None and st is not None and st.price():
                # no spot from the vendor: our own last price says how far out of the money it is
                sp = st.price()
                p["spot"] = sp
                p["otm_pct"] = round(((p["strike"] - sp) if p["cp"] == "C" else (sp - p["strike"])) / sp * 100.0, 2)
            self._clock(t)
            self._rec({"ev": "flow", "t": t, "p": p})
            self.flow.add(p)
            if self.bigmoney is not None:
                self.bigmoney.add(p, t)
            self.flow_status["last_print"] = t
            if st is not None:
                self._trap_flow_watch(st, p, t)
            # urgency and the ladder marks run on the PRINT's own time: a batch of earlier prints arriving at once
            # (startup, a reconnect) is filed where it happened and never called as if it were happening now
            pt = min(t, p.get("t") or t)
            fresh = t - pt <= float(self.cfg.get("flow", {}).get("urgency_window_minutes", 10)) * 60.0
            self._urgency(p, pt, st, live=fresh)
            if st is not None:
                self._flow_mark(st, p, pt, live=fresh)
            self._check_flow_alerts(p, t)
            self._flow_scan(p, t, st)
            if (st is None and self.flow_alerts != "all") or not fresh:
                return                       # a late batch of earlier prints is filed, never called as if it were now
            u = self.flow.check(p["symbol"], t)
            if u is None:
                return
            k = lambda v: f"${v / 1e6:.1f}M" if v >= 1e6 else f"${v / 1e3:.0f}K"
            label = "UNUSUAL CALLS" if u["cp"] == "C" else "UNUSUAL PUTS"
            what = "calls" if u["cp"] == "C" else "puts"
            text = (f"{label}: {k(u['premium'])} of {what} bought at the ask in {u['prints']} prints"
                    f"{' · ' + str(u['otm_pct']) + '% out of the money' if u['otm_pct'] is not None else ''}"
                    f"{' · ' + str(u['dte']) + ' days out' if u['dte'] is not None else ''}"
                    f" · strikes {', '.join(narrative.px(s) for s in u['strikes'])}. Somebody paying up for a move that has not started.")
            alert = {"t": t, "symbol": p["symbol"], "label": label, "price": fmt_price(u["spot"]) if u.get("spot") else None,
                     "side": "ask", "role": "flow", "text": text, "premium": u["premium"], "cp": u["cp"],
                     "flow": self._receipt(p["symbol"], u["cp"], u.get("ids"), f"out of the money, {self.flow.cfg.get('max_dte')} days or less, bought at the ask, last {self.flow.cfg.get('window_minutes')} min"),
                     "otm_pct": u["otm_pct"], "dte": u["dte"]}
            alert["key"] = f"{round(t, 2)}|{p['symbol']}|{label}|{u['premium']}"
            self.alerts.appendleft(alert)
            self._rec(dict(alert, ev="alert"))
            for fn in self.listeners:
                try:
                    fn(alert)
                except Exception:
                    pass
            otm = u.get("otm_pct")
            again = u.get("minutes", 1) >= 2       # "they keep scooping" only when it came again in another minute
            words = (f"unusual {what} buying, {narrative.say_dollars(u['premium'])}"
                     + (f", {round(otm)} percent out of the money. " + (f"They keep scooping up the {what}." if again else f"One order, {u['prints']} prints. Watch if it comes again.")
                        if otm is not None and otm > 0 else
                        f", {abs(round(otm))} percent in the money. That is a hedge or stock replacement, not the dough." if otm is not None and otm <= -3 else
                        f", right at the money." if otm is not None else "."))
            if st is not None:
                self._say(st, "flow", u["cp"], "flow", t, words)
            else:                                    # off the watchlist: no per-symbol state, the detector's cooldown is enough
                item = {"t": t, "symbol": p["symbol"], "kind": "flow", "text": f"{p['symbol']}: {words}",
                        "key": f"{round(t, 2)}|{p['symbol']}|flow|{u['cp']}"}
                self.voice.appendleft(item)
                self._rec(dict(item, ev="voice"))

    def on_fill(self, exec_id, symbol, side, shares, price, when, t):
        with self.lock:
            self.account_seen = True
            if exec_id and exec_id in self.fills:
                return          # IBKR re-sends the day's executions on every refresh: count each one once
            # a correction of an earlier execution (IBKR bumps the last part of the exec id: .01 -> .02) replaces it
            base = exec_id.rsplit(".", 1)[0] if exec_id and exec_id.count(".") >= 3 else None
            if base:
                old = next((k for k in self.fills if k.rsplit(".", 1)[0] == base), None)
                if old is not None:
                    f = self.fills.pop(old)
                    before = dict(f)
                    f.update(exec_id=exec_id, shares=shares, price=price, side=side)
                    self.fills[exec_id] = f
                    self.fill_t[symbol] = t
                    self._message("warn", f"{symbol}: IBKR corrected execution {old} -> {shares:g} @ {price}", t, symbol)
                    if self.desk is not None and hasattr(self.desk, "correct_fill"):
                        self.desk.correct_fill(before, dict(f), t)
                    return
            self._fill_seq = getattr(self, "_fill_seq", 0) + 1
            key = exec_id or f"_local{self._fill_seq}"
            # every fill of the session is kept: the day P&L and the loss lock are built from all of them
            self.fills[key] = {"exec_id": key, "seq": self._fill_seq, "symbol": symbol, "side": side, "shares": shares,
                               "price": price, "time": when, "t": t}
            self.fill_t[symbol] = t
            if self.desk is not None:
                self.desk.on_fill(self.fills[key], t)

    def _start_qty(self, sym, net_fills):
        """Shares held at the start of the day = what the broker says now minus today's fills. Only worked out from a
        settled report (the position arrived after the last fill); kept once known (it can't change during the day)."""
        if sym in self.start_pos:
            return self.start_pos[sym]
        if sym not in self.pos_t:
            return 0.0
        if self.fill_t.get(sym) is not None and self.pos_t[sym] < self.fill_t[sym]:
            return 0.0                                # the report hasn't caught up with the last fill yet
        now_q = sum(p["qty"] for (a, s), p in self.positions.items() if s == sym)
        self.start_pos[sym] = now_q - net_fills
        return self.start_pos[sym]

    def day_pnl(self):
        """Today's P&L: realized (average cost over today's fills) + open, less commissions. A position carried in from
        yesterday counts from yesterday's close, the way a broker's daily P&L does."""
        with self.lock:
            fills = sorted(self.fills.values(), key=lambda f: f["seq"])   # the order they happened in
            syms = {f["symbol"] for f in fills} | {s for (_a, s) in self.positions}
            realized = open_pnl = 0.0
            for sym in syms:
                mine = [f for f in fills if f["symbol"] == sym]
                net = sum(f["shares"] * (1 if f["side"] == "BOT" else -1) for f in mine)
                st = self.syms.get(sym)
                ref = (st.l1.get("close") if st else None) or next(
                    (p["avg_cost"] for (a, s), p in self.positions.items() if s == sym), 0.0)
                q = self._start_qty(sym, net)
                cost = ref if q else 0.0
                for f in mine:
                    qty, px_ = f["shares"] * (1 if f["side"] == "BOT" else -1), f["price"]
                    if q == 0 or (q > 0) == (qty > 0):
                        nq = q + qty
                        cost = (q * cost + qty * px_) / nq if nq else 0.0
                        q = nq
                    else:
                        closed = min(abs(q), abs(qty))
                        realized += closed * (px_ - cost) * (1 if q > 0 else -1)
                        q += qty
                        if q == 0:
                            cost = 0.0
                        elif (q > 0) == (qty > 0):
                            cost = px_
                last = st.price() if st else None
                if q and last:
                    open_pnl += (last - cost) * q
            realized -= sum(c for k, c in self.commissions.items() if k in self.fills)
            opt_ids = {f.get("exec_id") for f in self.opt_fills if f.get("exec_id")}
            realized -= sum(c for k, c in self.commissions.items() if k in opt_ids)        # option commissions too
            # OPTIONS count too (the day-loss lock must see them): today's option fills, contract by contract, from
            # the position you started the day with (at its average cost), plus the open contracts at their mark
            o_real, o_open = self._opt_day_pnl()
            realized += o_real; open_pnl += o_open
            return {"realized": round(realized, 2), "open": round(open_pnl, 2), "total": round(realized + open_pnl, 2),
                    "options": round(o_real + o_open, 2)}

    def _opt_day_pnl(self):
        real = opn = 0.0
        fills = sorted(self.opt_fills, key=lambda f: f.get("seq", 0))
        keys = {f["symbol"] for f in fills} | set(self.opt_positions)
        for key in keys:
            pos = self.opt_positions.get(key) or {}
            mult = float(pos.get("mult") or 100)
            mine = [f for f in fills if f["symbol"] == key]
            net = sum(f["shares"] * (1 if f["side"] in ("BOT", "BUY") else -1) for f in mine)
            q = float(pos.get("qty") or 0) - net                     # what you held before today's fills
            cost = (float(pos.get("avg_cost") or 0) / mult) if q else 0.0
            for f in mine:
                qty, px_ = f["shares"] * (1 if f["side"] in ("BOT", "BUY") else -1), f["price"]
                if q == 0 or (q > 0) == (qty > 0):
                    nq = q + qty
                    cost = (q * cost + qty * px_) / nq if nq else 0.0
                    q = nq
                else:
                    closed = min(abs(q), abs(qty))
                    real += closed * (px_ - cost) * (1 if q > 0 else -1) * mult
                    q += qty
                    if q == 0:
                        cost = 0.0
                    elif (q > 0) == (qty > 0):
                        cost = px_
            if q and pos:
                b, a, last = pos.get("bid"), pos.get("ask"), pos.get("last")
                mark = (b + a) / 2 if b and a else last
                if mark:
                    opn += (mark - cost) * q * mult
        return real, opn

    # ---- levels drawn on the chart -------------------------------------------

    def add_level(self, symbol, price, t=None, kind="extra"):
        """An extra level, or (kind "sneaky") a SNEAKY PIVOT you marked: a line on the chart and the ladder, watched for
        reloaders like the pivot."""
        with self.lock:
            st = self._st(symbol)
            if st is None or not price or price <= 0:
                return False
            price = round(float(price), 4)
            lv = st.play.setdefault("sneaky_levels" if kind == "sneaky" else "extra_levels", [])
            if any(price_key(price) == price_key(x) for x in lv):
                return True
            lv.append(price)
            if st.book is not None:  # depth is on: start watching it right away
                for side in (BID, ASK):
                    key = (side, price_key(price))
                    if key not in st.trackers:
                        st.trackers[key] = LevelTracker(symbol, price, side, "extra", self.cfg["reload"], t or self.last_t)
            self._rec({"ev": "level", "t": t or self.last_t, "sym": symbol, "px": price, "on": True, "kind": kind})
            self._save_plays()
            return True

    def set_zone(self, symbol, lo, hi, on=True, t=None):
        """A ZONE you drew on the chart (two prices): part of the PS60 story's HIGH ATTENTION from the moment it is
        drawn, saved with the play. on=False removes the zone that contains / matches lo..hi."""
        with self.lock:
            st = self._st(symbol)
            if st is None:
                return False
            zs = st.play.setdefault("zones", [])
            try:
                lo, hi = sorted((round(float(lo), 4), round(float(hi), 4)))
            except (TypeError, ValueError):
                return False
            if on:
                if lo <= 0 or hi - lo < 1e-9:
                    return False
                if not any(abs(z[0] - lo) < 1e-6 and abs(z[1] - hi) < 1e-6 for z in zs):
                    zs.append([lo, hi])
            else:
                keep = [z for z in zs if not (z[0] - 1e-6 <= lo and hi <= z[1] + 1e-6)]
                if len(keep) == len(zs):
                    return False
                st.play["zones"] = keep
            self._rec({"ev": "zone", "t": t or self.last_t, "sym": symbol, "lo": lo, "hi": hi, "on": bool(on)})
            self._save_plays()
            return True

    def set_play_setup(self, symbol, fields, t=None):
        """The trader's inputs for a play, all at once: side, pivot, 2nd entry, target, stop, mp, atr, notes.
        Everything else (grade, MP vs ATR, brackets, risk sizing) derives from these. Returns (ok, reason)."""
        with self.lock:
            st = self._st(symbol)
            if st is None:
                return False, "unknown symbol"
            p = st.play

            def num(k):
                v = fields.get(k)
                if v in (None, ""):
                    return None
                try:
                    v = float(v)
                except (TypeError, ValueError):
                    raise ValueError(f"{k} must be a number")
                if v <= 0:
                    raise ValueError(f"{k} must be positive")
                return v
            try:
                trigger = num("trigger") if "trigger" in fields else p.get("trigger")
                second = num("second_entry") if "second_entry" in fields else p.get("second_entry")
                target = num("mp") if "mp" in fields else num("target") if "target" in fields else p.get("target")
                stop = num("stop") if "stop" in fields else p.get("stop")
                atr = num("atr") if "atr" in fields else p.get("atr")
                side = fields.get("side", p["side"])
                # typed levels pick the side unless you picked it yourself with L/S: a stop above the target is a
                # short, a stop below it a long (then a 2nd entry under the pivot a short, over it a long)
                if "side" not in fields and not p.get("side_set"):
                    if stop and target and stop != target:
                        side = "short" if stop > target else "long"
                    elif trigger and second and trigger != second:
                        side = "short" if second < trigger else "long"
                if side not in ("long", "short"):
                    return False, "side must be long or short"
            except ValueError as exc:
                return False, str(exc)
            if trigger and second:
                if side == "long" and second <= trigger:
                    return False, f"2nd entry {second} must be ABOVE the pivot {trigger} for a long"
                if side == "short" and second >= trigger:
                    return False, f"2nd entry {second} must be BELOW the pivot {trigger} for a short"
            # the stop sits on the risk side of the entry you actually take: the 2nd entry when one is drawn
            # (a short's stop above its 2nd entry can sit UNDER the pivot — that is the PS60 stop), else the pivot
            why = self._stop_conflict(side, trigger, second, stop)
            if why:
                return False, why
            if trigger and target:
                if side == "long" and target <= trigger:
                    return False, f"MP {target} must be above the pivot {trigger} for a long"
                if side == "short" and target >= trigger:
                    return False, f"MP {target} must be below the pivot {trigger} for a short"
            p["side"] = side
            if "side" in fields:
                p["side_set"] = True
            if "notes" in fields:
                p["notes"] = str(fields.get("notes") or "")[:200]
            if "setup" in fields:
                p["setup"] = str(fields.get("setup") or "")[:40]
            p["atr"] = atr
            for role, val in (("trigger", trigger), ("second_entry", second), ("target", target), ("stop", stop)):
                if val != p.get(role):
                    if role == "trigger" and val is None:
                        continue
                    self.set_play_level(symbol, role, val, t, source="PLAY SETUP")
            p["mp"] = p.get("target")        # MP is the level: one number, two names
            st.invalidation_armed = False   # new stop / target: don't retire the play on the next tick by accident
            self._rec({"ev": "setup", "t": t or self.last_t, "sym": symbol,
                       "fields": {k: p.get(k) for k in ("side", "trigger", "second_entry", "target", "stop", "mp", "atr", "notes")}})
            self._save_plays()
            return True, None

    def log(self, symbol, text, t=None, kind="auto"):
        """One line in the symbol's trade log (the journal): what you set, what you said, what you typed."""
        t = t if t is not None else self.last_t
        if self.desk is not None:
            self.desk.add_note(t, text, symbol, kind=kind)
        else:
            self.notes_list.append({"t": t, "symbol": symbol, "text": text, "kind": kind})

    def symbol_log(self, symbol, limit=40):
        notes = self.desk.notes if self.desk is not None else self.notes_list
        out = [n for n in notes if n.get("symbol") == symbol]
        return [{"t": n["t"], "text": n["text"], "kind": n.get("kind", "typed")} for n in out[-limit:]]

    LEVEL_NAMES = {"trigger": "PIVOT", "second_entry": "2ND ENTRY", "target": "TARGET", "stop": "STOP"}

    def set_play_level(self, symbol, role, price, t=None, source="setup", alt=False):
        """Set (or clear, with price None) the play's trigger / second_entry / target / stop
        from the chart, re-point the reload trackers, and save plays.json. ``alt`` = the play's OTHER SIDE."""
        if alt:
            return self._set_alt_level(symbol, role, price, t, source)
        with self.lock:
            st = self._st(symbol)
            if st is None or role not in ("trigger", "second_entry", "target", "stop"):
                return False
            if price is not None:
                price = round(float(price), 4)
                if price <= 0:
                    return False
            if role == "trigger" and price is None:
                old = st.play.get("trigger")
                if old is None:
                    return True
                st.play["trigger"] = None
                st.play["watch"] = True              # no pivot: a watch-only chart until you draw one
                for side in (BID, ASK):
                    tr = st.trackers.get((side, price_key(old)))
                    if tr is not None:
                        roles = [r for r in tr.role.split("+") if r != "trigger"]
                        if roles:
                            tr.role = "+".join(roles)
                        else:
                            del st.trackers[(side, price_key(old))]
                self.log(symbol, f"PIVOT removed (was {narrative.px(old)})", t, kind="level")
                self._rec({"ev": "play_level", "t": t or self.last_t, "sym": symbol, "role": role, "px": None})
                self._save_plays()
                return True
            if role == "trigger" and price is not None:
                st.play["watch"] = False  # a typed-in ticker becomes a real play once it has a pivot
                if st.play.get("trigger") is None and (st.play.get("trade_as_set") or st.play.get("opt_key")):
                    # a NEW pivot is a new play: yesterday's contract link never rides today's 2nd entry. The next 2nd
                    # entry asks STOCK / OPTIONS again (a contract picked in OPTIONS is offered only if it fits the side)
                    self._unlink_contract(st, t, "a new pivot: the 2nd entry trades the STOCK unless you pick a contract that fits")
            old = st.play.get(role)
            st.play[role] = price
            if role == "second_entry" and price is not None and (old is None or price_key(old) != price_key(price)):
                st.play["auto"] = True      # a 2nd entry drawn (or moved) is an automatic entry again
            if (old is None) != (price is None) or (old is not None and price is not None and price_key(old) != price_key(price)):
                name = self.LEVEL_NAMES[role]
                self.log(symbol, f"{name} cleared (was {narrative.px(old)})" if price is None else
                         f"{name} set {narrative.px(price)}" if old is None else f"{name} {narrative.px(old)} → {narrative.px(price)}",
                         t, kind="level")
            if role == "trigger" and old is not None and price is not None and price_key(old) != price_key(price):
                # every pivot move leaves a trace: where it was, where it is, and what moved it
                self._message("warn", f"{symbol}: PIVOT moved {narrative.px(old)} -> {narrative.px(price)} (from {source})",
                              t or self.last_t, symbol)
            if role == "target":
                st.play["mp"] = price
            if role in ("target", "stop", "second_entry") and price is not None:
                self._side_from_levels(st, t)
                self._opt_fit(st, t)
            if role in ("trigger", "second_entry"):
                # drop the old trackers for this role (unless another role shares that price)
                if old is not None:
                    for side in (BID, ASK):
                        tr = st.trackers.get((side, price_key(old)))
                        if tr is not None:
                            roles = [r for r in tr.role.split("+") if r != role]
                            if roles:
                                tr.role = "+".join(roles)
                            else:
                                del st.trackers[(side, price_key(old))]
                if price is not None and st.book is not None:
                    for side in (BID, ASK):
                        key = (side, price_key(price))
                        tr = st.trackers.get(key)
                        if tr is None:
                            st.trackers[key] = LevelTracker(symbol, price, side, role, self.cfg["reload"], t or self.last_t)
                        elif role not in tr.role.split("+"):
                            tr.role = role + "+" + tr.role if tr.role == "auto" else tr.role + "+" + role
            self._rec({"ev": "play_level", "t": t or self.last_t, "sym": symbol, "role": role, "px": price})
            self._save_plays()
            if role == "second_entry" and price is not None and old is None and source == "chart":
                self._auto_stop(symbol, st.play, False, price, t)
            if role == "second_entry" and price is None and old is not None:
                self._orphan_auto_stop(symbol, st.play, False, t)
            return True

    def _auto_stop(self, symbol, lines, alt, se, t):
        """A NEW 2nd entry drawn on the chart with no stop on its side: the STOP goes in ``trading.auto_stop_dollars``
        ($1) away — under a long's 2nd entry, over a short's. Drag it where you want it."""
        d = float((self.cfg.get("trading") or {}).get("auto_stop_dollars") or 0)
        if d <= 0 or lines.get("stop") is not None:
            return
        st = self._st(symbol)
        side = lines.get("side") or (("short" if st.play.get("side", "long") == "long" else "long") if alt else st.play.get("side", "long"))
        stop = round(se - d if side == "long" else se + d, 2)
        if stop <= 0:
            return
        if alt:
            self._set_alt_level(symbol, "stop", stop, t, source="auto stop")
        else:
            self.set_play_level(symbol, "stop", stop, t, source="auto stop")
        lines["auto_stop_px"] = stop          # the stop the DESK drew: it goes with its 2nd entry while you are not in
        self._message("info", f"{symbol}: STOP set ${d:g} from your 2nd entry at {narrative.px(stop)} — drag it to move it", t or self.last_t, symbol)

    def _orphan_auto_stop(self, symbol, lines, alt, t):
        """Its 2nd entry taken off before any trade: the stop the desk drew with it goes too (one you moved or drew stays)."""
        px = lines.get("auto_stop_px")
        lines.pop("auto_stop_px", None)
        if px is None or lines.get("stop") is None or abs(float(lines["stop"]) - float(px)) > 1e-9:
            return
        tr = getattr(self, "trader", None)
        try:
            held = bool(tr and int(tr.broker.position(symbol))) or any(int(p.get("qty") or 0) for p in list(self.opt_positions.values()) if p.get("symbol") == symbol)
        except Exception:
            held = True
        if held or self._pending(symbol):
            return                                # in a trade (or an order working): the stop is protecting it, never touched here
        if alt:
            self._set_alt_level(symbol, "stop", None, t, source="2nd entry off")
        else:
            self.set_play_level(symbol, "stop", None, t, source="2nd entry off")

    def _set_alt_level(self, symbol, role, price, t=None, source="setup"):
        """The OTHER SIDE of a play (the short under a long, the long over a short): its own pivot, 2nd entry, stop and
        target. Only its 2nd entry becomes an order; whichever side's 2nd entry fills first, the other is cancelled."""
        with self.lock:
            st = self._st(symbol)
            if st is None or role not in ("trigger", "second_entry", "target", "stop"):
                return False
            if price is not None:
                price = round(float(price), 4)
                if price <= 0:
                    return False
            alt = st.play.setdefault("alt", {})
            old = alt.get(role)
            alt[role] = price
            if role == "second_entry" and price is not None and (old is None or price_key(old) != price_key(price)):
                alt["auto"] = True
            other = "SHORT" if st.play.get("side", "long") == "long" else "LONG"
            name = f"{other} {self.LEVEL_NAMES[role]}"
            if (old is None) != (price is None) or (old is not None and price is not None and price_key(old) != price_key(price)):
                self.log(symbol, f"{name} cleared (was {narrative.px(old)})" if price is None else
                         f"{name} set {narrative.px(price)}" if old is None else f"{name} {narrative.px(old)} → {narrative.px(price)}",
                         t, kind="level")
            if not any(alt.get(r) for r in ("trigger", "second_entry", "target", "stop")):
                st.play.pop("alt", None)
            self._save_plays()
            if role == "second_entry" and price is not None and old is None and source == "chart" and st.play.get("alt"):
                self._auto_stop(symbol, st.play["alt"], True, price, t)
            if role == "second_entry" and price is None and old is not None and st.play.get("alt"):
                self._orphan_auto_stop(symbol, st.play["alt"], True, t)
            return True

    def set_side_level(self, symbol, side, role, price, t=None, source="chart"):
        """Draw a level for a SIDE (long or short). The play's own side takes it; the other side goes to the play's OTHER
        SIDE. A blank play takes the side you draw first."""
        with self.lock:
            st = self._st(symbol)
            if st is None or side not in ("long", "short"):
                return False
            p = st.play
            blank = not any(p.get(r) for r in ("trigger", "second_entry", "target", "stop"))
            if blank and side != p.get("side", "long"):
                p["side"] = side; p["side_set"] = True
                if p.get("alt"):                       # what was the other side is now the play's own side
                    p.pop("alt", None)
            if side == p.get("side", "long"):
                return self.set_play_level(symbol, role, price, t, source)
            return self._set_alt_level(symbol, role, price, t, source)

    def clear_play(self, symbol, t=None):
        """Wipe every level off a play (pivot, 2nd entry, target, stop, extras): a blank chart, still watched."""
        with self.lock:
            st = self._st(symbol)
            if st is None:
                return False
            t = t or self.last_t
            for role in ("second_entry", "target", "stop"):
                if st.play.get(role) is not None:
                    self.set_play_level(symbol, role, None, t, source="CLEAR PLAY")
            for px_ in list(st.play.get("extra_levels") or []):
                self.remove_level(symbol, px_, t)
            for px_ in list(st.play.get("sneaky_levels") or []):
                self.remove_level(symbol, px_, t, kind="sneaky")
            st.play.pop("alt", None)              # and the other side
            st.play["zones"] = []                 # your zones too: a blank chart
            st.play.pop("auto_stop_px", None)
            st.play["side_set"] = False          # a blank chart has no side until you pick one or draw it
            old = st.play.get("trigger")
            if old is not None:
                st.play["trigger"] = None
                for side in (BID, ASK):
                    tr = st.trackers.get((side, price_key(old)))
                    if tr is not None:
                        roles = [r for r in tr.role.split("+") if r != "trigger"]
                        if roles:
                            tr.role = "+".join(roles)
                        else:
                            del st.trackers[(side, price_key(old))]
                self.log(symbol, f"PIVOT cleared (was {narrative.px(old)})", t, kind="level")
            st.play["watch"] = True
            st.play["mp"] = None
            st.invalidation_armed = False
            st.retired = None
            self.log(symbol, "PLAY cleared — blank chart", t, kind="level")
            self._rec({"ev": "play_clear", "t": t, "sym": symbol})
            self._save_plays()
            return True

    def remove_level(self, symbol, price, t=None, kind="extra"):
        with self.lock:
            st = self._st(symbol)
            if st is None:
                return False
            k = price_key(price)
            fld = "sneaky_levels" if kind == "sneaky" else "extra_levels"
            lv = st.play.get(fld, [])
            st.play[fld] = [x for x in lv if price_key(x) != k]
            for side in (BID, ASK):
                tr = st.trackers.get((side, k))
                if tr is not None and tr.role == "extra":
                    del st.trackers[(side, k)]
            self._rec({"ev": "level", "t": t or self.last_t, "sym": symbol, "px": price, "on": False, "kind": kind})
            self._save_plays()
            return True

    @staticmethod
    def _close_on(st, date_str):
        """The stock's close on a given day (YYYY-MM-DD) from its daily bars, or None."""
        import datetime as _dt
        for t0, bar in st.daily.items():
            day = _dt.datetime.fromtimestamp(t0 + 43200, _dt.timezone.utc).date().isoformat()   # noon: either day-start convention
            if day == str(date_str)[:10]:
                return float(bar[3])
        return None

    def _save_plays(self):
        """Write plays.json back so drawn levels survive a restart."""
        if not self.plays_path:
            return
        import json
        keep = ("symbol", "side", "side_set", "trigger", "second_entry", "target", "stop", "mp", "atr", "extra_levels", "sneaky_levels", "zones", "notes", "setup", "active", "watch",
                "auto", "exchange", "primary_exchange", "currency", "alt", "trade_as", "trade_as_set", "opt_key", "opt_qty")
        def row(p):
            r = {("pivot" if k == "trigger" else k): p[k] for k in keep if k in p}
            return r
        out = {"plays": [row(p) for p in self.plays]}
        tmp = self.plays_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=2)
        import os
        os.replace(tmp, self.plays_path)

    @staticmethod
    def order_state(o):
        """One word the trader can trust, from IBKR's status (IBKR is authoritative; submitted is not filled)."""
        s = o.get("status") or ""
        filled = o.get("filled") or 0
        if s == "Filled":
            return "FILLED"
        if s in ("Cancelled", "ApiCancelled"):
            return "CANCELED"
        if s == "PendingCancel":
            return "CANCEL PENDING"
        if s == "Inactive":
            return "REJECTED"
        if filled and (o.get("remaining") or 0) > 0:
            return "PARTIALLY FILLED"
        if s in ("Submitted", "PreSubmitted"):
            return "ACKNOWLEDGED"
        if s in ("PendingSubmit", "ApiPending"):
            return "SUBMITTED"
        if s == "Done":
            return "CLOSED"       # left IBKR's working list without a final status: never assume it filled
        return s.upper() or "CREATED"

    def _pending(self, symbol=None):
        with self.lock:          # a copy, taken under the lock: callers on other threads can iterate it safely
            return [dict(o) for o in self.orders.values()
                    if o.get("status") not in self.DONE_STATUSES + ("Done",)
                    and (symbol is None or o.get("symbol") == symbol)]

    def recently_filled(self, symbol, roles, t, within=10.0):
        """An order of these roles on this symbol filled and the broker hasn't reported the position since (so the
        position on screen may still include those shares)."""
        with self.lock:
            pt = self.pos_t.get(symbol, -1e18)
            return any(o.get("symbol") == symbol and o.get("role") in roles and o.get("status") == "Filled"
                       and t - o.get("t", -1e9) < within and o.get("t", -1e9) > pt for o in self.orders.values())

    def _position_view(self, symbol, price):
        qty = sum(p["qty"] for (a, s), p in self.positions.items() if s == symbol)
        if not qty:
            return None
        cost = sum(p["qty"] * p["avg_cost"] for (a, s), p in self.positions.items() if s == symbol) / qty
        pnl = (price - cost) * qty if price else None
        return {"qty": qty, "avg_cost": round(cost, 4), "pnl": None if pnl is None else round(pnl, 2)}

    def on_connection(self, state, detail, t, market_data_type=None):
        """state: CONNECTED | CONNECTING | RECONNECTING | DISCONNECTED | DATA_LOST | FEED_DOWN (DEMO / REPLAY for the
        practice feeds). DATA DELAYED is CONNECTED with market_data_type 3 / 4 (the status line says so)."""
        with self.lock:
            self._clock(t)
            self._rec({"ev": "conn", "t": t, "state": state, "detail": detail})
            prev = self.connection["state"]
            self.connection.update(state=state, since=t, detail=detail)
            if state == "CONNECTED":
                self.connection["ever_connected"] = True
                if prev != "CONNECTED":
                    for _st in self.syms.values():          # a new connection: identical prints count from the 1st again
                        pg = _st.__dict__.get("_pguard")
                        if pg is not None:
                            pg.new_connection()
            if market_data_type is not None:
                self.connection["market_data_type"] = market_data_type
            if state in ("DISCONNECTED", "DATA_LOST"):
                # IBKR subscriptions do not survive this; depth must be requested again
                for sym in list(self.slots):
                    self._deactivate(sym, t, record=True, reason=state)
            if state != prev:
                level = "info" if state == "CONNECTED" else "warn"
                self._message(level, f"connection {state}{': ' + detail if detail else ''}", t)

    def set_data_problem(self, text, t):
        """IBKR said why there is no data (subscriptions): the MKT light carries it until ticks flow."""
        with self.lock:
            if text != self.data_problem:
                self.data_problem = text
                self._message("error", text, t)

    def on_market_data_type(self, mdt, t, symbol=None):
        """IBKR says per request whether it is live (1) or delayed (3) / frozen. The light shows the worst one:
        one delayed symbol is enough to say the data is not all live."""
        with self.lock:
            if symbol:
                self.mdt_by_sym[symbol] = mdt
                worst = max(self.mdt_by_sym.values())
                self.connection["market_data_type"] = worst
                if mdt in (3, 4):
                    self._message("warn", f"{symbol}: IBKR is sending DELAYED data (no live subscription)", t, symbol)
            else:
                self.connection["market_data_type"] = mdt

    def _speech_view(self):
        """Which voice the desk speaks in, and how the cloud voice did last (VOICE button)."""
        from . import tts
        sc = self.cfg.get("speech") or {}
        cloud = tts.ready(self.cfg)
        return {"engine": "cloud" if cloud else "browser", "wanted": sc.get("engine") or "auto",
                "ok": tts.STATUS["ok"] if cloud else None, "error": tts.STATUS["error"] if cloud else ""}

    def desk_alert(self, symbol, label, text, words, t, side=None, price=None):
        """A desk call (halt, expiry, option stop): on the alert list, in the log, and spoken."""
        with self.lock:
            alert = {"t": t, "symbol": symbol, "label": label, "price": price, "side": side, "role": "desk",
                     "text": text, "words": words, "key": f"{round(t, 2)}|{symbol}|{label}"}
            self.alerts.appendleft(alert); self._rec(dict(alert, ev="alert")); self.log(symbol, text, t, kind="level")
        for fn in self.listeners:
            try:
                fn(alert)
            except Exception:
                pass

    def on_halt(self, symbol, value, t):
        """IBKR's halted tick (49): 1 = halted, 2 = volatility pause (LULD), 0 = trading. Said once each way."""
        st = self._st(symbol)
        if st is None:
            return
        halted = value in (1, 2, 1.0, 2.0)
        was = getattr(st, "halted", False)
        st.halted = halted
        st.halt_kind = ("LULD PAUSE" if value in (2, 2.0) else "HALTED") if halted else None
        if halted and not was:
            st.halt_t = t
            what = "a volatility pause (LULD), usually 5 minutes" if value in (2, 2.0) else "a trading halt"
            self.desk_alert(symbol, "HALTED", f"{symbol} is HALTED: {what}. Nothing trades; your working orders sit until it reopens, "
                                              f"and it can reopen far from here.", f"{symbol} is halted.", t)
        elif was and not halted:
            self.desk_alert(symbol, "RESUMED", f"{symbol} is trading again after the halt. Check your orders and stops: the open can gap.",
                            f"{symbol} is trading again.", t)

    def on_commission(self, exec_id, amount):
        """Commissions per execution (IBKR commissionReport): taken off the day P&L and the loss lock."""
        if amount is None:
            return
        with self.lock:
            self.commissions[exec_id] = float(amount)

    def clear_positions(self):
        with self.lock:
            self.positions.clear()

    def on_depth_rejected(self, symbol, code, msg, t):
        with self.lock:
            st = self._st(symbol)
            if st is None:
                return
            self._clock(t)
            self._rec({"ev": "depth_rejected", "t": t, "sym": symbol, "code": code, "msg": msg})
            st.rejected_until = t + self.cfg["depth"]["reject_cooldown_seconds"]
            st.last_error = f"{code}: {msg}"
            st.depth_refused = self.depth_refusal(code, msg)
            self._message("error", f"{symbol}: Level II refused by IBKR [{code}]: {st.depth_refused}", t, symbol, category="MARKET DATA")
            if symbol in self.slots:
                self._deactivate(symbol, t, record=True, reason=f"rejected {code}")

    @staticmethod
    def depth_refusal(code, msg):
        """What a Level II refusal means and what fixes it, in plain words."""
        try:
            code = int(code)
        except (TypeError, ValueError):
            code = 0
        if code == 309:
            return ("too many depth lines open: IBKR allows 3 at a time across EVERYTHING on this login (TWS depth windows, "
                    "other apps). Close the other depth windows, or lower SETTINGS > Market depth > slots")
        if code == 10092:
            return ("no Level II market data for this exchange on your account: SMART depth needs NASDAQ TotalView (and NYSE "
                    "ArcaBook / OpenBook) in IBKR Account Management > Market Data Subscriptions. Or turn SMART depth off in "
                    "SETTINGS > Market depth and the single-exchange book is used")
        return f"{msg} (the desk asks again in a moment; the tape and quote still read)"

    def on_contract(self, symbol, details, t):
        """Contract details from IBKR: the instrument is valid, and this is its minimum tick (never assume a penny)."""
        from .prices import set_min_tick
        with self.lock:
            self._clock(t)
            st = self._st(symbol)
            if st is None:
                return
            st.contract = dict(details)
            tick = details.get("min_tick")
            if tick:
                set_min_tick(symbol, tick)
                st.lad_center = None      # the ladder re-grids on the real increment
            self._rec({"ev": "contract", "t": t, "sym": symbol, "details": dict(details)})
            self._message("info", f"{symbol}: {details.get('long_name') or 'contract'} resolved · tick {tick} · conId {details.get('con_id')}", t, symbol)

    def on_error(self, symbol, code, msg, t, level="warn", category=None):
        with self.lock:
            self._clock(t)
            self._rec({"ev": "error", "t": t, "sym": symbol, "code": code, "msg": msg, "category": category})
            st = self._st(symbol) if symbol else None
            if st is not None:
                st.last_error = f"{code}: {msg}"
            self._message(level, f"{symbol + ': ' if symbol else ''}[{code}] {msg}", t, symbol, category=category)

    def _message(self, level, text, t, symbol=None, category=None):
        # IBKR repeats the same refusal for every request on a symbol (history, daily, quotes): one line per
        # symbol and text within five minutes, with a count, so the panel says each thing once
        for m in self.messages:
            if m["text"] == text and m.get("symbol") == symbol and t - m["t"] <= 300:
                m["n"] = m.get("n", 1) + 1
                m["t"] = t
                return
        self.messages.appendleft({"t": t, "level": level, "text": text, "symbol": symbol, "category": category})

    # ---- depth slots ---------------------------------------------------------

    def _activate(self, symbol, t, reason=""):
        st = self.syms[symbol]
        self.slots[symbol] = t
        if symbol not in self.slot_order:
            if None not in self.slot_order:
                self.slot_order.append(None)
                self.slot_changes.append(None)
                self._slot_last.append(None)
            i = self.slot_order.index(None)
            self.slot_order[i] = symbol
            self.slot_changes[i] = {"prev": self._slot_last[i], "symbol": symbol, "t": t, "reason": reason}
        st.depth_active = True
        st.depth_since = t
        st.depth_t = None
        st.book = Book(self.cfg["depth"]["rows_requested"])
        st.resync_until = t + self.cfg["reload"]["resync_grace_seconds"]
        p = st.play
        wanted = [(p["trigger"], "trigger")] if p.get("trigger") else []
        if p.get("second_entry"):
            wanted.append((p["second_entry"], "second_entry"))
        wanted += [(lv, "extra") for lv in p.get("extra_levels", [])] + [(lv, "extra") for lv in p.get("sneaky_levels", [])]
        for price, role in wanted:
            for side in (BID, ASK):
                key = (side, price_key(price))
                if key in st.trackers:
                    if role not in st.trackers[key].role.split("+"):
                        st.trackers[key].role += "+" + role
                    continue
                st.trackers[key] = LevelTracker(symbol, price, side, role, self.cfg["reload"], t)

    def _deactivate(self, symbol, t, record=False, reason=""):
        st = self.syms[symbol]
        self.slots.pop(symbol, None)
        if symbol in self.slot_order:
            i = self.slot_order.index(symbol)
            self.slot_order[i] = None
            self._slot_last[i] = symbol
        st.depth_active = False
        st.book = None
        st.trackers = {}
        st.voice_pending.clear()          # nothing half-decided survives the slot going away
        st.sizes = {ASK: {}, BID: {}}
        if record:
            self._rec({"ev": "slot", "t": t, "sym": symbol, "on": False, "reason": reason})

    def apply_slot(self, symbol, on, t, reason=""):
        with self.lock:
            if symbol not in self.syms:
                return
            self._clock(t)
            self._rec({"ev": "slot", "t": t, "sym": symbol, "on": on, "reason": reason})
            if on:
                if symbol not in self.slots:
                    self._activate(symbol, t, reason)
            else:
                self._deactivate(symbol, t)

    def set_pinned(self, symbol, on, t=None):
        """Pin a symbol to a depth slot: it gets a ladder and is never rotated out."""
        with self.lock:
            if symbol not in self.syms:
                return False
            if on:
                self.pinned.add(symbol)
            else:
                self.pinned.discard(symbol)
            self._rec({"ev": "ui", "t": t or self.last_t, "pin": symbol, "on": bool(on)})
            return True

    def set_auto_rotate(self, on, t=None):
        with self.lock:
            self.auto_rotate = bool(on)
            self._rec({"ev": "ui", "t": t or self.last_t, "auto_rotate": self.auto_rotate})

    def _protected(self, t=None):
        """Symbols with a live reload (or a pending verdict), or a proven reloader still RELOADING or STILL THERE, are
        never rotated out: a level's conviction only keeps moving while the desk can see its book."""
        t = self.last_t if t is None else t
        out = set()
        for sym in self.slots:
            trackers = self.syms[sym].trackers.values()
            if any(tr.state in (RELOAD, GONE_PENDING) or tr.stage(t) in (ACTIVE, FADING) for tr in trackers):
                out.add(sym)
        return out

    def best_conviction(self, st, t):
        """The strongest proven reloader on this symbol right now, 0..1."""
        return max((tr.conviction(t) for tr in st.trackers.values()), default=0.0)

    def _knows(self, st, side, t):
        """SOMEBODY KNOWS SOMETHING for a level side: a reload BUYER (bid) is confirmed by short-dated out-of-the-money CALLS
        bought at the ask; a reload SELLER (ask) by PUTS. Cached for the tick so twenty rows cost one read."""
        cp = "C" if side == BID else "P"
        cache = st.__dict__.setdefault("_knows_cache", {})
        # good until a new print lands on this name or a second passes: twenty rows, the reloaders list, the pane
        # and the rotation all share one read, and a quiet name costs nothing between prints
        stamp = (self.flow.seq.get(st.symbol, 0), int(t))
        hit = cache.get(cp)
        if hit is not None and hit[0] == stamp:
            return hit[1]
        index = st.symbol in set(self.cfg.get("flow", {}).get("index_symbols", ()))
        k = self.flow.knows(st.symbol, cp, t, index=index)
        k["cp"] = cp
        k["words"] = self._knows_words(k, side)
        cache[cp] = (stamp, k)
        return k

    @staticmethod
    def _knows_words(k, side):
        what = "calls" if k["cp"] == "C" else "puts"
        who = "buyer" if side == BID else "seller"
        money = lambda v: f"${v / 1e6:.1f}M" if v >= 1e6 else f"${v / 1e3:.0f}K"
        if k["knows"]:
            top = k["top"] or {}
            strike = f" {narrative.px(top['strike'])} strike" if top.get("strike") is not None else ""
            dte = f", {round(top['dte'])} day{'s' if round(top['dte']) != 1 else ''} out" if top.get("dte") is not None else ""
            return (f"SOMEBODY KNOWS SOMETHING: {money(k['dollars'])} of short-dated out-of-the-money {what} bought at the ask in {k['window_minutes']} min"
                    f" ({k['prints']} prints{', ' + str(k['sweeps']) + ' sweeps' if k['sweeps'] else ''}){strike}{dte}. The flow agrees with the reload {who}.")
        if k["dollars"] > 0:
            return (f"some short-dated {what} coming in ({money(k['dollars'])} in {k['prints']} prints), not enough yet" +
                    (f"; the other side has more ({money(k['against'])})" if k["against"] > k["dollars"] else ""))
        return f"no short-dated out-of-the-money {what} at the ask in the last {k['window_minutes']} min"

    def best_knows(self, st, t):
        """The strongest SOMEBODY KNOWS SOMETHING score on this symbol, either side, 0..1."""
        return max(self._knows(st, BID, t)["score"], self._knows(st, ASK, t)["score"])

    def _rotation_ranking(self, t):
        """The proximity ranking, with a live reloader pulling a symbol closer: distance x (1 - weight x conviction).
        The watchlist's own ranking (``ranking``) stays distance-only so the order you read never jumps."""
        w = float(self.cfg["depth"].get("conviction_weight", 0.0))
        wf = float(self.cfg["depth"].get("flow_weight", 0.0))
        out = []
        for sym, d in self.ranking(t):
            st = self.syms[sym]
            cv = self.best_conviction(st, t) if w > 0 else 0.0
            kf = self.best_knows(st, t) if wf > 0 else 0.0
            out.append((sym, d * max(0.0, 1.0 - w * cv - wf * kf)))
        out.sort(key=lambda r: (r[1], r[0]))
        return out

    def _auto_levels(self, st, t):
        rc = self.cfg["reload"]
        if not rc["auto_levels"]:
            return
        for side in (BID, ASK):
            lv = st.book.levels(side, 1)
            if not lv or lv[0][1] < rc["auto_min_display_shares"]:
                continue
            price = lv[0][0]
            key = (side, price_key(price))
            if key in st.trackers:
                continue
            autos = [k for k, tr in st.trackers.items() if tr.role == "auto"]
            if len(autos) >= rc["max_auto_levels"]:
                idle = [k for k in autos if st.trackers[k].state in (WATCHING, BUILDING)
                        and not st.trackers[k].absorbed_window(t)]
                if not idle:
                    continue
                del st.trackers[min(idle, key=lambda k: st.trackers[k].last_active)]
            tr = LevelTracker(st.symbol, price, side, "auto", rc, t)
            st.trackers[key] = tr
            tr.on_book(st.book, t, judge=True)

    # ---- clock ---------------------------------------------------------------

    def tick(self, t, allocate_slots=True):
        """Time-based evaluation. Returns slot commands for the adapter."""
        with self.lock:
            self._clock(t)
            self._rec({"ev": "tick", "t": t})       # replay runs its ticks at exactly these times
            if self.connection["state"] == "CONNECTED" and self.opt_sim(t):
                self.practice_opt_tick(t)          # after hours on paper: the contracts you hold / chart move with the stock
            self._pace_tick(t)
            self._levels_tick(t)
            self._story_tick(t)
            if (self.score.open or self.score.day is None) and t - getattr(self, "_score_t", -1e9) >= 1.0:
                self._score_t = t
                try:
                    self.score.tick(t, {sym: st.price() for sym, st in self.syms.items() if st.price()})
                except Exception:
                    log.exception("scorecard tick")
            rc = self.cfg["reload"]
            if self.desk is not None and t - getattr(self, "_recon_t", -1e9) >= 5:
                self._recon_t = t
                try:
                    self.desk.reconcile(t)          # the journal's open trades are real positions
                except Exception as exc:
                    self._message("warn", f"journal check: {exc}", t)
            # the charted contract's book (live): PULL / STACK judged on the same quarter-second reads as the stocks
            for key, bk in list((getattr(self, "opt_dbook", None) or {}).items()):
                pb = self.opt_dpulls.get(key)
                if pb is not None and bk.synced:
                    for side in (ASK, BID):
                        pb.on_book(bk, side, t, judge=True)
                    pb.prune(t, 600.0)
            for st in self.syms.values():
                if st.book is None:
                    continue
                # REAL / FAKE size is judged on settled reads of the book, once a tick (about every quarter second,
                # IBKR's own depth cadence), never in the middle of a burst of row operations: a delete that shifts
                # every row up looks like size leaving and coming back at every price until the burst is done
                judge = self._judge(st, t)
                for side in (ASK, BID):
                    st.pulls.on_book(st.book, side, t, judge=judge)
                st.pulls.prune(t, float(self.cfg.get("ladder", {}).get("real_memory_seconds", 3600.0)))
                if st.voice_pending:
                    self._voice_settle(st, t)
                # the tape went quiet but the quote stream moved on: the price follows the quote (never stuck)
                if (st.l1_last_raw and st.l1_last_raw != st.l1["last"] and st.tape_t is not None
                        and t - st.tape_t >= 10):
                    st.l1["last"] = st.l1_last_raw
                    st.bar_update(t, st.l1_last_raw)
                for key, tr in list(st.trackers.items()):
                    label = tr.evaluate(t, st.book)
                    if label:
                        self._emit(st, tr, label, t)
                    if (tr.role == "auto" and tr.state in (WATCHING, BUILDING) and tr.displayed <= 0
                            and not tr.absorbed_window(t) and t - tr.last_active > rc["auto_idle_seconds"]):
                        del st.trackers[key]
            self._check_plays(t)
            self._check_remounts(t)
            if not allocate_slots or self.connection["state"] not in ("CONNECTED", "DEMO"):
                return []
            return self._rotate(t)

    def big_shares_for(self, st):
        return st.big_shares if st.big_shares else self.cfg.get("ladder", {}).get("big_shares", 5000)

    def set_big_shares(self, symbol, shares, t=None):
        """The trader's bar for 'big size' on this symbol's ladder (None = back to the config default)."""
        with self.lock:
            st = self._st(symbol)
            if st is None:
                return False
            st.big_shares = float(shares) if shares else None
            for side in (ASK, BID):   # re-judge what is showing right now against the new bar
                for k, rec in st.big[side].items():
                    rec[2] = False
            self._track_big(st, ASK); self._track_big(st, BID)
            self._rec({"ev": "big", "t": t or self.last_t, "sym": symbol, "shares": st.big_shares})
            return True

    def _track_big(self, st, side, t=None):
        """Count how many separate times big size has appeared at each price (shows up, leaves for real, shows up
        again). Only on a synced book: a depth reset, a slot rotating back in or one venue re-quoting (delete +
        insert) is not a new appearance; the size has to have been gone BIG_GONE_SECONDS first."""
        if st.book is None:
            return
        t = self.last_t if t is None else t
        if not st.book.synced:
            return
        settling = t < st.resync_until      # book still being rebuilt: nothing counts as coming back
        big = self.big_shares_for(st)
        lv = st.book.levels(side)
        showing = {price_key(p): s for p, s, _n in lv}
        prices_by_key = {price_key(p): p for p, s, _n in lv}
        recs = st.big[side]
        for k, s in showing.items():
            rec = recs.get(k)        # [times, peak, showing now, gone since]
            if s >= big:
                if rec is None:
                    recs[k] = [1, s, True, None, prices_by_key[k]]
                elif not rec[2]:
                    if rec[3] is not None and t - rec[3] >= self.BIG_GONE_SECONDS and not settling:
                        rec[0] += 1
                    rec[2] = True; rec[1] = max(rec[1], s); rec[3] = None
                    if len(rec) < 5:
                        rec.append(prices_by_key[k])
                else:
                    rec[1] = max(rec[1], s)
            elif rec is not None and rec[2]:
                rec[2] = False; rec[3] = t
        for k, rec in recs.items():
            if k not in showing and rec[2]:
                rec[2] = False
                # scrolled out of the book's window is not "gone": coming back into view is not a new appearance
                rec[3] = t if (len(rec) > 4 and st.book.in_view(side, rec[4])) else None

    BIG_GONE_SECONDS = 5.0

    def _voice_sizes(self, st, side, t):
        """Call out big size showing up at a price, and big size leaving it (pulled or hit)."""
        vc = self.cfg["voice"]
        big = vc["min_shares"]
        if not big or st.book is None:
            return
        now = {price_key(p): (p, s) for p, s, _n in st.book.levels(side)}
        prev = st.sizes[side]
        who = "buyer" if side == BID else "seller"
        synced = st.book.synced and t >= st.resync_until
        for k, (p, s) in now.items():
            was = prev.get(k, (p, 0.0))[1]
            if synced and s - was >= big and s >= big:
                self._say(st, side, k, "add", t, f"{_k(s)} {who} at {narrative.px(p)}")
        for k, (p, was) in prev.items():
            s = now.get(k, (p, 0.0))[1]
            gone = was - s
            if synced and was >= big and gone >= big * 0.8:
                if s <= 0 and not st.book.in_view(side, p):
                    continue          # it scrolled out of the book's window: not pulled, just out of sight
                # hit or pulled is decided a moment later, once the prints that took it have arrived
                st.voice_pending.setdefault((side, k), (t, p, gone, who))
        st.sizes[side] = now

    def _voice_settle(self, st, t, wait=1.5):
        """Hit or pulled: what traded at that price from 3 s before it left to now (by time, not a print count)."""
        for key, (t0, p, gone, who) in list(st.voice_pending.items()):
            if t - t0 < wait:
                continue
            del st.voice_pending[key]
            side, k = key
            hit_side = "buy" if side == ASK else "sell"
            traded = sum(m[4] for m in st.memory if t0 - 3.0 <= m[0] <= t and m[1] == k and m[3] != (
                "sell" if hit_side == "buy" else "buy"))
            if traded >= gone * 0.5:
                self._say(st, side, k, "hit", t, f"{who} at {narrative.px(p)} got hit for {_k(gone)}")
            else:
                self._say(st, side, k, "pull", t, f"{who} pulled {_k(gone)} from {narrative.px(p)}")

    def symbol_flow(self, sym, t=None):
        """OPTION FLOW for one ticker: every print the desk holds for it today (newest first), and the reads the voice
        uses on it right now (SOMEBODY KNOWS SOMETHING for calls and puts, with the prints each one counted)."""
        sym = str(sym or "").upper().strip()
        t = t if t is not None else self.last_t
        with self.lock:
            prints = list(self.flow.by_symbol.get(sym, ()))
            reads = {}
            index = sym in set(self.cfg.get("flow", {}).get("index_symbols", ()))
            for cp in ("C", "P"):
                k = self.flow.knows(sym, cp, t, index=index)
                reads[cp] = {"dollars": k["dollars"], "prints": k["prints"], "sweeps": k["sweeps"], "knows": k["knows"], "ids": k.get("ids") or [],
                             "window_minutes": k["window_minutes"], "max_dte": k["max_dte"], "min_otm": k.get("min_otm")}
        prints.sort(key=lambda p: -(p.get("t") or 0))
        return {"symbol": sym, "prints": prints, "reads": reads, "t": t}

    def _receipt(self, sym, cp, ids, what=None):
        """A flow call's RECEIPT: the exact option prints it added up (by id), and their total, so the OPTION FLOW panel
        can show you the same prints and the same dollars the voice said."""
        want = {i for i in (ids or []) if i is not None}
        if not want:
            return None
        rows = [p for p in self.flow.by_symbol.get(sym, ()) if p.get("id") in want]
        return {"symbol": sym, "cp": cp, "ids": sorted(want), "dollars": round(sum(p.get("premium") or 0 for p in rows)),
                "prints": len(rows), "what": what}

    def _say(self, st, side, k, kind, t, text):
        vc = self.cfg["voice"]
        key = (side, k, kind)
        if t - st.voice_last.get(key, -1e9) < vc["repeat_seconds"]:
            return
        st.voice_last[key] = t
        item = {"t": t, "symbol": st.symbol, "kind": kind, "text": f"{st.symbol}: {text}",
                "key": f"{round(t, 2)}|{st.symbol}|{kind}|{k}"}
        self.voice.appendleft(item)
        self._rec(dict(item, ev="voice"))

    def _check_remounts(self, t):
        """REMOUNT / REJECTION calls at your levels (through the level, then back through it)."""
        pc = self.cfg["ps60"]
        if not pc["remount_alerts"]:
            return
        for st in self.syms.values():
            if t - st.remount_check_t < 15 or st.retired or not st.play["active"]:
                continue
            st.remount_check_t = t
            bars = st.bar_list(120)
            if len(bars) < 3:
                continue
            for lv in self._user_levels(st.play):
                if lv["role"] not in ("trigger", "second_entry", "extra"):
                    continue
                ev = ps60.remount(bars, lv["price"], t, pc)
                if not ev or t - ev["t"] > 180:
                    continue
                key = (price_key(lv["price"]), ev["kind"], ev["t"])
                if key in st.remounts or t - st.remount_last.get(key[:2], -1e9) < 600:
                    continue
                st.remounts.add(key)
                st.remount_last[key[:2]] = t
                label = ev["kind"].upper()
                where = f"{narrative.px(lv['price'])} ({narrative.role_name(lv['role'])})"
                if ev["kind"] == "remount":
                    text = (f"REMOUNT at {where}: price went through it (down to {narrative.px(ev['extreme'])}) and "
                            f"reclaimed it. Dan's how-to: get in above the level once volume reclaims; if it doesn't "
                            f"work in a couple of minutes, max pain is that overshoot low. Cash flow, then breakeven.")
                else:
                    text = (f"REJECTION at {where}: price went through it (up to {narrative.px(ev['extreme'])}) and "
                            f"lost it again. For a short: in below the level; the top of that overshoot is the out.")
                alert = {"t": t, "symbol": st.symbol, "label": label, "price": fmt_price(lv["price"]),
                         "side": "bid" if ev["kind"] == "remount" else "ask", "role": lv["role"], "text": text}
                alert["key"] = f"{round(t, 2)}|{st.symbol}|{label}|{alert['price']}"
                self.alerts.appendleft(alert)
                self._rec(dict(alert, ev="alert"))
                for fn in self.listeners:
                    try:
                        fn(alert)
                    except Exception:
                        pass

    def _ranking_ps60(self, st, t):
        """Cheap PS60 summary for the plays list (cached per minute)."""
        cache = getattr(st, "_ps60_cache", None)
        if cache and t - cache[0] < 5:
            return cache[1]
        bars = st.bar_list(MAX_BARS)
        ps = self._ps60(st, t, bars, st.price())
        if st.symbol not in self.slots:
            self._day_trap_watch(st, self._day_trap(st, t, st.price()), t)
            # no ladder on it, still on the desk: the conviction board (and its with-you / against-you calls) run
            # on the levels you drew; the ladder lanes just have nothing to add
            try:
                self._board(st, t, ps, self._reloaders(st, t, st.price()), None, bars)
            except Exception:
                pass
        out = {"grade": ps["grade"], "why": ps["why"], "mp": ps["mp"], "state": ps["se"]["state"], "flow": ps.get("flow")}
        st._ps60_cache = (t, out)
        return out

    def _atr(self, st, bars):
        pc = self.cfg["ps60"]
        if len(st.daily) >= 2:
            daily = [[k] + st.daily[k] for k in sorted(st.daily)]
        else:
            daily = ps60.daily_from_bars(bars)
        return ps60.atr(daily, pc["atr_days"])

    def _ps60(self, st, t, bars, price):
        """The PS60 read for one play: second entry engine, MP vs ATR, grade, sneaky pivots."""
        pc = self.cfg["ps60"]
        tc = self.cfg["trading"]
        atr_value = st.play.get("atr") or (self._atr(st, bars) if pc["atr_from_bars"] else None)
        se = ps60.second_entry(bars, st.play, t, pc)
        mp = ps60.measured_potential(st.play, price, atr_value, pc)
        shares = self.trader.default_shares if self.trader else tc["default_shares"]
        gr = ps60.grade(st.play, price, se, mp, shares, bool(st.play.get("stop")), tc)
        fc = self.cfg.get("flow", {})
        picked = board.side_picked(st.play)
        fs = self.flow.summary(st.symbol, t)
        if gr["grade"] == "READY" and fc.get("against_bias") and fs["bias"] is not None:
            against = fs["bias"] <= -fc["against_bias"] if st.play["side"] == "long" else fs["bias"] >= fc["against_bias"]
            if against and picked and (fs["calls"] + fs["puts"]) >= fc.get("against_min_premium", 0):
                gr = dict(gr, grade="WATCH", why=(gr["why"] + "; " if gr["why"] else "")
                          + f"option flow leans against this {st.play['side']}: {self.flow.context_text(st.symbol, t)}")
        gr["gates"].append({"q": "Flow with you?" if picked else "Flow?",
                            "ok": not picked or fs["bias"] is None or (fs["bias"] >= 0) == (st.play["side"] == "long") or abs(fs["bias"]) < 0.3,
                            "why": self.flow.context_text(st.symbol, t) if picked else "no side picked yet — " + self.flow.context_text(st.symbol, t)})
        # NO FLOW, NO DOUGH: Dan's confirmation. The setup comes first; then short-dated out-of-the-money money on
        # the play's side has to START and KEEP COMING. Until it does, a READY setup is held at WATCH (switchable)
        index = st.symbol in set(fc.get("index_symbols", ()))
        if picked:
            dough = self.flow.dough(st.symbol, "C" if st.play["side"] == "long" else "P", t, index)
        else:
            # no side picked: report the side the money is on, never 'against' a side nobody took
            dc, dp = self.flow.dough(st.symbol, "C", t, index), self.flow.dough(st.symbol, "P", t, index)
            dough = dict(dp if dp["dollars"] > dc["dollars"] else dc)
            dough["cp"] = "P" if dp["dollars"] > dc["dollars"] else "C"
            if dough["state"] == "FLOW AGAINST":
                dough["state"] = "NO FLOW"
            dough["text"] = "no side picked · " + dough["text"]
        dough["picked"] = picked
        gr["gates"].append({"q": "Flow confirming?", "ok": dough["state"] == "FLOW CONFIRMED", "why": dough["text"]})
        if gr["grade"] == "READY" and fc.get("no_flow_no_dough", True):
            prints = [p for p in self.flow.by_symbol.get(st.symbol, ()) if p.get("t", 0) >= t - float(fc.get("of_session_minutes", 390)) * 60.0]
            fgate = board.flow_gate(prints, st.play["side"], price, self._daily_closes(st), t, fc)
            if not fgate["gate"]:
                lane = "L5_FLOW_SIDE" if not fgate.get("cluster") else "L6_FLOW_QUALITY"
                gr = dict(gr, grade="WATCH", why=(gr["why"] + "; " if gr["why"] else "") + "ARMED — waiting the flow gate: " + fgate["lanes"][lane][1])
        self._dough_watch(st, dough, t)
        return {"se": se, "mp": mp, "grade": gr["grade"], "why": gr["why"], "gates": gr["gates"], "flow": fs,
                "dough": dough, "sneaky": self._sneaky_keep(st, ps60.sneaky_pivots(bars, atr_value, pc)), "atr": atr_value}

    @staticmethod
    def _sneaky_keep(st, sp):
        st.sneaky_auto = list(sp or [])          # the ladder marks them too
        return sp

    def _dough_watch(self, st, dough, t):
        """Say it once when the flow confirms the play's side (and once when it turns against it)."""
        prev = getattr(st, "dough_state", None)
        st.dough_state = dough["state"]
        if prev == dough["state"] or dough["state"] not in ("FLOW CONFIRMED", "FLOW AGAINST"):
            return
        if t - getattr(st, "dough_said_t", -1e9) < 600:
            return
        st.dough_said_t = t
        picked = dough.get("picked", True)
        cp = dough.get("cp") or ("C" if st.play["side"] == "long" else "P")
        side, other = ("calls", "puts") if cp == "C" else ("puts", "calls")
        money = narrative.say_dollars(dough["dollars"])
        top = dough.get("top") or {}
        exp = board.say_expiry(top.get("dte"))
        where = (f", {exp}" if exp else "") + (f", {top['strike']:g} strike" if top.get("strike") else "")
        if dough["state"] == "FLOW CONFIRMED" and not picked:
            text = f"FLOW on {st.symbol}: {dough['text']}. No side picked — this is what the money is doing."
            words = f"{money} just went into short term {side}{where}. They keep scooping up the {side}."
        elif dough["state"] == "FLOW CONFIRMED":
            text = f"FLOW CONFIRMED on {st.symbol} {st.play['side']}: {dough['text']}. The dough is here."
            words = f"{money} just went into short term {side}{where}, with your {st.play['side']}. They keep scooping up the {side}."
        else:
            text = f"FLOW AGAINST {st.symbol} {st.play['side']}: {dough['text']}."
            words = f"The flow is against your {st.play['side']}: {narrative.say_dollars(dough['against'])} went into short term {other}."
        against = dough["state"] == "FLOW AGAINST"
        alert = {"t": t, "symbol": st.symbol, "label": dough["state"] if picked else "FLOW", "price": fmt_price(st.price()), "side": "ask", "role": "flow",
                 "text": text, "premium": dough["dollars"], "cp": cp, "prints": dough["prints"], "words": words,
                 "flow": self._receipt(st.symbol, ("P" if cp == "C" else "C") if against else cp, dough.get("against_ids") if against else dough.get("ids"),
                                       "short-dated, out of the money, bought at the ask, last " + str(self.flow.cfg.get("dough_window_minutes", 30)) + " min")}
        alert["key"] = f"{round(t, 2)}|{st.symbol}|{dough['state']}"
        self.alerts.appendleft(alert)
        self._rec(dict(alert, ev="alert"))
        for fn in self.listeners:
            try:
                fn(alert)
            except Exception:
                pass

    def _check_plays(self, t):
        """Retire a play once its stop or target trades: it stops taking a ladder."""
        for st in self.syms.values():
            if st.retired or not st.play["active"]:
                continue
            price = st.l1.get("last")
            if not price:
                continue
            p, long_ = st.play, st.play["side"] == "long"
            if not st.invalidation_armed:
                inside = (not p.get("stop") or (price > p["stop"] if long_ else price < p["stop"])) and \
                         (not p.get("target") or (price < p["target"] if long_ else price > p["target"]))
                if inside:
                    st.invalidation_armed = True
                continue
            hit = None
            if p.get("stop") and ((long_ and price <= p["stop"]) or (not long_ and price >= p["stop"])):
                hit = "stopped out"
            elif p.get("target") and ((long_ and price >= p["target"]) or (not long_ and price <= p["target"])):
                hit = "target hit"
            if hit:
                self.retire_play(st.symbol, hit, t, price)

    def add_play(self, symbol, t=None, side="long"):
        """A ticker typed into the workstation: a watch-only play (no pivot yet) that gets quotes at once."""
        symbol = str(symbol).strip().upper()
        if not symbol or not symbol.replace(".", "").replace("-", "").isalnum() or len(symbol) > 10:
            return None
        with self.lock:
            if symbol in self.syms:
                return self.syms[symbol].play
            play = {"symbol": symbol, "side": side, "trigger": None, "second_entry": None, "target": None, "stop": None,
                    "mp": None, "atr": None, "extra_levels": [], "notes": "", "active": True, "watch": True,
                    "exchange": "SMART", "primary_exchange": "", "currency": "USD"}
            self.plays.append(play)
            self.syms[symbol] = SymbolState(play, self.cfg)
            self._rec({"ev": "play_add", "t": t or self.last_t, "play": play})
            self._save_plays()
        for fn in self.play_listeners:
            try:
                fn(play)
            except Exception:
                pass
        return play

    @staticmethod
    def side_picked(play):
        """Has the trader taken a side on this ticker (a pick, or levels that only fit one side)? See board.side_picked."""
        return board.side_picked(play)

    def _unlink_contract(self, st, t, why):
        """The chart's lines go back to trading the STOCK (no contract rides them)."""
        from . import options as _o
        key = st.play.get("opt_key")
        st.play["trade_as"] = "stock"
        st.play["trade_as_set"] = False
        st.play.pop("opt_key", None)
        st.play.pop("opt_qty", None)
        tr = getattr(self, "trader", None)
        if tr is not None and getattr(tr, "opt_link", None) is not None:
            tr.opt_link.pop(st.symbol, None)
        self._message("warn", f"{st.symbol}: {'the ' + str(key) + ' link is off: ' if key else ''}{why}", t or self.last_t, st.symbol)
        self.log(st.symbol, f"contract link off ({why})", t, kind="level")

    def _opt_fit(self, st, t=None):
        """The linked contract must fit the side the levels say: a CALL on a LONG, a PUT on a SHORT. One that does
        not (yesterday's call under today's short 2nd entry) comes off, and the 2nd entry trades the STOCK."""
        from . import options as _o
        if st.play.get("trade_as") != "option" or not st.play.get("opt_key"):
            return True
        side = st.play.get("side", "long")
        fit = _o.fits_side(st.play["opt_key"], side)
        if fit is False:
            key = st.play["opt_key"]
            right = _o.parse_key(key)[3]
            self._unlink_contract(st, t, f"{key} is a {'CALL' if right == 'C' else 'PUT'}, the {'LONG' if right == 'C' else 'SHORT'} side; "
                                         f"your 2nd entry is a {side.upper()}. The 2nd entry trades the STOCK (pick a "
                                         f"{'PUT' if side == 'short' else 'CALL'} in OPTIONS to trade the contract)")
            return False
        return True

    @staticmethod
    def side_from_levels_only(play):
        """What the drawn levels say the side is (None when they say nothing): a stop above the target or a 2nd
        entry under the pivot is a SHORT; the other way round a LONG."""
        stop, target = play.get("stop"), play.get("target")
        trigger, second = play.get("trigger"), play.get("second_entry")
        if stop and target and stop != target:
            return "short" if stop > target else "long"
        if trigger and second and trigger != second:
            return "short" if second < trigger else "long"
        return None

    def _side_from_levels(self, st, t=None):
        """The side reads off the levels: a stop ABOVE the target can only be a short, a stop BELOW it a long
        (and a 2nd entry under the pivot a short, over it a long). Draw them and the play follows, no SIDE pick
        needed (a tie changes nothing)."""
        stop, target = st.play.get("stop"), st.play.get("target")
        trigger, second = st.play.get("trigger"), st.play.get("second_entry")
        if stop and target and stop != target:
            side, why = "short" if stop > target else "long", f"stop {narrative.px(stop)} {'above' if stop > target else 'under'} target {narrative.px(target)}"
        elif trigger and second and trigger != second:
            side, why = "short" if second < trigger else "long", f"2nd entry {narrative.px(second)} {'under' if second < trigger else 'over'} pivot {narrative.px(trigger)}"
        else:
            return
        if st.play.get("side") == side:
            return
        st.play["side"] = side
        st.invalidation_armed = False
        self.log(st.symbol, f"SIDE → {side.upper()} ({why})", t, kind="level")
        self._rec({"ev": "flip", "t": t or self.last_t, "sym": st.symbol, "side": side, "keep": True})

    @staticmethod
    def _stop_conflict(side, trigger, second, stop):
        """Why a stop is on the wrong side of the entry (None when it is fine). The entry is the 2nd entry when
        there is one, else the pivot: a long's stop goes under it, a short's over it."""
        if not stop:
            return None
        entry, name = (second, "2nd entry") if second else (trigger, "pivot")
        if not entry:
            return None
        if side == "long" and stop >= entry:
            return f"stop {stop} must be below the {name} {entry} for a long"
        if side == "short" and stop <= entry:
            return f"stop {stop} must be above the {name} {entry} for a short"
        return None

    def side_conflicts(self, play):
        """The levels on a play that sit on the wrong side for its side (so a side change can say what to redraw)."""
        side, trigger, second = play.get("side", "long"), play.get("trigger"), play.get("second_entry")
        out = []
        if trigger and second and ((side == "long" and second <= trigger) or (side == "short" and second >= trigger)):
            out.append(f"2nd entry {second} must be {'above' if side == 'long' else 'below'} the pivot {trigger} for a {side}")
        why = self._stop_conflict(side, trigger, second, play.get("stop"))
        if why:
            out.append(why)
        target = play.get("target")
        if trigger and target and ((side == "long" and target <= trigger) or (side == "short" and target >= trigger)):
            out.append(f"target {target} must be {'above' if side == 'long' else 'below'} the pivot {trigger} for a {side}")
        return out

    def set_side(self, symbol, side, t=None):
        """LONG / SHORT, applied the moment it is picked. Every level drawn on the chart stays where it is: the
        desk re-reads them for the new side (and tells you which ones now sit on the wrong side of it).
        Returns (ok, warnings)."""
        with self.lock:
            st = self._st(symbol)
            if st is None:
                return False, ["unknown symbol"]
            side = str(side or "").lower()
            if side not in ("long", "short"):
                return False, ["side must be long or short"]
            st.play["side_set"] = True
            if st.play.get("side") != side:
                st.play["side"] = side
                st.invalidation_armed = False
                self.log(symbol, f"SIDE → {side.upper()}", t, kind="level")
                self._rec({"ev": "flip", "t": t or self.last_t, "sym": symbol, "side": side, "keep": True})
                self._save_plays()
            return True, self.side_conflicts(st.play)

    def flip_side(self, symbol, t=None):
        """Long <-> short on a play (the second entry must sit beyond the pivot, so it is cleared)."""
        with self.lock:
            st = self._st(symbol)
            if st is None:
                return False
            st.play["side"] = "short" if st.play["side"] == "long" else "long"
            st.play["side_set"] = True
            self.log(symbol, f"SIDE → {st.play['side'].upper()}", t, kind="level")
            st.play["second_entry"] = None
            self._rec({"ev": "flip", "t": t or self.last_t, "sym": symbol, "side": st.play["side"]})
            self._save_plays()
            return True

    def set_focus(self, symbol, t=None):
        """The symbol on screen gets a ladder: pin it (and release the previous auto-pin)."""
        with self.lock:
            symbol = str(symbol).upper()
            if symbol not in self.syms:
                return False
            t = t or self.last_t
            prev = getattr(self, "focus", None)
            if prev and prev != symbol and prev in self.pinned and getattr(self, "focus_pinned", False):
                self.pinned.discard(prev)
            self.focus = symbol
            self.focus_pinned = symbol not in self.pinned
            self.pinned.add(symbol)
            self._rec({"ev": "focus", "t": t, "sym": symbol})
            return True

    def remove_play(self, symbol, t=None):
        """Take a ticker off the desk: its quotes, depth and its place in plays.json go with it."""
        symbol = str(symbol).strip().upper()
        with self.lock:
            st = self._st(symbol)
            if st is None:
                return False
            t = t or self.last_t
            if symbol in self.slots:
                self.apply_slot(symbol, False, t, reason="removed")
                self._slot_cmds.append(("depth_off", symbol))
            self.pinned.discard(symbol)
            self.plays = [p for p in self.plays if p["symbol"] != symbol]
            del self.syms[symbol]
            self.user_alerts = [a for a in self.user_alerts if a["symbol"] != symbol]
            self._rec({"ev": "play_remove", "t": t, "sym": symbol})
            self._save_plays()
            self._save_user_alerts()
        for fn in self.remove_listeners:
            try:
                fn(symbol)
            except Exception:
                pass
        return True

    # ---- your alerts ----------------------------------------------------------

    def load_user_alerts(self, path):
        import json, os
        self.alerts_path = path
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            with self.lock:
                self.user_alerts = [a for a in data.get("alerts", []) if isinstance(a, dict) and a.get("symbol") and a.get("kind")]
                self._alert_seq = max([int(a.get("id", 0)) for a in self.user_alerts] + [0])
        except (OSError, ValueError):
            pass

    def _save_user_alerts(self):
        if not self.alerts_path:
            return
        import json, os
        keep = ("id", "symbol", "kind", "price", "when", "min_premium", "cp", "min_dollars", "repeat", "note", "created", "last")
        out = {"alerts": [{k: a[k] for k in keep if k in a} for a in self.user_alerts]}
        tmp = self.alerts_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=2)
        os.replace(tmp, self.alerts_path)

    def add_user_alert(self, symbol, kind, t=None, **f):
        """kind: price (price + when: above / below / hit), flow (min_premium, cp: any / C / P), equity (min_dollars).
        repeat=False fires once and is gone; True keeps firing (with a cooldown)."""
        symbol = str(symbol or "").strip().upper()
        if not symbol or kind not in ("price", "flow", "equity"):
            return None, "bad alert"
        with self.lock:
            t = t or self.last_t
            a = {"symbol": symbol, "kind": kind, "repeat": bool(f.get("repeat", False)), "note": str(f.get("note") or "")[:80],
                 "created": t, "last": None}
            if kind == "price":
                try:
                    a["price"] = float(f.get("price"))
                except (TypeError, ValueError):
                    return None, "price needed"
                if a["price"] <= 0:
                    return None, "price needed"
                a["when"] = f.get("when") if f.get("when") in ("above", "below", "hit") else "hit"
                st = self._st(symbol)
                a["side"] = None if st is None or not st.price() else ("above" if st.price() > a["price"] else "below")
            elif kind == "flow":
                a["min_premium"] = float(f.get("min_premium") or self.cfg.get("ladder", {}).get("flow_min_premium", 100000))
                a["cp"] = f.get("cp") if f.get("cp") in ("C", "P") else "any"
            else:
                a["min_dollars"] = float(f.get("min_dollars") or self.cfg.get("quantdata", {}).get("equity_min_dollars", 500000))
            self._alert_seq += 1
            a["id"] = self._alert_seq
            self.user_alerts.append(a)
            self._rec({"ev": "alert_add", "t": t, "alert": a})
            self._save_user_alerts()
            return a, ""

    def remove_user_alert(self, aid, t=None):
        with self.lock:
            n = len(self.user_alerts)
            self.user_alerts = [a for a in self.user_alerts if a.get("id") != aid]
            if len(self.user_alerts) != n:
                self._rec({"ev": "alert_remove", "t": t or self.last_t, "id": aid})
                self._save_user_alerts()
                return True
        return False

    @staticmethod
    def _spoken(v):
        """Dollars the voice can say: 1.2 million, 411 thousand."""
        return f"{v / 1e6:.1f} million" if v >= 1e6 else f"{round(v / 1e3)} thousand"

    def _fire_user_alert(self, a, label, text, words, t, **extra):
        """One of your alerts goes off: it lands in CALLS, gets spoken, and (unless repeat) is done."""
        a["last"] = t
        alert = {"t": t, "symbol": a["symbol"], "label": label, "price": fmt_price(extra.pop("price", None)) if extra.get("price") else None,
                 "side": "ask", "role": "alert", "text": text, "words": words, "alert_id": a["id"]}
        alert.update(extra)
        alert["key"] = f"{round(t, 2)}|{a['symbol']}|{label}|{a['id']}"
        self.alerts.appendleft(alert)
        self._rec(dict(alert, ev="alert"))
        item = {"t": t, "symbol": a["symbol"], "kind": "alert", "text": f"{a['symbol']}: {words}", "key": alert["key"]}
        self.voice.appendleft(item)
        self._rec(dict(item, ev="voice"))
        for fn in self.listeners:
            try:
                fn(alert)
            except Exception:
                pass
        if not a.get("repeat"):
            self.user_alerts = [x for x in self.user_alerts if x is not a]
        self._save_user_alerts()

    def _check_price_alerts(self, symbol, price, t):
        for a in list(self.user_alerts):
            if a["kind"] != "price" or a["symbol"] != symbol:
                continue
            target = a["price"]
            side = "above" if price > target else "below" if price < target else "at"
            prev = a.get("side")
            a["side"] = side if side != "at" else prev
            if a.get("repeat") and a.get("last") is not None and t - a["last"] < 60:
                continue
            hit = (a["when"] == "above" and price >= target and prev == "below") or \
                  (a["when"] == "below" and price <= target and prev == "above") or \
                  (a["when"] == "hit" and (side == "at" or (prev is not None and side != prev)))
            if not hit:
                continue
            how = {"above": "went above", "below": "went below", "hit": "hit"}[a["when"]]
            note = f" - {a['note']}" if a.get("note") else ""
            self._fire_user_alert(a, "PRICE ALERT", f"PRICE ALERT: {symbol} {how} {narrative.px(target)} (now {narrative.px(price)}){note}",
                                  f"price alert, {symbol} {how} {narrative.px(target)}", t, price=price)

    def _check_flow_alerts(self, p, t):
        for a in list(self.user_alerts):
            if a["kind"] != "flow" or a["symbol"] != p["symbol"]:
                continue
            if p.get("side") != "ask" or (p.get("premium") or 0) < a["min_premium"]:
                continue
            if a["cp"] != "any" and p.get("cp") != a["cp"]:
                continue
            if a.get("repeat") and a.get("last") is not None and t - a["last"] < 300:
                continue
            what = "calls" if p["cp"] == "C" else "puts"
            k = lambda v: f"${v / 1e6:.1f}M" if v >= 1e6 else f"${v / 1e3:.0f}K"
            dte = f", {round(p['dte'])} days out" if p.get("dte") is not None else ""
            self._fire_user_alert(a, "FLOW ALERT", f"FLOW ALERT: {p['symbol']} option flow - {k(p['premium'])} of {what} bought at the ask, "
                                  f"{narrative.px(p['strike'])} strike{dte}" + (f", stock at {narrative.px(p['spot'])}" if p.get("spot") else ""),
                                  f"option flow, {self._spoken(p['premium'])} of {what}, {narrative.px(p['strike'])} strike{dte}", t,
                                  premium=p["premium"], cp=p["cp"], flow=self._receipt(p["symbol"], p["cp"], [p.get("id")], "this print"))

    # ---- equity prints (lit / dark) ---------------------------------------------

    def on_equity(self, p, t=None):
        """One big stock print from the flow vendor: into EQUITY FLOW, and your equity alerts."""
        with self.lock:
            t = t if t is not None else p.get("t", self.last_t)
            self._clock(t)
            self._rec({"ev": "equity", "t": t, "p": p})
            self.equity.appendleft(p)
            self.equity_status["last_print"] = t
            for a in list(self.user_alerts):
                if a["kind"] != "equity" or a["symbol"] != p["symbol"] or (p.get("dollars") or 0) < a["min_dollars"]:
                    continue
                if a.get("repeat") and a.get("last") is not None and t - a["last"] < 300:
                    continue
                k = lambda v: f"${v / 1e6:.1f}M" if v >= 1e6 else f"${v / 1e3:.0f}K"
                where = "off-exchange" if p.get("dark") else "on the tape"
                self._fire_user_alert(a, "EQUITY FLOW", f"EQUITY FLOW: {p['symbol']} {k(p['dollars'])} print, {narrative.shares(p['size'])} shares at "
                                      f"{narrative.px(p['price'])} {where}", f"equity print, {self._spoken(p['dollars'])} {where}", t,
                                      price=p.get("price"), dollars=p["dollars"])

    # ---- option flow on the ladder -----------------------------------------------

    def _flow_mark(self, st, p, t, live=True):
        """A big option print on a watched name: remember where the stock was when it hit, so the ladder shows
        it on that row. The same strike bought again and again, expiring soon, is what to look for: it gets
        marked hot and called out once."""
        lc = self.cfg.get("ladder", {})
        index = p["symbol"] in set(self.cfg.get("flow", {}).get("index_symbols", ()))
        need = lc.get("flow_index_min_premium", 1e6) if index else lc.get("flow_min_premium", 1e5)
        prem = p.get("premium") or 0.0
        if prem < need or p.get("side") not in ("ask", "bid"):
            return
        spot = p.get("spot") or st.price()
        if not spot:
            return
        keep = lc.get("flow_window_minutes", 60) * 60.0
        while st.flow_marks and t - st.flow_marks[0]["t"] > keep:
            st.flow_marks.popleft()
        key = (p["strike"], p["cp"], p.get("expiry") or "")
        m = {"t": t, "spot": spot, "strike": p["strike"], "cp": p["cp"], "exp": p.get("expiry") or "", "dte": p.get("dte"),
             "prem": prem, "side": p["side"], "kind": p.get("kind", "trade"), "hot": False, "id": p.get("id")}
        st.flow_marks.append(m)
        # repeat: this strike / expiry, bought (at the ask) this many times inside the repeat window
        short = p.get("dte") is not None and p["dte"] <= lc.get("flow_short_dte", 7)
        rw = lc.get("flow_repeat_minutes", 30) * 60.0
        same = [x for x in st.flow_marks if (x["strike"], x["cp"], x["exp"]) == key and x["side"] == "ask" and t - x["t"] <= rw]
        if len(same) >= lc.get("flow_repeat_prints", 2) and short:
            for x in same:
                x["hot"] = True
            if not live:
                return
            cool = lc.get("flow_repeat_cooldown_minutes", 15) * 60.0
            if t - st.rflow_said.get(key, -1e9) >= cool:
                st.rflow_said[key] = t
                tot = sum(x["prem"] for x in same)
                k = lambda v: f"${v / 1e6:.1f}M" if v >= 1e6 else f"${v / 1e3:.0f}K"
                what = "CALL" if p["cp"] == "C" else "PUT"
                days = f"{round(p['dte'])} day{'s' if round(p['dte']) != 1 else ''}"
                alert = {"t": t, "symbol": st.symbol, "label": "REPEAT FLOW", "price": fmt_price(spot), "side": "ask", "role": "flow",
                         "text": f"REPEAT {what} FLOW: {st.symbol} {narrative.px(p['strike'])} strike expiring in {days} bought at the ask "
                                 f"{len(same)} times in {int(rw / 60)} min, {k(tot)} in all, with the stock at {narrative.px(spot)}. "
                                 f"Short-dated size hitting the same strike: they want a move now.",
                         "premium": tot, "cp": p["cp"], "strike": p["strike"], "dte": p["dte"], "prints": len(same),
                         "flow": self._receipt(st.symbol, p["cp"], [x.get("id") for x in same], f"the {narrative.px(p['strike'])} strike, bought at the ask, last {int(rw / 60)} min")}
                alert["key"] = f"{round(t, 2)}|{st.symbol}|REPEAT FLOW|{p['strike']}{p['cp']}"
                self.alerts.appendleft(alert)
                self._rec(dict(alert, ev="alert"))
                for fn in self.listeners:
                    try:
                        fn(alert)
                    except Exception:
                        pass
                self._say(st, "flow", key, "rflow", t, f"repeat {what.lower()} flow, {narrative.px(p['strike'])} strike, {days} out, {self._spoken(tot)} total")

    # ---- urgent flow: short-dated, out of the money, being pounded ----------------------

    def _urg_stats(self, key, rows, t):
        fc = self.cfg.get("flow", {})
        win = fc.get("urgency_window_minutes", 10) * 60.0
        rows = [r for r in rows if t - r["t"] <= win]
        if not rows:
            return None
        n, tot = len(rows), sum(r["prem"] for r in rows)
        sweeps = sum(1 for r in rows if r["kind"] in ("sweep", "split"))
        half = t - win / 2
        late = sum(r["prem"] for r in rows if r["t"] >= half)
        accel = late > (tot - late) * 1.5 and n >= 2
        last = rows[-1]
        score = tot / max(1.0, win / 60.0) * (1 + sweeps / n) * (2 if accel else 1)
        return {"symbol": key[0], "strike": key[1], "cp": key[2], "expiry": key[3], "dte": last["dte"], "otm_pct": last["otm"],
                "spot": last["spot"], "prints": n, "sweeps": sweeps, "dollars": round(tot), "last_t": last["t"], "first_t": rows[0]["t"],
                "accel": accel, "pace": round(tot / max(1.0, win / 60.0)), "score": score, "key": "|".join(str(k) for k in key),
                "ids": [r["id"] for r in rows if r.get("id") is not None]}

    def _flow_scan(self, p, t, st):
        """The option scanner Dan runs on the whole market (URaAZxC23YU): any ticker whose flow passes the board's
        flow gate gets a WATCH — the flow found it, the chart work is still to do. Plays on the desk are handled by
        their board; other tickers only when flow alerts are on for ALL. One call per ticker and side per cooldown."""
        if st is not None or self.flow_alerts != "all":
            return
        fc = self.cfg.get("flow", {})
        sym = p["symbol"]
        if sym in set(fc.get("index_symbols", ())):
            return
        side = "long" if p.get("cp") == "C" else "short"
        key = (sym, side)
        cool = float(fc.get("of_scan_cooldown_minutes", 30)) * 60.0
        if t - self.scan_said.get(key, -1e9) < cool:
            return
        prints = [x for x in self.flow.by_symbol.get(sym, ()) if x.get("t", 0) >= t - float(fc.get("of_session_minutes", 390)) * 60.0]
        fg = board.flow_gate(prints, side, p.get("spot"), [], t, fc)
        if not fg["gate"]:
            return
        self.scan_said[key] = t
        text = board.market_watch_text(sym, side, fg, p.get("spot"))
        alert = {"t": t, "symbol": sym, "label": "FLOW WATCH", "price": fmt_price(p.get("spot")), "side": "ask", "role": "conviction",
                 "text": text, "cp": p.get("cp"), "premium": fg["cluster"]["dollars"], "rules": fg["rules"],
                 "flow": self._receipt(sym, p.get("cp"), fg["cluster"].get("ids"), "short-term, bought at the ask, today"),
                 "words": f"flow watch. {narrative.say_dollars(fg['cluster']['dollars'])} went into short term {'calls' if side == 'long' else 'puts'}"
                          f"{', ' + board.say_expiry(fg['cluster'].get('dte')) if board.say_expiry(fg['cluster'].get('dte')) else ''}, {fg['cluster']['repeats']} times. Not a play yet, no chart work done."}
        alert["key"] = f"{round(t, 2)}|{sym}|FLOW WATCH|{side}"
        self.alerts.appendleft(alert)
        self._rec(dict(alert, ev="alert"))
        for fn in self.listeners:
            try:
                fn(alert)
            except Exception:
                pass

    def _urgency(self, p, t, st, live=True):
        """Every print bought at the ask on a short-dated, out-of-the-money contract counts toward that contract's
        urgency. Enough of them fast enough, with size, and it is called URGENT FLOW (watchlist names; every name
        when flow alerts are on for all)."""
        fc = self.cfg.get("flow", {})
        if p.get("side") != "ask" or p.get("dte") is None or p["dte"] > fc.get("urgency_max_dte", 7):
            return
        otm = p.get("otm_pct")
        if otm is None or otm < fc.get("urgency_min_otm_pct", 0.5):
            return
        key = (p["symbol"], p["strike"], p["cp"], p.get("expiry") or "")
        win = fc.get("urgency_window_minutes", 10) * 60.0
        rows = self.urg.setdefault(key, deque())
        while rows and t - rows[0]["t"] > win:
            rows.popleft()
        rows.append({"t": t, "prem": p.get("premium") or 0.0, "kind": p.get("kind", "trade"), "otm": otm, "dte": p["dte"], "spot": p.get("spot"), "id": p.get("id")})
        # every urgent-type print of the session, for the ticker search (what came in earlier, not just the last 10 min)
        self.urg_hist.append({"t": t, "symbol": p["symbol"], "strike": p["strike"], "cp": p["cp"], "expiry": p.get("expiry") or "",
                              "dte": p["dte"], "otm_pct": round(otm, 2), "premium": round(p.get("premium") or 0.0),
                              "size": p.get("size"), "price": p.get("price"), "kind": p.get("kind", "trade"), "spot": p.get("spot")})
        if len(self.urg) > 3000:                   # the whole market all day: keep it bounded
            for k in [k for k, v in self.urg.items() if not v or t - v[-1]["t"] > win][:500]:
                self.urg.pop(k, None)
        u = self._urg_stats(key, rows, t)
        hot = u["prints"] >= fc.get("urgency_min_prints", 3) and u["dollars"] >= fc.get("urgency_min_dollars", 250000)
        if hot:
            self.urgent_keys.add(key)
        else:
            self.urgent_keys.discard(key)
        if not hot or not live or (st is None and self.flow_alerts != "all"):
            return
        cool = fc.get("urgency_cooldown_minutes", 15) * 60.0
        if t - self.urg_said.get(key, -1e9) < cool:
            return
        self.urg_said[key] = t
        what = "CALL" if p["cp"] == "C" else "PUT"
        k = lambda v: f"${v / 1e6:.1f}M" if v >= 1e6 else f"${v / 1e3:.0f}K"
        days = f"{round(p['dte'])} day{'s' if round(p['dte']) != 1 else ''}"
        sw = f", {u['sweeps']} of them sweeps" if u["sweeps"] else ""
        text = (f"URGENT {what} FLOW: {p['symbol']} {narrative.px(p['strike'])} strike, {days} out, {otm:.1f}% out of the money - bought at the ask "
                f"{u['prints']} times in {int(win / 60)} min{sw}, {k(u['dollars'])} in all" + (", and picking up speed" if u["accel"] else "") +
                (f", stock at {narrative.px(p['spot'])}" if p.get("spot") else "") + ". Short-dated, out of the money, in a hurry: somebody wants this move now.")
        words = (f"urgent {what.lower()} buying, {narrative.px(p['strike'])} strike, {days} out, {round(otm)} percent out of the money, "
                 f"{self._spoken(u['dollars'])} in {u['prints']} prints" + (", mostly sweeps" if u["sweeps"] * 2 >= u["prints"] else "") + (", speeding up" if u["accel"] else ""))
        alert = {"t": t, "symbol": p["symbol"], "label": "URGENT FLOW", "price": fmt_price(p.get("spot")) if p.get("spot") else None, "side": "ask", "role": "flow",
                 "text": text, "words": words, "premium": u["dollars"], "cp": p["cp"], "strike": p["strike"], "dte": p["dte"], "otm_pct": otm,
                 "prints": u["prints"], "sweeps": u["sweeps"], "accel": u["accel"],
                 "flow": self._receipt(p["symbol"], p["cp"], u.get("ids"), f"the {narrative.px(p['strike'])} strike, bought at the ask, last {int(self.cfg.get('flow', {}).get('urgency_window_minutes', 10))} min")}
        alert["key"] = f"{round(t, 2)}|{p['symbol']}|URGENT FLOW|{p['strike']}{p['cp']}"
        self.alerts.appendleft(alert)
        self._rec(dict(alert, ev="alert"))
        for fn in self.listeners:
            try:
                fn(alert)
            except Exception:
                pass
        if st is not None:
            self._say(st, "flow", key, "urgent", t, words)
        else:
            item = {"t": t, "symbol": p["symbol"], "kind": "urgent", "text": f"{p['symbol']}: {words}", "key": alert["key"]}
            self.voice.appendleft(item)
            self._rec(dict(item, ev="voice"))

    def urgency_for(self, symbol, t=None, limit=400):
        """The URGENT FLOW search: one ticker's contracts being chased right now (all of them) and every urgent-type
        print of the session, newest first, each marked if its contract was CALLED urgent."""
        symbol = str(symbol or "").strip().upper()
        with self.lock:
            t = t if t is not None else self.last_t
            live = []
            for key, rows in list(self.urg.items()):
                if key[0] != symbol:
                    continue
                u = self._urg_stats(key, rows, t)
                if u:
                    u["hot"] = key in self.urgent_keys
                    live.append(u)
            live.sort(key=lambda u: -u["score"])
            called = {k for k in self.urg_said if k[0] == symbol}
            hist = [dict(h, called=(h["symbol"], h["strike"], h["cp"], h["expiry"]) in called)
                    for h in reversed(self.urg_hist) if h["symbol"] == symbol][:limit]
            return {"symbol": symbol, "live": live, "history": hist,
                    "calls": round(sum(h["premium"] for h in hist if h["cp"] == "C")),
                    "puts": round(sum(h["premium"] for h in hist if h["cp"] == "P"))}

    def _urgency_list(self, t, limit=30):
        out = []
        for key, rows in list(self.urg.items()):
            u = self._urg_stats(key, rows, t)
            if u:
                u["hot"] = key in self.urgent_keys
                out.append(u)
        out.sort(key=lambda u: -u["score"])
        return out[:limit]

    def _flow_rows(self, st, t, tk):
        """The ladder's flow marks by price row: calls / puts premium at that spot, prints, the hot ones, the top few."""
        lc = self.cfg.get("ladder", {})
        keep = lc.get("flow_window_minutes", 60) * 60.0
        out = {}
        for m in st.flow_marks:
            if t - m["t"] > keep:
                continue
            k = price_key(m["spot"], tk)
            r = out.setdefault(k, {"c": 0.0, "p": 0.0, "n": 0, "hot": False, "items": []})
            r["c" if m["cp"] == "C" else "p"] += m["prem"]
            r["n"] += 1
            r["hot"] = r["hot"] or m["hot"]
            r["items"].append(m)
        for r in out.values():
            top = sorted(r["items"], key=lambda m: -m["prem"])[:3]
            r["items"] = [{"cp": m["cp"], "strike": m["strike"], "exp": m["exp"][5:] if m["exp"] else "", "dte": None if m["dte"] is None else round(m["dte"]),
                           "prem": round(m["prem"]), "side": m["side"], "kind": m["kind"], "hot": m["hot"], "age": round(t - m["t"]),
                           "urgent": (st.symbol, m["strike"], m["cp"], m["exp"]) in self.urgent_keys} for m in top]
            r["urgent"] = any(i["urgent"] for i in r["items"])
            r["c"] = round(r["c"]); r["p"] = round(r["p"])
        return out

    def retire_play(self, symbol, reason, t=None, price=None):
        with self.lock:
            st = self._st(symbol)
            if st is None:
                return False
            t = t or self.last_t
            st.retired = {"reason": reason, "t": t, "price": fmt_price(price or st.price())}
            self._rec({"ev": "retire", "t": t, "sym": symbol, "reason": reason})
            self._message("warn", f"{symbol}: {reason} at {st.retired['price']} — play retired (Reactivate in the plays list to bring it back)", t, symbol)
            if symbol in self.slots and symbol not in self.pinned:
                self.apply_slot(symbol, False, t, reason="retired")
                self._slot_cmds.append(("depth_off", symbol))
            return True

    def reactivate_play(self, symbol, t=None):
        with self.lock:
            st = self._st(symbol)
            if st is None:
                return False
            st.retired = None
            st.invalidation_armed = False
            self._rec({"ev": "retire", "t": t or self.last_t, "sym": symbol, "reason": None})
            return True

    # ---- grading calls (feeds the tuning tool) --------------------------------

    def grade(self, key, verdict, t=None):
        with self.lock:
            if verdict not in ("good", "bad", None):
                return False
            if verdict is None:
                self.grades.pop(key, None)
            else:
                self.grades[key] = verdict
            rec = {"t": t or self.last_t, "key": key, "verdict": verdict}
            self._rec(dict(rec, ev="grade"))
            if self.grades_path:
                import json, os
                os.makedirs(os.path.dirname(self.grades_path) or ".", exist_ok=True)
                with open(self.grades_path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(rec) + "\n")
            return True

    def ranking(self, t):
        blocked = {s for s, st in self.syms.items() if st.rejected_until > t or st.retired}
        prices = {s: st.price() for s, st in self.syms.items()}
        return rank(self.plays, prices, blocked)

    def _rotate(self, t):
        dc = self.cfg["depth"]
        blocked = {s for s, st in self.syms.items() if st.rejected_until > t}
        n_slots = max(1, dc["slots"] - (1 if self.opt_depth_wanted(t) else 0))   # the charted contract's book takes one
        new = allocate(self.slots, self._rotation_ranking(t), n_slots, t,
                       dc["rotate_hysteresis"], dc["min_hold_seconds"],
                       pinned=self.pinned - blocked, protected=self._protected(t),
                       rotate=self.auto_rotate,
                       focus=self.focus if self.focus in self.syms and self.syms[self.focus].rejected_until <= t else None)
        cmds = list(self._slot_cmds)
        self._slot_cmds = []
        for sym in [s for s in self.slots if s not in new]:
            self.apply_slot(sym, False, t, reason="rotated")
            cmds.append(("depth_off", sym))
        for sym in [s for s in new if s not in self.slots]:
            self.apply_slot(sym, True, t, reason="pinned" if sym in self.pinned else "closest")
            cmds.append(("depth_on", sym))
        return cmds

    # ---- replay --------------------------------------------------------------

    def ingest(self, ev):
        """Feed one recorded event (see recorder.py)."""
        kind, t = ev.get("ev"), ev.get("t", 0.0)
        if kind == "l1":
            self.on_l1(ev["sym"], ev["f"], ev["v"], t)
        elif kind == "depth":
            self.on_depth(ev["sym"], ev["pos"], ev["op"], ev["side"], ev["px"], ev["sz"], ev.get("mm", ""), t)
        elif kind == "reset":
            self.on_depth_reset(ev["sym"], t, ev.get("reason", "317"))
        elif kind == "print":
            self.on_print(ev["sym"], ev["px"], ev["sz"], ev.get("ex", ""), t, ev.get("cond", ""), ev.get("xt"))
        elif kind == "slot":
            self.apply_slot(ev["sym"], ev["on"], t, ev.get("reason", ""))
        elif kind == "conn":
            with self.lock:
                if self.replay is None:  # while replaying, the header keeps saying REPLAY
                    self.connection.update(state=ev["state"], since=t, detail=ev.get("detail", ""))
        elif kind == "depth_rejected":
            self.on_depth_rejected(ev["sym"], ev.get("code"), ev.get("msg", ""), t)
        elif kind == "error":
            self.on_error(ev.get("sym"), ev.get("code"), ev.get("msg", ""), t)
        elif kind == "retire":
            (self.retire_play if ev.get("reason") else self.reactivate_play)(ev["sym"], *( [ev["reason"], t] if ev.get("reason") else [t]))
        elif kind == "grade":
            with self.lock:
                if ev.get("verdict"):
                    self.grades[ev["key"]] = ev["verdict"]
                else:
                    self.grades.pop(ev["key"], None)
        elif kind == "dbar":
            self.on_daily_bar(ev["sym"], ev["t0"], ev["o"], ev["h"], ev["l"], ev["c"], ev.get("v"))
        elif kind == "sbar":
            self.on_study_bar(ev["sym"], ev["k"], ev["t0"], ev["o"], ev["h"], ev["l"], ev["c"], ev.get("v"))
        elif kind == "flow":
            self.on_flow(ev["p"], t)
        elif kind == "flow_alerts":
            self.set_flow_alerts(ev.get("who", "watchlist"), t)
        elif kind == "flow_scope":
            self.set_flow_scope(ev.get("scope", "all"), t)
        elif kind == "big":
            self.set_big_shares(ev["sym"], ev.get("shares"), t)
        elif kind == "setup":
            self.set_play_setup(ev["sym"], ev.get("fields", {}), t)
        elif kind == "flip":
            with self.lock:
                st = self._st(ev["sym"])
                if st is not None:
                    st.play["side"] = ev["side"]
                    if not ev.get("keep"):           # a SIDE pick keeps the drawn levels; the old flip cleared the 2nd entry
                        st.play["second_entry"] = None
        elif kind == "level":
            (self.add_level if ev.get("on", True) else self.remove_level)(ev["sym"], ev.get("px"), t, kind=ev.get("kind", "extra"))
        elif kind == "zone":
            self.set_zone(ev["sym"], ev.get("lo"), ev.get("hi"), ev.get("on", True), t)
        elif kind == "play_level":
            self.set_play_level(ev["sym"], ev["role"], ev.get("px"), t, source="replay")
        elif kind == "ui":
            if "pin" in ev:
                self.set_pinned(ev["pin"], ev.get("on"), t)
            elif "auto_rotate" in ev:
                self.set_auto_rotate(ev["auto_rotate"], t)
        elif kind == "focus":
            self.set_focus(ev["sym"], t)
        elif kind == "settings":
            with self.lock:           # a setting changed mid-session: the replay changes it at the same moment
                for path, val in (ev.get("changes") or {}).items():
                    d = self.cfg
                    keys = path.split(".")
                    for k in keys[:-1]:
                        d = d.setdefault(k, {})
                    d[keys[-1]] = val
        elif kind == "play_add":
            self.add_play(ev["play"]["symbol"], t, ev["play"].get("side", "long"))
        elif kind == "mark":
            with self.lock:
                self.marks_list.append({k: ev.get(k) for k in ("t", "symbol", "price", "note", "headline", "shot", "n", "audio", "audio_s")})
        elif kind == "mark_audio":
            with self.lock:
                for m in self.marks_list:
                    if m.get("n") == ev.get("n"):
                        m.update(audio=ev.get("audio"), audio_s=ev.get("audio_s"), note=ev.get("note", m.get("note")))
        elif kind == "note":
            with self.lock:
                self.notes_list.append({k: ev.get(k) for k in ("t", "symbol", "text", "kind")})
        elif kind == "mark_note":
            with self.lock:
                for m in self.marks_list:
                    if m.get("n") == ev.get("n"):
                        m["note"] = ev.get("note", "")
        elif kind == "hbar":
            self.on_hist_bar(ev["sym"], ev["t0"], ev["o"], ev["h"], ev["l"], ev["c"], ev.get("v"))

    # ---- dashboard -----------------------------------------------------------

    def _health(self, st, t):
        hc = self.cfg["health"]

        def age(x):
            return None if x is None else round(t - x, 1)

        status = "OK"
        if st.l1_t is None:
            status = "NO DATA"
        elif t - st.l1_t > hc["l1_stale_seconds"]:
            status = "STALE"
        if st.depth_active:
            if st.book is None or not st.book.synced or t < st.resync_until:
                status = "RESYNC" if st.resets else "SYNCING"
            elif st.depth_t is not None and t - st.depth_t > hc["depth_stale_seconds"]:
                status = "STALE"
        return {
            "status": status,
            "l1_age": age(st.l1_t),
            "depth_age": age(st.depth_t) if st.depth_active else None,
            "tape_age": age(st.tape_t),
            "tape_stale": st.tape_t is not None and t - st.tape_t > hc["tape_stale_seconds"],
            "resets": st.resets,
            "anomalies": st.book.anomalies if st.book else 0,
            "last_error": st.last_error,
            "depth_refused": getattr(st, "depth_refused", None) if st.rejected_until > t else None,
        }

    def _user_levels(self, play):
        out = [{"price": play["trigger"], "role": "trigger", "label": "PIVOT"}] if play.get("trigger") else []
        if play.get("second_entry"):
            out.append({"price": play["second_entry"], "role": "second_entry", "label": "2ND ENTRY"})
        for lv in play.get("extra_levels", []):
            out.append({"price": lv, "role": "extra", "label": "LEVEL"})
        for lv in play.get("sneaky_levels", []):
            out.append({"price": lv, "role": "sneaky", "label": "SNEAKY PIVOT"})
        for key, label in (("target", "TARGET"), ("stop", "STOP")):
            if play.get(key):
                out.append({"price": play[key], "role": key, "label": label})
        alt = play.get("alt") or {}
        if alt:
            arrow = "↓" if play.get("side", "long") == "long" else "↑"      # the other side: a short under a long, a long over a short
            for key, label in (("trigger", "PIVOT"), ("second_entry", "2ND ENTRY"), ("target", "TARGET"), ("stop", "STOP")):
                if alt.get(key):
                    out.append({"price": alt[key], "role": "alt_" + key, "label": arrow + " " + label, "alt": True})
        return out

    def _prune_memory(self, st, t):
        """Drop prints that left the windows, taking them off the running sums (on every print and every tick,
        so a quiet tape still ages out)."""
        while st.memory and t - st.memory[0][0] > MEMORY_SECONDS:
            _t, k, _p, side, size = st.memory.popleft()
            key = (k, side)
            cl = (getattr(st, "mem_clear", None) or {}).get(key)
            if cl is not None and _t <= cl[0]:
                cl[1] -= size
                if cl[1] <= 1e-9:
                    del st.mem_clear[key]
            v = st.mem_sums.get(key, 0.0) - size
            if v <= 1e-9:
                st.mem_sums.pop(key, None)
            else:
                st.mem_sums[key] = v
        tw = self.cfg["trap"]["window_seconds"]
        if tw > getattr(st, "trap_w", tw):
            # the window was raised: rebuild from the level memory (which reaches back MEMORY_SECONDS)
            st.trap_mem = deque(m for m in st.memory if t - m[0] <= tw)
            st.trap_sums = {}
            for _t, k, p, side, size in st.trap_mem:
                ts = st.trap_sums.get((k, side))
                if ts is None:
                    st.trap_sums[(k, side)] = [size, p * size, p]
                else:
                    ts[0] += size; ts[1] += p * size
        st.trap_w = tw
        while st.trap_mem and t - st.trap_mem[0][0] > tw:
            _t, k, p, side, size = st.trap_mem.popleft()
            key = (k, side)
            ts = st.trap_sums.get(key)
            if ts is not None:
                ts[0] -= size; ts[1] -= p * size
                if ts[0] <= 1e-9:
                    del st.trap_sums[key]

    def _visit(self, st, k, side, size, t):
        """SOLD / BOUGHT THIS VISIT: what hit the bid / lifted the ask at a price since price last came back to it. A
        visit ends when price trades ``ladder.visit_away_ticks`` ticks away (3): one cent of chop is not leaving."""
        away = max(1, int(self.cfg.get("ladder", {}).get("visit_away_ticks", 3)))
        vis = st.__dict__.setdefault("visits", {})
        op = st.__dict__.setdefault("visit_open", set())
        for j in [j for j in op if abs(j - k) >= away]:
            op.discard(j)
        v = vis.get(k)
        if k not in op or v is None:                    # (a price cleared from under an open visit starts a new one)
            if v is None:
                v = vis[k] = {"s": 0.0, "b": 0.0, "ts": deque(maxlen=60), "t": t}
            else:
                v["s"] = v["b"] = 0.0
            v["ts"].append(t)
            op.add(k)
        if side == "sell":
            v["s"] += size
        elif side == "buy":
            v["b"] += size
        v["t"] = t
        if len(vis) > 3000:
            for j in sorted(vis, key=lambda j: vis[j]["t"])[:1000]:
                if j not in op:
                    del vis[j]

    def ladder_clear(self, symbol, where, t=None):
        """The ladder's clear buttons (Jigsaw's arrows, both counts): "above" clears what traded over the ask (after a
        move down), "below" under the bid (after a move up), "all" the whole ladder. The prints stay in the tape."""
        with self.lock:
            st = self._st(symbol)
            if st is None:
                return False
            t = t or self.last_t
            bid, ask = st.bbo()
            hi = price_key(ask) if ask else None
            lo = price_key(bid) if bid else None
            if where == "above" and hi is None or where == "below" and lo is None:
                return False
            hit = (lambda k: k > hi) if where == "above" else (lambda k: k < lo) if where == "below" else (lambda k: True)
            clear = st.__dict__.setdefault("mem_clear", {})
            for key, v in list(st.mem_sums.items()):
                if hit(key[0]) and v > 0:
                    clear[key] = [t, v]
            for k in [k for k in (getattr(st, "visits", None) or {}) if hit(k)]:
                del st.visits[k]
                (getattr(st, "visit_open", None) or set()).discard(k)     # a cleared price starts a NEW visit
            bks = st.__dict__.get("basket") or {}
            for k in [k for k in bks if hit(k)]:
                del bks[k]
            for sd in (BID, ASK):
                st.pulls.clear_ps(sd, lambda k: not hit(k))
            return True

    def _ladder_marks(self, st, t, user_levels, last):
        """Everything worth a line on the ladder, with its distance from price: your PS60 lines (both sides, as drawn
        on the chart), the day's high / low, and the option STRIKES getting the money today."""
        out = []
        for lv in user_levels:
            out.append({"price": float(lv["price"]), "role": lv["role"].replace("alt_", ""), "label": lv["label"].replace("↓ ", "").replace("↑ ", ""),
                        "alt": bool(lv.get("alt"))})
        refs = self._refs(st, t)
        sc = self.cfg.get("studies") or {}
        if refs.get("vwap"):
            out.append({"price": refs["vwap"], "role": "vwap", "label": refs["vwap_label"], "color": self._key_color("VWAP", sc)})
        if refs.get("sma50"):
            out.append({"price": refs["sma50"], "role": "sma50", "label": "50-DAY", "color": self._key_color("D50", sc)})
        if st.day_hi:
            out.append({"price": st.day_hi[0], "role": "hod", "label": "HIGH OF DAY", "color": self._key_color("HOD", sc)})
        if st.day_lo:
            out.append({"price": st.day_lo[0], "role": "lod", "label": "LOW OF DAY", "color": self._key_color("LOD", sc)})
        # the KEY LEVELS from the daily chart and the session (VWAP / 50-day / HOD / LOD are above already)
        for L in self.key_levels(st, t):
            if L["code"] in ("VWAP", "D50", "HOD", "LOD"):
                continue
            out.append({"price": L["price"], "role": "key", "code": L["code"], "label": L["name"], "short": L["short"], "color": L["color"]})
        lc = self.cfg.get("ladder", {})
        keep = lc.get("flow_window_minutes", 60) * 60.0
        agg = {}
        # the strikes being HAMMERED: out-of-the-money calls or puts BOUGHT at the ask, close expirations only
        # (SETTINGS > Ladder). Sold-at-the-bid, in-the-money and far-dated prints stay in the flow feed, off the ladder
        max_dte = float(lc.get("strike_max_dte", 7))
        otm_only = bool(lc.get("strike_otm_only", True))
        for m in st.flow_marks:
            if t - m["t"] > max(keep, 6.5 * 3600) or not m.get("strike") or m.get("side") != "ask":
                continue
            if m.get("dte") is not None and float(m["dte"]) > max_dte:
                continue
            sp = m.get("spot")
            if otm_only and sp and (m["strike"] <= sp if m["cp"] == "C" else m["strike"] >= sp):
                continue
            a = agg.setdefault((m["strike"], m["cp"]), {"prem": 0.0, "n": 0, "hot": False, "t": 0, "dte": None})
            a["prem"] += m["prem"]; a["n"] += 1; a["hot"] = a["hot"] or m["hot"]; a["t"] = max(a["t"], m["t"])
            if m.get("dte") is not None:
                a["dte"] = float(m["dte"]) if a["dte"] is None else min(a["dte"], float(m["dte"]))
        floor = float(lc.get("strike_min_premium", 100000))
        top = sorted(((k, a) for k, a in agg.items() if a["prem"] >= floor), key=lambda x: -x[1]["prem"])[:4]
        for (strike, cp), a in top:
            out.append({"price": float(strike), "role": "strike", "cp": cp, "label": f"{strike:g}{cp}",
                        "prem": round(a["prem"]), "n": a["n"], "hot": a["hot"], "age": round(t - a["t"]),
                        "dte": None if a["dte"] is None else round(a["dte"], 1), "bought": True})
        # the SNEAKY PIVOTS TED found on the 60-minute (micro supply / demand inside the channel)
        for sp in (getattr(st, "sneaky_auto", None) or [])[:3]:
            out.append({"price": float(sp["price"]), "role": "sneaky_auto", "label": f"SNEAKY {sp.get('kind', '').upper()}",
                        "touches": sp.get("touches"), "room": sp.get("room")})
        # the RELOAD buyers / sellers TED has proven: your edge, on the ladder strip too when they are off the rows
        for tr in st.trackers.values():
            if tr.proven and tr.displayed > 0:
                out.append({"price": float(tr.price), "role": "reload_" + ("bid" if tr.side == BID else "ask"),
                            "label": "RELOAD " + ("BUYER" if tr.side == BID else "SELLER"),
                            "refills": max(tr.refreshes_window(t), tr.proven_refills), "absorbed": round(tr.absorbed_total)})
        for m in out:
            m["dist"] = round(m["price"] - last, 4) if last else None
        return out

    LADDER_ROW_ROLES = ("trigger", "second_entry", "stop", "target", "mp", "extra", "sneaky")   # your drawn lines

    def _memory_ladder(self, st, t, user_levels, half_rows=None):
        """Price rows around the market, each carrying what happened there.

        Unlike a normal ladder (current size only), every row remembers: shares
        that traded into the bid / the ask at that price over MEMORY_SECONDS, how
        many times resting size came back after being hit, and the reload state.
        """
        bid, ask = st.bbo()
        center = (bid + ask) / 2 if bid and ask else st.price()
        if not center:
            return {"rows": [], "max_size": 0, "max_traded": 0}
        half_rows = int(half_rows or getattr(self, "ladder_half_rows", None) or self.cfg.get("ladder", {}).get("half_rows", 12))
        tk = tick_size(center, st.symbol)      # the instrument's own increment when IBKR has told us
        ck = price_key(center, tk)
        # a STILL ladder: the rows stay where they are while price moves inside them, so a size at a price stays
        # at the same spot on screen (re-centring on every tick made every row jump). Re-centres only when price
        # comes within a few rows of the top or bottom edge
        edge = max(2, int(self.cfg.get("ladder", {}).get("recenter_rows", 4)))
        lc = getattr(st, "lad_center", None)
        if lc is None or lc[1] != tk or abs(ck - lc[0]) > half_rows - edge:
            st.lad_center = (ck, tk)
        ck = st.lad_center[0]
        keys = list(range(ck + half_rows, ck - half_rows - 1, -1))
        tags = {}
        for lv in user_levels:
            k = price_key(lv["price"], tk)
            tags.setdefault(k, []).append(lv["label"])
        marks = self._ladder_marks(st, t, user_levels, st.price())
        lvmap = {}
        for m in marks:
            k = price_key(m["price"], tk)
            lvmap.setdefault(k, []).append(m)
            # YOUR lines (pivot, 2nd entry, stop, target, your levels) get their own row past a gap so you see them
            # come: they only change when you draw. Marks that come and go (flow strikes, reloaders, auto sneaky
            # pivots, HOD / LOD) do NOT add rows (that made the ladder grow, shrink and jump): the strip lists them
            if k not in keys and abs(k - ck) <= 80 and m["role"] in self.LADDER_ROW_ROLES:
                keys.append(k)
        keys = sorted(set(keys), reverse=True)
        self._prune_memory(st, t)
        sums = st.mem_sums
        # the tape, visits, PULL / STACK and big-size memory are filed under the default tick key (the print's own
        # price); the rows use the instrument's tick: translate, so a non-default IBKR tick never blanks the columns
        dk = {k: price_key(round(k * tk, 4)) for k in keys}
        clr = getattr(st, "mem_clear", None) or {}
        # URGENCY: what hit the bid / lifted the offer at each price in the last few seconds (the clean ladder's bars)
        u_win = float(self.cfg.get("ladder", {}).get("urgency_seconds", 15))
        urg = {}
        for it in reversed(st.memory):
            if t - it[0] > u_win:
                break
            urg[(it[1], it[3])] = urg.get((it[1], it[3]), 0.0) + it[4]
        sold = {k: max(0.0, sums.get((dk[k], "sell"), 0.0) - (clr.get((dk[k], "sell")) or (0, 0.0))[1]) for k in keys}
        bought = {k: max(0.0, sums.get((dk[k], "buy"), 0.0) - (clr.get((dk[k], "buy")) or (0, 0.0))[1]) for k in keys}
        vis = getattr(st, "visits", None) or {}
        vopen = getattr(st, "visit_open", None) or set()
        lc = self.cfg.get("ladder", {})
        sw = float(lc.get("stack_seconds", 60))
        mine = {}
        for o in self._pending(st.symbol):
            # a stop / stop-limit sits on the ladder at its TRIGGER (where it fires), a limit at its limit
            stopish = str(o.get("type") or "") in ("STP", "STP LMT")
            for p_ in ((o.get("aux"), o.get("lmt")) if stopish else (o.get("lmt"), o.get("aux"))):
                if p_:
                    mine.setdefault(price_key(p_, tk), []).append({
                        "id": o.get("order_id"), "action": o.get("action", "?"),
                        "qty": int(o.get("remaining") or o.get("qty") or 0), "role": o.get("role", "entry"),
                        "status": o.get("status")})
                    break
        trk = {}
        for tr in st.trackers.values():
            trk[("bid" if tr.side == BID else "ask", price_key(tr.price, tk))] = tr
        bb = price_key(bid, tk) if bid else None
        ba = price_key(ask, tk) if ask else None
        last = st.l1["last"]
        lk = price_key(last, tk) if last else None
        fw = st.__dict__.get("_flipw")
        rows, prev = [], None
        max_size = max_traded = 0.0
        big_bar = self.big_shares_for(st); huge_x = self.cfg.get("ladder", {}).get("huge_multiple", 3.0)
        flow_rows = self._flow_rows(st, t, tk) if st.flow_marks else {}
        for k in keys:
            price = round(k * tk, 4)
            b_sz = st.book.size_at(BID, price) if st.book else None
            a_sz = st.book.size_at(ASK, price) if st.book else None
            row = {
                "price": fmt_price(price),
                "gap": prev is not None and prev - k > 1,
                "bid": round(b_sz) if b_sz else 0, "ask": round(a_sz) if a_sz else 0,
                "sold": round(sold.get(k, 0)), "bought": round(bought.get(k, 0)),
                "tags": tags.get(k, []),
                "mine": mine.get(k, []),
                "flow": flow_rows.get(k),
                "best_bid": k == bb, "best_ask": k == ba, "last": k == lk,
                "u_s": round(urg.get((dk[k], "sell"), 0.0)), "u_b": round(urg.get((dk[k], "buy"), 0.0)),
            }
            bk = (st.__dict__.get("basket") or {}).get(dk[k])
            if bk is not None:
                row["bk"] = [round(bk[0]), round(bk[1]), round(bk[2]), bk[3]]
            if fw is not None and fw.flips:
                fl = fw.at(price)
                if fl:
                    row["flip"] = fl
            v = vis.get(dk[k])
            if v is not None:
                row["vs"], row["vb"] = round(v["s"]), round(v["b"])
                row["vn"] = sum(1 for x in v["ts"] if t - x <= MEMORY_SECONDS)
                row["vopen"] = dk[k] in vopen
            for side, sd in (("b", BID), ("a", ASK)):
                ps = st.pulls.pullstack(sd, dk[k], t, sw)
                if ps is not None:
                    row["ps_" + side] = ps
            if k in lvmap:
                row["lv"] = lvmap[k]
            for side in ("bid", "ask"):
                sd = BID if side == "bid" else ASK
                rec = st.big[sd].get(dk[k])
                if rec is not None and rec[2]:
                    row[side + "_big"] = {"times": rec[0], "huge": row[side] >= big_bar * huge_x}
                # REAL / MIXED / FAKE: of the size that has left this price, how much traded vs vanished
                real = st.pulls.at(sd, dk[k])
                if real is not None:
                    row[side + "_real"] = real
                story = st.pulls.story(sd, dk[k])
                if story is not None:
                    row[side + "_story"] = story
                tr = trk.get((side, k))
                if tr is not None:
                    # a proven reload keeps the refills that proved it, even after they age out of the window
                    row[side + "_refills"] = max(tr.refreshes_window(t), tr.proven_refills if tr.proven else 0)
                    row[side + "_rseq"] = tr.refill_seq                    # the BASKET pulses once per new refill
                    row[side + "_rf"] = sum(1 for x in tr.refresh_times if t - x <= 60)   # refills in the last minute: the glow
                    row[side + "_state"] = tr._display_state(t)
                    row[side + "_proven"] = tr.proven
                    row[side + "_absorbed"] = round(tr.absorbed_total)
                    row[side + "_peak"] = round(tr.peak_displayed)
                    # the same participant across visits: BACK ×n, how long he was gone, what he absorbed in all
                    row[side + "_back"] = dict(tr.back) if tr.back and tr.proven else None
                    row[side + "_episodes"] = len(tr.episodes)
                    row[side + "_absorbed_all"] = round(tr.absorbed_all + tr.absorbed_total)
                    # conviction drives the brightness of a proven row: RELOADING bright, STILL THERE, NOT RELOADING dim,
                    # CLEANED UP / PULLED a ghost
                    row[side + "_conv"] = tr.conviction(t)
                    row[side + "_stage"] = tr.stage(t)
                    row[side + "_slug"] = SLUG.get(row[side + "_stage"])
                    row[side + "_since_refill"] = round(tr.vol_since_refill) if tr.proven else 0
                    row[side + "_refill_age"] = round(t - tr.last_refill_t) if tr.proven and tr.last_refill_t is not None else None
                    # SOMEBODY KNOWS SOMETHING: short-dated out-of-the-money flow agreeing with this level (calls for a buyer, puts for a seller)
                    if tr.proven or tr.role != "auto":
                        kn = self._knows(st, sd, t)
                        if kn["dollars"] > 0:
                            row[side + "_knows"] = {"knows": kn["knows"], "score": kn["score"], "dollars": kn["dollars"],
                                                    "prints": kn["prints"], "against": kn["against"], "words": kn["words"]}
                    # never call a level cleared while something is sitting there again
                    row[side + "_verdict"] = (tr.last_verdict[0] if tr.last_verdict and t - tr.last_verdict[1] < 60
                                              and tr.displayed <= 0 else None)
                # the long memory: a level that absorbed real size here earlier today, whether or not anyone is
                # tracking it now. Only when nothing proven is lit on this row (the live read wins)
                ah = st.absorb_hist.get((side, k))
                if ah is not None:
                    row[side + "_abs"] = round(ah[1])                     # the BASKET's absorbed = the absorbed-here mark
                if ah is not None and ah[4] and ah[1] >= self.cfg["reload"]["min_absorbed_shares"] and not (tr is not None and tr.proven):
                    row[side + "_was"] = {"shares": round(ah[1]), "age": round(t - ah[2]), "verdict": ah[3]}
            max_size = max(max_size, row["bid"], row["ask"])
            max_traded = max(max_traded, row["sold"], row["bought"])
            rows.append(row)
            prev = k
        return {"rows": rows, "max_size": round(max_size), "max_traded": round(max_traded),
                "memory_minutes": MEMORY_SECONDS // 60, "big_shares": big_bar, "big_default": st.big_shares is None,
                "huge_shares": big_bar * huge_x, "marks": marks, "last": last, "tick": tk,
                "visit_away": int(lc.get("visit_away_ticks", 3)), "stack_seconds": int(sw),
                "basket": dict({k: v for k, v in lc.items() if k.startswith("basket_")}, norm=self._basket_norm(st, t))}

    def _basket_norm(self, st, t):
        """A price's NORMAL volume today (the median of every traded price's total): a full basket is
        ``basket_full_x`` times it. Kept for a few seconds."""
        memo = st.__dict__.setdefault("_bknorm", [None, 0.0])
        if memo[0] is not None and t - memo[0] < 5:
            return memo[1]
        vals = sorted(v[0] for v in (st.__dict__.get("basket") or {}).values() if v[0] > 0)
        memo[0], memo[1] = t, (vals[len(vals) // 2] if vals else 0.0)
        return round(memo[1])

    BREAK_CODES = ("PMH", "PML", "PDH", "PDL", "PDC", "PDO", "AHH", "AHL", "OPEN")

    def _break_trap(self, st, t, price, size, side, day):
        """BREAK TRAPS (breaktrap.py): every print checks the key levels it may have taken out, counts the breakout
        crowd, and calls it when they get trapped (price back through the level), released (new extreme) or back
        at their exit."""
        bc = self.cfg.get("breaktrap") or {}
        if not bc.get("enabled", True):
            return
        from .breaktrap import BreakTraps
        bt = st.__dict__.get("_bt")
        if bt is None:
            bt = st._bt = BreakTraps()
        rth = self.connection["state"] == "DEMO" or ps60.is_rth(t)
        if bt.day != day:
            bt.reset_day(day)
        if rth:                                     # a desk started mid-session knows the day's high / low already
            if bt.hi is None and st.day_hi:
                bt.hi = [st.day_hi[0], st.day_hi[1]]
            if bt.lo is None and st.day_lo:
                bt.lo = [st.day_lo[0], st.day_lo[1]]
        tk = tick_size(price, st.symbol)

        def resting(up, lv):
            sd = ASK if up else BID
            k = price_key(lv)
            vals = [st.book.size_at(sd, lv) if st.book else 0, st.pulls.prev[sd].get(k, 0.0)]
            ad = st.pulls.added[sd].get(k)
            if ad and t - ad[2] <= 120:
                vals.append(ad[1])
            return max(v or 0 for v in vals)
        levels = st.__dict__.get("_bt_levels") or []
        evs = bt.update(t, price, size, side, tk, levels, rth, day, bc, resting)
        for kind, b in evs:
            if kind != "BROKE":
                self._break_trap_alert(st, kind, b, price, t)

    def _break_trap_alert(self, st, kind, b, price, t):
        bc = self.cfg.get("breaktrap") or {}
        if kind == "TRAPPED" and b["shares"] < float(bc.get("min_shares", 1000)):
            b["quiet"] = True                       # too few caught to call: the box still shows it
            return
        if b.get("quiet"):
            return
        who = "longs" if b["up"] else "shorts"
        avg = b["usd"] / b["shares"] if b["shares"] else b["level"]
        under = (avg - price) if b["up"] else (price - avg)
        if kind == "TRAPPED":
            label = f"TRAPPED {who.upper()} · {b['name']}"
            text = (f"TRAPPED {who.upper()} at {b['name']} {narrative.px(b['level'])}: {b['prints']:,} {'buy' if b['up'] else 'sell'} orders, "
                    f"{narrative.shares(b['shares'])} shares, {narrative.dollars(b['usd'])} {'bought at or over' if b['up'] else 'sold at or under'} it, "
                    f"average {narrative.px(avg)}; price {narrative.px(price)}, {self._cents(under)} under them. They get out at {narrative.px(avg)}.")
            words = (f"Trapped {who} at {b['say']}. {narrative.shares(b['shares'])} shares, {b['prints']} orders, average {narrative.px(avg)}. "
                     f"Price {narrative.px(price)}, {self._cents(under)} under them. They get out at {narrative.px(avg)}.")
        elif kind == "RECLAIMED":
            label = f"BREAK HELD · {b['name']}"
            text = f"BREAK HELD at {b['name']} {narrative.px(b['level'])}: new {'high' if b['up'] else 'low'} {narrative.px(price)} — the trapped {who} are out of it."
            words = f"{b['say'].capitalize()} break held. New {'high' if b['up'] else 'low'}, the trapped {who} are out."
        else:
            label = f"AT TRAPPED {who.upper()}' EXIT · {b['name']}"
            text = f"AT THE TRAPPED {who.upper()}' EXIT {narrative.px(avg)} ({b['name']} {narrative.px(b['level'])}): {narrative.shares(b['shares'])} shares {'sell' if b['up'] else 'cover'} here to get out."
            words = f"Back at the trapped {who}' exit, {narrative.px(avg)}. Watch for their {'selling' if b['up'] else 'covering'}."
        alert = {"t": t, "symbol": st.symbol, "label": label, "price": fmt_price(b["level"]), "side": "bid" if b["up"] else "ask",
                 "role": "breaktrap", "text": text, "words": f"{st.symbol}. {words}" if bc.get("voice", True) else None,
                 "key": f"{round(t, 2)}|{st.symbol}|{label}"}
        self.alerts.appendleft(alert); self._rec(dict(alert, ev="alert")); self.log(st.symbol, text, t, kind="level")
        try:            # the PS60 STORY carries it too: who got caught at which level
            st.storybook.say("breaktrap", (kind, round(b["level"], 4)), text, "bad" if b["up"] == (kind == "TRAPPED") else "good", t, repeat=600.0)
        except Exception:
            pass
        for fn in self.listeners:
            try:
                fn(alert)
            except Exception:
                pass

    def _break_trap_levels(self, st, t):
        """The key levels a break is watched at (refreshed on the pace clock, read on every print)."""
        from . import studies as _stu
        pm_live = self.connection["state"] != "DEMO" and _stu.ny_secs(t) < 34200     # premarket high / low still forming
        out = []
        for L in self.key_levels(st, t):
            codes = str(L.get("code") or "").split("/")
            if pm_live and any(c in ("PMH", "PML") for c in codes):
                continue
            if any(c in self.BREAK_CODES for c in codes):
                out.append((L["name"], L["say"], float(L["price"])))
        st._bt_levels = out

    def _break_trap_pane(self, st, t):
        bt = st.__dict__.get("_bt")
        if bt is None or not (self.cfg.get("breaktrap") or {}).get("enabled", True):
            return None
        bc = self.cfg.get("breaktrap") or {}
        v = bt.view(t, st.price(), int(bc.get("show", 3)), float(bc.get("retrace_dollars", 0.30)))
        return v or None

    def _sequence(self, st, t, ps):
        """The PS60 SEQUENCE over the BASKET ladder (ladderbasket.sequence), with the live verdict at the trigger."""
        if not (self.cfg.get("ladder") or {}).get("basket_sequence", True):
            return None
        from .ladderbasket import sequence
        se = (ps or {}).get("se") if isinstance(ps, dict) else None
        trig = st.play.get("trigger")
        if not trig or not se:
            return None
        k = price_key(trig)

        def stage_at(side):
            tr = st.trackers.get((BID if side == "bid" else ASK, k))
            if tr is None:
                return None, 0
            return tr.stage(t), tr.displayed
        return sequence(st.play, se, stage_at, t)

    def _day_trap_pane(self, st, t):
        dt = self._day_trap(st, t, st.price())
        self._day_trap_watch(st, dt, t)
        memo = getattr(st, "day_trap_memo", None)
        if dt is not None:
            dt["exit_level"] = {"price": memo["exit"], "side": memo["side"], "state": memo["state"], "age": round(t - memo["t"])} if memo else None
        return dt

    def _day_trap(self, st, t, price):
        """TRAPPED on the day: the strong move that reversed. Everything bought at the ask ABOVE the current price
        since the open is a long underwater (sold at the bid below it, a short underwater): how many shares, their
        average price, how far under they sit, and what share of the session they are. The session high / low
        with its time says what the move was ("opening high 187.40 at 9:52, now −2.3%"). Gross figures: we cannot
        see who got out, so read it as pressure — their average is where the next push meets supply / demand."""
        tc = self.cfg["trap"]
        if not price or not st.day_sums:
            return None
        tk = tick_size(price, st.symbol)
        pk = price_key(price, tk)
        longs = shorts = total = 0.0
        l_w = s_w = 0.0
        for (k, side), (size, w, p) in st.day_sums.items():
            total += size
            if side == "buy" and k > pk:
                longs += size; l_w += w
            elif side == "sell" and k < pk:
                shorts += size; s_w += w
        if total <= 0:
            return None
        hi, lo = st.day_hi, st.day_lo
        drop = (hi[0] - price) / hi[0] * 100 if hi and hi[0] else 0.0
        rise = (price - lo[0]) / lo[0] * 100 if lo and lo[0] else 0.0
        heavy, lean, min_move = float(tc.get("session_heavy_fraction", 0.35)), float(tc.get("session_lean_fraction", 0.20)), float(tc.get("session_min_move_pct", 1.0))
        min_under, min_age = float(tc.get("session_min_under_pct", 1.0)), float(tc.get("session_min_minutes_since_extreme", 15)) * 60.0
        lf, sf = longs / total, shorts / total
        l_avg = l_w / longs if longs else None
        s_avg = s_w / shorts if shorts else None
        l_under = (l_avg - price) / l_avg * 100 if l_avg else 0.0
        s_under = (price - s_avg) / s_avg * 100 if s_avg else 0.0
        state, side = "", None
        # a trap needs a MOVE that reversed: the extreme set a while ago, price well off it, and the crowd's
        # average really underwater — chop inside a range is not a trap, whatever the fractions say. Once called,
        # it holds until the crowd is less than half as deep (no flicker at the threshold)
        prev = getattr(st, "day_trap_state", "") or ""
        hold_l, hold_s = "LONGS" in prev, "SHORTS" in prev
        # the share of the day's volume gates the CALL only: once trapped, the crowd does not shrink because more
        # volume trades later — it holds on how deep underwater they still are
        l_ok = (hold_l or lf >= lean) and l_under >= (min_under / 2 if hold_l else min_under) and drop >= (min_move / 2 if hold_l else min_move) and hi and t - hi[1] >= min_age
        s_ok = (hold_s or sf >= lean) and s_under >= (min_under / 2 if hold_s else min_under) and rise >= (min_move / 2 if hold_s else min_move) and lo and t - lo[1] >= min_age
        # the SHAPE: a trap is a move that went one way and turned (gap / run down, then back up: shorts TRAPPED). A clean
        # trend from the open that left the other side underwater is not a trap — shorts are SQUEEZED (longs FLUSHED)
        open_px = None
        try:
            from .ps60 import ny_offset, SESSION_OPEN
            off = ny_offset(t); day0 = (int((t + off) // 86400) * 86400) - off + SESSION_OPEN
            first = [m for m in st.bars if m >= day0]
            open_px = st.bars[min(first)][0] if first else None
        except Exception:
            open_px = None
        down_first = (open_px - lo[0]) / open_px * 100 if open_px and lo else None     # how far it fell from the open before the low
        up_first = (hi[0] - open_px) / open_px * 100 if open_px and hi else None       # how far it ran from the open before the high
        if l_ok and (lf >= sf or hold_l) and not (s_ok and hold_s):
            clean = up_first is not None and up_first < min_move / 2
            word = "LONGS FLUSHED" if clean else "LONGS TRAPPED"
            state, side = (word + " HEAVY" if lf >= heavy else word), "long"
        elif s_ok:
            clean = down_first is not None and down_first < min_move / 2
            word = "SHORTS SQUEEZED" if clean else "SHORTS TRAPPED"
            state, side = (word + " HEAVY" if sf >= heavy else word), "short"
        out = {"state": state, "side": side, "session_shares": round(total),
               "longs": {"shares": round(longs), "avg": fmt_price(l_avg), "under_pct": round((l_avg - price) / l_avg * 100, 2) if l_avg else None,
                         "fraction": round(lf, 2), "dollars": round(l_w)} if longs else None,
               "shorts": {"shares": round(shorts), "avg": fmt_price(s_avg), "under_pct": round((price - s_avg) / s_avg * 100, 2) if s_avg else None,
                          "fraction": round(sf, 2), "dollars": round(s_w)} if shorts else None,
               "high": {"price": fmt_price(hi[0]), "t": hi[1], "drop_pct": round(drop, 2)} if hi else None,
               "low": {"price": fmt_price(lo[0]), "t": lo[1], "rise_pct": round(rise, 2)} if lo else None}
        # option flow on the trap: puts bought while longs are trapped (calls while shorts are) is money pressing the
        # same way the trapped crowd will be forced to go; flow the other way says somebody is fading the move
        out["flow"] = self._trap_flow(st, side, (hi[1] if side == "long" else lo[1]) if side and hi and lo else None, t) if side else None
        out["text"] = narrative.day_trap_text(st.symbol, out, price)
        # the actionable level: the trapped crowd's average is where the next push meets their exit
        out["exit"] = (fmt_price(l_avg) if side == "long" else fmt_price(s_avg)) if side else None
        return out

    def _trap_flow(self, st, side, since, t):
        """Option money on this name since the extreme that set the trap: calls and puts bought at the ask, and
        which way they lean against the trapped crowd. 'presses' = flow goes the way the trapped side must exit
        (puts on trapped longs, calls on trapped shorts); 'fades' = flow is betting on the trapped side's recovery."""
        prints = list(self.flow.by_symbol.get(st.symbol, ()))
        since = since if since is not None else t - 3600.0
        prints = [p for p in prints if p.get("t", 0) >= since and p.get("side") == "ask"]
        lean, calls, puts = board.flow_leans(prints)
        presses = puts if side == "long" else calls
        fades = calls if side == "long" else puts
        verdict = "" if not calls and not puts else ("PRESSES" if presses > fades else "FADES" if fades > presses else "MIXED")
        return {"calls": calls, "puts": puts, "prints": len(prints), "since": since, "presses": presses, "fades": fades, "verdict": verdict}

    def _trap_flow_watch(self, st, p, t):
        """A print that presses a trapped crowd: puts bought while longs are trapped, calls while shorts are.
        Says it when the pressing money since the trap passes the bar, then again each time it doubles."""
        side = "long" if "LONGS" in (getattr(st, "day_trap_state", "") or "") else "short" if "SHORTS" in (getattr(st, "day_trap_state", "") or "") else None
        if not side or p.get("side") != "ask" or p.get("cp") != ("P" if side == "long" else "C"):
            return
        ext = st.day_hi if side == "long" else st.day_lo        # money since the extreme that set the trap, as on the pane
        f = self._trap_flow(st, side, ext[1] if ext else None, t)
        bar = float(self.cfg["trap"].get("session_flow_min_dollars", 100000))
        said = getattr(st, "day_trap_flow_said", 0.0)
        if f["presses"] < bar or f["presses"] < 2 * said or t - getattr(st, "day_trap_flow_said_t", -1e9) < 120:
            return
        st.day_trap_flow_said, st.day_trap_flow_said_t = f["presses"], t
        what = "puts" if side == "long" else "calls"
        who = "trapped longs" if side == "long" else "trapped shorts"
        label = f"FLOW PRESSES {who.upper()}"
        text = (f"{label}: {narrative.dollars(f['presses'])} of {what} bought at the ask since the trap"
                f"{' (' + narrative.dollars(f['fades']) + ' the other way)' if f['fades'] else ''}. "
                f"Option money is leaning on the same side the {who} will be forced to {'sell' if side == 'long' else 'cover'} into.")
        words = f"{board.say_money(f['presses'])} in {what} since the {who} were called. The flow is pressing them."
        alert = {"t": t, "symbol": st.symbol, "label": label, "price": fmt_price(st.price()), "side": "ask" if side == "short" else "bid",
                 "role": "trap", "text": text, "words": words, "premium": f["presses"], "cp": p.get("cp"),
                 "key": f"{round(t, 2)}|{st.symbol}|{label}|{f['presses']}"}
        self.alerts.appendleft(alert); self._rec(dict(alert, ev="alert")); self.log(st.symbol, text, t, kind="flow")
        for fn in self.listeners:
            try:
                fn(alert)
            except Exception:
                pass

    def _day_trap_watch(self, st, dt, t):
        """Say it once when the day's trap state changes (and not again for 5 minutes); and once when price comes
        back to the trapped crowd's average — their exit — where the push meets their selling / covering."""
        if dt is None:
            return
        prev = getattr(st, "day_trap_state", "") or ""
        state = dt["state"]
        st.day_trap_state = state
        # one call per trap: when it starts, when the side flips, and once when it goes HEAVY — not on every wobble
        same_side = state and prev and state.split(" ")[0] == prev.split(" ")[0]
        if not same_side:
            st.day_trap_heavy_said = "HEAVY" in state          # a new trap: HEAVY counts as said if it starts heavy
        if same_side and not ("HEAVY" in state and "HEAVY" not in prev and not getattr(st, "day_trap_heavy_said", False)):
            return
        if same_side:
            st.day_trap_heavy_said = True                      # HEAVY is said once per trap, never on a wobble at the line
        price = st.price()
        # the crowd's exit stays a level for an hour after the trap was called: by the time price gets back there
        # they are no longer "underwater", but that is exactly where their selling / covering meets the push
        if state and dt.get("exit"):
            if not same_side:
                st.day_trap_flow_said = 0.0
            st.day_trap_memo = {"side": dt["side"], "exit": dt["exit"], "t": t, "state": state}
        memo = getattr(st, "day_trap_memo", None)
        if memo and t - memo["t"] > float(self.cfg["trap"].get("session_exit_memory_seconds", 3600)):
            st.day_trap_memo = memo = None
        if memo and price:
            band = 4 * tick_size(price, st.symbol) + 1e-9
            prev = getattr(st, "day_trap_prev_price", None)
            crossed = prev is not None and ((prev < memo["exit"] <= price) or (prev > memo["exit"] >= price))
            at = abs(price - memo["exit"]) <= band or crossed
            was = getattr(st, "day_trap_at_exit", False)
            if at and not was and t - getattr(st, "day_trap_exit_said_t", -1e9) >= 600:
                st.day_trap_exit_said_t = t
                who = "trapped longs" if memo["side"] == "long" else "trapped shorts"
                text = (f"AT THE {who.upper()}' EXIT {narrative.px(memo['exit'])}: price is back at the price {who} paid on average — "
                        f"expect them to {'sell into this push: look for a reload seller or a rejection here' if memo['side'] == 'long' else 'cover into this dip: look for a reload buyer or a remount here'}.")
                alert = {"t": t, "symbol": st.symbol, "label": "AT TRAPPED EXIT", "price": fmt_price(price), "side": "ask" if memo["side"] == "long" else "bid",
                         "role": "trap", "text": text, "words": f"back at the {who}' exit, {narrative.px(memo['exit'])}. Expect them to {'sell' if memo['side'] == 'long' else 'cover'} here.",
                         "key": f"{round(t, 2)}|{st.symbol}|AT TRAPPED EXIT"}
                self.alerts.appendleft(alert); self._rec(dict(alert, ev="alert")); self.log(st.symbol, text, t, kind="level")
                for fn in self.listeners:
                    try:
                        fn(alert)
                    except Exception:
                        pass
            st.day_trap_at_exit = at and not crossed
        if price:
            st.day_trap_prev_price = price
        if state == prev or not state or t - getattr(st, "day_trap_said_t", -1e9) < 300:
            return
        st.day_trap_said_t = t
        alert = {"t": t, "symbol": st.symbol, "label": state, "price": fmt_price(st.price()), "side": "bid" if dt["side"] == "long" else "ask",
                 "role": "trap", "text": dt["text"], "words": narrative.day_trap_words(dt), "key": f"{round(t, 2)}|{st.symbol}|{state}"}
        self.alerts.appendleft(alert)
        self._rec(dict(alert, ev="alert"))
        self.log(st.symbol, f"{state}: {dt['text']}", t, kind="level")
        for fn in self.listeners:
            try:
                fn(alert)
            except Exception:
                pass

    def _trap(self, st, t, price):
        """Aggressive prints that are now underwater.

        Buys (paid the offer) above the current price are trapped longs; sells
        (hit the bid) below it are trapped shorts. Gross figures over the window:
        we cannot see who already got out, so read them as pressure, not fact.
        """
        tc = self.cfg["trap"]
        if not price:
            return None
        tk = tick_size(price)
        pk = price_key(price, tk)
        longs = shorts = 0.0
        l_lo = l_hi = s_lo = s_hi = None
        l_w = s_w = 0.0
        self._prune_memory(st, t)
        for (k, side), (size, w, p) in st.trap_sums.items():   # one entry per price, not per print
            if side == "buy" and k > pk:
                longs += size
                l_w += w
                l_lo = p if l_lo is None else min(l_lo, p)
                l_hi = p if l_hi is None else max(l_hi, p)
            elif side == "sell" and k < pk:
                shorts += size
                s_w += w
                s_lo = p if s_lo is None else min(s_lo, p)
                s_hi = p if s_hi is None else max(s_hi, p)

        def pack(shares, lo, hi, w):
            if shares < tc["min_shares"]:
                return None
            return {"shares": round(shares), "low": fmt_price(lo), "high": fmt_price(hi),
                    "avg": fmt_price(w / shares), "heavy": shares >= tc["heavy_shares"]}
        out = {"longs": pack(longs, l_lo, l_hi, l_w), "shorts": pack(shorts, s_lo, s_hi, s_w),
               "window_minutes": tc["window_seconds"] // 60}
        return out if out["longs"] or out["shorts"] else None

    # ---- CONVICTION BOARD: Dan's option-flow timing, from the source-of-truth spec (twiney/board.py) ---------
    def _daily_closes(self, st):
        return [float(st.daily[k][3]) for k in sorted(st.daily)]

    def _board(self, st, t, ps, reloaders, tape, bars):
        prints = list(self.flow.by_symbol.get(st.symbol, ()))
        cut = t - float(self.cfg.get("flow", {}).get("of_session_minutes", 390)) * 60.0
        prints = [p for p in prints if p.get("t", 0) >= cut]
        b = board.build(st.play, st.price(), (ps or {}).get("se"), (ps or {}).get("mp"), reloaders, tape, prints,
                        self._daily_closes(st), bars, t, self.cfg.get("flow", {}), getattr(st, "board_state", None))
        self._board_watch(st, b, ps, t)
        st.board_state = b["board_state"]
        return b

    def _board_watch(self, st, b, ps, t):
        """§5.4: one alert per state change (WATCH, ARMED, READY TO GO, INVALIDATED), spoken for READY and INVALIDATED."""
        prev = getattr(st, "board_state", None)
        state = b["board_state"]
        if state == prev or state == "PASS":
            return
        if state == "WATCH" and not board.watch_worthy(b["flow_gate"]):
            return                                        # a WATCH is called on real flow, not on a stray print
        if t - getattr(st, "board_said_t", {}).get(state, -1e9) < 300:
            return
        st.board_said_t = getattr(st, "board_said_t", {})
        st.board_said_t[state] = t
        text = board.alert_text(b, st.play, (ps or {}).get("mp"), (ps or {}).get("se"))
        alert = {"t": t, "symbol": st.symbol, "label": {"READY_TO_GO": "READY TO GO", "ARMED": "ARMED", "WATCH": "FLOW WATCH", "INVALIDATED": "INVALIDATED"}[state],
                 "price": fmt_price(st.price()), "side": "ask" if st.play.get("side", "long") == "long" else "bid", "role": "conviction",
                 "text": text, "score": b["score"], "rules": b["rules"], "words": board.words(b)}
        cl = (b.get("flow_gate") or {}).get("cluster") or {}
        if cl.get("ids"):
            alert["flow"] = self._receipt(st.symbol, "C" if st.play.get("side", "long") == "long" else "P", cl["ids"], "short-term, bought at the ask, today")
        alert["key"] = f"{round(t, 2)}|{st.symbol}|BOARD|{state}"
        self.alerts.appendleft(alert)
        self._rec(dict(alert, ev="alert"))
        if state != "WATCH":
            self.log(st.symbol, f"{alert['label']} ({b['score']}): {text}", t, kind="level")
        for fn in self.listeners:
            try:
                fn(alert)
            except Exception:
                pass

    def _big_tape(self, st, t):
        """The BIG TAPE for the pane: large prints and position builders, prices formatted, ages in seconds."""
        b = st.tape.big(t)
        return {"prints": [{"age": round(t - p["t"], 1), "price": fmt_price(p["price"]), "size": round(p["size"]),
                            "dollars": round(p["size"] * p["price"]), "side": p["side"], "exchange": p["exchange"]} for p in b["prints"]],
                "builders": [dict(g, price=fmt_price(g["price"]), biggest=round(g["biggest"])) for g in b["builders"]],
                "shares": b["shares"], "dollars": b["dollars"], "minutes": b["minutes"], "window": b["window"], "need": b["need"]}

    def _reload_basket(self, st, t):
        """THE RELOAD BASKET: every reload buyer and seller of the session on this stock, by price: the shares he
        bought (a buyer) or sold (a seller) at that price over every visit, the dollars, how often he refilled, what he
        shows now and whether he is there. One that leaves stays in the basket for the day."""
        from . import studies
        day = studies.day_key(t)
        bk = st.__dict__.get("_rl_basket")
        if bk is None or bk.get("day") != day:
            bk = st.__dict__["_rl_basket"] = {"day": day, "rows": {}}
        rows = bk["rows"]
        for tr in list(st.trackers.values()):
            if not (tr.state == RELOAD or tr.proven):
                continue
            key = ("bid" if tr.side == BID else "ask", price_key(tr.price))
            sh = float(tr.absorbed_all + tr.absorbed_total)
            r = rows.setdefault(key, {"side": key[0], "price": float(tr.price), "shares": 0.0, "refills": 0, "first": t})
            r["shares"] = max(r["shares"], sh)
            r["refills"] = max(r["refills"], int(max(tr.refreshes_window(t), tr.proven_refills if tr.proven else 0)))
            r["showing"], r["seen"], r["stage"] = round(tr.displayed), t, tr.stage(t)
        out = []
        for (side, _k), r in rows.items():
            here = t - r.get("seen", 0) < 2.0 and (r.get("showing") or 0) > 0
            out.append({"side": side, "price": fmt_price(r["price"]), "shares": round(r["shares"]),
                        "usd": round(r["shares"] * r["price"]), "refills": r["refills"], "showing": r.get("showing", 0) if here else 0,
                        "here": here, "stage": r.get("stage"), "first": r["first"]})
        out.sort(key=lambda x: -x["price"])
        return {"rows": out, "buy_usd": sum(x["usd"] for x in out if x["side"] == "bid"),
                "sell_usd": sum(x["usd"] for x in out if x["side"] == "ask")}

    def _reloaders(self, st, t, price):
        """Nearest confirmed / likely reloaders on each side of the market."""
        below, above = [], []
        for tr in st.trackers.values():
            if tr.state == RELOAD or tr.proven:
                kind = "confirmed"
            elif tr.state == BUILDING and tr.refreshes_window(t) >= 2 and tr.absorbed_window(t) > 0:
                kind = "likely"
            else:
                continue
            item = {"price": fmt_price(tr.price), "side": "bid" if tr.side == BID else "ask", "kind": kind,
                    "role": tr.role, "refills": tr.refreshes_window(t), "absorbed": round(tr.absorbed_total),
                    "showing": round(tr.displayed), "conviction": tr.conviction(t), "stage": tr.stage(t),
                    "knows": self._knows(st, tr.side, t)["knows"], "ps60": self._ps60_reload(tr.price, st.symbol)}
            # at the last price itself: a buyer is holding under price, a seller over it
            at = price and abs(tr.price - price) < 1e-9
            (below if (tr.side == BID if at else (price and tr.price < price)) else above).append(item)
        below.sort(key=lambda x: -x["price"])
        above.sort(key=lambda x: x["price"])
        return {"below": below[:3], "above": above[:3]}

    def fast_pane(self, sym, t=None):
        """STREAMING: what the LEVEL II, the T&S, the quote and the live candle need, the moment it changes. The same
        code as the full pane builds them (same numbers); everything slower stays on the regular refresh."""
        t = t if t is not None else self.last_t
        with self.lock:
            st = self.syms.get(str(sym or "").upper())
            if st is None:
                return None
            bid, ask = st.bbo()
            user_levels = self._user_levels(st.play)

            def at_level(price):
                for lv in user_levels:
                    if lv["role"] in ("trigger", "second_entry", "extra") and price_key(price) == price_key(lv["price"]):
                        return lv["label"]
                return None
            m = max(st.bars) if st.bars else None
            bar = [m] + [round(x, 4) for x in st.bars[m]] if m is not None else None      # the same row the chart gets
            return {"symbol": st.symbol, "sv": st.sv, "now": t,
                    "last": fmt_price(st.l1["last"]), "bid": fmt_price(bid), "ask": fmt_price(ask),
                    "spread": fmt_price(ask - bid) if bid and ask else None,
                    "ladder": self._memory_ladder(st, t, user_levels),
                    "recent": [{"age": round(t - p["t"], 1), "price": fmt_price(p["price"]), "size": round(p["size"]),
                                "side": p["side"], "large": p["large"], "exchange": p["exchange"], "at": at_level(p["price"])}
                               for p in st.tape.recent(14)],
                    "bar": bar}

    def stream_ver(self, sym):
        st = self.syms.get(str(sym or "").upper())
        return st.sv if st is not None else None

    def _pane(self, sym, i, t, order, full=True):
        st = self.syms[sym]
        self._hist_flush(st, t)              # a history change still pending shows in this snapshot's version
        rows = self.cfg["depth"]["rows_displayed"]
        book = st.book
        bids = [[fmt_price(p), round(s), n] for p, s, n in book.levels(BID, rows)] if book else []
        asks = [[fmt_price(p), round(s), n] for p, s, n in book.levels(ASK, rows)] if book else []
        levels = sorted((tr.snapshot(t) for tr in st.trackers.values()),
                        key=lambda x: (x["role"] == "auto", -x["price"], x["side"]))
        for lv in levels:
            for k in ("displayed", "peak_displayed", "absorbed_window", "absorbed_total"):
                lv[k] = round(lv[k])
            lv["real"] = st.pulls.at(BID if lv["side"] == "bid" else ASK, price_key(lv["price"]))
            lv["words"] = stage_words(lv["stage"], lv["side"]) if lv.get("stage") else ""
            kn = self._knows(st, BID if lv["side"] == "bid" else ASK, t)
            lv["knows"] = {"knows": kn["knows"], "score": kn["score"], "dollars": kn["dollars"], "prints": kn["prints"],
                           "sweeps": kn["sweeps"], "against": kn["against"], "top": kn["top"], "cp": kn["cp"], "words": kn["words"]}
            lv["price"] = fmt_price(lv["price"])
        bid, ask = st.bbo()
        tape = st.tape.stats(t)
        tape["speed"] = st.tape.speed(t)
        tape["pace"] = st.pace
        pc = st.pace or {}
        if pc.get("state") not in (None, "QUIET", "WARMING UP"):
            # the T&S SPEED box says what the voice says: one read (PACE: this stock against its own normal, and
            # the last seconds against the ones before), never a second count that can disagree
            tape["speed"]["trend"] = pc.get("accel") or "STEADY"
            tape["speed"]["ratio"] = pc.get("ratio")
        user_levels = self._user_levels(st.play)
        bars = st.bar_list(MAX_BARS)
        first_bar = bars[0][0] if bars else t
        sym_alerts = [a for a in self.alerts if a["symbol"] == sym]
        trap = self._trap(st, t, st.price())
        reloaders = self._reloaders(st, t, st.price())
        headline, tone, lines = narrative.story(st.play, st.price(), levels, bars, tape, t, sym_alerts,
                                                min_shares=self.cfg["reload"]["min_absorbed_shares"],
                                                trap=trap, reloaders=reloaders)

        def at_level(price):
            for lv in user_levels:
                if lv["role"] in ("trigger", "second_entry", "extra") and \
                        price_key(price) == price_key(lv["price"]):
                    return lv["label"]
            return None

        change = self.slot_changes[i] if 0 <= i < len(self.slot_changes) else None
        ps = self._ps60(st, t, bars, st.price())
        kids_ = (st.__dict__.get("_inst") or {}).get("kids")   # the child-order stream, for the ⚙ marks on the tape
        return {
            "slot": i,
            "sv": st.sv,
            "ps60": ps,
            "symbol": sym,
            "pinned": sym in self.pinned,
            "changed": change if change and t - change["t"] < 20 and change.get("prev") else None,
            "play": {k: st.play.get(k) for k in ("side", "trigger", "second_entry", "target", "stop", "mp", "atr", "notes", "setup", "alt",
                                                  "trade_as", "trade_as_set", "opt_key", "opt_qty", "sneaky_levels", "zones")},
            "last": fmt_price(st.l1["last"]),
            "prev_close": fmt_price(st.l1.get("close")),
            "bid": fmt_price(bid), "ask": fmt_price(ask),
            "day": {"open": fmt_price(st.l1.get("open")), "high": fmt_price(st.l1.get("high")), "low": fmt_price(st.l1.get("low")),
                    "prev_close": fmt_price(st.l1.get("close")), "volume": st.l1.get("volume"),
                    "bid_size": st.l1.get("bid_size"), "ask_size": st.l1.get("ask_size")},
            "spread": fmt_price(ask - bid) if bid and ask else None,
            "headline": headline, "tone": tone, "lines": lines,
            # what stays inside the ladder itself: only who is defending a level (the rest goes to the story window)
            "keep_lines": [l for l in [headline] + lines if l.startswith(("Maybe a ", "RELOAD "))][:2],
            "book": {"bids": bids, "asks": asks},
            "ladder": self._memory_ladder(st, t, user_levels),
            "bigtape": self._big_tape(st, t),
            "orderflow": orderflow.pressure(st.tape.prints, t, self.cfg.get("orderflow", {})),
            "daytrap": self._day_trap_pane(st, t),
            "breaktraps": self._break_trap_pane(st, t),
            "seq": self._sequence(st, t, ps),
            "tape": dict(tape, recent=[                  # ⚙ on the prints an algo's child-order stream is made of
                {"age": round(t - p["t"], 1), "price": fmt_price(p["price"]), "size": round(p["size"]),
                 "side": p["side"], "large": p["large"], "exchange": p["exchange"], "at": at_level(p["price"]),
                 "kid": bool(kids_ and p["side"] == kids_["side"].lower() and int(p["size"]) in kids_["sizes_set"] and p["t"] >= kids_["t0"])}
                for p in st.tape.recent(14)]),
            "levels": levels,
            "trap": trap,
            "reloaders": reloaders,
            "reload_basket": self._reload_basket(st, t),
            "dark": st.dark.view(t, st.price()),
            "inst": self._safe_view(self._inst_view, st, t, "institutional footprints"),
            "user_levels": user_levels,
            "log": self.symbol_log(sym),
            "bigmoney": self.bigmoney.for_symbol(sym, st.price(), t, lambda d: self._close_on(st, d)) if self.bigmoney is not None else [],
            "orders": [{"id": o.get("order_id"), "action": o.get("action"), "qty": o.get("remaining") or o.get("qty"),
                        "type": o.get("type"),
                        "price": o.get("aux") if o.get("type") in ("STP", "STP LMT") and o.get("aux") else o.get("lmt") or o.get("aux"),
                        "role": o.get("role", "entry"),
                        "status": o.get("status")}
                       for o in self._pending(sym)],
            "position": self._position_view(sym, st.price()),
            "conviction": self._board(st, t, ps, reloaders, tape, bars),
            # the page keeps its own bar history: full history on request, otherwise just the live tail
            "bars": bars if full else bars[-6:],
            "bars_full": full,
            "hist_ver": st.hist_ver,
            "flow": self.flow.summary(sym, t),
            "daily": [[t0] + [fmt_price(x) for x in st.daily[t0]] + [round(st.daily_vol.get(t0) or 0), 0, 0] for t0 in sorted(st.daily)] if full else None,
            # IBKR's native 5 / 30 minute history: the 5 / 15 and 30 / 60 minute charts reach far enough back for
            # their 200 EMAs to settle like TradingView's (the minute bars only go back 5 days)
            "m5": [[k] + [fmt_price(x) for x in st.m5[k][:4]] + [round(st.m5[k][4] or 0), 0, 0] for k in sorted(st.m5)] if full else None,
            "m30": [[k] + [fmt_price(x) for x in st.m30[k][:4]] + [round(st.m30[k][4] or 0), 0, 0] for k in sorted(st.m30)] if full else None,
            "studies": self.studies_for(st, t),
            "opt_est": self._opt_est(st, t),
            "story": self._story_pane(st),
            "refs": self._refs(st, t),
            "footprint": self._footprint(st, t),
            "marks": [[m, fmt_price(v[0]), side, round(v[1])] for (m, _k, side), v in st.marks.items()
                      if m >= max(first_bar, t - 390 * 60)],
            "events": [[a["t"], a["price"], a["label"], a["side"]] for a in sym_alerts if a["t"] >= first_bar][:60],
            "health": self._health(st, t),
            "halted": getattr(st, "halt_kind", None),
            "slot_age": round(t - self.slots[sym], 1) if sym in self.slots else None,
        }

    def _footprint(self, st, t):
        """Footprint cells per minute. A finished minute never changes: it is built once and kept."""
        cur = int(t // BAR_SECONDS) * BAR_SECONDS
        cache = st.__dict__.setdefault("_foot_cache", {})
        out = []
        for m in sorted(st.foot)[-90:]:
            row = cache.get(m) if m < cur else None
            if row is None:
                row = [m, [[round(c[0], 4), round(c[1]), round(c[2])] for c in sorted(st.foot[m].values(), key=lambda c: c[0])]]
                if m < cur:
                    cache[m] = row
            out.append(row)
        if len(cache) > 300:
            for m in sorted(cache)[:-200]:
                del cache[m]
        return out

    def snapshot(self, t, extra=(), full=None, tv=None):
        """``full``: symbols the page wants the whole bar history for (None = every pane, as before).
        ``tv``: the journal version the page already holds; the same version = the trades are not sent again."""
        jver = self.desk.ver if self.desk else 0      # read BEFORE the trades: a trade closing in between is sent next time
        with self.lock:
            ranked = self.ranking(t)
            wants = (lambda s: True) if full is None else (lambda s: s in full)
            extra_panes = {sym: self._pane(sym, -1, t, None, wants(sym)) for sym in extra
                           if sym in self.syms and sym not in self.slots}
            order = {s: i + 1 for i, (s, _d) in enumerate(ranked)}
            ranking = []
            for p in self.plays:
                st = self.syms[p["symbol"]]
                price = st.price()
                d_trig, d_second = distances(p, price)
                ranking.append({
                    "symbol": p["symbol"], "side": p["side"], "active": p["active"],
                    "rank": order.get(p["symbol"]),
                    "last": fmt_price(st.l1["last"]), "bid": fmt_price(st.l1["bid"]),
                    "ask": fmt_price(st.l1["ask"]),
                    "trigger": p["trigger"], "second_entry": p["second_entry"],
                    "dist_trigger_pct": None if d_trig is None else round(d_trig * 100, 3),
                    "dist_second_pct": None if d_second is None else round(d_second * 100, 3),
                    "status": narrative.short_status(p, price),
                    "depth": st.depth_active,
                    "pinned": p["symbol"] in self.pinned,
                    "retired": st.retired,
                    "target": p.get("target"), "stop": p.get("stop"),
                    "ps60": self._ranking_ps60(st, t),
                    "health": self._health(st, t)["status"],
                    "notes": p["notes"],
                })
            ranking.sort(key=lambda r: (r["rank"] is None, r["rank"] or 0, r["symbol"]))
            # panes keep a fixed screen position; an empty position is None
            panes = [self._pane(sym, i, t, order, wants(sym)) if sym else None for i, sym in enumerate(self.slot_order)]
            return {
                "now": t,
                "uptime": round(t - self.started, 1) if self.started else 0,
                "mode": "PAPER-ONLY ORDER ENTRY · LIVE LOCKED" if not self.cfg["trading"]["allow_live"] else "LIVE TRADING ENABLED",
                "connection": dict(self.connection),
                "feeds": self._feeds(t),
                "chart_rth": bool(self.cfg["chart"].get("regular_hours_only", True)),
                "names": self._spoken_names(),
                "studies_on": {k: bool((self.cfg.get("studies") or {}).get(k)) for k in ("gas", "airspace", "unvisited", "air_board", "gas_readout", "whole_numbers", "atr_zones")},
                "slots": self.cfg["depth"]["slots"],
                "depth_smart": bool(self.cfg["depth"].get("smart_depth", True)),
                "auto_rotate": self.auto_rotate,
                "ranking": ranking,
                "user_alerts": [dict(a) for a in self.user_alerts],
                "urgency": self._urgency_list(t),
                "equity": list(self.equity)[:80],
                "equity_status": dict(self.equity_status),
                "panes": panes,
                "extra": extra_panes,
                "focus": self.focus,
                "symbols": [p["symbol"] for p in self.plays if p["active"]],
                "depth": [pn["symbol"] for pn in panes if pn],   # the page only counts them; the panes carry the data
                "trading": self.trader.snapshot(run_watchdog=False) if self.trader else {"mode": "NONE", "can_trade": False,
                                                                        "why_not": "order entry not loaded"},
                "replay": dict(self.replay) if self.replay else None,
                "score": self.score.view() if (self.cfg.get("score") or {}).get("enabled", True) else None,
                "training": self.trainer.view() if self.trainer is not None else None,
                "account": {
                    "seen": self.account_seen,
                    "pending": sorted((dict(o, state=self.order_state(o)) for o in self._pending()), key=lambda o: -o.get("first_seen", 0)),
                    "done": sorted((dict(o, state=self.order_state(o)) for o in self.orders.values() if o not in self._pending()),
                                   key=lambda o: -o["t"])[:15],
                    "positions": [dict(p, last=fmt_price(self.syms[p["symbol"]].price())
                                       if p["symbol"] in self.syms else None) for p in self.positions.values()],
                    "opt_positions": [self._opt_view(p) for p in self.opt_positions.values()],
                    "fills": sorted(list(self.fills.values()) + self.opt_fills, key=lambda f: -f["t"])[:30],
                },
                "alerts": [dict(a, grade=self.grades.get(a["key"])) for a in list(self.alerts)[:40]],
                "voice": [v for v in list(self.voice)[:20] if t - v["t"] < 60],
                "speech": self._speech_view(),
                "flow": list(self.flow.recent)[:150],
                "flow_scope": self.flow_scope,
                "ladder_half_rows": int(getattr(self, "ladder_half_rows", None) or self.cfg.get("ladder", {}).get("half_rows", 12)),
                "flow_alerts": self.flow_alerts,
                "flow_index_min": self.cfg.get("flow", {}).get("index_min_premium", 5000000),
                "messages": list(self.messages)[:25],
                "recording": getattr(self.recorder, "path", None),
                "desk": {"recording": self.recorder is not None,
                         "started": self.desk.started if self.desk else None,
                         "notes": (self.desk.notes if self.desk else self.notes_list)[-30:],
                         "marks": (self.desk.marks if self.desk else self.marks_list)[-60:],
                         "trades_ver": jver,
                         "trades": (None if self.desk and tv is not None and tv == jver else
                                    self.desk.trades[-60:] if self.desk else []),
                         "open": self.desk.open_view() if self.desk else [],
                         "journal_dir": self.desk.journal_dir() if self.desk else None},
            }
