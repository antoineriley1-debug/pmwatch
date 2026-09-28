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
                "locked": self.locked,
                "max_position": self.cfg["max_position_shares"],
                "max_daily_loss": self.cfg["max_daily_loss"],
                "blocked": list(self.blocked)[:10],
            }


def bracket_legs(play, action, qty, entry_price, stop_limit_ticks=10, scale_plan=None):
    """Exit legs for an entry, taken from the play. Empty if the play has none.

    The stop is a STOP-LIMIT (trigger at the stop, limit ``stop_limit_ticks``
    through it), never a naked stop. With ``scale_plan`` the target leg becomes
    PS60 cash-flow legs plus a runner to the target.
    """
    stop, target = play.get("stop"), play.get("target")
    if not stop and not target:
        return []
    exit_action = SELL if action == BUY else BUY
    legs = []
    if stop:
        ok = stop < entry_price if action == BUY else stop > entry_price
        if ok:
            tk = tick_size(stop)
            lmt = round(stop - tk * stop_limit_ticks, 4) if action == BUY else round(stop + tk * stop_limit_ticks, 4)
            legs.append({"action": exit_action, "qty": qty, "type": "STP LMT", "price": lmt, "aux": stop,
                         "role": "stop"})
    if scale_plan:
        legs.extend(ps60.cash_flow_legs(play, action, qty, entry_price, scale_plan))
    elif target:
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

    def place(self, symbol, action, qty, price, now, order_type="LMT", parent=None, role="entry", tif="DAY",
              aux=None):
        with self.lock:
            oid = self.next_id
            self.next_id += 1
            o = {"id": oid, "symbol": symbol, "action": action, "qty": qty, "remaining": qty,
                 "type": order_type, "price": price, "aux": aux, "parent": parent, "role": role,
                 "status": "Submitted", "tif": tif, "t": now, "children": []}
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
        # activate children, and once one child fills cancel its sibling (OCO)
        for c in o["children"]:
            child = self.orders.get(c)
            if child and child["status"] == "PreSubmitted":
                child["status"] = "Submitted"
                self._report(child, now)
        if o["parent"] in self.orders:
            for sib in self.orders[o["parent"]]["children"]:
                s = self.orders.get(sib)
                if not (s and s is not o and s["status"] in ("Submitted", "PreSubmitted")):
                    continue
                if o["role"] == "stop" or s["role"] != "stop":
                    self._cancel(s, now)      # stop hit: every other exit goes; a target fill cancels other targets
                else:
                    s["remaining"] -= qty     # a cash-flow / runner fill shrinks the stop
                    if s["remaining"] <= 0:
                        self._cancel(s, now)
                    else:
                        self._report(s, now)

    def position(self, symbol):
        return self.pos.get(symbol, [0.0, 0.0])[0]


class IbkrBroker:
    """Sends orders to TWS through the market-data session (paper or live)."""

    def __init__(self, engine, session):
        self.engine = engine
        self.session = session

    def place(self, symbol, action, qty, price, now, order_type="LMT", parent=None, role="entry", tif="DAY",
              aux=None):
        return self.session.send_order(symbol, action, qty, price, order_type, parent, role, tif, now, aux=aux)

    def cancel(self, oid, now):
        return self.session.cancel_order(oid, now)

    def modify(self, oid, price, now):
        return self.session.modify_order(oid, price, now)

    def order_info(self, oid):
        for o in self.engine.orders.values():
            if o.get("order_id") == oid:
                return o
        return None

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
        self.scale = bool(self.cfg["scale_plan"]["enabled"])
        self.families = {}   # entry order id -> {"symbol", "entry", "stop", "cash": [...], "be_done"}
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
        if not reason:
            pos = int(self.broker.position(symbol))
            after = pos + (qty if action == BUY else -qty)
            cap = self.cfg["max_position_shares"]
            if abs(after) > cap and abs(after) > abs(pos):
                reason = f"that would make the {symbol} position {abs(after):,} shares — your cap is {cap:,}"
                self.gate.blocked.appendleft({"t": now, "action": action, "qty": qty, "price": price, "reason": reason})
        if reason:
            self._note(now, f"BLOCKED {action} {qty} {symbol} @ {money(price)}: {reason}", False)
            return {"ok": False, "reason": reason}
        use_bracket = self.bracket if bracket is None else bool(bracket)
        plan = self.cfg["scale_plan"]["cash_flow"] if self.scale else None
        legs = bracket_legs(play, action, qty, price, self.cfg["stop_limit_ticks"], plan) if use_bracket else []
        try:
            parent_id = self.broker.place(symbol, action, qty, price, now, "LMT", None, "entry")
            fam = {"symbol": symbol, "entry": price, "stop": None, "cash": [], "be_done": False}
            for leg in legs:
                lid = self.broker.place(symbol, leg["action"], leg["qty"], leg["price"], now, leg["type"], parent_id,
                                        leg["role"], aux=leg.get("aux"))
                if leg["role"] == "stop":
                    fam["stop"] = lid
                elif leg["role"].startswith("cash_flow"):
                    fam["cash"].append(lid)
            if fam["stop"] is not None and fam["cash"]:
                self.families[parent_id] = fam
        except Exception as exc:
            self._note(now, f"FAILED {action} {qty} {symbol} @ {money(price)}: {exc}", False)
            return {"ok": False, "reason": str(exc)}
        what = f"{action} {qty} {symbol} @ {money(price)} LMT"
        if legs:
            what += " + " + " + ".join(
                f"stop {money(l['aux'])} (limit {money(l['price'])})" if l["role"] == "stop"
                else f"{l['role'].replace('_', ' ')} {l['qty']} @ {money(l['price'])}" for l in legs)
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

    def watchdog(self, now=None):
        """Called on every dashboard snapshot: breakeven stops after cash flow; daily-loss lock."""
        self._breakeven(now or time.time())
        limit = self.cfg["max_daily_loss"]
        if not limit or self.gate.locked:
            return
        pnl = self.day_pnl()
        if pnl["total"] <= -abs(limit):
            self.gate.lock_out(f"daily loss limit hit ({money(abs(pnl['total']))} against a {money(limit)} limit)")
            self._note(now or time.time(), f"TRADING LOCKED — day P&L {pnl['total']:+,.0f} hit your {limit:,.0f} loss limit", False)
            try:
                self.broker.cancel_all(now or time.time())
            except Exception:
                pass

    def _breakeven(self, now):
        """PS60: once the first cash-flow leg fills, the stop goes to breakeven (the entry price)."""
        if not self.cfg["scale_plan"]["breakeven_after_cash_flow"]:
            return
        for pid, fam in list(self.families.items()):
            if fam["be_done"]:
                continue
            stop = self.broker.order_info(fam["stop"])
            if stop is None or stop.get("status") in ("Filled", "Cancelled", "ApiCancelled", "Inactive", "Done"):
                fam["be_done"] = True
                continue
            if any((self.broker.order_info(c) or {}).get("status") == "Filled" for c in fam["cash"]):
                fam["be_done"] = True
                try:
                    if self.broker.modify(fam["stop"], fam["entry"], now):
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
        return self.submit(symbol, action, price, shares, now, bracket=False)

    def set_size(self, shares):
        shares = int(shares)
        if shares <= 0:
            return False
        self.default_shares = min(shares, self.cfg["max_shares_per_order"])
        return True

    def snapshot(self):
        self.watchdog()
        s = self.gate.snapshot()
        s.update(default_shares=self.default_shares, bracket=self.bracket, scale=self.scale,
                 scale_plan=self.cfg["scale_plan"]["cash_flow"], log=list(self.log)[:12], pnl=self.day_pnl())
        return s
