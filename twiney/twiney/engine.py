"""TWINEY engine: pure market-data state machine.

Every input carries its own timestamp, so the same engine drives live data,
JSONL replay and tests identically. The engine never talks to IBKR; it returns
slot commands ("depth_on"/"depth_off") which the market-data adapter executes.
"""

import threading
from collections import deque

from .book import ASK, BID, Book
from .levels import BUILDING, LevelTracker, WATCHING
from .prices import fmt_price, price_key
from .ranking import allocate, distances, rank
from .tape import Tape

L1_FIELDS = ("bid", "ask", "last", "bid_size", "ask_size", "last_size", "volume",
             "high", "low", "close", "open")

ALERT_LABELS = ("RELOAD BUYER DETECTED", "RELOAD SELLER DETECTED", "CLEANED UP", "PULLED")


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
        self.alerts = deque(maxlen=300)
        self.messages = deque(maxlen=80)
        self.listeners = []
        self.connection = {"state": "DISCONNECTED", "since": None, "detail": "",
                           "market_data_type": None}
        self.started = None
        self.last_t = 0.0

    # ---- plumbing ------------------------------------------------------------

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
            for tr in list(st.trackers.values()):
                label = tr.on_print(price, size, rec["side"], t, st.book)
                if label:
                    self._emit(st, tr, label, t)

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

    def _activate(self, symbol, t):
        st = self.syms[symbol]
        self.slots[symbol] = t
        st.depth_active = True
        st.depth_since = t
        st.depth_t = None
        st.book = Book(self.cfg["depth"]["rows_requested"])
        st.resync_until = t + self.cfg["reload"]["resync_grace_seconds"]
        p = st.play
        wanted = [(p["trigger"], "trigger")]
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
                    self._activate(symbol, t)
            else:
                self._deactivate(symbol, t)

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
            if not allocate_slots or self.connection["state"] not in ("CONNECTED", "DEMO"):
                return []
            return self._rotate(t)

    def ranking(self, t):
        blocked = {s for s, st in self.syms.items() if st.rejected_until > t}
        prices = {s: st.price() for s, st in self.syms.items()}
        return rank(self.plays, prices, blocked)

    def _rotate(self, t):
        dc = self.cfg["depth"]
        new = allocate(self.slots, self.ranking(t), dc["slots"], t,
                       dc["rotate_hysteresis"], dc["min_hold_seconds"])
        cmds = []
        for sym in [s for s in self.slots if s not in new]:
            self.apply_slot(sym, False, t, reason="rotated")
            cmds.append(("depth_off", sym))
        for sym in [s for s in new if s not in self.slots]:
            self.apply_slot(sym, True, t, reason="closest")
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
                self.connection.update(state=ev["state"], since=t, detail=ev.get("detail", ""))
        elif kind == "depth_rejected":
            self.on_depth_rejected(ev["sym"], ev.get("code"), ev.get("msg", ""), t)
        elif kind == "error":
            self.on_error(ev.get("sym"), ev.get("code"), ev.get("msg", ""), t)

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

    def snapshot(self, t):
        with self.lock:
            rows = self.cfg["depth"]["rows_displayed"]
            ranked = self.ranking(t)
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
                    "depth": st.depth_active,
                    "health": self._health(st, t)["status"],
                    "notes": p["notes"],
                })
            ranking.sort(key=lambda r: (r["rank"] is None, r["rank"] or 0, r["symbol"]))

            depth = []
            for sym in sorted(self.slots, key=lambda s: order.get(s, 999)):
                st = self.syms[sym]
                book = st.book
                bids = [[fmt_price(p), round(s), n] for p, s, n in book.levels(BID, rows)] if book else []
                asks = [[fmt_price(p), round(s), n] for p, s, n in book.levels(ASK, rows)] if book else []
                levels = sorted((tr.snapshot(t) for tr in st.trackers.values()),
                                key=lambda x: (x["role"] == "auto", -x["price"], x["side"]))
                for lv in levels:
                    lv["displayed"] = round(lv["displayed"])
                    lv["peak_displayed"] = round(lv["peak_displayed"])
                    lv["absorbed_window"] = round(lv["absorbed_window"])
                    lv["absorbed_total"] = round(lv["absorbed_total"])
                    lv["price"] = fmt_price(lv["price"])
                bid, ask = st.bbo()
                depth.append({
                    "symbol": sym,
                    "play": {k: st.play[k] for k in ("side", "trigger", "second_entry", "target", "stop", "notes")},
                    "last": fmt_price(st.l1["last"]),
                    "bid": fmt_price(bid), "ask": fmt_price(ask),
                    "spread": fmt_price(ask - bid) if bid and ask else None,
                    "book": {"bids": bids, "asks": asks},
                    "tape": dict(st.tape.stats(t), recent=[
                        {"age": round(t - p["t"], 1), "price": fmt_price(p["price"]), "size": round(p["size"]),
                         "side": p["side"], "large": p["large"], "exchange": p["exchange"]}
                        for p in st.tape.recent(12)]),
                    "levels": levels,
                    "health": self._health(st, t),
                    "slot_age": round(t - self.slots[sym], 1),
                })
            return {
                "now": t,
                "uptime": round(t - self.started, 1) if self.started else 0,
                "mode": "READ-ONLY · MARKET DATA ONLY",
                "connection": dict(self.connection),
                "slots": self.cfg["depth"]["slots"],
                "ranking": ranking,
                "depth": depth,
                "alerts": list(self.alerts)[:40],
                "messages": list(self.messages)[:25],
                "recording": getattr(self.recorder, "path", None),
            }
