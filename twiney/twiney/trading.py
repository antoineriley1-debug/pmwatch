"""Order entry with a hard PAPER-ONLY lock.

Every order goes through ``TradingGate.check`` before it can reach a broker.
The gate refuses anything that is not:
  - armed by the trader this session (starts DISARMED every launch),
  - on a PAPER account (IBKR paper accounts start with "DU") or the built-in
    simulator, unless ``trading.allow_live`` is explicitly set true in config,
  - a LIMIT (or STOP for the bracket leg) — never a market order,
  - within max shares / max dollars per order and the per-minute order cap.

Two brokers:
  - ``SimBroker``  fills against the engine's own book (demo mode). No IBKR.
  - ``IbkrBroker`` sends to TWS through the session (paper or live).
Both report back through the engine's on_order / on_fill / on_position so the
dashboard shows the same thing either way.
"""

import logging
import math
import threading
import time
from collections import deque

from . import ps60
from .book import ASK, BID
from .prices import fmt_price, price_key, tick_size


def money(p):
    v = fmt_price(p)
    return "—" if v is None else (f"{v:.2f}" if v >= 1 else f"{v:.4f}")

log = logging.getLogger("twiney.trading")

BUY, SELL = "BUY", "SELL"


class OrderRejected(ValueError):
    pass


class TradingGate:
    def __init__(self, cfg):
        self.cfg = cfg["trading"]
        self.armed = False
        self.one_click = False
        self.accounts = []           # account ids reported by the broker
        self.mode = "NONE"           # NONE | SIM | PAPER | LIVE
        self.recent = deque()        # timestamps of accepted orders (rate limit)
        self.blocked = deque(maxlen=50)
        self.locked = None           # reason trading is locked for the rest of the session
        self.lock = threading.RLock()

    # ---- state ------------------------------------------------------------
    def set_accounts(self, accounts):
        with self.lock:
            self.accounts = [a for a in accounts if a]
            if self.mode != "SIM":
                self.mode = "PAPER" if self.accounts and all(a.upper().startswith("DU") for a in self.accounts) \
                    else ("LIVE" if self.accounts else "NONE")

    def set_sim(self):
        with self.lock:
            self.mode = "SIM"
            self.accounts = ["SIM"]

    def lock_out(self, reason):
        """Disarm and refuse to re-arm until restart (daily loss limit)."""
        with self.lock:
            self.locked = reason
            self.armed = False

    def arm(self, on):
        with self.lock:
            if on and not self.can_trade():
                return False
            self.armed = bool(on)
            return True

    def can_trade(self):
        if not self.cfg["enabled"] or self.locked:
            return False
        if self.mode in ("SIM", "PAPER"):
            return True
        return self.mode == "LIVE" and bool(self.cfg["allow_live"])

    def why_not(self):
        if not self.cfg["enabled"]:
            return "trading is disabled in config.json"
        if self.locked:
            return f"LOCKED for today: {self.locked}"
        if self.mode == "NONE":
            return "no account connected yet"
        if self.mode == "LIVE" and not self.cfg["allow_live"]:
            return "LIVE account detected — TWINEY only trades PAPER (DU…) accounts until trading.allow_live is set"
        if not self.armed:
            return "trading is DISARMED — click ARM"
        return None

    # ---- the check every order must pass ------------------------------------
    def check(self, action, qty, price, now, order_type="LMT"):
        with self.lock:
            reason = self.why_not()
            if reason:
                return self._block(reason, action, qty, price, now)
            if action not in (BUY, SELL):
                return self._block(f"bad action {action}", action, qty, price, now)
            if order_type in ("MKT", "STP") and not self.cfg.get("allow_market"):
                return self._block("only LIMIT and STOP-LIMIT orders by your rules (limit ~99%); market and naked stops "
                                   "stay off unless trading.allow_market is on", action, qty, price, now)
            if order_type not in ("LMT", "STP LMT", "MKT", "STP"):
                return self._block(f"order type {order_type} is not supported", action, qty, price, now)
            try:
                qty = int(qty)
                price = float(price)
            except (TypeError, ValueError):
                return self._block("size and price must be numbers", action, qty, price, now)
            if qty <= 0:
                return self._block("size must be positive", action, qty, price, now)
            if price <= 0 and order_type != "MKT":
                return self._block("price must be positive", action, qty, price, now)
            if qty > self.cfg["max_shares_per_order"]:
                return self._block(f"{qty} shares is over your cap of {self.cfg['max_shares_per_order']}",
                                   action, qty, price, now)
            if qty * price > self.cfg["max_dollars_per_order"]:
                return self._block(f"${qty * price:,.0f} is over your cap of ${self.cfg['max_dollars_per_order']:,.0f}",
                                   action, qty, price, now)
            while self.recent and now - self.recent[0] > 60:
                self.recent.popleft()
            if len(self.recent) >= self.cfg["max_orders_per_minute"]:
                return self._block(f"more than {self.cfg['max_orders_per_minute']} orders in a minute — slow down",
                                   action, qty, price, now)
            self.recent.append(now)
            return None

    def can_reduce(self):
        """Getting OUT is always allowed on a paper / sim account: disarmed, locked for the day or over a cap."""
        if not self.cfg["enabled"]:
            return False
        if self.mode in ("SIM", "PAPER"):
            return True
        return self.mode == "LIVE" and bool(self.cfg["allow_live"])

    def check_reduce(self, action, qty, price, now):
        """The check for a flatten / close: never blocked by ARM, the day loss lock, the size / dollar caps or
        the rate limit (a stuck position is the danger, not the exit). Still paper only, still a limit, sane numbers."""
        with self.lock:
            if not self.can_reduce():
                return self._block(self.why_not() or "no account", action, qty, price, now)
            if action not in (BUY, SELL):
                return self._block(f"bad action {action}", action, qty, price, now)
            try:
                qty, price = int(qty), float(price)
            except (TypeError, ValueError):
                return self._block("size and price must be numbers", action, qty, price, now)
            if qty <= 0 or price <= 0:
                return self._block("size and price must be positive", action, qty, price, now)
            return None

    def _block(self, reason, action, qty, price, now):
        self.blocked.appendleft({"t": now, "action": action, "qty": qty, "price": price, "reason": reason})
        log.warning("order blocked: %s (%s %s @ %s)", reason, action, qty, price)
        return reason

    def snapshot(self):
        with self.lock:
            return {
                "mode": self.mode,
                "armed": self.armed,
                "one_click": self.one_click,
                "allow_market": bool(self.cfg.get("allow_market")),
                "can_trade": self.can_trade(),
                "why_not": self.why_not(),
                "accounts": list(self.accounts),
                "default_shares": self.cfg["default_shares"],
                "max_shares": self.cfg["max_shares_per_order"],
                "max_dollars": self.cfg["max_dollars_per_order"],
                "bracket": self.cfg["bracket"],
                "locked": self.locked,
                "max_position": self.cfg["max_position_shares"],
                "max_daily_loss": self.cfg["max_daily_loss"],
                "blocked": list(self.blocked)[:10],
            }


def snap(price, direction=0):
    """A price on a valid tick: 0.01 at $1 and up, 0.0001 below. direction +1 rounds up, -1 down, 0 nearest."""
    if not price or price <= 0:
        return price
    tk = tick_size(price)
    n = price / tk
    n = math.ceil(n - 1e-7) if direction > 0 else math.floor(n + 1e-7) if direction < 0 else round(n)
    out = round(n * tk, 4)
    tk2 = tick_size(out)          # crossing $1 changes the tick
    if tk2 != tk:
        n = out / tk2
        out = round((math.ceil(n - 1e-7) if direction > 0 else math.floor(n + 1e-7) if direction < 0 else round(n)) * tk2, 4)
    return out


def stop_ok(play, action, entry_price):
    stop = play.get("stop")
    return not stop or (stop < entry_price if action == BUY else stop > entry_price)


def bracket_legs(play, action, qty, entry_price, stop_limit_ticks=10, scale_plan=None):
    """Exit legs for an entry, taken from the play. Empty if the play has none.

    The stop is a STOP-LIMIT (trigger at the stop, limit ``stop_limit_ticks``
    through it, on a valid tick), never a naked stop. With ``scale_plan`` the target
    leg becomes PS60 cash-flow legs plus a runner to the target.

    Every exit piece is paired with its own stop for the same shares (``oca``): a target
    fill takes its stop down with it and leaves the other pieces alone; a stop fill takes
    only its own target. That way a cash-flow fill can never cancel the runner, and the
    stops always cover exactly the shares still open.
    """
    stop, target = play.get("stop"), play.get("target")
    if not stop and not target:
        return []
    exit_action = SELL if action == BUY else BUY
    targets = []
    if scale_plan:
        targets = ps60.cash_flow_legs(play, action, qty, entry_price, scale_plan)
        targets = [t for t in targets if t["price"] > 0 and
                   (t["price"] > entry_price if action == BUY else t["price"] < entry_price)]
    elif target and (target > entry_price if action == BUY else target < entry_price):
        targets = [{"action": exit_action, "qty": qty, "type": "LMT", "price": snap(target), "role": "target"}]
    stop = snap(stop) if stop else stop
    stop_leg = None
    if stop and stop_ok(play, action, entry_price):
        tk = tick_size(stop)
        lmt = snap(stop - tk * stop_limit_ticks, -1) if action == BUY else snap(stop + tk * stop_limit_ticks, +1)
        stop_leg = {"action": exit_action, "type": "STP LMT", "price": lmt, "aux": stop, "role": "stop"}
    legs, covered = [], 0
    for i, t in enumerate(targets):
        g = f"x{i + 1}"
        if stop_leg:
            legs.append(dict(stop_leg, qty=t["qty"], oca=g))
        legs.append(dict(t, oca=g))
        covered += t["qty"]
    if stop_leg and covered < qty:                # shares with no target still get a stop
        legs.append(dict(stop_leg, qty=qty - covered, oca=f"x{len(targets) + 1}"))
    return legs


# ---------------------------------------------------------------------------

class SimBroker:
    """Fills limit orders against the engine's own book / prints (demo mode)."""

    def __init__(self, engine, account="SIM"):
        self.engine = engine
        self.account = account
        self.orders = {}       # id -> order dict
        self.next_id = 1
        self.pos = {}          # symbol -> [qty, avg_cost]
        # the engine's own lock: the broker is called from the engine (on every print) and calls back into it
        # (orders, fills). One lock, one order: no deadlock between the feed and a click
        self.lock = engine.lock
        self.session = int(time.time() * 1000) % 100000000   # fill ids unique across restarts (the journal dedupes on them)
        self.n_fills = 0

    def place(self, symbol, action, qty, price, now, order_type="LMT", parent=None, role="entry", tif="DAY",
              aux=None, oca=None, transmit=True, reducing=False):
        """``transmit=False`` holds the order (and later its legs) until an order of the family is sent with
        transmit=True, the way TWS holds a bracket: the entry can never fill before its stop exists."""
        with self.lock:
            oid = self.next_id
            self.next_id += 1
            o = {"id": oid, "symbol": symbol, "action": action, "qty": qty, "remaining": qty,
                 "type": order_type, "price": price, "aux": aux, "parent": parent, "role": role,
                 "status": "Submitted", "tif": tif, "t": now, "children": [], "oca": oca,
                 "held": not transmit}
            self.orders[oid] = o
            if parent in self.orders:
                par = self.orders[parent]
                par["children"].append(oid)
                o["held"] = False
                if par["status"] != "Filled":
                    o["status"] = "PreSubmitted"  # waits for the parent to fill
                if transmit:
                    par["held"] = False
            self._report(o, now)
            if transmit:
                self.on_market(symbol, now)  # marketable at once? fill it now
            return oid

    def cancel(self, oid, now):
        with self.lock:
            o = self.orders.get(oid)
            if o and o["status"] not in ("Filled", "Cancelled"):
                self._cancel(o, now)
                return True
            return False

    def modify(self, oid, price, now):
        with self.lock:
            o = self.orders.get(oid)
            if not o or o["status"] not in ("Submitted", "PreSubmitted"):
                return None
            if o["type"] == "STP LMT" and o.get("aux") is not None:
                o["price"] = round(o["price"] + (price - o["aux"]), 4)  # keep the limit offset
                o["aux"] = price
            else:
                o["price"] = price
            o["t"] = now
            self._report(o, now)
            if o["status"] == "Submitted":
                self.on_market(o["symbol"], now)
            return o

    def order_info(self, oid):
        o = self.orders.get(oid)
        return dict(o) if o else None

    def cancel_all(self, now, symbol=None):
        with self.lock:
            n = 0
            for o in list(self.orders.values()):
                if o["status"] in ("Submitted", "PreSubmitted") and (symbol is None or o["symbol"] == symbol):
                    self._cancel(o, now)
                    n += 1
            return n

    def _cancel(self, o, now):
        o["status"] = "Cancelled"
        o["t"] = now
        self._report(o, now)
        for c in o["children"]:
            child = self.orders.get(c)
            if child and child["status"] in ("Submitted", "PreSubmitted"):
                self._cancel(child, now)

    def _report(self, o, now):
        self.engine.on_order(f"sim{o['id']}", now, symbol=o["symbol"], action=o["action"], qty=float(o["qty"]),
                             remaining=float(o["remaining"]), filled=float(o["qty"] - o["remaining"]),
                             type=o["type"], lmt=o["price"] if o["type"] in ("LMT", "STP LMT") else None,
                             aux=o["price"] if o["type"] == "STP" else o.get("aux"), tif=o["tif"], status=o["status"],
                             role=o["role"], order_id=o["id"], sim=True, mine=True, parent=o["parent"])

    def on_market(self, symbol, now):
        """Called by the engine after each print / book update for ``symbol``."""
        with self.lock:
            st = self.engine.syms.get(symbol)
            if st is None:
                return
            bid, ask = st.bbo()
            last = st.l1.get("last")
            for o in list(self.orders.values()):
                if o["symbol"] != symbol or o["status"] != "Submitted" or o.get("held"):
                    continue
                if o["type"] == "LMT":
                    hit = (o["action"] == BUY and ask is not None and ask <= o["price"]) or \
                          (o["action"] == SELL and bid is not None and bid >= o["price"])
                    # a marketable limit fills at the touch, never worse than the market was
                    fill_px = (min(o["price"], ask) if o["action"] == BUY else max(o["price"], bid)) if hit else o["price"]
                elif o["type"] == "STP":
                    hit = last is not None and ((o["action"] == SELL and last <= o["price"]) or
                                                (o["action"] == BUY and last >= o["price"]))
                    fill_px = last
                elif o["type"] == "MKT":
                    hit = (o["action"] == BUY and ask is not None) or (o["action"] == SELL and bid is not None)
                    fill_px = ask if o["action"] == BUY else bid
                elif o["type"] == "STP LMT":
                    trig = last is not None and ((o["action"] == SELL and last <= o["aux"]) or
                                                 (o["action"] == BUY and last >= o["aux"]))
                    # triggered: fill as a limit if the market is inside the limit, else rest as a limit
                    hit = trig and ((o["action"] == SELL and last >= o["price"]) or
                                    (o["action"] == BUY and last <= o["price"]))
                    if trig and not hit:
                        o["type"] = "LMT"
                        self._report(o, now)
                    fill_px = last
                else:
                    hit = False
                if hit:
                    self._fill(o, fill_px, now)

    def _fill(self, o, price, now):
        qty = o["remaining"]
        o["remaining"] = 0
        o["status"] = "Filled"
        o["avg_fill"] = price
        o["t"] = now
        self.n_fills += 1
        signed = qty if o["action"] == BUY else -qty
        p = self.pos.setdefault(o["symbol"], [0.0, 0.0])
        if p[0] == 0 or (p[0] > 0) == (signed > 0):
            new_qty = p[0] + signed
            p[1] = (p[0] * p[1] + signed * price) / new_qty if new_qty else 0.0
            p[0] = new_qty
        else:
            p[0] += signed  # reducing / flipping keeps the old cost basis on the remainder
            if p[0] == 0:
                p[1] = 0.0
            elif (p[0] > 0) == (signed > 0):
                p[1] = price
        self.engine.on_position(self.account, o["symbol"], p[0], p[1], now)
        self.engine.on_fill(f"sim{self.session}-{o['id']}-{self.n_fills}", o["symbol"], "BOT" if o["action"] == BUY else "SLD",
                            float(qty), price, time.strftime("%H:%M:%S", time.localtime(now)), now)
        self._report(o, now)
        # activate children
        for c in o["children"]:
            child = self.orders.get(c)
            if child and child["status"] == "PreSubmitted":
                child["status"] = "Submitted"
                self._report(child, now)
        # an exit fill reduces the other order of its pair (OCA, reduce): the target's stop, or the stop's target
        if o["parent"] in self.orders and o.get("oca"):
            for sib in self.orders[o["parent"]]["children"]:
                s = self.orders.get(sib)
                if not (s and s is not o and s.get("oca") == o["oca"] and s["status"] in ("Submitted", "PreSubmitted")):
                    continue
                s["remaining"] -= qty
                if s["remaining"] <= 0:
                    self._cancel(s, now)
                else:
                    self._report(s, now)
        if o["children"]:
            self.on_market(o["symbol"], now)   # a leg that is marketable right away

    def resize(self, oid, remaining, now):
        with self.lock:
            o = self.orders.get(oid)
            if not o or o["status"] not in ("Submitted", "PreSubmitted"):
                return False
            if remaining <= 0:
                self._cancel(o, now)
                return True
            o["qty"] = o["qty"] - o["remaining"] + remaining
            o["remaining"] = remaining
            self._report(o, now)
            return True

    def position(self, symbol):
        return self.pos.get(symbol, [0.0, 0.0])[0]


class IbkrBroker:
    """Sends orders to TWS through the market-data session (paper or live)."""

    def __init__(self, engine, session):
        self.engine = engine
        self.session = session

    def place(self, symbol, action, qty, price, now, order_type="LMT", parent=None, role="entry", tif="DAY",
              aux=None, oca=None, transmit=True, reducing=False):
        return self.session.send_order(symbol, action, qty, price, order_type, parent, role, tif, now, aux=aux,
                                       oca=oca, transmit=transmit, reducing=reducing)

    def cancel(self, oid, now):
        return self.session.cancel_order(oid, now)

    def modify(self, oid, price, now):
        return self.session.modify_order(oid, price, now)

    def resize(self, oid, remaining, now):
        return self.session.modify_order(oid, None, now, remaining=remaining)

    def order_info(self, oid):
        with self.engine.lock:
            for o in self.engine.orders.values():
                if o.get("order_id") == oid:
                    return dict(o)
        return None

    def cancel_all(self, now, symbol=None):
        return self.session.cancel_all(now, symbol)

    def position(self, symbol):
        with self.engine.lock:
            return sum(p["qty"] for (a, s), p in self.engine.positions.items() if s == symbol)


# ---------------------------------------------------------------------------

class Trader:
    """What the dashboard talks to. Applies the gate, then hands to the broker."""

    def __init__(self, engine, cfg, broker, gate):
        self.engine = engine
        self.cfg = cfg["trading"]
        self.broker = broker
        self.gate = gate
        self.default_shares = self.cfg["default_shares"]
        self.bracket = bool(self.cfg["bracket"])
        self.scale = bool(self.cfg["scale_plan"]["enabled"])
        self.families = {}   # entry order id -> {"symbol", "entry", "stop", "cash": [...], "be_done"}
        self.nonces = {}     # ticket nonce -> result (double-submit protection)
        self.mismatch = {}   # symbol -> since when its working exits have not matched the position
        # AUTO 2ND ENTRY: the 2nd entry you draw becomes a stop-limit entry with the play's stop + target attached,
        # sized from your risk dollars, placed while ARMED, cancelled when the level goes or you disarm
        self.auto_on = bool(self.cfg.get("auto_second_entry", True))
        self.risk_dollars = float(self.cfg.get("risk_dollars", 100) or 0)
        self.auto = {}       # symbol -> {"id", "action", "aux", "price", "qty", "stop", "target", "t"} (the working auto entry)
        self.auto_done = {}  # symbol -> price_key of the 2nd entry that already filled (one entry per drawn level)
        self.auto_why = {}   # symbol -> why there is no working auto entry right now
        self.auto_fail = {}  # symbol -> (level key, when, reason): a refused order is not retried every half second
        # every order action (clicks on HTTP threads, the watchdog thread) runs one at a time: a check and the order
        # it allows can never be split by another click (two flattens, two closes, the same ticket twice)
        self.lock = threading.RLock()
        self.log = deque(maxlen=200)

    def _note(self, now, text, ok):
        self.log.appendleft({"t": now, "text": text, "ok": ok})
        self.engine._message("info" if ok else "error", text, now)

    def submit(self, symbol, action, price, qty=None, now=None, bracket=None, order_type="LMT", aux=None, tif="DAY", nonce=None):
        with self.lock:
            return self._submit_unlocked(symbol, action, price, qty, now, bracket, order_type, aux, tif, nonce)

    def _submit_unlocked(self, symbol, action, price, qty=None, now=None, bracket=None, order_type="LMT", aux=None,
               tif="DAY", nonce=None):
        now = now or time.time()
        qty = int(qty or self.default_shares)
        play = self.engine.syms[symbol].play if symbol in self.engine.syms else None
        if play is None:
            self._note(now, f"{symbol}: not one of your plays", False)
            return {"ok": False, "reason": "unknown symbol"}
        order_type = (order_type or "LMT").upper()
        tif = (tif or "DAY").upper()
        if tif not in ("DAY", "GTC", "IOC"):
            return {"ok": False, "reason": f"time in force {tif} is not supported"}
        # the same ticket sent twice (double-click, retry, lag) is one order
        if nonce:
            seen = self.nonces.get(nonce)
            if seen is not None:
                return dict(seen, duplicate=True)
            self.nonces[nonce] = {"ok": False, "reason": "this ticket is already being sent"}   # reserved
        price = snap(round(float(price or 0), 4))          # a price the exchange takes
        if order_type == "STP LMT":
            try:
                aux = snap(round(float(aux), 4))
            except (TypeError, ValueError):
                return {"ok": False, "reason": "a stop-limit needs a stop price"}
            if aux <= 0:
                return {"ok": False, "reason": "stop price must be positive"}
        else:
            aux = None
        # a ticket order that takes the position DOWN (a SELL while long, a BUY while short, no bigger than the
        # position) is a close, not a trade: it goes through the reducing gate, which the day-loss lock, DISARM
        # and the caps never block. Getting out is always allowed
        pos0 = int(self.broker.position(symbol))
        closing = bool(pos0) and order_type == "LMT" and action == (SELL if pos0 > 0 else BUY) and qty <= abs(pos0)
        if closing:
            reason = self.gate.check_reduce(action, qty, price, now)
        else:
            reason = self.gate.check(action, qty, price if order_type != "MKT" else (self.engine.syms[symbol].price() or 0), now, order_type)
        if not reason and order_type in ("LMT", "STP LMT"):
            # a limit far through the market is a typo or a stale price (the wrong symbol's), not a trade:
            # a BUY more than 5% over the offer / a SELL more than 5% under the bid is refused
            st_ = self.engine.syms[symbol]
            bid, ask = st_.bbo()
            ref_last = st_.l1.get("last") or st_.l1.get("close")
            band = 0.05
            if order_type == "STP LMT":       # a stop entry sits away from the market on purpose: judge its limit by its trigger
                ask = bid = aux
            ask, bid = ask or ref_last, bid or ref_last
            if action == BUY and ask and price > ask * (1 + band):
                reason = f"BUY limit {money(price)} is {100 * (price / ask - 1):.1f}% over {money(ask)} — check the price"
            elif action == SELL and bid and price < bid * (1 - band):
                reason = f"SELL limit {money(price)} is {100 * (1 - price / bid):.1f}% under {money(bid)} — check the price"
            if reason:
                self.gate.blocked.appendleft({"t": now, "action": action, "qty": qty, "price": price, "reason": reason})
        if not reason and not closing:
            pos = int(self.broker.position(symbol))
            # entries still working count too: five resting 500-share bids are a 2,500 share position waiting to happen
            # the worst case on this side: opposite working orders may never fill
            same = sum((o.get("remaining") if o.get("remaining") is not None else o.get("qty") or 0)
                       for o in self.engine._pending(symbol) if o.get("role") == "entry" and o.get("action") == action)
            after = pos + (int(same) + qty) * (1 if action == BUY else -1)
            cap = self.cfg["max_position_shares"]
            if abs(after) > cap and abs(after) > abs(pos):
                reason = f"that would make the {symbol} position {abs(after):,} shares — your cap is {cap:,}"
                self.gate.blocked.appendleft({"t": now, "action": action, "qty": qty, "price": price, "reason": reason})
        if reason:
            self._note(now, f"BLOCKED {action} {qty} {symbol} @ {money(price)}: {reason}", False)
            if nonce:
                self.nonces.pop(nonce, None)
            return {"ok": False, "reason": reason}
        if closing:
            out = self._reduce(symbol, action, price, qty, now, "close")
            if nonce:
                self.nonces[nonce] = out
            return out
        use_bracket = self.bracket if bracket is None else bool(bracket)
        plan = self.cfg["scale_plan"]["cash_flow"] if self.scale else None
        ref = price if order_type in ("LMT", "STP LMT") else (self.engine.syms[symbol].price() or price)
        if use_bracket and ref and not stop_ok(play, action, ref):
            reason = (f"your stop {money(play['stop'])} is on the wrong side of a {action} at {money(ref)} — "
                      f"the order would go out with no stop. Fix the stop first")
            self._note(now, f"BLOCKED {action} {qty} {symbol} @ {money(price)}: {reason}", False)
            return {"ok": False, "reason": reason}
        legs = bracket_legs(play, action, qty, ref, self.cfg["stop_limit_ticks"], plan) if use_bracket and ref else []
        try:
            # the family goes out together: the entry is held until its last leg is sent
            parent_id = self.broker.place(symbol, action, qty, price, now, order_type, None, "entry", tif, aux=aux,
                                          transmit=not legs)
            fam = {"symbol": symbol, "entry": price, "stops": [], "cash": [], "be_done": False}
            for i, leg in enumerate(legs):
                lid = self.broker.place(symbol, leg["action"], leg["qty"], leg["price"], now, leg["type"], parent_id,
                                        leg["role"], aux=leg.get("aux"), oca=leg.get("oca"),
                                        transmit=i == len(legs) - 1)
                if leg["role"] == "stop":
                    fam["stops"].append(lid)
                elif leg["role"].startswith("cash_flow"):
                    fam["cash"].append(lid)
            if fam["stops"] and fam["cash"]:
                self.families[parent_id] = fam
        except Exception as exc:
            self._note(now, f"FAILED {action} {qty} {symbol} @ {money(price)}: {exc}", False)
            return {"ok": False, "reason": str(exc)}
        what = f"{action} {qty} {symbol} " + (f"@ {money(price)} " if order_type != "MKT" else "") + order_type + (f" stop {money(aux)}" if aux else "") + ("" if tif == "DAY" else " " + tif)
        if legs:
            what += " + " + " + ".join(
                f"stop {money(l['aux'])} (limit {money(l['price'])})" if l["role"] == "stop"
                else f"{l['role'].replace('_', ' ')} {l['qty']} @ {money(l['price'])}" for l in legs)
        self._note(now, f"SENT {what}", True)
        self.engine._rec({"ev": "order", "t": now, "sym": symbol, "action": action, "qty": qty, "px": price,
                          "type": order_type, "aux": aux, "tif": tif, "legs": legs, "id": parent_id})
        out = {"ok": True, "id": parent_id, "sent": what}
        if nonce:
            self.nonces[nonce] = out
            if len(self.nonces) > 500:
                for k in list(self.nonces)[:250]:
                    del self.nonces[k]
        return out

    def cancel(self, oid, now=None):
        with self.lock:
            return self._cancel_unlocked(oid, now)

    def _cancel_unlocked(self, oid, now=None):
        now = now or time.time()
        ok = self.broker.cancel(oid, now)
        self._note(now, f"cancel {oid}: {'sent' if ok else 'nothing to cancel'}", ok)
        return {"ok": ok}

    def cancel_all(self, symbol=None, now=None):
        with self.lock:
            return self._cancel_all_unlocked(symbol, now)

    def _cancel_all_unlocked(self, symbol=None, now=None):
        now = now or time.time()
        n = self.broker.cancel_all(now, symbol)
        self._note(now, f"cancelled {n} working order{'s' if n != 1 else ''}{' in ' + symbol if symbol else ''}", True)
        return {"ok": True, "cancelled": n}

    REDUCING = ("flatten", "close", "partial")

    def _can_reduce_by(self, symbol, now):
        """Shares that can still be taken off: the position less the flatten / close orders already working. A close
        that filled a moment ago may not show in the position yet: then nothing more is sent until it does."""
        pos = int(self.broker.position(symbol))
        if self.engine.recently_filled(symbol, self.REDUCING, now):
            return pos, 0, "the last close just filled — the position is updating, try again in a moment"
        working = sum((o.get("remaining") if o.get("remaining") is not None else o.get("qty") or 0)
                      for o in self.engine._pending(symbol)
                      if o.get("role") in self.REDUCING and o.get("status") != "PendingCancel")
        return pos, max(0, abs(pos) - int(working)), (f"{int(working)} shares are already being closed" if working else None)

    def flatten(self, symbol, now=None):
        with self.lock:
            return self._flatten_unlocked(symbol, now)

    def _flatten_unlocked(self, symbol, now=None):
        """Close the position with a marketable limit (through the spread by a few ticks). Works disarmed, locked
        for the day and over the caps: getting out is never blocked. One flatten at a time per symbol."""
        now = now or time.time()
        # a ticket close resting away from the market (a SELL above it while long) is not the way out FLATTEN
        # means: it goes, and the whole position is closed at the market
        for o in self.engine._pending(symbol):
            if o.get("role") == "close" and o.get("order_id") is not None and o.get("status") != "PendingCancel":
                try:
                    self.broker.cancel(o["order_id"], now)
                except Exception as exc:
                    log.warning("cancel close %s: %s", o.get("order_id"), exc)
        pos, free, why = self._can_reduce_by(symbol, now)
        if not pos:
            self._note(now, f"{symbol}: already flat", True)
            return {"ok": True, "flat": True}
        if any(o.get("role") == "flatten" for o in self.engine._pending(symbol)) or not free:
            reason = "a flatten order is already working" if any(o.get("role") == "flatten" for o in self.engine._pending(symbol)) else why
            self._note(now, f"{symbol}: {reason}", False)
            return {"ok": False, "reason": reason}
        qty = free if pos > 0 else -free
        st = self.engine.syms.get(symbol)
        bid, ask = st.bbo() if st else (None, None)
        if bid is None or ask is None:
            self._note(now, f"{symbol}: no quote to flatten against", False)
            return {"ok": False, "reason": "no quote"}
        tk = tick_size(ask)
        slip = self.cfg["flatten_slip_ticks"] * tk
        action = SELL if qty > 0 else BUY
        price = snap(bid - slip, -1) if qty > 0 else snap(ask + slip, +1)
        reason = self.gate.check_reduce(action, abs(qty), price, now)
        if reason:            # checked BEFORE the stops are cancelled: a refused flatten leaves them in place
            self._note(now, f"BLOCKED flatten {symbol}: {reason}", False)
            return {"ok": False, "reason": reason}
        self.broker.cancel_all(now, symbol)
        return self._reduce(symbol, action, price, abs(qty), now, "flatten")

    def partial(self, symbol, shares, price, now=None):
        with self.lock:
            return self._partial_unlocked(symbol, shares, price, now)

    def _partial_unlocked(self, symbol, shares, price, now=None):
        """Take part of the profit: a limit for ``shares`` of the position at ``price``, working next to the bracket.
        The target is cut by the same shares right away (target + partial = what you hold); when the partial fills,
        the stop comes down to the shares left. Works like flatten / close: disarmed or locked, it still goes out."""
        now = now or time.time()
        try:
            shares, price = int(shares), float(price)
        except (TypeError, ValueError):
            return {"ok": False, "reason": "shares and price must be numbers"}
        if shares <= 0 or price <= 0:
            return {"ok": False, "reason": "shares and price must be positive"}
        pos, free, why = self._can_reduce_by(symbol, now)
        if not pos:
            return {"ok": False, "reason": "no position to take profit on"}
        if not free:
            return {"ok": False, "reason": why}
        if shares >= abs(pos):
            return {"ok": False, "reason": f"that is the whole position ({abs(pos)} shares) — use CLOSE or FLATTEN"}
        shares = min(shares, free)
        action = SELL if pos > 0 else BUY
        price = snap(price, -1 if action == SELL else +1)
        reason = self.gate.check_reduce(action, shares, price, now)
        if reason:
            self._note(now, f"BLOCKED partial {symbol}: {reason}", False)
            return {"ok": False, "reason": reason}
        out = self._reduce(symbol, action, price, shares, now, "partial")
        if out.get("ok"):
            # the target(s) give up the same shares, biggest first, so exits never add up to more than you hold
            left = shares
            tg = sorted((o for o in self.engine._pending(symbol) if o.get("role") in ("target", "runner")
                         and o.get("order_id") is not None and o.get("action") == action),
                        key=lambda o: -(o.get("remaining") or o.get("qty") or 0))
            for o in tg:
                if left <= 0:
                    break
                have = int(o.get("remaining") or o.get("qty") or 0)
                cut = min(have, left)
                try:
                    self.broker.resize(o["order_id"], have - cut, now)
                except Exception as exc:
                    self._note(now, f"{symbol}: could not trim the target: {exc}", False)
                left -= cut
            out["sent"] = f"PARTIAL {action} {shares} {symbol} @ {money(price)}"
        return out

    def breakeven(self, symbol, now=None):
        with self.lock:
            return self._breakeven_unlocked(symbol, now)

    def _breakeven_unlocked(self, symbol, now=None):
        """Move every working stop of this position to the entry price (your average cost). Protective, so it works
        disarmed or locked. Refused when price is already through the entry: the stop would fire at once."""
        now = now or time.time()
        pos = self.broker.position(symbol)
        if not pos:
            return {"ok": False, "reason": "no position"}
        view = self.engine._position_view(symbol, None) or {}
        entry = view.get("avg_cost")
        if not entry:
            return {"ok": False, "reason": "no entry price for the position yet"}
        long_ = pos > 0
        be = snap(entry, -1 if long_ else +1)            # never a penny on the wrong side of your cost
        st = self.engine.syms.get(symbol)
        bid, ask = st.bbo() if st else (None, None)
        last = st.price() if st else None
        mkt = bid if long_ else ask
        mkt = mkt or last
        if mkt is not None and ((long_ and mkt <= be) or (not long_ and mkt >= be)):
            where = "below" if long_ else "above"
            return {"ok": False, "reason": f"price {money(mkt)} is {where} your entry {money(be)} — a breakeven stop would fire now"}
        if not self.gate.can_reduce():
            return {"ok": False, "reason": self.gate.why_not() or "no account"}
        closing = SELL if long_ else BUY
        left = lambda o: int(o.get("remaining") if o.get("remaining") is not None else o.get("qty") or 0)
        # every stop-type order working on this symbol: the bracket's stops first, then any placed by hand
        stop_orders = [o for o in self.engine._pending(symbol) if o.get("order_id") is not None
                       and (o.get("role") == "stop" or o.get("type") in ("STP", "STP LMT"))]
        keep_pool = sorted((o for o in stop_orders if o.get("action") == closing),
                           key=lambda o: (o.get("role") != "stop", -left(o)))
        if not keep_pool:
            return {"ok": False, "reason": "no working stop to move — the position has no stop"}
        # after this: stops at breakeven covering exactly the position, and no other stop on the board
        need, moved, cancelled = abs(int(pos)), 0, 0
        for o in keep_pool:
            have = left(o)
            try:
                if need <= 0:
                    self.broker.cancel(o["order_id"], now); cancelled += 1
                    continue
                if have > need:
                    self.broker.resize(o["order_id"], need, now)
                    have = need
                if self.broker.modify(o["order_id"], be, now):
                    moved += 1
                need -= have
            except Exception as exc:
                self._note(now, f"{symbol}: could not move stop {o['order_id']}: {exc}", False)
        for o in stop_orders:                      # stop orders on the other side (a stop entry still waiting)
            if o.get("action") != closing:
                try:
                    self.broker.cancel(o["order_id"], now); cancelled += 1
                except Exception as exc:
                    self._note(now, f"{symbol}: could not cancel stop {o['order_id']}: {exc}", False)
        if not moved:
            return {"ok": False, "reason": "the stop could not be moved"}
        if need > 0:
            self._note(now, f"{symbol}: breakeven stops cover {abs(int(pos)) - need} of {abs(int(pos))} shares — "
                            f"the rest has no stop", False)
        extra = f" · {cancelled} other stop order{'s' if cancelled != 1 else ''} cancelled" if cancelled else ""
        self._note(now, f"{symbol}: stop moved to BREAKEVEN {money(be)}{extra}", True)
        self.engine._rec({"ev": "breakeven", "t": now, "sym": symbol, "px": be})
        return {"ok": True, "price": be, "moved": moved, "cancelled": cancelled,
                "sent": f"stop to breakeven {money(be)}{extra}"}

    def _reduce(self, symbol, action, price, qty, now, role):
        try:
            oid = self.broker.place(symbol, action, qty, price, now, "LMT", None, role, "DAY", reducing=True)
        except Exception as exc:
            self._note(now, f"FAILED {role} {action} {qty} {symbol} @ {money(price)}: {exc}", False)
            return {"ok": False, "reason": str(exc)}
        self._note(now, f"SENT {role.upper()} {action} {qty} {symbol} @ {money(price)}", True)
        self.engine._rec({"ev": "order", "t": now, "sym": symbol, "action": action, "qty": qty, "px": price,
                          "type": "LMT", "aux": None, "tif": "DAY", "legs": [], "id": oid, "role": role})
        return {"ok": True, "id": oid, "sent": f"{action} {qty} {symbol} @ {money(price)} ({role})"}

    def modify(self, oid, price, now=None):
        with self.lock:
            return self._modify_unlocked(oid, price, now)

    def _modify_unlocked(self, oid, price, now=None):
        """Move a working order to a new price (drag on the ladder / chart)."""
        now = now or time.time()
        oid = int(oid)
        info = self.broker.order_info(oid)
        if not info:
            return {"ok": False, "reason": "no such order"}
        price = snap(round(float(price), 4))
        qty = int(info.get("remaining") or info.get("qty") or 0)
        reason = self.gate.check(info.get("action"), qty, price, now, order_type=info.get("type", "LMT"))
        if reason:
            self._note(now, f"BLOCKED move of order {oid} to {money(price)}: {reason}", False)
            return {"ok": False, "reason": reason}
        try:
            ok = self.broker.modify(oid, price, now)
        except Exception as exc:
            return {"ok": False, "reason": str(exc)}
        if not ok:
            return {"ok": False, "reason": "order is no longer working"}
        self._note(now, f"MOVED {info.get('action')} {qty} {info.get('symbol')} to {money(price)}", True)
        self.engine._rec({"ev": "order_modify", "t": now, "id": oid, "px": price})
        return {"ok": True, "price": price}

    def day_pnl(self):
        return self.engine.day_pnl()

    EXIT_ROLES = ("stop", "target", "runner", "partial")

    def _is_exit(self, o):
        r = o.get("role") or ""
        return r in self.EXIT_ROLES or r.startswith("cash_flow")

    def _guard_exits(self, now):
        """Exits must never outgrow the position: after a manual close (or a fill IBKR booked elsewhere) a stop or
        target left for more shares than you hold would open a position the other way when it fills. Once the
        mismatch has held for 2 seconds (fills and position reports settle), exits for shares you no longer hold are
        trimmed or cancelled. Nothing is touched while an entry of that symbol is still working."""
        by_sym = {}
        pend = self.engine._pending()
        working_ids = {o.get("order_id") for o in pend}
        for o in pend:
            # exits of an entry that is still working wait for it (they aren't live yet): leave them alone
            if self._is_exit(o) and o.get("order_id") is not None and o.get("parent") not in working_ids:
                by_sym.setdefault(o.get("symbol"), []).append(o)
        for sym in list(self.mismatch):
            if sym not in by_sym:
                del self.mismatch[sym]
        for sym, exits in by_sym.items():
            # only on a SETTLED position: the broker reported it after the last fill, and 2 s have passed since that
            # fill (IBKR's position report can trail the fill; a stop is never cancelled on a stale 0)
            ft, pt = self.engine.fill_t.get(sym), self.engine.pos_t.get(sym)
            if pt is None or (ft is not None and (pt < ft or now - ft < 2.0)):
                self.mismatch.pop(sym, None)
                continue
            pos = self.broker.position(sym)
            closing = SELL if pos > 0 else BUY
            left = lambda o: float(o.get("remaining") if o.get("remaining") is not None else o.get("qty") or 0)
            wrong = [o for o in exits if not pos or o.get("action") != closing]
            over = []
            for kind in (("stop",), ("target", "runner", "cash_flow", "partial")):
                grp = sorted((o for o in exits if o not in wrong and (o.get("role") or "").startswith(kind)),
                             key=left, reverse=True)
                extra = sum(left(o) for o in grp) - abs(pos)
                for o in grp:
                    if extra <= 1e-9:
                        break
                    cut = min(left(o), extra)
                    over.append((o, left(o) - cut))
                    extra -= cut
            if not wrong and not over:
                self.mismatch.pop(sym, None)
                continue
            since = self.mismatch.setdefault(sym, now)
            if now - since < 2.0:
                continue
            del self.mismatch[sym]
            for o in wrong:
                self.broker.cancel(o["order_id"], now)
            for o, keep in over:
                self.broker.resize(o["order_id"], int(keep), now)
            self._note(now, f"{sym}: exits trimmed to the {abs(pos):g} shares you hold" if pos else
                       f"{sym}: flat — leftover exit orders cancelled", True)

    def watchdog(self, now=None):
        with self.lock:
            return self._watchdog_unlocked(now)

    def _watchdog_unlocked(self, now=None):
        """Called on every dashboard snapshot: breakeven stops after cash flow; exits never bigger than the
        position; daily-loss lock."""
        self._breakeven(now or time.time())
        try:
            self._guard_exits(now or time.time())
        except Exception as exc:
            log.warning("exit guard: %s", exc)
        try:
            self._auto_entries(now or time.time())
        except Exception as exc:
            log.warning("auto 2nd entry: %s", exc)
        limit = self.cfg["max_daily_loss"]
        if self.gate.locked:
            self._cancel_entries(now or time.time())   # every run while locked: one that failed or came in late goes too
            return
        if not limit:
            return
        pnl = self.day_pnl()
        if pnl["total"] <= -abs(limit):
            self.gate.lock_out(f"daily loss limit hit ({money(abs(pnl['total']))} against a {money(limit)} limit)")
            self._note(now or time.time(), f"TRADING LOCKED — day P&L {pnl['total']:+,.0f} hit your {limit:,.0f} loss limit", False)
            # entries that have not filled are cancelled (with their legs); the stops and targets protecting
            # what you hold stay working, and flatten / close still work while locked
            self._cancel_entries(now or time.time())


    # ---- AUTO 2ND ENTRY -------------------------------------------------------------------------------------
    AUTO_RETRY_SECONDS = 30.0

    def _order_by_id(self, oid):
        with self.engine.lock:
            for o in self.engine.orders.values():
                if o.get("order_id") == oid:
                    return dict(o)
        return None

    def set_auto(self, on, symbol=None, now=None):
        """The desk switch (no symbol) or one play's switch. Off cancels the working auto entry at once."""
        now = now or time.time()
        if symbol:
            st = self.engine.syms.get(symbol)
            if st is None:
                return False
            with self.engine.lock:
                st.play["auto"] = bool(on)
                self.engine._save_plays()
            self.engine.log(symbol, f"AUTO 2ND ENTRY {'on' if on else 'off'}", now, kind="level")
        else:
            self.auto_on = bool(on)
            self._note(now, f"AUTO 2ND ENTRY {'ON' if on else 'OFF'} for every play", True)
        with self.lock:
            self._auto_entries(now)
        return True

    def set_risk(self, dollars):
        try:
            dollars = float(dollars)
        except (TypeError, ValueError):
            return False
        if dollars < 0:
            return False
        self.risk_dollars = dollars
        return True

    def auto_size(self, play):
        """Shares for the auto entry: risk dollars over the distance 2nd entry -> stop, inside the order caps."""
        se, stop = play.get("second_entry"), play.get("stop")
        if not se or not stop or not self.risk_dollars:
            return 0
        risk = abs(float(se) - float(stop))
        if risk < tick_size(se) / 2:
            return 0
        qty = int(self.risk_dollars // risk)
        qty = min(qty, int(self.cfg["max_shares_per_order"]))
        if self.cfg.get("max_dollars_per_order"):
            qty = min(qty, int(self.cfg["max_dollars_per_order"] // float(se)))
        return max(qty, 0)

    def _auto_want(self, play):
        """The auto entry this play calls for now: (order or None, why not, may_place)."""
        sym = play["symbol"]
        if not self.auto_on:
            return None, "AUTO 2ND ENTRY is off on the desk", False
        if play.get("auto") is False:
            return None, "off for this play (cancelled by hand or switched off) — redraw the 2nd entry or switch it on", False
        if not play.get("active", True):
            return None, "play is retired", False
        se, stop, target = play.get("second_entry"), play.get("stop"), play.get("target")
        missing = [n for n, v in (("2nd entry", se), ("stop", stop), ("target", target)) if not v]
        if missing:
            return None, "needs a " + " and a ".join(missing) + " on the chart", False
        long_ = play.get("side", "long") == "long"
        action = BUY if long_ else SELL
        if (long_ and not (stop < se < target)) or (not long_ and not (target < se < stop)):
            return None, f"stop {money(stop)} and target {money(target)} must sit either side of the 2nd entry {money(se)}", False
        if not (self.gate.can_trade() and self.gate.armed):
            return None, self.gate.why_not() or "trading is DISARMED — click ARM", False
        if self.auto_done.get(sym) == price_key(se):
            return None, f"entered at {money(se)} already — one entry per 2nd entry (redraw it for another)", False
        qty = self.auto_size(play)
        if qty < 1:
            return None, f"${self.risk_dollars:,.0f} risk does not buy one share with the stop {money(abs(se - stop))} away", False
        pos = int(self.broker.position(sym))
        if pos:
            return None, f"already {'long' if pos > 0 else 'short'} {abs(pos):,} — the auto entry waits until you are flat", False
        mine = self.auto.get(sym)
        others = [o for o in self.engine._pending(sym) if o.get("role") == "entry"
                  and not (mine and o.get("order_id") == mine["id"])]
        if others:
            return None, "a manual entry is working on this symbol — the auto entry stays out of its way", False
        ticks = int(self.cfg.get("auto_entry_limit_ticks", 5))
        limit = snap(round(se + (ticks * tick_size(se) if long_ else -ticks * tick_size(se)), 4))
        want = {"action": action, "aux": snap(round(float(se), 4)), "price": limit, "qty": qty,
                "stop": float(stop), "target": float(target)}
        # PS60: the entry is BACK through the 2nd entry after the retrace. A stop entry placed with price already
        # through the level would fill at once (a chase), so it waits for the retrace; one already working stays
        last = self.engine.syms[sym].price()
        may_place = last is None or (last < se if long_ else last > se)
        return want, ("" if may_place else f"price {money(last)} is through the 2nd entry — waiting for the retrace {'under' if long_ else 'over'} {money(se)}"), may_place

    def _auto_entries(self, now):
        for play in list(self.engine.plays):
            try:
                self._auto_one(play, now)
            except Exception as exc:
                log.warning("auto 2nd entry %s: %s", play.get("symbol"), exc)

    def _auto_one(self, play, now):
        sym = play["symbol"]
        cur = self.auto.get(sym)
        if cur is not None:
            o = self._order_by_id(cur["id"])
            status = (o or {}).get("status")
            if status == "Filled" or (o and o.get("remaining") == 0 and (o.get("filled") or 0) > 0):
                self.auto_done[sym] = price_key(cur["aux"])
                self.auto.pop(sym, None)
                self._note(now, f"AUTO 2ND ENTRY FILLED {sym}: {cur['action']} {cur['qty']} through {money(cur['aux'])} — "
                                f"stop {money(cur['stop'])} and target {money(cur['target'])} are working", True)
                self.engine.log(sym, f"AUTO 2ND ENTRY filled {cur['action']} {cur['qty']} @ {money(cur['aux'])}", now, kind="level")
                cur = None
            elif o is not None and status in self.engine.DONE_STATUSES + ("Done",):
                # gone without a fill: cancelled by hand (from the ticket, TWS) or rejected. Not re-sent until the
                # 2nd entry is drawn again or the play's switch is put back on
                self.auto.pop(sym, None)
                if not cur.get("by_desk"):
                    with self.engine.lock:
                        play["auto"] = False
                        self.engine._save_plays()
                    self._note(now, f"AUTO 2ND ENTRY {sym} off: its order was {status.lower()} outside the desk — "
                                    f"redraw the 2nd entry (or switch AUTO on in PLAY SETUP) to arm it again", False)
                cur = None
        want, why, may_place = self._auto_want(play)
        if want is None:
            if cur is not None:
                cur["by_desk"] = True
                self._cancel_unlocked(cur["id"], now)
                self.auto.pop(sym, None)
                self._note(now, f"AUTO 2ND ENTRY {sym} cancelled: {why}", True)
            self.auto_why[sym] = why
            return
        if cur is not None:
            same = all(cur.get(k) == want[k] for k in ("action", "aux", "price", "qty"))
            if same and cur.get("stop") == want["stop"] and cur.get("target") == want["target"]:
                self.auto_why[sym] = ""
                return
            cur["by_desk"] = True
            self._cancel_unlocked(cur["id"], now)
            self.auto.pop(sym, None)
            self._note(now, f"AUTO 2ND ENTRY {sym} re-sent: the play's levels moved", True)
            cur = None
        if not may_place:
            self.auto_why[sym] = why
            return
        key = (price_key(want["aux"]), want["qty"], price_key(want["stop"]), price_key(want["target"]))
        f = self.auto_fail.get(sym)
        if f and f[0] == key and now - f[1] < self.AUTO_RETRY_SECONDS:
            self.auto_why[sym] = f[2]
            return
        out = self._submit_unlocked(sym, want["action"], want["price"], want["qty"], now, True, "STP LMT", want["aux"], "DAY")
        if out.get("ok"):
            self.auto[sym] = dict(want, id=out["id"], t=now, by_desk=False)
            self.auto_fail.pop(sym, None)
            self.auto_why[sym] = ""
            self.engine.log(sym, f"AUTO 2ND ENTRY armed: {want['action']} {want['qty']} through {money(want['aux'])} "
                                 f"(limit {money(want['price'])}) · stop {money(want['stop'])} · target {money(want['target'])}",
                            now, kind="level")
        else:
            reason = out.get("reason") or "refused"
            self.auto_fail[sym] = (key, now, reason)
            self.auto_why[sym] = reason

    def auto_status(self):
        """Per play: is the auto entry on, working, waiting, done — for the PLAY SETUP readout."""
        out = {}
        for play in list(self.engine.plays):
            sym = play["symbol"]
            on = self.auto_on and play.get("auto") is not False
            cur = self.auto.get(sym)
            se = play.get("second_entry")
            if cur is not None:
                state, text = "WORKING", (f"{cur['action']} {cur['qty']:,} fills when price comes through {money(cur['aux'])} · "
                                          f"stop {money(cur['stop'])} · target {money(cur['target'])}")
            elif se and self.auto_done.get(sym) == price_key(se):
                state, text = "DONE", f"entered at {money(se)} — the stop and target are running the trade"
            elif not on:
                state, text = "OFF", self.auto_why.get(sym) or "off"
            else:
                state, text = "WAITING", self.auto_why.get(sym) or "waiting"
            out[sym] = {"on": on, "state": state, "text": text, "qty": cur["qty"] if cur else self.auto_size(play),
                        "id": cur["id"] if cur else None}
        return out

    def _cancel_entries(self, now):
        for o in self.engine._pending():
            if o.get("role") == "entry" and o.get("order_id") is not None and o.get("status") != "PendingCancel":
                try:
                    self.broker.cancel(o["order_id"], now)
                except Exception as exc:
                    log.warning("cancel entry %s: %s", o.get("order_id"), exc)

    def _breakeven(self, now):
        """PS60: once the first cash-flow leg fills, the stop goes to breakeven (the entry price)."""
        if not self.cfg["scale_plan"]["breakeven_after_cash_flow"]:
            return
        for pid, fam in list(self.families.items()):
            if fam["be_done"]:
                continue
            live = [sid for sid in fam["stops"] if (self.broker.order_info(sid) or {}).get("status")
                    not in (None, "Filled", "Cancelled", "ApiCancelled", "Inactive", "Done")]
            if not live:
                fam["be_done"] = True
                continue
            if any((self.broker.order_info(c) or {}).get("status") == "Filled" for c in fam["cash"]):
                fam["be_done"] = True
                try:
                    moved = [sid for sid in live if self.broker.modify(sid, fam["entry"], now)]
                    if moved:
                        self._note(now, f"{fam['symbol']}: cash flow taken — stop moved to breakeven {money(fam['entry'])}", True)
                except Exception as exc:
                    self._note(now, f"{fam['symbol']}: could not move the stop to breakeven: {exc}", False)

    def adjust(self, symbol, shares, mode, now=None):
        with self.lock:
            return self._adjust_unlocked(symbol, shares, mode, now)

    def _adjust_unlocked(self, symbol, shares, mode, now=None):
        """Close or add ``shares`` to the position with a limit at the touch.

        mode "close": trade against the position (sell for a long, buy for a short).
        mode "add":   same direction as the position; if flat, "add" opens long.
        Limit price is the current bid (selling) or ask (buying): marketable now,
        but never worse than the quote you clicked.
        """
        now = now or time.time()
        shares = int(shares)
        if shares <= 0:
            return {"ok": False, "reason": "size must be positive"}
        pos = int(self.broker.position(symbol))
        st = self.engine.syms.get(symbol)
        bid, ask = st.bbo() if st else (None, None)
        if bid is None or ask is None:
            self._note(now, f"{symbol}: no quote yet", False)
            return {"ok": False, "reason": "no quote"}
        if mode == "close":
            if not pos:
                self._note(now, f"{symbol}: already flat, nothing to close", True)
                return {"ok": False, "reason": "flat"}
            _p, free, why = self._can_reduce_by(symbol, now)
            if not free:
                self._note(now, f"{symbol}: {why}", False)
                return {"ok": False, "reason": why}
            shares = min(shares, free)            # never more than is left to close
            action = SELL if pos > 0 else BUY
        elif mode == "add":
            action = BUY if pos >= 0 else SELL
        else:
            return {"ok": False, "reason": "mode must be close or add"}
        price = bid if action == SELL else ask
        if mode == "close":           # getting out: the reducing path (works locked / disarmed), exits trimmed after
            reason = self.gate.check_reduce(action, shares, price, now)
            if reason:
                self._note(now, f"BLOCKED close {symbol}: {reason}", False)
                return {"ok": False, "reason": reason}
            return self._reduce(symbol, action, price, shares, now, "close")
        return self.submit(symbol, action, price, shares, now, bracket=False)

    def set_size(self, shares):
        shares = int(shares)
        if shares <= 0:
            return False
        self.default_shares = min(shares, self.cfg["max_shares_per_order"])
        return True

    def snapshot(self, run_watchdog=True):
        # the engine calls this with its lock held: the watchdog (which talks to the broker) is run by the
        # dashboard before it takes the snapshot, never under the engine lock (TWS thread lock order)
        if run_watchdog:
            self.watchdog()
        s = self.gate.snapshot()
        s.update(default_shares=self.default_shares, bracket=self.bracket, scale=self.scale,
                 scale_plan=self.cfg["scale_plan"]["cash_flow"], log=list(self.log)[:12], pnl=self.day_pnl(),
                 auto_on=self.auto_on, risk_dollars=self.risk_dollars, auto=self.auto_status())
        return s
