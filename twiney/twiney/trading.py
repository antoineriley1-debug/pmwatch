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
from .prices import fmt_price, tick_size


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
        targets = [{"action": exit_action, "qty": qty, "type": "LMT", "price": target, "role": "target"}]
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
        self.lock = threading.RLock()
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
                             role=o["role"], order_id=o["id"], sim=True)

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
        self.engine.on_fill(f"sim{o['id']}-{self.n_fills}", o["symbol"], "BOT" if o["action"] == BUY else "SLD",
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
        self.log = deque(maxlen=200)

    def _note(self, now, text, ok):
        self.log.appendleft({"t": now, "text": text, "ok": ok})
        self.engine._message("info" if ok else "error", text, now)

    def submit(self, symbol, action, price, qty=None, now=None, bracket=None, order_type="LMT", aux=None,
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
        price = snap(round(float(price or 0), 4))          # a price the exchange takes
        if order_type == "STP LMT":
            try:
                aux = round(float(aux), 4)
            except (TypeError, ValueError):
                return {"ok": False, "reason": "a stop-limit needs a stop price"}
            if aux <= 0:
                return {"ok": False, "reason": "stop price must be positive"}
        else:
            aux = None
        reason = self.gate.check(action, qty, price if order_type != "MKT" else (self.engine.syms[symbol].price() or 0), now, order_type)
        if not reason:
            pos = int(self.broker.position(symbol))
            # entries still working count too: five resting 500-share bids are a 2,500 share position waiting to happen
            working = sum((o.get("remaining") if o.get("remaining") is not None else o.get("qty") or 0) *
                          (1 if o.get("action") == BUY else -1)
                          for o in self.engine._pending(symbol) if o.get("role") == "entry")
            after = pos + int(working) + (qty if action == BUY else -qty)
            cap = self.cfg["max_position_shares"]
            if abs(after) > cap and abs(after) > abs(pos):
                reason = f"that would make the {symbol} position {abs(after):,} shares — your cap is {cap:,}"
                self.gate.blocked.appendleft({"t": now, "action": action, "qty": qty, "price": price, "reason": reason})
        if reason:
            self._note(now, f"BLOCKED {action} {qty} {symbol} @ {money(price)}: {reason}", False)
            return {"ok": False, "reason": reason}
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
        now = now or time.time()
        ok = self.broker.cancel(oid, now)
        self._note(now, f"cancel {oid}: {'sent' if ok else 'nothing to cancel'}", ok)
        return {"ok": ok}

    def cancel_all(self, symbol=None, now=None):
        now = now or time.time()
        n = self.broker.cancel_all(now, symbol)
        self._note(now, f"cancelled {n} working order{'s' if n != 1 else ''}{' in ' + symbol if symbol else ''}", True)
        return {"ok": True, "cancelled": n}

    def flatten(self, symbol, now=None):
        """Close the position with a marketable limit (through the spread by a few ticks). Works disarmed, locked
        for the day and over the caps: getting out is never blocked. One flatten at a time per symbol."""
        now = now or time.time()
        qty = int(self.broker.position(symbol))
        if not qty:
            self._note(now, f"{symbol}: already flat", True)
            return {"ok": True, "flat": True}
        if any(o.get("role") == "flatten" for o in self.engine._pending(symbol)):
            self._note(now, f"{symbol}: a flatten order is already working", False)
            return {"ok": False, "reason": "a flatten order is already working"}
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
        """Move a working order to a new price (drag on the ladder / chart)."""
        now = now or time.time()
        oid = int(oid)
        info = self.broker.order_info(oid)
        if not info:
            return {"ok": False, "reason": "no such order"}
        price = round(float(price), 4)
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

    EXIT_ROLES = ("stop", "target", "runner")

    def _is_exit(self, o):
        r = o.get("role") or ""
        return r in self.EXIT_ROLES or r.startswith("cash_flow")

    def _guard_exits(self, now):
        """Exits must never outgrow the position: after a manual close (or a fill IBKR booked elsewhere) a stop or
        target left for more shares than you hold would open a position the other way when it fills. Once the
        mismatch has held for 2 seconds (fills and position reports settle), exits for shares you no longer hold are
        trimmed or cancelled. Nothing is touched while an entry of that symbol is still working."""
        by_sym = {}
        for o in self.engine._pending():
            if self._is_exit(o) and o.get("order_id") is not None:
                by_sym.setdefault(o.get("symbol"), []).append(o)
        for sym in list(self.mismatch):
            if sym not in by_sym:
                del self.mismatch[sym]
        for sym, exits in by_sym.items():
            if any(o.get("role") == "entry" for o in self.engine._pending(sym)):
                self.mismatch.pop(sym, None)
                continue
            pos = self.broker.position(sym)
            closing = SELL if pos > 0 else BUY
            left = lambda o: float(o.get("remaining") if o.get("remaining") is not None else o.get("qty") or 0)
            wrong = [o for o in exits if not pos or o.get("action") != closing]
            over = []
            for kind in (("stop",), ("target", "runner", "cash_flow")):
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
        """Called on every dashboard snapshot: breakeven stops after cash flow; exits never bigger than the
        position; daily-loss lock."""
        self._breakeven(now or time.time())
        try:
            self._guard_exits(now or time.time())
        except Exception as exc:
            log.warning("exit guard: %s", exc)
        limit = self.cfg["max_daily_loss"]
        if not limit or self.gate.locked:
            return
        pnl = self.day_pnl()
        if pnl["total"] <= -abs(limit):
            self.gate.lock_out(f"daily loss limit hit ({money(abs(pnl['total']))} against a {money(limit)} limit)")
            self._note(now or time.time(), f"TRADING LOCKED — day P&L {pnl['total']:+,.0f} hit your {limit:,.0f} loss limit", False)
            # entries that have not filled are cancelled (with their legs); the stops and targets protecting
            # what you hold stay working, and flatten / close still work while locked
            for o in self.engine._pending():
                if o.get("role") == "entry" and o.get("order_id") is not None:
                    try:
                        self.broker.cancel(o["order_id"], now or time.time())
                    except Exception:
                        pass

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
            shares = min(shares, abs(pos))
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
                 scale_plan=self.cfg["scale_plan"]["cash_flow"], log=list(self.log)[:12], pnl=self.day_pnl())
        return s
