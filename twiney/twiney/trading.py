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
import threading
import time
from collections import deque

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

    def arm(self, on):
        with self.lock:
            if on and not self.can_trade():
                return False
            self.armed = bool(on)
            return True

    def can_trade(self):
        if not self.cfg["enabled"]:
            return False
        if self.mode in ("SIM", "PAPER"):
            return True
        return self.mode == "LIVE" and bool(self.cfg["allow_live"])

    def why_not(self):
        if not self.cfg["enabled"]:
            return "trading is disabled in config.json"
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
            if order_type not in ("LMT", "STP"):
                return self._block("only LIMIT orders (and bracket stops) are allowed", action, qty, price, now)
            try:
                qty = int(qty)
                price = float(price)
            except (TypeError, ValueError):
                return self._block("size and price must be numbers", action, qty, price, now)
            if qty <= 0:
                return self._block("size must be positive", action, qty, price, now)
            if price <= 0:
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
                "can_trade": self.can_trade(),
                "why_not": self.why_not(),
                "accounts": list(self.accounts),
                "default_shares": self.cfg["default_shares"],
                "max_shares": self.cfg["max_shares_per_order"],
                "max_dollars": self.cfg["max_dollars_per_order"],
                "bracket": self.cfg["bracket"],
                "blocked": list(self.blocked)[:10],
            }


def bracket_legs(play, action, qty, entry_price):
    """Stop + target legs for an entry, taken from the play. None if the play has none."""
    stop, target = play.get("stop"), play.get("target")
    if not stop and not target:
        return []
    exit_action = SELL if action == BUY else BUY
    legs = []
    if stop:
        ok = stop < entry_price if action == BUY else stop > entry_price
        if ok:
            legs.append({"action": exit_action, "qty": qty, "type": "STP", "price": stop, "role": "stop"})
    if target:
        ok = target > entry_price if action == BUY else target < entry_price
        if ok:
            legs.append({"action": exit_action, "qty": qty, "type": "LMT", "price": target, "role": "target"})
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

    def place(self, symbol, action, qty, price, now, order_type="LMT", parent=None, role="entry", tif="DAY"):
        with self.lock:
            oid = self.next_id
            self.next_id += 1
            o = {"id": oid, "symbol": symbol, "action": action, "qty": qty, "remaining": qty,
                 "type": order_type, "price": price, "parent": parent, "role": role, "status": "Submitted",
                 "tif": tif, "t": now, "children": []}
            self.orders[oid] = o
            if parent in self.orders:
                self.orders[parent]["children"].append(oid)
                o["status"] = "PreSubmitted"  # waits for the parent to fill
            self._report(o, now)
            if o["status"] == "Submitted":
                self.on_market(symbol, now)  # marketable at once? fill it now
            return oid

    def cancel(self, oid, now):
        with self.lock:
            o = self.orders.get(oid)
            if o and o["status"] not in ("Filled", "Cancelled"):
                self._cancel(o, now)
                return True
            return False

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
                             type=o["type"], lmt=o["price"] if o["type"] == "LMT" else None,
                             aux=o["price"] if o["type"] == "STP" else None, tif=o["tif"], status=o["status"],
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
                if o["symbol"] != symbol or o["status"] != "Submitted":
                    continue
                if o["type"] == "LMT":
                    hit = (o["action"] == BUY and ask is not None and ask <= o["price"]) or \
                          (o["action"] == SELL and bid is not None and bid >= o["price"])
                    fill_px = o["price"]
                elif o["type"] == "STP":
                    hit = last is not None and ((o["action"] == SELL and last <= o["price"]) or
                                                (o["action"] == BUY and last >= o["price"]))
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
        # activate children, and once one child fills cancel its sibling (OCO)
        for c in o["children"]:
            child = self.orders.get(c)
            if child and child["status"] == "PreSubmitted":
                child["status"] = "Submitted"
                self._report(child, now)
        if o["parent"] in self.orders:
            for sib in self.orders[o["parent"]]["children"]:
                s = self.orders.get(sib)
                if s and s is not o and s["status"] in ("Submitted", "PreSubmitted"):
                    self._cancel(s, now)

    def position(self, symbol):
        return self.pos.get(symbol, [0.0, 0.0])[0]


class IbkrBroker:
    """Sends orders to TWS through the market-data session (paper or live)."""

    def __init__(self, engine, session):
        self.engine = engine
        self.session = session

    def place(self, symbol, action, qty, price, now, order_type="LMT", parent=None, role="entry", tif="DAY"):
        return self.session.send_order(symbol, action, qty, price, order_type, parent, role, tif, now)

    def cancel(self, oid, now):
        return self.session.cancel_order(oid, now)

    def cancel_all(self, now, symbol=None):
        return self.session.cancel_all(now, symbol)

    def position(self, symbol):
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
        self.log = deque(maxlen=200)

    def _note(self, now, text, ok):
        self.log.appendleft({"t": now, "text": text, "ok": ok})
        self.engine._message("info" if ok else "error", text, now)

    def submit(self, symbol, action, price, qty=None, now=None, bracket=None):
        now = now or time.time()
        qty = int(qty or self.default_shares)
        play = self.engine.syms[symbol].play if symbol in self.engine.syms else None
        if play is None:
            self._note(now, f"{symbol}: not one of your plays", False)
            return {"ok": False, "reason": "unknown symbol"}
        price = round(float(price), 4)
        reason = self.gate.check(action, qty, price, now)
        if reason:
            self._note(now, f"BLOCKED {action} {qty} {symbol} @ {money(price)}: {reason}", False)
            return {"ok": False, "reason": reason}
        use_bracket = self.bracket if bracket is None else bool(bracket)
        legs = bracket_legs(play, action, qty, price) if use_bracket else []
        try:
            parent_id = self.broker.place(symbol, action, qty, price, now, "LMT", None, "entry")
            for leg in legs:
                self.broker.place(symbol, leg["action"], leg["qty"], leg["price"], now, leg["type"], parent_id,
                                  leg["role"])
        except Exception as exc:
            self._note(now, f"FAILED {action} {qty} {symbol} @ {money(price)}: {exc}", False)
            return {"ok": False, "reason": str(exc)}
        what = f"{action} {qty} {symbol} @ {money(price)} LMT"
        if legs:
            what += " + " + " + ".join(f"{l['role']} {money(l['price'])}" for l in legs)
        self._note(now, f"SENT {what}", True)
        self.engine._rec({"ev": "order", "t": now, "sym": symbol, "action": action, "qty": qty, "px": price,
                          "legs": legs, "id": parent_id})
        return {"ok": True, "id": parent_id, "sent": what}

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
        """Close the position with a marketable limit (through the spread by a few ticks)."""
        now = now or time.time()
        qty = int(self.broker.position(symbol))
        if not qty:
            self._note(now, f"{symbol}: already flat", True)
            return {"ok": True, "flat": True}
        st = self.engine.syms.get(symbol)
        bid, ask = st.bbo() if st else (None, None)
        if bid is None or ask is None:
            self._note(now, f"{symbol}: no quote to flatten against", False)
            return {"ok": False, "reason": "no quote"}
        tk = tick_size(ask)
        slip = self.cfg["flatten_slip_ticks"] * tk
        action = SELL if qty > 0 else BUY
        price = round(bid - slip, 4) if qty > 0 else round(ask + slip, 4)
        self.broker.cancel_all(now, symbol)
        return self.submit(symbol, action, price, abs(qty), now, bracket=False)

    def set_size(self, shares):
        shares = int(shares)
        if shares <= 0:
            return False
        self.default_shares = min(shares, self.cfg["max_shares_per_order"])
        return True

    def snapshot(self):
        s = self.gate.snapshot()
        s.update(default_shares=self.default_shares, bracket=self.bracket, log=list(self.log)[:12])
        return s
