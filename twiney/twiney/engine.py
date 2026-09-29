"""TWINEY engine: pure market-data state machine.

Every input carries its own timestamp, so the same engine drives live data,
JSONL replay and tests identically. The engine never talks to IBKR; it returns
slot commands ("depth_on"/"depth_off") which the market-data adapter executes.
"""

import threading
from collections import deque

from . import narrative, ps60

from .book import ASK, BID, Book
from .flow import FLOW_LABELS, FlowBook
from .levels import BUILDING, GONE_PENDING, RELOAD, LevelTracker, WATCHING
from .prices import fmt_price, price_key, tick_size
from .ranking import allocate, distances, rank
from .tape import Tape

L1_FIELDS = ("bid", "ask", "last", "bid_size", "ask_size", "last_size", "volume",
             "high", "low", "close", "open")

ALERT_LABELS = ("RELOAD BUYER DETECTED", "RELOAD SELLER DETECTED", "CLEANED UP", "PULLED")
PS60_LABELS = ("REMOUNT", "REJECTION")

BAR_SECONDS = 60
def _k(n):
    """5,000 -> '5k', 18,400 -> '18k', 800 -> '800' (for speech)."""
    n = int(round(n))
    return f"{n // 1000}k" if n >= 1000 else str(n)


MAX_BARS = 2400  # ~6 trading days of 1-minute bars, enough for 60-minute candles
MEMORY_SECONDS = 900   # how long the price-level memory (traded volume by price) looks back
MARK_MINUTES = 400     # absorption bubbles kept for the chart


class SymbolState:
    def __init__(self, play, cfg):
        self.play = play
        self.symbol = play["symbol"]
        self.l1 = {k: None for k in L1_FIELDS}
        self.l1_t = None
        self.depth_active = False
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
        self.remounts = set()   # (level, kind, t) already called
        self.sizes = {ASK: {}, BID: {}}   # last aggregated size per price on each side (voice call-outs)
        self.big = {ASK: {}, BID: {}}     # price_key -> [times big size has shown up here, peak, showing now]
        self.big_shares = None            # per-symbol override of ladder.big_shares
        self.foot = {}          # minute -> {price_key: [bought at ask, sold into bid]} (footprint chart)
        self.voice_last = {}    # (side, price_key, kind) -> t of the last call-out
        self.remount_last = {}  # (level, kind) -> t of the last call (cooldown)
        self.remount_check_t = 0.0
        self.memory = deque()   # (t, price_key, price, aggressor side, size) for the level memory
        self.marks = {}         # (minute, price_key, side) -> [price, absorbed shares]

    def bar_update(self, t, price, size=0.0, side=None):
        m = int(t // BAR_SECONDS) * BAR_SECONDS
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
        keys = sorted(self.bars)
        if limit:
            keys = keys[-limit:]
        return [[k] + [round(x, 4) for x in self.bars[k]] for k in keys]

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
            return self.book.best(BID), self.book.best(ASK)
        return self.l1["bid"], self.l1["ask"]


class Engine:
    def __init__(self, plays, cfg, recorder=None):
        self.cfg = cfg
        self.plays = [p for p in plays]
        self.recorder = recorder
        self.lock = threading.RLock()
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
        self.positions = {}     # (account, symbol) -> {"qty", "avg_cost"}
        self.fills = {}         # exec id -> fill dict
        self.account_seen = False
        self.trader = None      # set by run_twiney when order entry is enabled
        self.sim_broker = None  # demo-mode fill simulator, if any
        self.plays_path = None  # where to save levels added from the chart
        self.replay = None      # replay control block when replaying a recording
        self.grades = {}        # alert key -> "good" | "bad" (trader's verdict on a call)
        self.voice = deque(maxlen=60)   # spoken call-outs: big size added / pulled / hit
        self.desk = None        # recording desk (REC / markers / screenshots), set by run_twiney
        self.flow = FlowBook(cfg.get("flow", {"min_premium": 250000, "min_prints": 2, "otm_pct": 3.0, "max_dte": 30,
                                              "window_minutes": 10, "repeat_minutes": 20}))
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
        self.started = None
        self.last_t = 0.0

    # ---- plumbing ------------------------------------------------------------

    def dump_state(self, rec, t):
        from .desk import dump_state
        dump_state(self, rec, t)

    def _rec(self, event):
        if self.recorder is not None:
            self.recorder.write(event)

    def _clock(self, t):
        if self.started is None:
            self.started = t
        if t > self.last_t:
            self.last_t = t

    def _st(self, symbol):
        return self.syms.get(symbol)

    def _emit(self, st, tracker, label, t):
        final = label in ("CLEANED UP", "PULLED") and tracker.verdict_info
        alert = {
            "t": t,
            "symbol": st.symbol,
            "label": label,
            "price": fmt_price(tracker.price),
            "side": "ask" if tracker.side == ASK else "bid",
            "role": tracker.role,
            "absorbed": round(final["absorbed"] if final else tracker.absorbed_total),
            "refreshes": final["refreshes"] if final else tracker.refreshes_window(t),
        }
        if final:
            alert["size_before_gone"] = round(final["size_before_gone"])
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
        with self.lock:
            st = self._st(symbol)
            if st is None or field not in st.l1:
                return
            self._clock(t)
            self._rec({"ev": "l1", "t": t, "sym": symbol, "f": field, "v": value})
            st.l1[field] = value
            st.l1_t = t
            if field == "last" and not st.depth_active and value:
                st.bar_update(t, value)  # symbols without a tape still get a price chart

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
            st.depth_t = t
            self._voice_sizes(st, side, t)
            self._track_big(st, side)
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

    def on_depth_reset(self, symbol, t, reason="317"):
        st0 = self._st(symbol)
        if st0 is not None:
            st0.sizes = {ASK: {}, BID: {}}

        with self.lock:
            st = self._st(symbol)
            if st is None:
                return
            self._clock(t)
            self._rec({"ev": "reset", "t": t, "sym": symbol, "reason": reason})
            st.resets += 1
            st.resync_until = t + self.cfg["reload"]["resync_grace_seconds"]
            if st.book is not None:
                st.book.reset()
            for tr in st.trackers.values():
                tr.on_resync()
            self._message("warn", f"{symbol}: depth book reset ({reason}); resyncing", t, symbol)

    def on_print(self, symbol, price, size, exchange, t, conditions=""):
        with self.lock:
            st = self._st(symbol)
            if st is None or price is None or price <= 0 or not size or size <= 0:
                return
            self._clock(t)
            self._rec({"ev": "print", "t": t, "sym": symbol, "px": price, "sz": size,
                       "ex": exchange, "cond": conditions})
            bid, ask = st.bbo()
            rec = st.tape.add(t, price, size, bid, ask, exchange)
            st.tape_t = t
            st.l1["last"] = price
            st.bar_update(t, price, size, rec["side"])
            k = price_key(price)
            if rec["side"] in ("buy", "sell"):
                fm = st.foot.setdefault(int(t // BAR_SECONDS) * BAR_SECONDS, {})
                cell = fm.setdefault(k, [price, 0.0, 0.0])
                cell[1 if rec["side"] == "buy" else 2] += size
                if len(st.foot) > 240:
                    del st.foot[min(st.foot)]
            st.memory.append((t, k, price, rec["side"], size))
            while st.memory and t - st.memory[0][0] > MEMORY_SECONDS:
                st.memory.popleft()
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
                if label:
                    self._emit(st, tr, label, t)

    def on_daily_bar(self, symbol, t0, o, h, l, c):
        """Historical daily bar (ATR / measured potential)."""
        with self.lock:
            st = self._st(symbol)
            if st is None or None in (o, h, l, c):
                return
            self._rec({"ev": "dbar", "t": self.last_t or t0, "sym": symbol, "t0": t0, "o": o, "h": h, "l": l, "c": c})
            st.daily[t0] = [o, h, l, c]
            if len(st.daily) > 300:
                for k in sorted(st.daily)[:len(st.daily) - 300]:
                    del st.daily[k]

    def on_hist_bar(self, symbol, t0, o, h, l, c, v):
        """Historical 1-minute bar (reqHistoricalData) so the chart has context at startup."""
        with self.lock:
            st = self._st(symbol)
            if st is None:
                return
            self._rec({"ev": "hbar", "t": self.last_t or t0, "sym": symbol, "t0": t0, "o": o, "h": h, "l": l, "c": c, "v": v})
            m = int(t0 // BAR_SECONDS) * BAR_SECONDS
            if m in st.bars:
                return  # live data for that minute wins
            st.bars[m] = [o, h, l, c, v or 0.0, 0.0, 0.0]

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

    def on_position(self, account, symbol, qty, avg_cost, t):
        with self.lock:
            self.account_seen = True
            if qty:
                self.positions[(account, symbol)] = {"account": account, "symbol": symbol,
                                                     "qty": qty, "avg_cost": avg_cost}
            else:
                self.positions.pop((account, symbol), None)

    def on_flow(self, p, t=None):
        """One option print for a watchlist symbol. Recorded, kept, and run through the unusual detector."""
        with self.lock:
            t = t if t is not None else p.get("t", self.last_t)
            st = self._st(p["symbol"])
            if st is None:
                return
            self._clock(t)
            self._rec({"ev": "flow", "t": t, "p": p})
            self.flow.add(p)
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
                     "otm_pct": u["otm_pct"], "dte": u["dte"]}
            alert["key"] = f"{round(t, 2)}|{p['symbol']}|{label}|{u['premium']}"
            self.alerts.appendleft(alert)
            self._rec(dict(alert, ev="alert"))
            for fn in self.listeners:
                try:
                    fn(alert)
                except Exception:
                    pass
            self._say(st, "flow", u["cp"], "flow", t,
                      f"unusual {what} buying, {k(u['premium'])} premium"
                      f"{', ' + str(round(u['otm_pct'])) + ' percent out of the money' if u['otm_pct'] is not None else ''}")

    def on_fill(self, exec_id, symbol, side, shares, price, when, t):
        with self.lock:
            self.account_seen = True
            self.fills[exec_id] = {"symbol": symbol, "side": side, "shares": shares, "price": price,
                                   "time": when, "t": t}
            if self.desk is not None:
                self.desk.on_fill(self.fills[exec_id], t)
            if len(self.fills) > 200:
                for k in sorted(self.fills, key=lambda k: self.fills[k]["t"])[:len(self.fills) - 200]:
                    del self.fills[k]

    def day_pnl(self):
        """Realized (average-cost, from today's fills) + open P&L, in dollars."""
        with self.lock:
            realized, pos = 0.0, {}
            for f in sorted(self.fills.values(), key=lambda f: f["t"]):
                sym, qty, px_ = f["symbol"], f["shares"] * (1 if f["side"] == "BOT" else -1), f["price"]
                q, cost = pos.get(sym, (0.0, 0.0))
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
                pos[sym] = (q, cost)
            open_pnl = 0.0
            for (a, sym), p in self.positions.items():
                last = self.syms[sym].price() if sym in self.syms else None
                if last:
                    open_pnl += (last - p["avg_cost"]) * p["qty"]
            return {"realized": round(realized, 2), "open": round(open_pnl, 2), "total": round(realized + open_pnl, 2)}

    # ---- levels drawn on the chart -------------------------------------------

    def add_level(self, symbol, price, t=None):
        with self.lock:
            st = self._st(symbol)
            if st is None or not price or price <= 0:
                return False
            price = round(float(price), 4)
            lv = st.play.setdefault("extra_levels", [])
            if any(price_key(price) == price_key(x) for x in lv):
                return True
            lv.append(price)
            if st.book is not None:  # depth is on: start watching it right away
                for side in (BID, ASK):
                    key = (side, price_key(price))
                    if key not in st.trackers:
                        st.trackers[key] = LevelTracker(symbol, price, side, "extra", self.cfg["reload"], t or self.last_t)
            self._rec({"ev": "level", "t": t or self.last_t, "sym": symbol, "px": price, "on": True})
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
                side = fields.get("side", p["side"])
                if side not in ("long", "short"):
                    return False, "side must be long or short"
                trigger = num("trigger") if "trigger" in fields else p.get("trigger")
                second = num("second_entry") if "second_entry" in fields else p.get("second_entry")
                target = num("mp") if "mp" in fields else num("target") if "target" in fields else p.get("target")
                stop = num("stop") if "stop" in fields else p.get("stop")
                atr = num("atr") if "atr" in fields else p.get("atr")
            except ValueError as exc:
                return False, str(exc)
            if trigger and second:
                if side == "long" and second <= trigger:
                    return False, f"2nd entry {second} must be ABOVE the pivot {trigger} for a long"
                if side == "short" and second >= trigger:
                    return False, f"2nd entry {second} must be BELOW the pivot {trigger} for a short"
            if trigger and stop:
                if side == "long" and stop >= trigger:
                    return False, f"stop {stop} must be below the pivot {trigger} for a long"
                if side == "short" and stop <= trigger:
                    return False, f"stop {stop} must be above the pivot {trigger} for a short"
            if trigger and target:
                if side == "long" and target <= trigger:
                    return False, f"MP {target} must be above the pivot {trigger} for a long"
                if side == "short" and target >= trigger:
                    return False, f"MP {target} must be below the pivot {trigger} for a short"
            p["side"] = side
            if "notes" in fields:
                p["notes"] = str(fields.get("notes") or "")[:200]
            if "setup" in fields:
                p["setup"] = str(fields.get("setup") or "")[:40]
            p["atr"] = atr
            for role, val in (("trigger", trigger), ("second_entry", second), ("target", target), ("stop", stop)):
                if val != p.get(role):
                    if role == "trigger" and val is None:
                        continue
                    self.set_play_level(symbol, role, val, t)
            p["mp"] = p.get("target")        # MP is the level: one number, two names
            st.invalidation_armed = False   # new stop / target: don't retire the play on the next tick by accident
            self._rec({"ev": "setup", "t": t or self.last_t, "sym": symbol,
                       "fields": {k: p.get(k) for k in ("side", "trigger", "second_entry", "target", "stop", "mp", "atr", "notes")}})
            self._save_plays()
            return True, None

    def set_play_level(self, symbol, role, price, t=None):
        """Set (or clear, with price None) the play's trigger / second_entry / target / stop
        from the chart, re-point the reload trackers, and save plays.json."""
        with self.lock:
            st = self._st(symbol)
            if st is None or role not in ("trigger", "second_entry", "target", "stop"):
                return False
            if price is not None:
                price = round(float(price), 4)
                if price <= 0:
                    return False
            if role == "trigger" and price is None:
                return False  # a play always needs a trigger
            if role == "trigger" and price is not None:
                st.play["watch"] = False  # a typed-in ticker becomes a real play once it has a pivot
            old = st.play.get(role)
            st.play[role] = price
            if role == "target":
                st.play["mp"] = price
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
            return True

    def remove_level(self, symbol, price, t=None):
        with self.lock:
            st = self._st(symbol)
            if st is None:
                return False
            k = price_key(price)
            lv = st.play.get("extra_levels", [])
            st.play["extra_levels"] = [x for x in lv if price_key(x) != k]
            for side in (BID, ASK):
                tr = st.trackers.get((side, k))
                if tr is not None and tr.role == "extra":
                    del st.trackers[(side, k)]
            self._rec({"ev": "level", "t": t or self.last_t, "sym": symbol, "px": price, "on": False})
            self._save_plays()
            return True

    def _save_plays(self):
        """Write plays.json back so drawn levels survive a restart."""
        if not self.plays_path:
            return
        import json
        keep = ("symbol", "side", "trigger", "second_entry", "target", "stop", "mp", "atr", "extra_levels", "notes", "setup", "active", "watch",
                "exchange", "primary_exchange", "currency")
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
            return "FILLED"
        return s.upper() or "CREATED"

    def _pending(self, symbol=None):
        return [o for o in self.orders.values()
                if o.get("status") not in self.DONE_STATUSES + ("Done",)
                and (symbol is None or o.get("symbol") == symbol)]

    def _position_view(self, symbol, price):
        qty = sum(p["qty"] for (a, s), p in self.positions.items() if s == symbol)
        if not qty:
            return None
        cost = sum(p["qty"] * p["avg_cost"] for (a, s), p in self.positions.items() if s == symbol) / qty
        pnl = (price - cost) * qty if price else None
        return {"qty": qty, "avg_cost": round(cost, 4), "pnl": None if pnl is None else round(pnl, 2)}

    def on_connection(self, state, detail, t, market_data_type=None):
        """state: CONNECTED | DISCONNECTED | CONNECTING | DATA_LOST | FEED_DOWN."""
        with self.lock:
            self._clock(t)
            self._rec({"ev": "conn", "t": t, "state": state, "detail": detail})
            prev = self.connection["state"]
            self.connection.update(state=state, since=t, detail=detail)
            if market_data_type is not None:
                self.connection["market_data_type"] = market_data_type
            if state in ("DISCONNECTED", "DATA_LOST"):
                # IBKR subscriptions do not survive this; depth must be requested again
                for sym in list(self.slots):
                    self._deactivate(sym, t, record=True, reason=state)
            if state != prev:
                level = "info" if state == "CONNECTED" else "warn"
                self._message(level, f"connection {state}{': ' + detail if detail else ''}", t)

    def on_market_data_type(self, mdt, t):
        with self.lock:
            self.connection["market_data_type"] = mdt

    def on_depth_rejected(self, symbol, code, msg, t):
        with self.lock:
            st = self._st(symbol)
            if st is None:
                return
            self._clock(t)
            self._rec({"ev": "depth_rejected", "t": t, "sym": symbol, "code": code, "msg": msg})
            st.rejected_until = t + self.cfg["depth"]["reject_cooldown_seconds"]
            st.last_error = f"{code}: {msg}"
            if symbol in self.slots:
                self._deactivate(symbol, t, record=True, reason=f"rejected {code}")
            self._message("error", f"{symbol}: depth rejected ({code}) {msg}", t, symbol)

    def on_error(self, symbol, code, msg, t, level="warn"):
        with self.lock:
            self._clock(t)
            self._rec({"ev": "error", "t": t, "sym": symbol, "code": code, "msg": msg})
            st = self._st(symbol) if symbol else None
            if st is not None:
                st.last_error = f"{code}: {msg}"
            self._message(level, f"{symbol + ': ' if symbol else ''}[{code}] {msg}", t, symbol)

    def _message(self, level, text, t, symbol=None):
        self.messages.appendleft({"t": t, "level": level, "text": text, "symbol": symbol})

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
        wanted += [(lv, "extra") for lv in p.get("extra_levels", [])]
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

    def _protected(self):
        """Symbols with a live reload (or a pending verdict) are never rotated out."""
        out = set()
        for sym in self.slots:
            if any(tr.state in (RELOAD, GONE_PENDING) for tr in self.syms[sym].trackers.values()):
                out.add(sym)
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
            rc = self.cfg["reload"]
            for st in self.syms.values():
                if st.book is None:
                    continue
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

    def _track_big(self, st, side):
        """Count how many separate times big size has appeared at each price (shows up, leaves, shows up again)."""
        if st.book is None:
            return
        big = self.big_shares_for(st)
        showing = {price_key(p): s for p, s, _n in st.book.levels(side)}
        recs = st.big[side]
        for k, s in showing.items():
            rec = recs.get(k)
            if s >= big:
                if rec is None:
                    recs[k] = [1, s, True]
                elif not rec[2]:
                    rec[0] += 1; rec[2] = True; rec[1] = max(rec[1], s)
                else:
                    rec[1] = max(rec[1], s)
            elif rec is not None:
                rec[2] = False
        for k, rec in recs.items():
            if k not in showing:
                rec[2] = False

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
                # hit, or pulled? look at what traded at that price in the last few seconds
                traded = sum(pr["size"] for pr in st.tape.recent(60)
                             if t - pr["t"] <= 3.0 and price_key(pr["price"]) == k)
                if traded >= gone * 0.5:
                    self._say(st, side, k, "hit", t, f"{who} at {narrative.px(p)} got hit for {_k(gone)}")
                else:
                    self._say(st, side, k, "pull", t, f"{who} pulled {_k(gone)} from {narrative.px(p)}")
        st.sizes[side] = now

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
        fs = self.flow.summary(st.symbol, t)
        if gr["grade"] == "READY" and fc.get("against_bias") and fs["bias"] is not None:
            against = fs["bias"] <= -fc["against_bias"] if st.play["side"] == "long" else fs["bias"] >= fc["against_bias"]
            if against and (fs["calls"] + fs["puts"]) >= fc.get("against_min_premium", 0):
                gr = dict(gr, grade="WATCH", why=(gr["why"] + "; " if gr["why"] else "")
                          + f"option flow leans against this {st.play['side']}: {self.flow.context_text(st.symbol, t)}")
        gr["gates"].append({"q": "Flow with you?", "ok": fs["bias"] is None or (fs["bias"] >= 0) == (st.play["side"] == "long") or abs(fs["bias"]) < 0.3,
                            "why": self.flow.context_text(st.symbol, t)})
        return {"se": se, "mp": mp, "grade": gr["grade"], "why": gr["why"], "gates": gr["gates"], "flow": fs,
                "sneaky": ps60.sneaky_pivots(bars, atr_value, pc), "atr": atr_value}

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

    def flip_side(self, symbol, t=None):
        """Long <-> short on a play (the second entry must sit beyond the pivot, so it is cleared)."""
        with self.lock:
            st = self._st(symbol)
            if st is None:
                return False
            st.play["side"] = "short" if st.play["side"] == "long" else "long"
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
            return True

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
        new = allocate(self.slots, self.ranking(t), dc["slots"], t,
                       dc["rotate_hysteresis"], dc["min_hold_seconds"],
                       pinned=self.pinned - blocked, protected=self._protected(),
                       rotate=self.auto_rotate)
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
            self.on_print(ev["sym"], ev["px"], ev["sz"], ev.get("ex", ""), t, ev.get("cond", ""))
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
            self.on_daily_bar(ev["sym"], ev["t0"], ev["o"], ev["h"], ev["l"], ev["c"])
        elif kind == "flow":
            self.on_flow(ev["p"], t)
        elif kind == "big":
            self.set_big_shares(ev["sym"], ev.get("shares"), t)
        elif kind == "setup":
            self.set_play_setup(ev["sym"], ev.get("fields", {}), t)
        elif kind == "flip":
            with self.lock:
                st = self._st(ev["sym"])
                if st is not None:
                    st.play["side"] = ev["side"]
                    st.play["second_entry"] = None
        elif kind == "play_add":
            self.add_play(ev["play"]["symbol"], t, ev["play"].get("side", "long"))
        elif kind == "mark":
            with self.lock:
                self.marks_list.append({k: ev.get(k) for k in ("t", "symbol", "price", "note", "headline", "shot", "n")})
        elif kind == "note":
            with self.lock:
                self.notes_list.append({k: ev.get(k) for k in ("t", "symbol", "text")})
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
        }

    def _user_levels(self, play):
        out = [{"price": play["trigger"], "role": "trigger", "label": "PIVOT"}] if play.get("trigger") else []
        if play.get("second_entry"):
            out.append({"price": play["second_entry"], "role": "second_entry", "label": "2ND ENTRY"})
        for lv in play.get("extra_levels", []):
            out.append({"price": lv, "role": "extra", "label": "LEVEL"})
        for key, label in (("target", "TARGET"), ("stop", "STOP")):
            if play.get(key):
                out.append({"price": play[key], "role": key, "label": label})
        return out

    def _memory_ladder(self, st, t, user_levels, half_rows=12):
        """Price rows around the market, each carrying what happened there.

        Unlike a normal ladder (current size only), every row remembers: shares
        that traded into the bid / the ask at that price over MEMORY_SECONDS, how
        many times resting size came back after being hit, and the reload state.
        """
        bid, ask = st.bbo()
        center = (bid + ask) / 2 if bid and ask else st.price()
        if not center:
            return {"rows": [], "max_size": 0, "max_traded": 0}
        tk = tick_size(center)
        ck = price_key(center, tk)
        keys = list(range(ck + half_rows, ck - half_rows - 1, -1))
        tags = {}
        for lv in user_levels:
            k = price_key(lv["price"], tk)
            tags.setdefault(k, []).append(lv["label"])
            if k not in keys and abs(k - ck) <= 80 and lv["role"] in ("trigger", "second_entry", "extra"):
                keys.append(k)
        keys = sorted(set(keys), reverse=True)
        sold, bought = {}, {}
        for mt, k, _p, side, size in st.memory:
            if t - mt > MEMORY_SECONDS:
                continue
            if side == "sell":
                sold[k] = sold.get(k, 0.0) + size
            elif side == "buy":
                bought[k] = bought.get(k, 0.0) + size
        mine = {}
        for o in self._pending(st.symbol):
            for p_ in (o.get("lmt"), o.get("aux")):
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
        rows, prev = [], None
        max_size = max_traded = 0.0
        big_bar = self.big_shares_for(st); huge_x = self.cfg.get("ladder", {}).get("huge_multiple", 3.0)
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
                "best_bid": k == bb, "best_ask": k == ba, "last": k == lk,
            }
            for side in ("bid", "ask"):
                rec = st.big[BID if side == "bid" else ASK].get(k)
                if rec is not None and rec[2]:
                    row[side + "_big"] = {"times": rec[0], "huge": row[side] >= big_bar * huge_x}
                tr = trk.get((side, k))
                if tr is not None:
                    row[side + "_refills"] = tr.refreshes_window(t)
                    row[side + "_state"] = tr._display_state(t)
                    row[side + "_absorbed"] = round(tr.absorbed_total)
                    # never call a level cleared while something is sitting there again
                    row[side + "_verdict"] = (tr.last_verdict[0] if tr.last_verdict and t - tr.last_verdict[1] < 60
                                              and tr.displayed <= 0 else None)
            max_size = max(max_size, row["bid"], row["ask"])
            max_traded = max(max_traded, row["sold"], row["bought"])
            rows.append(row)
            prev = k
        return {"rows": rows, "max_size": round(max_size), "max_traded": round(max_traded),
                "memory_minutes": MEMORY_SECONDS // 60, "big_shares": big_bar, "big_default": st.big_shares is None,
                "huge_shares": big_bar * huge_x}

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
        for mt, k, p, side, size in st.memory:
            if t - mt > tc["window_seconds"]:
                continue
            if side == "buy" and k > pk:
                longs += size
                l_w += p * size
                l_lo = p if l_lo is None else min(l_lo, p)
                l_hi = p if l_hi is None else max(l_hi, p)
            elif side == "sell" and k < pk:
                shorts += size
                s_w += p * size
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

    def _reloaders(self, st, t, price):
        """Nearest confirmed / likely reloaders on each side of the market."""
        below, above = [], []
        for tr in st.trackers.values():
            if tr.state == RELOAD:
                kind = "confirmed"
            elif tr.state == BUILDING and tr.refreshes_window(t) >= 2 and tr.absorbed_window(t) > 0:
                kind = "likely"
            else:
                continue
            item = {"price": fmt_price(tr.price), "side": "bid" if tr.side == BID else "ask", "kind": kind,
                    "role": tr.role, "refills": tr.refreshes_window(t), "absorbed": round(tr.absorbed_total),
                    "showing": round(tr.displayed)}
            (below if price and tr.price < price else above).append(item)
        below.sort(key=lambda x: -x["price"])
        above.sort(key=lambda x: x["price"])
        return {"below": below[:3], "above": above[:3]}

    def _pane(self, sym, i, t, order, full=True):
        st = self.syms[sym]
        rows = self.cfg["depth"]["rows_displayed"]
        book = st.book
        bids = [[fmt_price(p), round(s), n] for p, s, n in book.levels(BID, rows)] if book else []
        asks = [[fmt_price(p), round(s), n] for p, s, n in book.levels(ASK, rows)] if book else []
        levels = sorted((tr.snapshot(t) for tr in st.trackers.values()),
                        key=lambda x: (x["role"] == "auto", -x["price"], x["side"]))
        for lv in levels:
            for k in ("displayed", "peak_displayed", "absorbed_window", "absorbed_total"):
                lv[k] = round(lv[k])
            lv["price"] = fmt_price(lv["price"])
        bid, ask = st.bbo()
        tape = st.tape.stats(t)
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
        return {
            "slot": i,
            "ps60": ps,
            "symbol": sym,
            "pinned": sym in self.pinned,
            "changed": change if change and t - change["t"] < 20 and change.get("prev") else None,
            "play": {k: st.play.get(k) for k in ("side", "trigger", "second_entry", "target", "stop", "mp", "atr", "notes", "setup")},
            "last": fmt_price(st.l1["last"]),
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
            "tape": dict(tape, recent=[
                {"age": round(t - p["t"], 1), "price": fmt_price(p["price"]), "size": round(p["size"]),
                 "side": p["side"], "large": p["large"], "exchange": p["exchange"], "at": at_level(p["price"])}
                for p in st.tape.recent(14)]),
            "levels": levels,
            "trap": trap,
            "reloaders": reloaders,
            "user_levels": user_levels,
            "orders": [{"id": o.get("order_id"), "action": o.get("action"), "qty": o.get("remaining") or o.get("qty"),
                        "type": o.get("type"),
                        "price": o.get("aux") if o.get("type") in ("STP", "STP LMT") and o.get("aux") else o.get("lmt") or o.get("aux"),
                        "role": o.get("role", "entry"),
                        "status": o.get("status")}
                       for o in self._pending(sym)],
            "position": self._position_view(sym, st.price()),
            # the page keeps its own bar history: full history on request, otherwise just the live tail
            "bars": bars if full else bars[-6:],
            "bars_full": full,
            "flow": self.flow.summary(sym, t),
            "daily": [[t0] + [fmt_price(x) for x in st.daily[t0]] + [0, 0, 0] for t0 in sorted(st.daily)] if full else None,
            "footprint": [[m, [[round(c[0], 4), round(c[1]), round(c[2])] for c in sorted(cells.values(), key=lambda c: c[0])]]
                          for m, cells in sorted(st.foot.items())[-150:]],
            "marks": [[m, fmt_price(v[0]), side, round(v[1])] for (m, _k, side), v in st.marks.items()
                      if m >= first_bar],
            "events": [[a["t"], a["price"], a["label"], a["side"]] for a in sym_alerts if a["t"] >= first_bar][:60],
            "health": self._health(st, t),
            "slot_age": round(t - self.slots[sym], 1) if sym in self.slots else None,
        }

    def snapshot(self, t, extra=(), full=None):
        """``full``: symbols the page wants the whole bar history for (None = every pane, as before)."""
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
                "slots": self.cfg["depth"]["slots"],
                "auto_rotate": self.auto_rotate,
                "ranking": ranking,
                "panes": panes,
                "extra": extra_panes,
                "focus": self.focus,
                "symbols": [p["symbol"] for p in self.plays if p["active"]],
                "depth": [pn for pn in panes if pn],
                "trading": self.trader.snapshot() if self.trader else {"mode": "NONE", "can_trade": False,
                                                                        "why_not": "order entry not loaded"},
                "replay": dict(self.replay) if self.replay else None,
                "account": {
                    "seen": self.account_seen,
                    "pending": sorted((dict(o, state=self.order_state(o)) for o in self._pending()), key=lambda o: -o.get("first_seen", 0)),
                    "done": sorted((dict(o, state=self.order_state(o)) for o in self.orders.values() if o not in self._pending()),
                                   key=lambda o: -o["t"])[:15],
                    "positions": [dict(p, last=fmt_price(self.syms[p["symbol"]].price())
                                       if p["symbol"] in self.syms else None) for p in self.positions.values()],
                    "fills": sorted(self.fills.values(), key=lambda f: -f["t"])[:30],
                },
                "alerts": [dict(a, grade=self.grades.get(a["key"])) for a in list(self.alerts)[:40]],
                "voice": [v for v in list(self.voice)[:20] if t - v["t"] < 60],
                "flow": list(self.flow.recent)[:80],
                "messages": list(self.messages)[:25],
                "recording": getattr(self.recorder, "path", None),
                "desk": {"recording": self.recorder is not None,
                         "started": self.desk.started if self.desk else None,
                         "notes": (self.desk.notes if self.desk else self.notes_list)[-30:],
                         "marks": (self.desk.marks if self.desk else self.marks_list)[-60:],
                         "trades": self.desk.trades[-60:] if self.desk else []},
            }
