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



def is_option_key(symbol):
    """'TSLA 20261003 240C' style keys are option contracts."""
    parts = str(symbol or "").split(" ")
    return len(parts) == 3 and parts[1].isdigit() and len(parts[1]) == 8


def opt_snap(price):
    """A typed / dragged option price on a nickel (0.05): valid at any price on the busy (penny-program) names,
    and under $3 on every option. A price you type on a nickel is never moved."""
    if not price or price <= 0:
        return price
    step = 0.05
    return round(max(step, round(price / step) * step), 2)


def opt_through(touch, action):
    """An option limit that fills now: one price step through the touch (up for a buy, down for a sell). The step
    is the contract's own: a penny when it is quoted in pennies (the busy names under $3), else a nickel under $3 and
    a dime at $3 and up. A sell is never priced over the bid it is selling into (a 3-cent bid sells at 2 or 3 cents,
    never at a nickel that would sit unfilled)."""
    import math
    cents = round(touch * 100)
    step = 0.01 if (touch < 3 and cents % 5) else 0.05 if touch < 3 else 0.10
    n = touch / step
    if action == BUY:
        k = math.ceil(round(n, 6))
        if abs(n - round(n)) < 1e-6:
            k += 1
        return round(k * step, 2)
    k = math.floor(round(n, 6))
    if abs(n - round(n)) < 1e-6:
        k -= 1
    v = round(k * step, 2)
    if v <= 0:                                    # nothing under it on the grid: sell AT the bid
        v = round(touch, 2)
    return v

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
        self.unlocked_by_hand = False  # UNLOCK pressed on paper: the loss lock does not come back this session
        self.lock = threading.RLock()

    # ---- state ------------------------------------------------------------
    def set_accounts(self, accounts):
        with self.lock:
            self.accounts = [a for a in accounts if a]
            if self.mode != "SIM":
                # IBKR paper accounts all start with D (DU…, DF… for a paper advisor account, DI…)
                self.mode = "PAPER" if self.accounts and all(a.upper().startswith("D") for a in self.accounts) \
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

    def unlock(self, by_hand=False):
        """Lift the loss lock (paper / practice, or the limit was raised / switched off). Stays DISARMED: you ARM.
        By hand (UNLOCK, paper): it stays lifted for the rest of the session."""
        with self.lock:
            self.locked = None
            if by_hand:
                self.unlocked_by_hand = True
            return True

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
            return f"LIVE account {', '.join(self.accounts)} — TED trades PAPER only: log TWS into your PAPER account (or switch on Allow live in SETTINGS)"
        if not self.armed:
            return "trading is DISARMED — click ARM"
        return None

    # ---- the check every order must pass ------------------------------------
    def check(self, action, qty, price, now, order_type="LMT", mult=1):
        """``mult`` 100 for an option: ``price`` is per contract, the caps are checked in real dollars."""
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
            unit = "contracts" if mult != 1 else "shares"
            if qty > self.cfg["max_shares_per_order"]:
                return self._block(f"{qty} {unit} is over your cap of {self.cfg['max_shares_per_order']}",
                                   action, qty, price, now)
            if qty * price * mult > self.cfg["max_dollars_per_order"]:
                what = (f"{qty:,} contracts × ${price:,.2f} × {mult:g}" if mult != 1 else f"{qty:,} sh × {money(price)}")
                return self._block(f"{what} = ${qty * price * mult:,.2f} is over your ${self.cfg['max_dollars_per_order']:,.0f} per-order cap",
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
                "allow_live": bool(self.cfg.get("allow_live")),
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
                "loss_lock_on": bool(self.cfg["max_daily_loss"]) and ((self.mode == "LIVE" and bool(self.cfg.get("allow_live"))) or (self.mode in ("PAPER", "SIM") and self.cfg.get("loss_limit_on_paper", False) and not self.unlocked_by_hand)),
                "blocked": list(self.blocked)[:10],
            }


def snap(price, direction=0, symbol=None):
    """A price on a valid tick: the instrument's own increment when IBKR has reported it, else 0.01 at $1 and up,
    0.0001 below. direction +1 rounds up, -1 down, 0 nearest."""
    if not price or price <= 0:
        return price
    tk = tick_size(price, symbol)
    n = price / tk
    n = math.ceil(n - 1e-7) if direction > 0 else math.floor(n + 1e-7) if direction < 0 else round(n)
    out = round(n * tk, 4)
    tk2 = tick_size(out, symbol)          # crossing $1 changes the tick
    if tk2 != tk:
        n = out / tk2
        out = round((math.ceil(n - 1e-7) if direction > 0 else math.floor(n + 1e-7) if direction < 0 else round(n)) * tk2, 4)
    return out


def stop_ok(play, action, entry_price):
    stop = play.get("stop")
    return not stop or (stop < entry_price if action == BUY else stop > entry_price)


def template_legs(template, action, qty, entry_price, stop_limit_ticks=10, symbol=None):
    """Exit legs from a bracket template measured off the ENTRY price: stop at entry -/+ stop, targets at
    entry +/- offset with pct of the shares each (the last target takes whatever rounding left over). Every
    target is paired with its own stop for the same shares (OCA), like the play bracket."""
    if not template or qty <= 0 or not entry_price:
        return []
    exit_action = SELL if action == BUY else BUY
    sign = 1 if action == BUY else -1
    stop_off = float(template.get("stop") or 0)
    stop = snap(entry_price - sign * stop_off, -sign, symbol) if stop_off > 0 else None
    tlist = [t for t in (template.get("targets") or []) if float(t.get("offset") or 0) > 0]
    targets, used = [], 0
    for i, t in enumerate(tlist):
        n = qty - used if i == len(tlist) - 1 else int(round(qty * float(t.get("pct") or 0) / 100.0))
        if n <= 0:
            continue
        used += n
        targets.append({"action": exit_action, "qty": n, "type": "LMT", "price": snap(entry_price + sign * float(t["offset"]), sign, symbol),
                        "role": f"target_{i + 1}"})
    stop_leg = None
    if stop:
        tk = tick_size(stop, symbol)
        lmt = snap(stop - tk * stop_limit_ticks, -1, symbol) if action == BUY else snap(stop + tk * stop_limit_ticks, +1, symbol)
        stop_leg = {"action": exit_action, "type": "STP LMT", "price": lmt, "aux": stop, "role": "stop"}
    legs, covered = [], 0
    for i, t in enumerate(targets):
        g = f"t{i + 1}"
        if stop_leg:
            legs.append(dict(stop_leg, qty=t["qty"], oca=g))
        legs.append(dict(t, oca=g))
        covered += t["qty"]
    if stop_leg and covered < qty:
        legs.append(dict(stop_leg, qty=qty - covered, oca=f"t{len(targets) + 1}"))
    return legs


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
                if o.get("opt"):
                    self.on_opt_market(o["symbol"], now)
                else:
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
        # (the chart lines' stop and target have no parent: the OCA group alone pairs them, like at IBKR)
        if o.get("oca"):
            sibs = self.orders[o["parent"]]["children"] if o["parent"] in self.orders else \
                [k for k, x in self.orders.items() if x.get("oca") == o["oca"] and x.get("symbol") == o.get("symbol")]
            for sib in sibs:
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

    # ---- practice options: LIMIT DAY orders on a contract, filled against the practice quote ------------
    def place_option(self, key, action, qty, price, now, reducing=False):
        with self.lock:
            oid = self.next_id
            self.next_id += 1
            o = {"id": oid, "symbol": key, "action": action, "qty": qty, "remaining": qty, "type": "LMT", "price": price,
                 "aux": None, "parent": None, "role": "option", "status": "Submitted", "tif": "DAY", "t": now, "children": [],
                 "oca": None, "held": False, "opt": True}
            self.orders[oid] = o
            self.engine.on_order(f"sim{oid}", now, symbol=key, action=action, qty=float(qty), remaining=float(qty), type="LMT",
                                 lmt=price, aux=None, tif="DAY", status="Submitted", order_id=oid, role="option", mine=True, parent=None, opt=True)
            self.on_opt_market(key, now)
            return oid

    def on_opt_market(self, key, now):
        """A practice option order fills when its limit reaches the quote (buy at or over the ask, sell at or
        under the bid), at the quote; the position lands in the engine like one from TWS."""
        q = self.engine.opt_quotes.get(key) or {}
        for o in list(self.orders.values()):
            if not o.get("opt") or o["symbol"] != key or o["status"] not in ("Submitted", "PreSubmitted"):
                continue
            px = q.get("ask") if o["action"] == BUY else q.get("bid")
            if px is None or (o["action"] == BUY and o["price"] < px) or (o["action"] == SELL and o["price"] > px):
                continue
            n = o["remaining"]
            o["remaining"], o["status"] = 0, "Filled"
            mult = 100.0
            pos = self.engine.opt_positions.get(key)
            cur = pos["qty"] if pos else 0
            cost = pos["avg_cost"] if pos else 0.0
            signed = n if o["action"] == BUY else -n
            new_qty = cur + signed
            if cur == 0 or (cur > 0) != (new_qty > 0) and new_qty != 0:
                avg = px * mult
            elif abs(new_qty) > abs(cur):
                avg = (cost * abs(cur) + px * mult * n) / abs(new_qty)
            else:
                avg = cost
            sym, exp, rest = key.split(" ", 2)
            fields = {"symbol": sym, "expiry": exp, "strike": float(rest[:-1]), "right": rest[-1], "mult": mult, "local": ""}
            self.engine.on_opt_position(self.account, key, fields, new_qty, avg if new_qty else 0.0, now)
            self.engine.on_order(f"sim{o['id']}", now, status="Filled", filled=float(n), remaining=0.0, avg_fill=px, order_id=o["id"])
            self.engine.on_opt_fill(f"sim{self.session}.{o['id']}", key, "BOT" if o["action"] == BUY else "SLD", n, px, now)


class IbkrBroker:
    """Sends orders to TWS through the market-data session (paper or live)."""

    def __init__(self, engine, session):
        self.engine = engine
        self.session = session

    def place(self, symbol, action, qty, price, now, order_type="LMT", parent=None, role="entry", tif="DAY",
              aux=None, oca=None, transmit=True, reducing=False):
        if is_option_key(symbol) and self.engine.opt_sim(now):
            raise RuntimeError(self.engine.SIM_WHY)
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

    def place_option(self, key, action, qty, price, now, reducing=False):
        if self.engine.opt_sim(now):          # a limit priced off a simulated quote never goes to IBKR
            raise RuntimeError(self.engine.SIM_WHY)
        return self.session.send_option_order(key, action, qty, price, now, reducing=reducing)


# ---------------------------------------------------------------------------

class Trader:
    """What the dashboard talks to. Applies the gate, then hands to the broker."""

    def __init__(self, engine, cfg, broker, gate):
        self.engine = engine
        self.cfg = cfg["trading"]
        self.broker = broker
        self.gate = gate
        self.bracket_template = str(self.cfg.get("bracket_template") or "PLAY").upper()
        self.default_shares = self.cfg["default_shares"]
        self.bracket = bool(self.cfg["bracket"])
        self.scale = bool(self.cfg["scale_plan"]["enabled"])
        self.scale_plans = {}          # symbol -> SCALE PLAN on the position (rungs from the average entry)
        self.trails = {}               # symbol -> {"dist", "best", "side"}: a trailing stop riding the STOP line
        self.opt_stops = {}            # option key -> {"price", "on": "stock" | "option"}: a stop you set on a contract
        self.opt_stop_fired = {}       # option key -> t it fired (no double sends while the close works)
        self.opt_link = {}             # symbol -> what the chart's lines did on the linked contract (OPTIONS mode)
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
        self.auto_sync = {}  # symbol -> the stop / target lines the exits of a filled auto entry were last set to
        self.auto_side = {}  # symbol -> was price beyond the 2nd entry at the last look (to catch the cross)
        self.auto_seen = {}  # symbol -> the 2nd entry last seen (a change is a line drawn or moved)
        self.auto_done_t = {}  # symbol -> when the auto entry filled (the FILLED chip goes after a minute and a half)
        # every order action (clicks on HTTP threads, the watchdog thread) runs one at a time: a check and the order
        # it allows can never be split by another click (two flattens, two closes, the same ticket twice)
        self.lock = threading.RLock()
        self.log = deque(maxlen=200)

    def _note(self, now, text, ok):
        self.log.appendleft({"t": now, "text": text, "ok": ok})
        self.engine._message("info" if ok else "error", text, now)
        # every order, stop, target and refusal lands in the journal: the trade's log (under the stock's symbol)
        sym = self._sym_in(text)
        if sym and getattr(self.engine, "desk", None) is not None:
            body = text[len(sym) + 2:] if text.startswith(sym + ": ") else text      # the log line already says the ticker
            try:
                self.engine.desk.add_note(now, ("" if ok else "✕ ") + body, sym, kind="order")
            except Exception as exc:
                log.warning("journal note: %s", exc)

    def _sym_in(self, text):
        """The ticker a desk note is about: the first word that is one of yours (a contract counts as its stock)."""
        syms = self.engine.syms
        for w in str(text).replace(":", " ").replace(",", " ").split():
            if w in syms:
                return w
        return None

    def submit(self, symbol, action, price, qty=None, now=None, bracket=None, order_type="LMT", aux=None, tif="DAY", nonce=None):
        with self.lock:
            return self._submit_unlocked(symbol, action, price, qty, now, bracket, order_type, aux, tif, nonce)

    def _submit_unlocked(self, symbol, action, price, qty=None, now=None, bracket=None, order_type="LMT", aux=None,
               tif="DAY", nonce=None, levels=None):
        """``levels``: the stop / target the bracket uses when it is not the play's own side (its OTHER SIDE)."""
        now = now or time.time()
        qty = int(qty or self.default_shares)
        play = self.engine.syms[symbol].play if symbol in self.engine.syms else None
        if play is not None and levels is not None:
            play = dict(play, side=levels.get("side", play.get("side")), stop=levels.get("stop"), target=levels.get("target"),
                        mp=levels.get("target"), second_entry=levels.get("second_entry"), trigger=levels.get("trigger"))
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
        price = snap(round(float(price or 0), 4), symbol=symbol)          # a price the exchange takes
        if order_type == "STP LMT":
            try:
                aux = snap(round(float(aux), 4), symbol=symbol)
            except (TypeError, ValueError):
                self.nonces.pop(nonce, None) if nonce else None
                return {"ok": False, "reason": "a stop-limit needs a stop price"}
            if aux <= 0:
                self.nonces.pop(nonce, None) if nonce else None
                return {"ok": False, "reason": "stop price must be positive"}
        else:
            aux = None
        # a ticket order that takes the position DOWN (a SELL while long, a BUY while short, no bigger than the
        # position) is a close, not a trade: it goes through the reducing gate, which the day-loss lock, DISARM
        # and the caps never block. Getting out is always allowed
        pos0 = int(self.broker.position(symbol))
        closing = bool(pos0) and order_type == "LMT" and action == (SELL if pos0 > 0 else BUY) and qty <= abs(pos0)
        if closing:
            # never more than is left to close: closes already working count (two SELL 100s on a 100 long would flip it short)
            _p, free, why = self._can_reduce_by(symbol, now)
            reason = None if qty <= free else (why or f"only {free} of {abs(pos0)} shares are left to close") + " — nothing sent"
            if not reason:
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
        # ADDING to a position that already has its stop / take profit working: no second bracket. The add joins
        # them: once it fills, the existing STOP and TAKE PROFIT grow to cover every share (_grow_exits)
        joins = False
        if use_bracket and pos0 and (pos0 > 0) == (action == BUY):
            exit_side = SELL if pos0 > 0 else BUY
            if any(o.get("role") in ("stop", "target") and o.get("action") == exit_side and o.get("order_id") is not None
                   for o in self.engine._pending(symbol)):
                use_bracket, joins = False, True
        plan = self.cfg["scale_plan"]["cash_flow"] if self.scale else None
        # the price the exits are measured from: a stop entry's TRIGGER (where you get in), never its limit (a cap
        # that can sit well past it — measured from there, a near target was dropped and the stop judged wrongly)
        ref = aux if order_type == "STP LMT" else price if order_type == "LMT" else (self.engine.syms[symbol].price() or price)
        if use_bracket and ref and self.bracket_template == "PLAY" and play is not None and not stop_ok(play, action, ref):
            # the chart's stop belongs to the OTHER direction (a long's stop under the price, and you SELL short): use
            # the side you drew for this direction, else a stop trading.auto_stop_dollars ($1) the right way. Never
            # an order with no stop, never a blocked order because an old line points the other way
            alt = play.get("alt") or {}
            alt_side = "short" if play.get("side", "long") == "long" else "long"
            want_side = "long" if action == BUY else "short"
            d = float(self.cfg.get("auto_stop_dollars") or 0)
            fix = None
            if alt_side == want_side and alt.get("stop") and stop_ok(alt, action, ref):
                fix = {"stop": alt["stop"], "target": alt.get("target")}
                why = f"your {want_side.upper()} side's stop {money(alt['stop'])}"
            elif d > 0:
                fix = {"stop": snap(ref - d if action == BUY else ref + d, -1 if action == BUY else 1), "target": None}
                why = f"a stop ${d:g} {'under' if action == BUY else 'over'} at {money(fix['stop'])} (the chart's stop {money(play['stop'])} is for the other direction)"
            if fix is not None:
                tgt = fix["target"]
                if tgt and not ((tgt > ref) if action == BUY else (tgt < ref)):
                    tgt = None
                play = dict(play, stop=fix["stop"], target=tgt, mp=tgt)
                self._note(now, f"{symbol}: {action} {qty} goes out with {why}", True)
        if use_bracket and ref and self.bracket_template == "PLAY" and not stop_ok(play, action, ref):
            reason = (f"your stop {money(play['stop'])} is on the wrong side of a {action} at {money(ref)} — "
                      f"the order would go out with no stop. Fix the stop first")
            self._note(now, f"BLOCKED {action} {qty} {symbol} @ {money(price)}: {reason}", False)
            if nonce:
                self.nonces.pop(nonce, None)
            return {"ok": False, "reason": reason}
        tpl = self.bracket_templates().get(self.bracket_template) if self.bracket_template != "PLAY" else None
        legs = (template_legs(tpl, action, qty, ref, self.cfg["stop_limit_ticks"], symbol) if tpl
                else bracket_legs(play, action, qty, ref, self.cfg["stop_limit_ticks"], plan)) if use_bracket and ref else []
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
            if nonce:
                self.nonces.pop(nonce, None)                  # a failed send can be retried with the same ticket
            return {"ok": False, "reason": str(exc)}
        what = f"{action} {qty} {symbol} " + (f"@ {money(price)} " if order_type != "MKT" else "") + order_type + (f" stop {money(aux)}" if aux else "") + ("" if tif == "DAY" else " " + tif)
        if legs:
            what += " + " + " + ".join(
                f"stop {money(l['aux'])} (limit {money(l['price'])})" if l["role"] == "stop"
                else f"{l['role'].replace('_', ' ')} {l['qty']} @ {money(l['price'])}" for l in legs)
        if joins:
            what += " — adds to your working stop and take profit (they grow when it fills)"
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
            return self._cancel_unlocked(oid, now, by_hand=True)

    def _cancel_unlocked(self, oid, now=None, by_hand=False):
        now = now or time.time()
        try:
            oid = int(oid)
        except (TypeError, ValueError):
            return {"ok": False, "reason": "no order id"}
        o = self._order_by_id(oid)
        if by_hand and o is not None and o.get("status") in self.engine.DONE_STATUSES + ("Done",):
            return {"ok": False, "reason": f"order #{oid} is already {str(o.get('status')).lower()}"}
        ok = self.broker.cancel(oid, now)
        self._note(now, f"cancel {oid}: {'sent' if ok else 'nothing to cancel'}", ok)
        if not ok:
            return {"ok": False, "reason": "not connected to IBKR" if o is not None else f"order #{oid} is not working any more"}
        if o is not None:
            with self.engine.lock:          # shown as CANCEL PENDING at once, until IBKR confirms (sim confirms at once)
                live = self.engine.orders.get(o.get("key"))
                if live is not None and live.get("status") not in self.engine.DONE_STATUSES + ("Done",):
                    live["status"] = "PendingCancel"
            if by_hand:
                self._hand_cancel_exit(o, now)
        return {"ok": True}

    def _hand_cancel_exit(self, o, now):
        """A STOP or TARGET order cancelled by hand from ORDERS: its line comes off the chart too, so the chart never
        shows an exit that is not working (and the desk does not send it again)."""
        role, sym = o.get("role"), o.get("symbol")
        if role not in ("stop", "target") or sym not in self.engine.syms:
            return
        s = self.auto_sync.get(sym) or {}
        alt = bool(s.get("alt"))
        play = self.engine.syms[sym].play
        lines = (play.get("alt") or {}) if alt else play
        if lines.get(role) is not None:
            self.engine.set_play_level(sym, role, None, now, source="cancelled", alt=alt)
            self._note(now, f"{sym}: {role} order cancelled — its {role.upper()} line is off the chart", True)
        if s:
            s[role] = None

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
        pos = int(self.broker.position(symbol))
        if not pos:
            self._note(now, f"{symbol}: already flat", True)
            return {"ok": True, "flat": True}
        if any(o.get("role") == "flatten" for o in self.engine._pending(symbol)):
            self._note(now, f"{symbol}: a flatten order is already working", False)
            return {"ok": False, "reason": "a flatten order is already working"}
        if self.engine.recently_filled(symbol, self.REDUCING, now):
            reason = "the last close just filled — the position is updating, try again in a moment"
            self._note(now, f"{symbol}: {reason}", False)
            return {"ok": False, "reason": reason}
        st = self.engine.syms.get(symbol)
        bid, ask = st.bbo() if st else (None, None)
        if bid is None or ask is None:
            self._note(now, f"{symbol}: no quote to flatten against", False)
            return {"ok": False, "reason": "no quote"}
        tk = tick_size(ask)
        slip = self.cfg["flatten_slip_ticks"] * tk
        action = SELL if pos > 0 else BUY
        price = snap(bid - slip, -1, symbol) if pos > 0 else snap(ask + slip, +1, symbol)
        reason = self.gate.check_reduce(action, abs(pos), price, now)
        if reason:            # checked BEFORE the stops are cancelled: a refused flatten leaves them in place
            self._note(now, f"BLOCKED flatten {symbol}: {reason}", False)
            return {"ok": False, "reason": reason}
        # closes and partials already working are not cancelled (a cancel is not instant: a fill in between would
        # flip the position): they are moved to the flatten price, and the flatten takes only the rest. Every other
        # order (stops, targets, entries) is cancelled. Close + partial + flatten = exactly the position, at the market
        working = 0
        for o in self.engine._pending(symbol):
            if o.get("order_id") is None or o.get("status") == "PendingCancel":
                continue
            if o.get("role") in ("close", "partial") and o.get("action") == action:
                try:
                    self.broker.modify(o["order_id"], price, now)
                except Exception as exc:
                    log.warning("move %s to flatten: %s", o.get("order_id"), exc)
                working += int(o.get("remaining") if o.get("remaining") is not None else o.get("qty") or 0)
            else:
                try:
                    self.broker.cancel(o["order_id"], now)
                except Exception as exc:
                    log.warning("cancel %s for flatten: %s", o.get("order_id"), exc)
        rest = abs(pos) - working
        if rest <= 0:
            self._note(now, f"FLATTEN {symbol}: the working close{'s' if working else ''} moved to {money(price)}", True)
            return {"ok": True, "sent": f"closes moved to {money(price)}"}
        return self._reduce(symbol, action, price, rest, now, "flatten")

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
        price = snap(price, -1 if action == SELL else +1, symbol)
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
        be = snap(entry, -1 if long_ else +1, symbol)            # never a tick on the wrong side of your cost
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
            # no stop working yet: BREAKEVEN puts one on the board — the chart's STOP line goes to your entry and
            # that line becomes the stop order for every share you hold
            for o in stop_orders:
                try:
                    self.broker.cancel(o["order_id"], now)
                except Exception as exc:
                    self._note(now, f"{symbol}: could not cancel stop {o['order_id']}: {exc}", False)
            self._stop_line_follows(symbol, be, now)
            if not self.cfg.get("lines_are_exits", True):
                return {"ok": False, "reason": f"the STOP line is at breakeven {money(be)}, but chart lines are not orders "
                                              f"(SETTINGS, Trading, lines are exits) — no stop order was sent"}
            if st is not None:
                self.auto_sync.pop(symbol, None)
                self._lines_are_exits(st.play, now)
            placed = [o for o in self.engine._pending(symbol) if o.get("action") == closing
                      and (o.get("role") == "stop" or o.get("type") in ("STP", "STP LMT"))]
            if not placed:
                return {"ok": False, "reason": f"the STOP line is at breakeven {money(be)} but the stop order did not go in — check ORDERS"}
            self._note(now, f"{symbol}: BREAKEVEN stop placed at {money(be)} for {abs(int(pos)):,} sh", True)
            self.engine._rec({"ev": "breakeven", "t": now, "sym": symbol, "px": be})
            return {"ok": True, "price": be, "moved": 0, "cancelled": 0, "placed": True,
                    "sent": f"breakeven stop {money(be)} placed for {abs(int(pos)):,} sh"}
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
                    self._stop_line_follows(symbol, be, now)
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
        opt = bool(info.get("opt")) or is_option_key(info.get("symbol"))
        price = opt_snap(round(float(price), 4)) if opt else snap(round(float(price), 4), symbol=info.get("symbol"))
        qty = int(info.get("remaining") or info.get("qty") or 0)
        # moving an EXIT (stop, target, close...) is protective: it goes through the reducing gate, which DISARM and
        # the day-loss lock never block (tighten your stop under the lock). An entry is checked like a new order;
        # an option order in real dollars (price x 100 x contracts), like when it was sent
        role = info.get("role") or ""
        if role in self.EXIT_ROLES + self.REDUCING or role.startswith("cash_flow") or (role == "option" and not self._opens(info)):
            reason = self.gate.check_reduce(info.get("action"), qty, price, now)
        else:
            reason = self.gate.check(info.get("action"), qty, price, now, order_type=info.get("type", "LMT"), mult=100 if opt else 1)
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

    def _grow_exits(self, now):
        """You added to a position: its STOP (always) and its TAKE PROFIT (with brackets on) grow to cover every share
        you hold — one stop, one take profit, never a second set. A single price each; pieces at different prices
        (PS60 cash flow, partials) are left as you set them. Only on a settled position (2 s after the last fill)."""
        grown = self.__dict__.setdefault("_grow_t", {})
        for sym in list(self.engine.syms):
            pos = int(self.broker.position(sym))
            if not pos or now - grown.get(sym, -1e9) < 2.0:
                continue
            ft, pt = self.engine.fill_t.get(sym), self.engine.pos_t.get(sym)
            if pt is None or (ft is not None and (pt < ft or now - ft < 2.0)):
                continue
            pend = self.engine._pending(sym)
            if any(o.get("role") == "entry" and o.get("action") == (BUY if pos > 0 else SELL) for o in pend):
                continue                                   # an add still working: wait until it is in
            exit_side = SELL if pos > 0 else BUY
            left = lambda o: int(o.get("remaining") if o.get("remaining") is not None else o.get("qty") or 0)
            for role in (("stop", "target") if self.bracket else ("stop",)):
                grp = [o for o in pend if o.get("role") == role and o.get("action") == exit_side and o.get("order_id") is not None
                       and o.get("status") != "PendingCancel"]
                have = sum(left(o) for o in grp)
                prices = {round(float(o.get("aux") or o.get("lmt") or 0), 4) for o in grp}
                if not grp or have >= abs(pos) or len(prices) != 1:
                    continue
                big = max(grp, key=left)
                try:
                    self.broker.resize(big["order_id"], left(big) + abs(pos) - have, now)
                    grown[sym] = now
                    self._note(now, f"{sym}: {'STOP' if role == 'stop' else 'TAKE PROFIT'} now covers all {abs(pos):,} shares (was {have:,})", True)
                except Exception as exc:
                    self._note(now, f"{sym}: could not grow the {role} to {abs(pos):,} shares: {exc}", False)

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

    # ---- option stops: on the STOCK's price (PS60 levels) or on the option's own price -----------------------

    def set_opt_stop(self, key, price, on="stock", now=None):
        """A stop on a contract you hold. ``on`` "stock": out when the stock trades through ``price`` (a call / short
        put: at or under it; a put / short call: at or over it). "option": out when the contract's own bid (ask on a
        short) reaches ``price``. ``price`` None takes it off (the chart's STOP line, if any, still protects)."""
        with self.lock:
            now = now or time.time()
            if price in (None, ""):
                self.opt_stops.pop(key, None)
                self._note(now, f"{key}: option stop off", True)
                return {"ok": True, "stop": None}
            try:
                price = round(float(price), 4)
            except (TypeError, ValueError):
                return {"ok": False, "reason": "stop price must be a number"}
            p = self.engine.opt_positions.get(key)
            if p is None:
                return {"ok": False, "reason": f"no position in {key}"}
            on = "option" if on == "option" else "stock"
            bull = (p.get("right") == "C") == (p["qty"] > 0)
            ref = self._opt_stop_ref(key, p, on)
            if ref is not None and ((on == "stock" and ((bull and price >= ref) or (not bull and price <= ref))) or
                                    (on == "option" and ((p["qty"] > 0 and price >= ref) or (p["qty"] < 0 and price <= ref)))):
                return {"ok": False, "reason": f"a stop at {price:g} is already through {'the stock' if on == 'stock' else 'the contract'} ({ref:g}) — it would fire at once"}
            self.opt_stops[key] = {"price": price, "on": on, "t": now}
            self.opt_stop_fired.pop(key, None)
            self._note(now, f"{key}: STOP {'when ' + p.get('symbol', '') + ' trades ' + ('under' if bull else 'over') if on == 'stock' else 'when the contract trades'} {price:g}", True)
            return {"ok": True, "stop": dict(self.opt_stops[key])}

    def _opt_stop_ref(self, key, p, on):
        if on == "stock":
            st = self.engine.syms.get(p.get("symbol"))
            return st.price() if st else None
        q = self.engine.opt_quotes.get(key) or {}
        return q.get("bid") if p["qty"] > 0 else q.get("ask")

    def _opt_stop_for(self, key, p):
        """The stop protecting a contract: the one you set, else (SETTINGS, option stop follows the chart) the stock
        chart's STOP line on the side that hurts this contract (under the price for a call, over it for a put)."""
        mine = self.opt_stops.get(key)
        if mine:
            return dict(mine, source="set")
        if not self.cfg.get("option_stop_follows_chart", True):
            return None
        st = self.engine.syms.get(p.get("symbol"))
        if st is None or not st.price():
            return None
        # a call (or a short put) rides the LONG side's STOP line, a put (or a short call) the SHORT side's — the play's
        # own side, or the other side drawn under / over it
        bull = (p.get("right") == "C") == (p["qty"] > 0)
        own_long = st.play.get("side", "long") == "long"
        lines = st.play if bull == own_long else (st.play.get("alt") or {})
        stop = lines.get("stop")
        return {"price": stop, "on": "stock", "source": "chart"} if stop else None

    # ---- OPTIONS from the stock chart: the 2nd entry, STOP and TARGET lines trade the linked contract ----------------
    def set_trade_as(self, symbol, mode, key=None, qty=None, now=None):
        """Which the stock chart's lines trade: "stock" (the shares, as always) or "option": the contract on the
        OPTION CHART (``key``), ``qty`` contracts. The stock's 2nd entry is then never sent as a stock order."""
        from . import options as _o
        with self.lock:
            now = now or time.time()
            symbol = str(symbol).upper()
            st = self.engine.syms.get(symbol)
            if st is None:
                return {"ok": False, "reason": f"{symbol} is not on the desk"}
            if mode == "option":
                try:
                    usym, exp, strike, right = _o.parse_key(str(key or ""))
                except (ValueError, IndexError):
                    return {"ok": False, "reason": "pick a contract first: OPTIONS, click a strike (it charts in the OPTION CHART)"}
                if usym != symbol:
                    return {"ok": False, "reason": f"the contract on the OPTION CHART is {usym}, not {symbol} — pick a {symbol} contract"}
                try:
                    n = max(1, int(qty or 1))
                except (TypeError, ValueError):
                    n = 1
                cur = self.auto.get(symbol)
                if cur is not None:                 # a stock entry already working for these lines: it goes
                    cur["by_desk"] = True
                    self._cancel_unlocked(cur["id"], now)
                    self.auto.pop(symbol, None)
                with self.engine.lock:
                    st.play.update(trade_as="option", opt_key=str(key), opt_qty=n, trade_as_set=True)
                    # the contract sets the direction: a call is the LONG side, a put the SHORT side. A one-sided play
                    # on the other side turns (a two-sided play already has both: the contract rides its own side)
                    want = "long" if right == "C" else "short"
                    if st.play.get("side", "long") != want and not st.play.get("alt"):
                        st.play["side"] = want; st.play["side_set"] = True
                        self._note(now, f"{symbol}: a {'CALL' if right == 'C' else 'PUT'} is the {want.upper()} side — the play is {want.upper()} now", True)
                    self.engine._save_plays()
                self.opt_link[symbol] = {"prev": st.price()}
                self._note(now, f"{symbol}: the chart's 2nd entry, STOP and TARGET now trade {n} {key}", True)
                return {"ok": True, "trade_as": "option", "opt_key": key, "opt_qty": n}
            with self.engine.lock:
                st.play["trade_as"] = "stock"; st.play["trade_as_set"] = True
                st.play.pop("opt_key", None); st.play.pop("opt_qty", None)
                self.engine._save_plays()
            self.opt_link.pop(symbol, None)
            self._note(now, f"{symbol}: the chart's lines trade the STOCK", True)
            return {"ok": True, "trade_as": "stock"}

    def _opt_lines(self, play, right):
        """The lines a contract rides: a call the LONG side's, a put the SHORT side's (the play's own side, or the
        other side drawn on the same chart)."""
        own_long = play.get("side", "long") == "long"
        if (right == "C") == own_long:
            return play, False
        return (play.get("alt") or {}), True

    def _opt_link_tick(self, now):
        """OPTIONS mode. The stock trades UP through the 2nd entry (a call; DOWN through it for a put): BUY the linked
        contract, a limit a step through the ask (fills now, never market). The STOP line is the contract's stop
        (out when the stock trades through it, the option stop). The stock reaches the TARGET: SELL every contract,
        a limit a step through the bid. Flat again after it was held: the 2nd entry, stop and target come off."""
        from . import options as _o
        for play in list(self.engine.plays):
            if play.get("trade_as") != "option" or not play.get("opt_key"):
                continue
            sym, key = play["symbol"], play["opt_key"]
            try:
                usym, exp, strike, right = _o.parse_key(key)
            except (ValueError, IndexError):
                continue
            st = self.engine.syms.get(sym)
            last = st.price() if st else None
            if last is None:
                continue
            s = self.opt_link.setdefault(sym, {})
            prev, s["prev"] = s.get("prev"), last
            lines, alt = self._opt_lines(play, right)
            bull = right == "C"
            pos = self.engine.opt_positions.get(key) or {}
            held = int(pos.get("qty") or 0)
            buying = [o for o in self.engine._pending(key) if o.get("action") == BUY]
            se, tgt = lines.get("second_entry"), lines.get("target")
            s["state"], s["why"] = ("IN" if held > 0 else "SENT" if buying else "WAITING"), ""
            if held > 0:
                s["held"] = True
            # the entry: a real cross of the 2nd entry, the way the contract pays (never chased from the far side)
            if se and held <= 0 and not buying and prev is not None and s.get("sent") != price_key(se):
                crossed = (prev < se <= last) if bull else (prev > se >= last)
                if crossed:
                    s["sent"] = price_key(se)
                    out = self.opt_open(sym, exp, strike, right, BUY, int(play.get("opt_qty") or 1), None, now)
                    if out.get("ok"):
                        s["state"] = "SENT"
                        self._note(now, f"OPTION ENTRY {sym} traded {'up' if bull else 'down'} through {money(se)}: {out['sent']}", True)
                        self.engine.log(sym, f"OPTION ENTRY {out['sent']} ({sym} through {money(se)})", now, kind="level")
                    else:
                        s["why"] = out.get("reason") or "refused"
                        self._note(now, f"OPTION ENTRY {sym} crossed {money(se)} but NOT sent: {s['why']}", False)
            if se and held <= 0 and not buying and s.get("sent") != price_key(se):
                if not (self.gate.can_trade() and self.gate.armed):
                    s["why"] = self.gate.why_not() or "trading is DISARMED — click ARM"
            # the target: the stock got there, every contract goes
            if tgt and held > 0 and s.get("tgt") != price_key(tgt) and ((last >= tgt) if bull else (last <= tgt)):
                s["tgt"] = price_key(tgt)
                out = self.opt_adjust(key, 0, "close", None, now)
                self._note(now, f"OPTION TARGET {sym} reached {money(tgt)}: " + (out.get("sent") or f"close refused — {out.get('reason')}"),
                           bool(out.get("ok")))
                if out.get("ok"):
                    self.engine.log(sym, f"OPTION TARGET {key} out ({sym} {money(tgt)})", now, kind="fill")
            # flat again after holding it: the trade is over, its lines come off (the pivot stays)
            if held <= 0 and s.get("held") and not self.engine._pending(key):
                s["held"] = False
                how = "target hit" if s.get("tgt") else "stopped out" if key in self.opt_stop_fired else f"out of {key}"
                s["sent"] = s["tgt"] = None
                if self.cfg.get("clear_lines_when_flat", True) and any(lines.get(r) is not None for r in ("second_entry", "stop", "target")):
                    self._clear_trade_lines(play, now, alt=alt, how=how)

    def _opt_link_view(self):
        out = {}
        for play in list(self.engine.plays):
            if play.get("trade_as") != "option" or not play.get("opt_key"):
                continue
            s = self.opt_link.get(play["symbol"]) or {}
            held = int((self.engine.opt_positions.get(play["opt_key"]) or {}).get("qty") or 0)
            out[play["symbol"]] = {"key": play["opt_key"], "qty": int(play.get("opt_qty") or 1), "held": held,
                                   "state": "IN" if held > 0 else (s.get("state") or "WAITING"), "why": s.get("why") or ""}
        return out

    def _opt_stop_view(self):
        out = {}
        for key, p in list(self.engine.opt_positions.items()):
            s = self._opt_stop_for(key, p)
            if s:
                out[key] = {"price": s["price"], "on": s["on"], "source": s["source"], "fired": key in self.opt_stop_fired}
        return out

    def _expiry_tick(self, now):
        """EXPIRATION DAY. A contract that expires today: said at the warning time (3:30 New York by default) with what
        happens at the close — a long one in the money is EXERCISED into shares (100 each), a short one can be
        ASSIGNED — and, with SETTINGS, Trading, close expiring options on (default), closed at the touch at the
        close-out time (3:50) so nothing turns into shares overnight."""
        from .ps60 import ny_offset
        from .options import parse_key
        off = ny_offset(now)
        today = time.strftime("%Y%m%d", time.gmtime(now + off))
        hm = time.strftime("%H:%M", time.gmtime(now + off))
        warn_at, close_at = str(self.cfg.get("expiry_warn_at", "15:30")), str(self.cfg.get("expiry_close_at", "15:50"))
        said = self.__dict__.setdefault("_expiry_said", {})
        for key, p in list(self.engine.opt_positions.items()):
            if not p.get("qty") or p.get("expiry") != today:
                continue
            sym, _exp, strike, right = parse_key(key)
            q, long_ = int(abs(p["qty"])), p["qty"] > 0
            st = self.engine.syms.get(sym)
            spot = st.price() if st else None
            itm = spot is not None and ((right == "C" and spot > strike) or (right == "P" and spot < strike))
            if hm >= warn_at and said.get((key, "warn")) != today:
                said[(key, "warn")] = today
                if long_:
                    risk = (f"it is IN the money: at 4:00 it is exercised into {100 * q:,} {sym} shares "
                            f"({'bought' if right == 'C' else 'sold short'} at {strike:g})" if itm else "it is out of the money: it expires worthless at 4:00")
                else:
                    risk = (f"it is IN the money: you can be ASSIGNED {100 * q:,} {sym} shares at {strike:g}" if itm
                            else "short and out of the money: it should expire worthless, assignment is still possible")
                auto = (f" The desk closes it at {close_at} (SETTINGS, Trading, close expiring options)." if self.cfg.get("expiry_auto_close", True)
                        else " Close it yourself before 4:00 if you don't want that.")
                self.engine.desk_alert(sym, "EXPIRES TODAY", f"{key}: {q} contract{'s' if q != 1 else ''} EXPIRE TODAY — {risk}.{auto}",
                                       f"Your {sym} {strike:g} {'calls' if right == 'C' else 'puts'} expire today.", now)
                self._note(now, f"{key}: expires today — {risk}", False)
            if self.cfg.get("expiry_auto_close", True) and hm >= close_at and hm < "16:00" and said.get((key, "close")) != today:
                said[(key, "close")] = today
                out = self.opt_adjust(key, 0, "close", None, now)
                self._note(now, f"EXPIRY CLOSE: {key} — {q} contract{'s' if q != 1 else ''} closed at the touch before the 4:00 expiry"
                                + ("" if out.get("ok") else f" — refused: {out.get('reason')} — CLOSE IT YOURSELF"), bool(out.get("ok")))
                self.engine.desk_alert(sym, "EXPIRY CLOSE", f"{key}: closing {q} before the 4:00 expiry" + ("" if out.get("ok") else " — the close was refused, close it yourself"),
                                       f"Closing your {sym} {strike:g} {'calls' if right == 'C' else 'puts'} before the expiry.", now)

    def _opt_stop_tick(self, now):
        for key, p in list(self.engine.opt_positions.items()):
            if not p.get("qty"):
                continue
            s = self._opt_stop_for(key, p)
            if not s or now - self.opt_stop_fired.get(key, -1e9) < 15.0:
                continue
            if self._opt_working(key, SELL if p["qty"] > 0 else BUY) >= abs(int(p["qty"])):
                continue                          # its close is already working: never a second one on top
            ref = self._opt_stop_ref(key, p, s["on"])
            if ref is None:
                continue
            bull = (p.get("right") == "C") == (p["qty"] > 0)
            hit = ((ref <= s["price"]) if bull else (ref >= s["price"])) if s["on"] == "stock" else \
                  ((ref <= s["price"]) if p["qty"] > 0 else (ref >= s["price"]))
            if not hit:
                continue
            self.opt_stop_fired[key] = now
            out = self.opt_adjust(key, 0, "close", None, now)
            what = f"{p.get('symbol')} traded {ref:g}" if s["on"] == "stock" else f"the contract traded {ref:g}"
            self._note(now, f"OPTION STOP: {key} out — {what}, through your {'chart ' if s['source'] == 'chart' else ''}stop {s['price']:g}"
                            + ("" if out.get("ok") else f" — the close was refused: {out.get('reason')}"), bool(out.get("ok")))
            self.engine.log(p.get("symbol") or key.split(" ")[0], f"OPTION STOP {key} @ {what}", now, kind="fill")
            if out.get("ok"):
                self.opt_stops.pop(key, None)

    def watchdog(self, now=None):
        with self.lock:
            return self._watchdog_unlocked(now)

    def _watchdog_unlocked(self, now=None):
        """Called on every dashboard snapshot: breakeven stops after cash flow; exits never bigger than the
        position; daily-loss lock."""
        try:
            self._breakeven(now or time.time())
        except Exception as exc:                 # one failing step never stops the rest (the loss lock check is last)
            log.warning("breakeven: %s", exc)
        try:
            self._scale_tick(now or time.time())
        except Exception as exc:
            log.warning("scale plan: %s", exc)
        try:
            self._trail_tick(now or time.time())
        except Exception as exc:
            log.warning("trailing stop: %s", exc)
        try:
            self._reverse_stop_tick(now or time.time())
        except Exception as exc:
            log.warning("reverse stop: %s", exc)
        try:
            self._guard_exits(now or time.time())
        except Exception as exc:
            log.warning("exit guard: %s", exc)
        try:
            self._grow_exits(now or time.time())
        except Exception as exc:
            log.warning("exit growth: %s", exc)
        try:
            self._opt_link_tick(now or time.time())
        except Exception as exc:
            log.warning("option lines: %s", exc)
        try:
            self._opt_stop_tick(now or time.time())
        except Exception as exc:
            log.warning("option stop: %s", exc)
        try:
            self._expiry_tick(now or time.time())
        except Exception as exc:
            log.warning("expiry guard: %s", exc)
        try:
            self._auto_entries(now or time.time())
        except Exception as exc:
            log.warning("auto 2nd entry: %s", exc)
        limit = self.cfg["max_daily_loss"]
        # the lock guards a LIVE account; paper / practice only if you switched it on — and never again today once you
        # lifted it by hand (UNLOCK sticks: it does not come straight back half a second later)
        guard = bool(limit) and ((self.gate.mode == "LIVE" and bool(self.cfg.get("allow_live"))) or
                                 (self.gate.mode in ("PAPER", "SIM") and self.cfg.get("loss_limit_on_paper", False) and not self.gate.unlocked_by_hand))
        if self.gate.locked:
            # a loss lock that no longer applies lifts by itself: a paper / practice account (live-only lock), the limit
            # switched off, or raised above today's loss. Never a lock that still holds
            if str(self.gate.locked).startswith("daily loss limit") and (not guard or self.day_pnl()["total"] > -abs(limit)):
                self.gate.unlock()
                self._note(now or time.time(), "Daily loss lock lifted" + ("" if guard else f" — it only guards a LIVE account; this is {self.gate.mode}") + " — click ARM to trade", True)
                return
            self._cancel_entries(now or time.time())   # every run while locked: one that failed or came in late goes too
            return
        if not guard:
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
        return max(min(qty, self._dollar_cap_qty(play)), 0)

    def _dollar_cap_qty(self, play):
        """Most shares the $ cap allows, judged at the price the gate judges: the order's LIMIT (the 2nd entry plus
        the fill cap on a long), never the 2nd entry itself — or a capped order comes out a few dollars over."""
        cap = self.cfg.get("max_dollars_per_order")
        se = play.get("second_entry")
        if not cap or not se:
            return 10 ** 9
        long_ = play.get("side", "long") == "long"
        limit = snap(round(se + (self.auto_slip(se) if long_ else -self.auto_slip(se)), 4), 1 if long_ else -1)
        return int(float(cap) // max(float(limit), float(se)))

    def auto_slip(self, se):
        """How far past the 2nd entry the entry may fill. A stop-limit whose limit is too tight never fills when
        price jumps through the level in one print (5 cents on a $240 stock is one tick of a fast tape): it turns
        into a limit left behind under the market. The limit is a CAP, not the fill: a buy fills at the offer
        the moment the stop triggers, never above this. The bigger of N ticks and a % of the price."""
        ticks = int(self.cfg.get("auto_entry_limit_ticks", 10))
        pct = float(self.cfg.get("auto_entry_max_slip_pct", 0.3))
        return max(ticks * tick_size(se), se * pct / 100.0)

    def _auto_want(self, play, k=None):
        """The auto entry this play calls for now: (order or None, why not, may_place).

        Drawing the 2nd entry puts the entry in at once. The target and the stop join it as you draw them (the entry
        is re-sent with them attached), and it is sized from your risk $ once the stop is there (the ticket size
        until then). Always a STOP-LIMIT: a long fills only when price comes back up through the 2nd entry, a short
        only when it comes back down through it. With price already past the level it waits for price to return."""
        sym = play["symbol"]
        k = k or sym
        if not self.auto_on:
            return None, "AUTO 2ND ENTRY is off on the desk", False
        if play.get("auto") is False:
            return None, "off for this play (cancelled by hand or switched off) — redraw the 2nd entry or switch it on", False
        if not play.get("active", True):
            return None, "play is retired", False
        real = (self.engine.syms.get(sym).play if self.engine.syms.get(sym) else play)
        if real.get("trade_as") == "option" and real.get("opt_key"):
            return None, f"these lines trade the contract {real['opt_key']} (OPTIONS) — no stock order", False
        se, stop, target = play.get("second_entry"), play.get("stop"), play.get("target")
        if not se:
            return None, "draw a 2nd entry on the chart — it goes in as your entry order", False
        long_ = play.get("side", "long") == "long"
        action = BUY if long_ else SELL
        if stop and (stop >= se if long_ else stop <= se):
            return None, f"stop {money(stop)} must be {'under' if long_ else 'over'} the 2nd entry {money(se)} for a {play.get('side', 'long')}", False
        if target and (target <= se if long_ else target >= se):
            return None, f"target {money(target)} must be {'over' if long_ else 'under'} the 2nd entry {money(se)} for a {play.get('side', 'long')}", False
        if not (self.gate.can_trade() and self.gate.armed):
            return None, self.gate.why_not() or "trading is DISARMED — click ARM", False
        if self.auto_done.get(k) == price_key(se):
            return None, f"entered at {money(se)} already — one entry per 2nd entry (redraw it for another)", False
        if stop:
            qty = self.auto_size(play)
            if qty < 1:
                return None, f"${self.risk_dollars:,.0f} risk does not buy one share with the stop {money(abs(se - stop))} away", False
        else:
            qty = min(int(self.default_shares), int(self.cfg["max_shares_per_order"]), self._dollar_cap_qty(play))
        pos = int(self.broker.position(sym))
        if pos:
            return None, f"already {'long' if pos > 0 else 'short'} {abs(pos):,} — the auto entry waits until you are flat", False
        mine = self.auto.get(k)
        # either side's auto entry is ours; anything else working as an entry is a manual one
        auto_ids = {c["id"] for kk, c in self.auto.items() if kk.split("|")[0] == sym}
        others = [o for o in self.engine._pending(sym) if o.get("role") == "entry" and o.get("order_id") not in auto_ids]
        if others:
            return None, "a manual entry is working on this symbol — the auto entry stays out of its way", False
        aux = snap(round(float(se), 4))
        st = self.engine.syms[sym]
        last = st.price()
        bid, ask = st.bbo()
        limit = snap(round(se + (self.auto_slip(se) if long_ else -self.auto_slip(se)), 4), 1 if long_ else -1)
        want = {"type": "STP LMT", "action": action, "aux": aux, "price": limit, "qty": qty,
                "stop": stop and float(stop), "target": target and float(target)}
        # the entry is ONLY price coming back up through the level (down through it, short): always a stop-limit.
        # With the market already past the level a stop-limit would fire at once (a chase), so a new one waits
        # until price is back under it (over it, short); one already working stays and does its job
        ref = (ask if long_ else bid) or last
        through = ref is not None and (ref > se if long_ else ref < se)
        if through and not mine:
            return want, (f"price {money(ref)} is {'above' if long_ else 'below'} the 2nd entry — the entry goes in when price is "
                          f"back {'under' if long_ else 'over'} {money(se)}, and fills when it comes back through"), False
        return want, "", True

    def _auto_arm_on_draw(self, play, now, k=None):
        """The lines are the orders: a 2nd entry DRAWN (or moved) while the desk is disarmed arms it, on a paper or
        practice account only, never when locked for the day. Levels already on the chart at start don't arm it."""
        sym, se = play["symbol"], play.get("second_entry")
        k = k or sym
        key = price_key(se) if se else None
        if k not in self.auto_seen:
            self.auto_seen[k] = key
            return
        if key == self.auto_seen[k]:
            return
        self.auto_seen[k] = key
        if key is None or self.gate.armed or not self.auto_on or play.get("auto") is False:
            return
        if not self.cfg.get("auto_arm_on_second_entry", True) or self.gate.mode not in ("SIM", "PAPER"):
            return
        if self.gate.arm(True):
            self._note(now, f"ARMED by your 2nd entry on {sym} — the entry order is going in", True)
            self.engine.log(sym, "desk ARMED by the 2nd entry you drew", now, kind="level")

    def _ran_past(self, sym, cur):
        last = self.engine.syms[sym].price()
        if last is None:
            return False
        return last > cur["price"] if cur["action"] == BUY else last < cur["price"]

    def _auto_cross_watch(self, play, cur, why, now, k=None):
        """Price through the 2nd entry and no entry filled: say why, once, loud (a missed entry is never silent)."""
        sym, se = play["symbol"], play.get("second_entry")
        k = k or sym
        if not se:
            self.auto_side.pop(k, None)
            return
        last = self.engine.syms[sym].price()
        if last is None:
            return
        long_ = play.get("side", "long") == "long"
        beyond = last > se if long_ else last < se
        was = self.auto_side.get(k)
        self.auto_side[k] = beyond
        if not beyond or was is not False:
            return                                     # only the moment price crosses the level
        if self.auto_done.get(k) == price_key(se) or self.broker.position(sym):
            return
        if cur is not None:
            return                                     # a working entry: its fill (or not) is reported below
        msg = f"{sym} went through your 2nd entry {money(se)} — NO ENTRY: {why or 'no order was working'}"
        self._note(now, msg, False)
        self.engine.log(sym, msg, now, kind="level")

    def _clear_trade_lines(self, play, now, alt=False, how=None):
        """The trade is over (stopped out, target hit, flattened): its 2nd entry, stop and target come off the
        chart, so the board is clean for the next one. The pivot stays."""
        sym = play["symbol"]
        last = self.engine.syms[sym].price()
        lines = (play.get("alt") or {}) if alt else play
        stop, target = lines.get("stop"), lines.get("target")
        how = how or ("stopped out" if stop and last is not None and abs(last - stop) <= abs(last - (target or 0)) else
                      "target hit" if target and last is not None else "flat")
        for role in ("second_entry", "stop", "target"):
            if lines.get(role) is not None:
                self.engine.set_play_level(sym, role, None, now, source="trade over", alt=alt)
        self.auto_seen[sym + "|alt" if alt else sym] = None      # clearing is not a new drawing
        self._note(now, f"{sym}: {how} — the 2nd entry, stop and target are off the chart", True)
        self.engine.log(sym, f"trade over ({how}) — 2nd entry, stop and target cleared", now, kind="level")

    def _auto_protect(self, play, now):
        """After the auto entry fills, the stop and target lines are the position's exits: draw one and it goes in,
        move it and the working order moves with it. Clearing a line leaves its order working (said once) —
        a stop never disappears because a line was removed."""
        sym = play["symbol"]
        s = self.auto_sync.get(sym)
        if not s:
            return
        pos = int(self.broker.position(sym))
        long_ = s["action"] == BUY
        if pos and (pos > 0) == long_:
            s["held"] = True
        if not pos or (pos > 0) != long_:
            if now - s["t"] > 5.0:                    # the position report can trail the fill; flat for real: done
                self.auto_sync.pop(sym, None)
                if s.get("held") and not s.get("manual") and self.cfg.get("clear_lines_when_flat", True):
                    self._clear_trade_lines(play, now, alt=bool(s.get("alt")))
            return
        exit_action = SELL if long_ else BUY
        last = self.engine.syms[sym].price()
        pend = [o for o in self.engine._pending(sym) if o.get("action") == exit_action and o.get("order_id") is not None]
        lines = (play.get("alt") or {}) if s.get("alt") else play
        closing = any(o.get("role") in self.REDUCING for o in pend) or self.engine.recently_filled(sym, self.REDUCING, now)
        for role in ("stop", "target"):
            want = lines.get(role)
            if want == s.get(role):
                # the STOP line is on the chart but its order is gone (cancel all, a cancel in TWS): it goes back in.
                # Never while the position is being closed (a stop on top of a flatten could open the other way)
                if not (role == "stop" and want is not None and not closing
                        and not any(o.get("role") == "stop" and o.get("status") != "PendingCancel" for o in pend)):
                    continue
                self._note(now, f"{sym}: the STOP line {money(want)} had no order working — it goes back in", False)
            if want is None:
                self._note(now, f"{sym}: {role} line cleared — the {role} order stays working (cancel it from the orders list)", True)
                s[role] = None
                continue
            want = snap(round(float(want), 4))
            wrong = last is not None and ((role == "stop" and (want >= last if long_ else want <= last)) or
                                          (role == "target" and (want <= last if long_ else want >= last)))
            if wrong:
                if s.get("warned_" + role) != want:
                    s["warned_" + role] = want
                    self._note(now, f"{sym}: {role} {money(want)} is already through the price {money(last)} — not sent "
                                    f"(it would fill at once). Move the line", False)
                continue
            mine = [o for o in pend if o.get("role") == role and o.get("status") != "PendingCancel"]
            try:
                if mine:
                    for o in mine:
                        self.broker.modify(o["order_id"], want, now)
                    self._note(now, f"{sym}: {role} order moved to {money(want)} with the line", True)
                elif role == "stop":
                    tk = tick_size(want)
                    lmt = snap(want - tk * self.cfg["stop_limit_ticks"], -1) if long_ else snap(want + tk * self.cfg["stop_limit_ticks"], +1)
                    self.broker.place(sym, exit_action, abs(pos), lmt, now, "STP LMT", None, "stop", "DAY", aux=want,
                                      oca=f"auto-{sym}-{int(s['t'])}", reducing=True)
                    self._note(now, f"{sym}: STOP order in at {money(want)} for {abs(pos):,} shares", True)
                else:
                    self.broker.place(sym, exit_action, abs(pos), want, now, "LMT", None, "target", "DAY",
                                      oca=f"auto-{sym}-{int(s['t'])}", reducing=True)
                    self._note(now, f"{sym}: TARGET order in at {money(want)} for {abs(pos):,} shares", True)
                s[role] = want
                self.engine.log(sym, f"{role.upper()} order {money(want)} ({abs(pos):,} sh)", now, kind="level")
            except Exception as exc:
                self._note(now, f"{sym}: {role} order failed: {exc}", False)
        # the STOP grows with the position: add shares and the stop covers them too (one stop price on the line)
        if s.get("stop") is not None:
            left = lambda o: int(o.get("remaining") if o.get("remaining") is not None else o.get("qty") or 0)
            stops = [o for o in self.engine._pending(sym) if o.get("action") == exit_action and o.get("order_id") is not None
                     and o.get("role") == "stop" and o.get("status") != "PendingCancel"]
            have = sum(left(o) for o in stops)
            prices = {round(float(o.get("aux") or o.get("lmt") or 0), 4) for o in stops}
            if stops and have < abs(pos) and len(prices) == 1 and now - s.get("grow_t", 0) > 2.0:
                s["grow_t"] = now
                big = max(stops, key=left)
                try:
                    self.broker.resize(big["order_id"], left(big) + abs(pos) - have, now)
                    self._note(now, f"{sym}: STOP now covers all {abs(pos):,} shares (was {have:,})", True)
                except Exception as exc:
                    self._note(now, f"{sym}: could not grow the stop to {abs(pos):,} shares: {exc}", False)

    def _auto_entries(self, now):
        for play in list(self.engine.plays):
            try:
                self._auto_one(play, now)
            except Exception as exc:
                log.warning("auto 2nd entry %s: %s", play.get("symbol"), exc)
            try:
                alt = play.get("alt") or {}
                if alt.get("second_entry") or self.auto.get(play["symbol"] + "|alt") is not None:
                    self._auto_one(self._alt_view(play), now, play["symbol"] + "|alt", alt)
            except Exception as exc:
                log.warning("auto 2nd entry (other side) %s: %s", play.get("symbol"), exc)
            try:
                self._lines_are_exits(play, now)
            except Exception as exc:
                log.warning("chart exits %s: %s", play.get("symbol"), exc)

    # ---- STOP and TRAIL from the ticket: they set the STOP line; the line is the stop order (_lines_are_exits) --------
    def set_stop(self, symbol, price, now=None):
        """A stop for the position at ``price``: below the market for a long, above it for a short. The STOP line is
        set and the stop order follows it (placed, or moved if one is working)."""
        with self.lock:
            now = now or time.time()
            pos = int(self.broker.position(symbol))
            if not pos:
                return {"ok": False, "reason": "no position to protect"}
            try:
                price = float(price)
            except (TypeError, ValueError):
                return {"ok": False, "reason": "stop price must be a number"}
            st = self.engine.syms.get(symbol)
            last = st.price() if st else None
            price = snap(price, -1 if pos > 0 else +1, symbol)
            if last is not None and ((pos > 0 and price >= last) or (pos < 0 and price <= last)):
                return {"ok": False, "reason": f"a stop at {money(price)} is through the price {money(last)} — it would fill at once. "
                                               f"Use CLOSE to get out now"}
            alt = bool(st and st.play.get("alt") and ("long" if pos > 0 else "short") != st.play.get("side", "long"))
            self.engine.set_play_level(symbol, "stop", price, now, source="ticket", alt=alt)
            self._note(now, f"{symbol}: STOP set {money(price)} for {abs(pos):,} sh", True)
            return {"ok": True, "stop": price, "sent": f"STOP {money(price)} on {abs(pos):,} {symbol}"}

    def set_trail(self, symbol, dollars, on=True, now=None):
        """Trail the stop ``dollars`` behind the best price since you turned it on: it only ever moves in your favour."""
        with self.lock:
            now = now or time.time()
            if not on:
                self.trails.pop(symbol, None)
                self._note(now, f"{symbol}: trail off (the stop stays where it is)", True)
                return {"ok": True, "trail": None}
            pos = int(self.broker.position(symbol))
            if not pos:
                return {"ok": False, "reason": "no position to trail"}
            try:
                d = float(dollars)
            except (TypeError, ValueError):
                return {"ok": False, "reason": "trail distance must be a number"}
            if d <= 0:
                return {"ok": False, "reason": "trail distance must be above 0"}
            st = self.engine.syms.get(symbol)
            last = st.price() if st else None
            if last is None:
                return {"ok": False, "reason": "no price yet"}
            self.trails[symbol] = {"dist": round(d, 4), "best": last, "side": "long" if pos > 0 else "short", "t": now}
            self._note(now, f"{symbol}: TRAIL ${d:.2f} behind the best price, from {money(last)}", True)
            self._trail_tick(now)
            return {"ok": True, "trail": dict(self.trails[symbol])}

    def _trail_tick(self, now):
        for symbol, tr in list(self.trails.items()):
            pos = int(self.broker.position(symbol))
            if not pos or ("long" if pos > 0 else "short") != tr["side"]:
                self.trails.pop(symbol, None)
                continue
            st = self.engine.syms.get(symbol)
            last = st.price() if st else None
            if last is None:
                continue
            long_ = pos > 0
            tr["best"] = max(tr["best"], last) if long_ else min(tr["best"], last)
            want = snap(tr["best"] - tr["dist"] if long_ else tr["best"] + tr["dist"], -1 if long_ else +1, symbol)
            alt = bool(st.play.get("alt")) and ("long" if long_ else "short") != st.play.get("side", "long")
            cur = self._side_levels(st.play, alt=alt).get("stop")
            tk = tick_size(want, symbol)
            better = cur is None or (want > cur + tk / 2 if long_ else want < cur - tk / 2)
            through = (want >= last) if long_ else (want <= last)
            if better and not through:
                self.engine.set_play_level(symbol, "stop", want, now, source="trail", alt=alt)
                tr["stop"] = want

    @staticmethod
    def _alt_view(play):
        """The OTHER SIDE of a play as a play of its own: the opposite side, its own pivot / 2nd entry / stop / target."""
        alt = play.get("alt") or {}
        return {"symbol": play["symbol"], "side": "short" if play.get("side", "long") == "long" else "long",
                "trigger": alt.get("trigger"), "second_entry": alt.get("second_entry"), "stop": alt.get("stop"),
                "target": alt.get("target"), "auto": alt.get("auto", True), "active": play.get("active", True)}

    def _side_levels(self, play, pos=None, alt=None):
        """The stop / target lines of the side you are in: the play's own, or its OTHER SIDE's."""
        if alt is None:
            alt = bool(pos) and play.get("alt") and (("long" if pos > 0 else "short") != play.get("side", "long"))
        return (play.get("alt") or {}) if alt else play

    def _stops_moved_by_desk(self, symbol):
        return any(f.get("symbol") == symbol and f.get("be_done") for f in getattr(self, "families", {}).values())

    def _stop_line_follows(self, symbol, price, now):
        """The desk moved the stop order itself (breakeven): the STOP line on the chart moves with it, so the line
        never pulls the order back to where it was."""
        try:
            if symbol in self.auto_sync:
                self.auto_sync[symbol]["stop"] = snap(round(float(price), 4))
            st = self.engine.syms.get(symbol)
            pos = int(self.broker.position(symbol))
            alt = bool(st and pos and st.play.get("alt") and ("long" if pos > 0 else "short") != st.play.get("side", "long"))
            self.engine.set_play_level(symbol, "stop", price, now, source="breakeven", alt=alt)
        except Exception as exc:
            log.warning("stop line follow %s: %s", symbol, exc)

    def _lines_are_exits(self, play, now):
        """CHART TRADING for every position, however it was opened (ticket, ladder, chart, auto): the STOP and TARGET
        lines on the chart are the position's exit orders. Draw a stop and a stop order goes in for the shares you
        hold; drag it and the order moves with it. Existing exits are adopted at their prices, so nothing is
        re-sent for a line that already matches."""
        if not self.cfg.get("lines_are_exits", True):
            return
        sym = play["symbol"]
        if sym in self.auto_sync:
            self._auto_protect(play, now)
            return
        pos = int(self.broker.position(sym))
        lines = self._side_levels(play, pos)
        if not pos or not (lines.get("stop") or lines.get("target")):
            return
        exit_action = SELL if pos > 0 else BUY
        pend = [o for o in self.engine._pending(sym) if o.get("action") == exit_action and o.get("status") != "PendingCancel"]
        # exits already working are adopted as they are: a bracket stop, or a target split into cash-flow / runner
        # pieces (PS60 exits) covers that line, so only a line with no order behind it sends one
        stops = [o for o in pend if o.get("role") == "stop"]
        tgts = [o for o in pend if o.get("role") == "target" or str(o.get("role") or "").startswith(("cash_flow", "runner"))]
        have_stop = (stops[0].get("aux") or stops[0].get("lmt")) if stops else None
        have_tgt = (next((o.get("lmt") for o in tgts if o.get("role") == "target"), None) or lines.get("target")) if tgts else None
        if stops and lines.get("stop") and len({round(float(o.get("aux") or o.get("lmt") or 0), 4) for o in stops}) > 1:
            have_stop = lines.get("stop")       # several stop pieces at different prices: leave them to the ladder
        if have_stop is not None and lines.get("stop") and abs(float(have_stop) - float(lines["stop"])) > 1e-6 and len(stops) and \
                self._stops_moved_by_desk(sym):
            self._stop_line_follows(sym, have_stop, now)
        self.auto_sync[sym] = {"stop": have_stop, "target": have_tgt, "action": BUY if pos > 0 else SELL, "t": now,
                               "held": True, "manual": True, "alt": lines is not play}
        self._auto_protect(play, now)

    def _auto_one(self, play, now, k=None, real=None):
        """``play`` is a side of a play: the play itself, or its OTHER SIDE (k = "SYM|alt", real = play["alt"]).
        Each side has its own entry order; whichever fills first, the other is cancelled (it waits until flat)."""
        sym = play["symbol"]
        k = k or sym
        real = real if real is not None else play
        cur = self.auto.get(k)
        o = None
        if cur is not None:
            o = self._order_by_id(cur["id"])
            status = (o or {}).get("status")
            if status == "Filled" or (o and o.get("remaining") == 0 and (o.get("filled") or 0) > 0):
                self.auto_done[k] = price_key(cur["aux"])
                self.auto.pop(k, None)
                # from here the lines ARE the exits: a stop or target drawn (or moved) later goes to the broker
                self.auto_sync[sym] = {"stop": cur["stop"], "target": cur["target"], "action": cur["action"], "t": now,
                                       "alt": k != sym}
                if k != sym:
                    self._note(now, f"{sym}: the OTHER SIDE's 2nd entry filled — the first side's entry is cancelled", True)
                self.auto_done_t[k] = now
                self._note(now, f"AUTO 2ND ENTRY FILLED {sym}: {cur['action']} {cur['qty']} through {money(cur['aux'])} — "
                                f"stop {money(cur['stop'])} and target {money(cur['target'])} are working", True)
                self.engine.log(sym, f"AUTO 2ND ENTRY filled {cur['action']} {cur['qty']} @ {money(cur['aux'])}", now, kind="level")
                cur = None
            elif o is not None and not cur.get("left_said") and self._ran_past(sym, cur):
                # the stop triggered but price ran past the cap: it is a limit waiting under the market now
                # (judged by price: IBKR keeps calling a triggered stop-limit "STP LMT")
                cur["left_said"] = True
                self._note(now, f"AUTO 2ND ENTRY {sym} TRIGGERED at {money(cur['aux'])} but price ran past your cap "
                                f"{money(cur['price'])} — not filled; it fills if price comes back to {money(cur['price'])}. "
                                f"Widen 'auto entry max slip %' in SETTINGS → Trading", False)
            if cur is not None and o is not None and status in self.engine.DONE_STATUSES + ("Done",) and status != "Filled":
                # gone without a fill: cancelled by hand (from the ticket, TWS) or rejected. Not re-sent until the
                # 2nd entry is drawn again or the play's switch is put back on
                self.auto.pop(k, None)
                if not cur.get("by_desk"):
                    with self.engine.lock:
                        real["auto"] = False
                        self.engine._save_plays()
                    self._note(now, f"AUTO 2ND ENTRY {sym} off: its order was {status.lower()} outside the desk — "
                                    f"redraw the 2nd entry (or switch AUTO on in PLAY SETUP) to arm it again", False)
                cur = None
        if cur is not None and o is not None and (o.get("filled") or 0) > 0 and \
                o.get("status") not in self.engine.DONE_STATUSES + ("Done",):
            # part-filled (IBKR fills in pieces): the rest stays working for the full size. Never cancelled
            # because "you already hold shares" — those shares ARE this entry
            self.auto_why[k] = ""
            cur["partial"] = int(o.get("filled") or 0)
            return
        self._auto_arm_on_draw(play, now, k)
        want, why, may_place = self._auto_want(play, k)
        self._auto_cross_watch(play, cur, why, now, k)
        if want is None:
            if cur is not None:
                cur["by_desk"] = True
                self._cancel_unlocked(cur["id"], now)
                self.auto.pop(k, None)
                self._note(now, f"AUTO 2ND ENTRY {sym} cancelled: {why}", True)
            self.auto_why[k] = why
            if k == sym:
                self._auto_protect(play, now)
            return
        if cur is not None:
            same = all(cur.get(k) == want[k] for k in ("type", "action", "aux", "price", "qty"))
            if same and cur.get("stop") == want["stop"] and cur.get("target") == want["target"]:
                self.auto_why[k] = ""
                return
            cur["by_desk"] = True
            self._cancel_unlocked(cur["id"], now)
            self.auto.pop(k, None)
            self._note(now, f"AUTO 2ND ENTRY {sym} re-sent: the play's levels moved", True)
            cur = None
        if not may_place:
            self.auto_why[k] = why
            return
        key = (want["type"], price_key(want["aux"]), want["qty"],
               want["stop"] and price_key(want["stop"]), want["target"] and price_key(want["target"]))
        f = self.auto_fail.get(k)
        if f and f[0] == key and now - f[1] < self.AUTO_RETRY_SECONDS:
            self.auto_why[k] = f[2]
            return
        out = self._submit_unlocked(sym, want["action"], want["price"], want["qty"], now, True, want["type"],
                                    want["aux"] if want["type"] == "STP LMT" else None, "DAY",
                                    levels=play if k != sym else None)
        if out.get("ok"):
            self.auto[k] = dict(want, id=out["id"], t=now, by_desk=False)
            self.auto_fail.pop(k, None)
            self.auto_why[k] = ""
            how = (f"STOP-LIMIT through {money(want['aux'])} (limit {money(want['price'])})" if want["type"] == "STP LMT"
                   else f"LIMIT at {money(want['aux'])}")
            legs = " · ".join(x for x in (f"stop {money(want['stop'])}" if want["stop"] else "",
                                          f"target {money(want['target'])}" if want["target"] else "") if x)
            self.engine.log(sym, f"ENTRY ORDER in: {want['action']} {want['qty']} {how}" + (f" · {legs}" if legs else
                                 " · draw the target and stop, they join it"), now, kind="level")
        else:
            reason = out.get("reason") or "refused"
            self.auto_fail[k] = (key, now, reason)
            self.auto_why[k] = reason

    def auto_status(self):
        """Per play (and per OTHER SIDE, key "SYM|alt"): is the auto entry on, working, waiting, done."""
        out = {}
        for play0 in list(self.engine.plays):
            sides = [(play0["symbol"], play0)]
            if (play0.get("alt") or {}).get("second_entry") or self.auto.get(play0["symbol"] + "|alt") is not None:
                sides.append((play0["symbol"] + "|alt", self._alt_view(play0)))
            for k, play in sides:
                sym = play["symbol"]
                on = self.auto_on and play.get("auto") is not False
                cur = self.auto.get(k)
                se = play.get("second_entry")
                if cur is not None:
                    how = "comes back through"
                    legs = " · ".join(x for x in (f"stop {money(cur['stop'])}" if cur.get("stop") else "draw the stop",
                                                  f"target {money(cur['target'])}" if cur.get("target") else "draw the target") if x)
                    state = "PARTIAL" if cur.get("partial") else "TRIGGERED" if self._ran_past(sym, cur) else "WORKING"
                    text0 = (f"price ran past your cap {money(cur['price'])} — not filled; fills if price comes back to it · "
                             if state == "TRIGGERED" else
                             f"{cur['partial']:,} of {cur['qty']:,} filled, the rest is working · " if state == "PARTIAL" else "")
                    text = text0 + (f"{cur['action']} {cur['qty']:,} {cur.get('type', 'STP LMT')} fills when price {how} "
                                    f"{money(cur['aux'])} (cap {money(cur['price'])}) · {legs}")
                elif se and self.auto_done.get(k) == price_key(se):
                    state, text = "DONE", f"entered at {money(se)} — the stop and target are running the trade"
                elif not on:
                    state, text = "OFF", self.auto_why.get(k) or "off"
                else:
                    state, text = "WAITING", self.auto_why.get(k) or "waiting"
                out[k] = {"on": on, "state": state, "text": text, "qty": cur["qty"] if cur else self.auto_size(play),
                          "id": cur["id"] if cur else None, "filled_t": self.auto_done_t.get(k) if state == "DONE" else None,
                          "side": play.get("side")}
        return out

    def _opens(self, o):
        """Does this working order OPEN (or add to) a position? Stock entries and reverses do; an option order does
        when it buys with no short (or sells with no long) on that contract."""
        r = o.get("role")
        if r in ("entry", "reverse"):
            return True
        if r == "option":
            q = int((self.engine.opt_positions.get(o.get("symbol")) or {}).get("qty") or 0)
            return (o.get("action") == BUY and q >= 0) or (o.get("action") == SELL and q <= 0)
        return False

    def _cancel_entries(self, now):
        # the day-loss lock: everything that would OPEN risk goes (stock entries, reverses, option opens); exits stay
        for o in self.engine._pending():
            if self._opens(o) and o.get("order_id") is not None and o.get("status") != "PendingCancel":
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
                # breakeven is where you actually got in (the entry's fill, else your average cost), never the
                # entry's limit cap; and never a stop through the market (it would fire at once and dump the runner)
                sym = fam["symbol"]
                be = (self.broker.order_info(pid) or {}).get("avg_fill") or self._avg_cost(sym) or fam["entry"]
                be = snap(round(float(be), 4), symbol=sym)
                pos = int(self.broker.position(sym))
                st_ = self.engine.syms.get(sym)
                bid, ask = st_.bbo() if st_ else (None, None)
                if pos and ((pos > 0 and bid is not None and be >= bid) or (pos < 0 and ask is not None and be <= ask)):
                    continue                                   # not yet: price is not past breakeven; try again next tick
                fam["be_done"] = True
                try:
                    moved = [sid for sid in live if self.broker.modify(sid, be, now)]
                    if moved:
                        self._note(now, f"{sym}: cash flow taken — stop moved to breakeven {money(be)}", True)
                        self._stop_line_follows(sym, be, now)
                except Exception as exc:
                    self._note(now, f"{fam['symbol']}: could not move the stop to breakeven: {exc}", False)

    def bracket_templates(self):
        return dict(self.cfg.get("bracket_templates") or {})

    def set_bracket_template(self, name):
        name = str(name or "PLAY").upper()
        if name != "PLAY" and name not in self.bracket_templates():
            return {"ok": False, "reason": f"no bracket template {name}"}
        with self.lock:
            self.bracket_template = name
        return {"ok": True, "template": name}

    def cancel_side(self, symbol, side, now=None):
        """Cancel this desk's working BUY (side 'bid') or SELL (side 'ask') orders on a symbol."""
        now = now or time.time()
        want = BUY if side in ("bid", "buy", BUY) else SELL
        n = 0
        for o in self.engine._pending(symbol):
            if o.get("mine") and o.get("order_id") is not None and o.get("action") == want and o.get("status") != "PendingCancel":
                try:
                    if self.broker.cancel(o["order_id"], now):
                        n += 1
                except Exception as exc:
                    log.warning("cancel %s: %s", o.get("order_id"), exc)
        self._note(now, f"{symbol}: cancelled {n} {want} order{'s' if n != 1 else ''}", True)
        return {"ok": True, "cancelled": n}

    def reverse(self, symbol, now=None):
        """LONG 500 -> SHORT 500 (or the other way): close the position (the flatten path: never blocked) and send
        the opposite entry for the same size as a marketable limit. Two orders, both reported; the resulting
        position is whatever the broker then says it is (the POSITIONS pane shows the truth, not this call)."""
        with self.lock:
            now = now or time.time()
            pos = int(self.broker.position(symbol))
            if not pos:
                self._note(now, f"{symbol}: flat, nothing to reverse", False)
                return {"ok": False, "reason": "flat — nothing to reverse"}
            if not (self.gate.can_trade() and self.gate.armed):
                return {"ok": False, "reason": self.gate.why_not() or "disarmed: a reverse opens a new position"}
            st = self.engine.syms.get(symbol)
            bid, ask = st.bbo() if st else (None, None)
            if bid is None or ask is None:
                return {"ok": False, "reason": "no quote"}
            qty = abs(pos)
            tk = tick_size(ask, symbol)
            slip = self.cfg["flatten_slip_ticks"] * tk
            action = SELL if pos > 0 else BUY
            price = snap(ask + slip, +1, symbol) if action == BUY else snap(bid - slip, -1, symbol)
            reason = self.gate.check(action, qty, price, now, "LMT")
            if reason:
                self._note(now, f"BLOCKED reverse {symbol}: {reason}", False)
                return {"ok": False, "reason": reason}
            flat = self._flatten_unlocked(symbol, now)
            if not flat.get("ok"):
                return {"ok": False, "reason": "flatten failed: " + str(flat.get("reason"))}
            try:
                oid = self.broker.place(symbol, action, qty, price, now, "LMT", None, "reverse", "DAY")
            except Exception as exc:
                self._note(now, f"FAILED reverse entry {action} {qty} {symbol}: {exc} — the flatten is still working", False)
                return {"ok": False, "reason": str(exc), "flatten": flat}
            # the new position is never left without a stop: your other side's stop if it is on the right side, else
            # trading.auto_stop_dollars ($1) the right way; it goes in the moment the new position shows (watchdog)
            play = self.engine.syms[symbol].play if symbol in self.engine.syms else {}
            new_long = action == BUY
            alt = play.get("alt") or {}
            d = float(self.cfg.get("auto_stop_dollars") or 1.0)
            cand = [x for x in (alt.get("stop"), play.get("stop")) if x and ((x < price) if new_long else (x > price))]
            stop_px = cand[0] if cand else snap(price - d if new_long else price + d, -1 if new_long else 1, symbol)
            self.__dict__.setdefault("reverse_stop", {})[symbol] = {"long": new_long, "stop": stop_px, "t": now}
            self._note(now, f"SENT REVERSE {action} {qty} {symbol} @ {money(price)} (after the flatten) · its stop {money(stop_px)} goes in when it fills", True)
            self.engine._rec({"ev": "reverse", "t": now, "sym": symbol, "from": pos, "action": action, "qty": qty, "px": price, "id": oid})
            return {"ok": True, "id": oid, "flatten": flat, "sent": f"{action} {qty} {symbol} @ {money(price)} (reverse)"}

    def _reverse_stop_tick(self, now):
        """A REVERSE's new position gets its stop the moment it shows (sized to what is held)."""
        for sym, r in list(getattr(self, "reverse_stop", {}).items()):
            pos = int(self.broker.position(sym))
            if now - r["t"] > 120:
                del self.reverse_stop[sym]
                if pos and (pos > 0) == r["long"]:
                    self._note(now, f"{sym}: could not put the reverse's stop in — put a stop on it", False)
                continue
            if not pos or (pos > 0) != r["long"]:
                continue                                   # the reverse has not filled yet
            exit_action = SELL if r["long"] else BUY
            if any(o.get("role") == "stop" and o.get("action") == exit_action and o.get("status") != "PendingCancel"
                   for o in self.engine._pending(sym)):
                del self.reverse_stop[sym]
                continue
            last = self.engine.syms[sym].price() if sym in self.engine.syms else None
            stop = r["stop"]
            if last is not None and ((stop >= last) if r["long"] else (stop <= last)):
                d = float(self.cfg.get("auto_stop_dollars") or 1.0)
                stop = snap(last - d if r["long"] else last + d, -1 if r["long"] else 1, sym)
            tk = tick_size(stop, sym)
            lmt = snap(stop - tk * self.cfg["stop_limit_ticks"], -1, sym) if r["long"] else snap(stop + tk * self.cfg["stop_limit_ticks"], +1, sym)
            try:
                self.broker.place(sym, exit_action, abs(pos), lmt, now, "STP LMT", None, "stop", "DAY", aux=stop, reducing=True)
                self._note(now, f"{sym}: reverse filled — STOP in at {money(stop)} for {abs(pos):,} shares", True)
            except Exception as exc:
                self._note(now, f"{sym}: the reverse's stop failed: {exc}", False)
            del self.reverse_stop[sym]

    def _sell_to_open_why(self, symbol, right, key, short_new):
        """None when this many contracts may be SOLD TO OPEN (written). Off by default (SETTINGS, Trading, Allow
        selling to open). Covered calls are always allowed: calls sold against 100 shares each that you hold and
        that no other short call already covers."""
        if short_new <= 0 or self.cfg.get("allow_sell_to_open", False):
            return None
        if right == "C":
            shares = int(self.broker.position(symbol))
            short_calls = sum(-int(p["qty"]) for k, p in self.engine.opt_positions.items()
                              if p.get("symbol") == symbol and p.get("right") == "C" and p["qty"] < 0 and k != key)
            short_calls += max(0, -int((self.engine.opt_positions.get(key) or {}).get("qty") or 0))
            if shares >= 100 * (short_calls + short_new):
                return None                                # covered: you own the shares
            return (f"selling {short_new} call{'s' if short_new != 1 else ''} to open would leave you SHORT calls not covered by "
                    f"{symbol} shares (you hold {shares:,}; covering takes {100 * (short_calls + short_new):,}). Selling to "
                    f"open is off — SETTINGS, Trading, Allow selling to open")
        return (f"selling {short_new} put{'s' if short_new != 1 else ''} to open would leave you SHORT puts. Selling to open is "
                f"off — SETTINGS, Trading, Allow selling to open")

    def opt_open(self, symbol, expiry, strike, right, action, contracts, price=None, now=None):
        """Open (or add to) an option position from the chain: BUY or SELL ``contracts`` of the picked contract,
        LIMIT DAY, at the touch (ask to buy, bid to sell) or at your price. Goes through the trading gate in real
        dollars (price × multiplier × contracts); never market, never blind: no quote and no price = no order."""
        from . import options as _o
        with self.lock:
            now = now or time.time()
            symbol = str(symbol).upper()
            if not (self.gate.can_trade() and self.gate.armed):
                return {"ok": False, "reason": self.gate.why_not() or "disarmed"}
            try:
                n = int(contracts)
                strike = float(strike)
            except (TypeError, ValueError):
                return {"ok": False, "reason": "contracts and strike must be numbers"}
            if n <= 0:
                return {"ok": False, "reason": "how many contracts?"}
            right = "P" if str(right).upper().startswith("P") else "C"
            action = BUY if str(action).upper() == BUY else SELL
            key = _o.key_of(symbol, expiry, strike, right)
            ch = self.engine.opt_chain.get(symbol) or {}
            if expiry not in (ch.get("expiries") or []):
                return {"ok": False, "reason": f"{expiry} is not an expiry on the {symbol} chain"}
            mult = float(ch.get("mult") or 100)
            q = self.engine.opt_quotes.get(key) or {}
            if not (q.get("bid") or q.get("ask")) and self.engine.practice_quote_key(key, now):
                q = self.engine.opt_quotes.get(key) or {}          # practice: any contract is priced from the stock
            if price in (None, ""):
                price = q.get("ask") if action == BUY else q.get("bid")
                if not price:
                    return {"ok": False, "reason": f"no quote on {key} yet — type a price"}
                price = opt_through(price, action)   # fills now: a step through the touch, never further
            else:
                price = opt_snap(float(price))
            price = round(float(price), 2)
            if price <= 0:
                return {"ok": False, "reason": "price must be positive"}
            held = int((self.engine.opt_positions.get(key) or {}).get("qty") or 0)
            # sells already working on this contract count: two SELL 2s on 2 calls held would leave you short 2
            short_new = max(0, n + self._opt_working(key, SELL) - max(0, held)) if action == SELL else 0
            why = self._sell_to_open_why(symbol, right, key, short_new)
            if why:
                self._note(now, f"BLOCKED SELL {n} {key}: {why}", False)
                return {"ok": False, "reason": why}
            reason = self.gate.check(action, n, price, now, "LMT", mult=mult)
            if reason:
                self._note(now, f"BLOCKED {action} {n} {key} @ {money(price)}: {reason}", False)
                return {"ok": False, "reason": reason}
            broker = self.broker
            if isinstance(broker, IbkrBroker) and key not in broker.session.opt_contracts:
                from .ibkr import make_option_contract
                broker.session.opt_contract(key, make_option_contract(symbol, expiry, strike, right, mult))
            try:
                oid = broker.place_option(key, action, n, price, now, reducing=False)
            except Exception as exc:
                self._note(now, f"FAILED {action} {n} {key} @ {money(price)}: {exc}", False)
                return {"ok": False, "reason": str(exc)}
            self._note(now, f"SENT {action} {n} {key} @ {money(price)} (${n * price * mult:,.0f})", True)
            self.engine._rec({"ev": "order", "t": now, "sym": key, "action": action, "qty": n, "px": price, "type": "LMT",
                              "aux": None, "tif": "DAY", "legs": [], "id": oid, "role": "option"})
            return {"ok": True, "id": oid, "key": key, "sent": f"{action} {n} {key} @ {money(price)}"}

    def _opt_working(self, key, action):
        """Contracts of ``key`` already working on this side (orders not being cancelled)."""
        return int(sum((o.get("remaining") if o.get("remaining") is not None else o.get("qty") or 0)
                       for o in self.engine._pending(key)
                       if o.get("action") == action and o.get("order_id") is not None and o.get("status") != "PendingCancel"))

    def opt_adjust(self, key, contracts, mode, price=None, now=None):
        """Scale an OPTION position you hold: mode "close" takes contracts off (all of them with contracts 0 /
        None), "add" puts more on in the same direction. A LIMIT DAY order on the contract at the touch (bid when
        selling, ask when buying) unless you give a price. Closing is never blocked; adding goes through the caps
        in real dollars (price × multiplier × contracts)."""
        with self.lock:
            now = now or time.time()
            p = self.engine.opt_positions.get(key)
            if p is None:
                return {"ok": False, "reason": f"no option position {key}"}
            if not hasattr(self.broker, "place_option"):
                return {"ok": False, "reason": "the practice desk trades stock only: option positions come from TWS"}
            held = int(abs(p["qty"])) ; long_ = p["qty"] > 0
            n = int(contracts or 0)
            if mode == "close":
                action = SELL if long_ else BUY
                free = held - self._opt_working(key, action)          # closes already working on it count
                if free <= 0:
                    return {"ok": False, "reason": f"{key}: all {held} already being closed"}
                n = free if n <= 0 else min(n, free)
            elif mode == "add":
                if n <= 0:
                    return {"ok": False, "reason": "how many contracts?"}
                action = BUY if long_ else SELL
                if not long_:                                   # adding to a short: more contracts sold to open
                    why = self._sell_to_open_why(p.get("symbol"), p.get("right"), key, n)
                    if why:
                        self._note(now, f"BLOCKED SELL {n} more {key}: {why}", False)
                        return {"ok": False, "reason": why}
            else:
                return {"ok": False, "reason": f"bad mode {mode}"}
            if price is None or price == "":
                price = p.get("bid") if action == SELL else p.get("ask")
                if not price:
                    return {"ok": False, "reason": f"no quote on {key} yet — type a price"}
                price = opt_through(price, action)
            else:
                price = opt_snap(float(price))
            price = round(float(price), 2)
            if price <= 0:
                return {"ok": False, "reason": "price must be positive"}
            mult = p.get("mult") or 100
            reducing = mode == "close"
            reason = (self.gate.check_reduce(action, n, price * mult, now) if reducing
                      else self.gate.check(action, n, price, now, "LMT", mult=mult))
            if reason:
                self._note(now, f"BLOCKED {action} {n} {key} @ {money(price)}: {reason}", False)
                return {"ok": False, "reason": reason}
            try:
                oid = self.broker.place_option(key, action, n, price, now, reducing=reducing)
            except Exception as exc:
                self._note(now, f"FAILED {action} {n} {key} @ {money(price)}: {exc}", False)
                return {"ok": False, "reason": str(exc)}
            what = "CLOSE" if reducing and n >= held else "SCALE OUT" if reducing else "SCALE IN"
            self._note(now, f"SENT {what} {action} {n} {key} @ {money(price)} (${n * price * mult:,.0f})", True)
            self.engine._rec({"ev": "order", "t": now, "sym": key, "action": action, "qty": n, "px": price,
                              "type": "LMT", "aux": None, "tif": "DAY", "legs": [], "id": oid, "role": "option"})
            return {"ok": True, "id": oid, "sent": f"{action} {n} {key} @ {money(price)} ({what.lower()})"}

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

    # ---- SCALE PLAN: scale out (and add) off the position as price moves from your entry -----------------
    def _avg_cost(self, symbol):
        for (a, s_), p in self.engine.positions.items():
            if s_ == symbol and p.get("qty"):
                return float(p.get("avg_cost") or 0) or None
        return None

    def set_scale_plan(self, symbol, kind=None, rungs=None, auto=None, now=None):
        """Put a plan on the position: a template (MP / CASH / BUILD from config) or your own rungs. Measured from
        the average entry; TAKE pct is of what is LEFT at that rung, ADD pct of the position."""
        with self.lock:
            now = now or time.time()
            pos = int(self.broker.position(symbol))
            if not pos:
                return {"ok": False, "reason": "no position: a scale plan goes on a position you hold"}
            cur = self.scale_plans.get(symbol)
            if rungs is None and kind is None and cur is not None and auto is not None:
                cur["auto"] = bool(auto)
                self._note(now, f"{symbol} scale plan AUTO {'on' if cur['auto'] else 'off'}", True)
                return {"ok": True, "plan": self._plan_view(symbol, cur, now)}
            tpls = self.cfg["scale_plan"].get("templates") or {}
            if rungs is None:
                kind = str(kind or "MP").upper()
                if kind not in tpls:
                    return {"ok": False, "reason": f"no scale template {kind}; have {', '.join(tpls)}"}
                rungs = tpls[kind]
            else:
                kind = str(kind or "CUSTOM").upper()
            clean = []
            for r in rungs:
                try:
                    mv, pct, act = float(r["move"]), float(r["pct"]), str(r.get("action", "TAKE")).upper()
                except (KeyError, TypeError, ValueError):
                    return {"ok": False, "reason": "each rung needs move (dollars), action TAKE or ADD, pct"}
                if mv <= 0 or not 0 < pct <= 100 or act not in ("TAKE", "ADD"):
                    return {"ok": False, "reason": "rung: move above 0, pct 1-100, action TAKE or ADD"}
                clean.append({"move": round(mv, 4), "action": act, "pct": round(pct, 1), "done": False, "ready": False,
                              "shares": None, "price": None, "t": None, "note": ""})
            clean.sort(key=lambda r: r["move"])
            entry = self._avg_cost(symbol) or (self.engine.syms[symbol].price() if symbol in self.engine.syms else None)
            plan = {"symbol": symbol, "kind": kind, "auto": bool(self.cfg["scale_plan"].get("auto_default", True)) if auto is None else bool(auto),
                    "entry": entry, "side": "long" if pos > 0 else "short", "basis": abs(pos), "rungs": clean, "t": now}
            self.scale_plans[symbol] = plan
            self._note(now, f"{symbol} SCALE PLAN {kind} on {abs(pos)} sh from {money(entry) if entry else '?'}: " +
                       ", ".join(f"+${r['move']:g} {r['action']} {r['pct']:g}%" for r in clean) + (" · AUTO" if plan["auto"] else " · manual"), True)
            return {"ok": True, "plan": self._plan_view(symbol, plan, now)}

    def clear_scale_plan(self, symbol, now=None):
        with self.lock:
            if self.scale_plans.pop(symbol, None) is not None:
                self._note(now or time.time(), f"{symbol} scale plan cleared", True)
            return {"ok": True}

    def fire_scale_rung(self, symbol, i, now=None):
        """Fire one rung by hand, reached or not."""
        with self.lock:
            plan = self.scale_plans.get(symbol)
            if not plan:
                return {"ok": False, "reason": "no scale plan on " + symbol}
            try:
                rung = plan["rungs"][int(i)]
            except (IndexError, TypeError, ValueError):
                return {"ok": False, "reason": "no such rung"}
            if rung["done"]:
                return {"ok": False, "reason": "that rung already fired"}
            return self._fire_rung(symbol, plan, rung, now or time.time())

    def _fire_rung(self, symbol, plan, rung, now):
        pos = int(self.broker.position(symbol))
        if not pos:
            return {"ok": False, "reason": "flat"}
        st = self.engine.syms.get(symbol)
        bid, ask = st.bbo() if st else (None, None)
        if bid is None or ask is None:
            return {"ok": False, "reason": "no quote"}
        if rung["action"] == "ADD":
            shares = max(1, int(round(abs(pos) * rung["pct"] / 100.0)))
            out = self._adjust_unlocked(symbol, shares, "add", now)
        else:
            _p, free, why = self._can_reduce_by(symbol, now)
            if not free:
                return {"ok": False, "reason": why or "nothing left to take off"}
            shares = int(round(free * rung["pct"] / 100.0))
            if rung["pct"] >= 100 or shares >= free:
                out = self._flatten_unlocked(symbol, now)
                shares = free
            else:
                shares = max(1, shares)
                touch = bid if pos > 0 else ask
                out = self._partial_unlocked(symbol, shares, touch, now)
        if out.get("ok"):
            rung.update(done=True, ready=False, shares=shares, price=bid if pos > 0 else ask, t=now)
            left = max(0, abs(pos) - shares) if rung["action"] == "TAKE" else abs(pos) + shares
            self._note(now, f"{symbol} scale {rung['action']} {rung['pct']:g}% at +${rung['move']:g}: {shares} sh, {left} left of {plan['basis']}", True)
        else:
            rung["note"] = out.get("reason", "")
        return dict(out, rung=rung)

    def _scale_tick(self, now):
        """Every watchdog pass: a rung is READY once price has moved its dollars from the entry in your favour;
        with AUTO on it fires at once. Flat = the plan is done."""
        for symbol, plan in list(self.scale_plans.items()):
            pos = int(self.broker.position(symbol))
            if not pos:
                self.scale_plans.pop(symbol, None)
                self._note(now, f"{symbol} flat: scale plan finished", True)
                continue
            st = self.engine.syms.get(symbol)
            price = st.price() if st else None
            if not price or not plan.get("entry"):
                continue
            move = (price - plan["entry"]) * (1 if plan["side"] == "long" else -1)
            for rung in plan["rungs"]:
                if rung["done"] or move + 1e-9 < rung["move"]:
                    continue
                rung["ready"] = True
                if plan["auto"]:
                    self._fire_rung(symbol, plan, rung, now)

    def _plan_view(self, symbol, plan, now):
        pos = int(self.broker.position(symbol))
        st = self.engine.syms.get(symbol)
        price = st.price() if st else None
        move = (price - plan["entry"]) * (1 if plan["side"] == "long" else -1) if price and plan.get("entry") else None
        left = abs(pos)
        return dict(plan, pos=pos, left=left, left_pct=round(100.0 * left / plan["basis"]) if plan["basis"] else None,
                    move=round(move, 2) if move is not None else None, price=price,
                    next=next((i for i, r in enumerate(plan["rungs"]) if not r["done"]), None))

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
                 auto_on=self.auto_on, risk_dollars=self.risk_dollars, auto=self.auto_status(),
                 filled_chip_seconds=float(self.cfg.get("filled_chip_seconds", 90)),
                 bracket_template=self.bracket_template, bracket_templates=list(self.bracket_templates().keys()),
                 scale_plans={sym: self._plan_view(sym, pl, time.time()) for sym, pl in self.scale_plans.items()},
                 trails={sym: dict(tr) for sym, tr in self.trails.items()},
                 opt_stops=self._opt_stop_view(), opt_links=self._opt_link_view(),
                 allow_sell_to_open=bool(self.cfg.get("allow_sell_to_open", False)),
                 scale_templates={k: v for k, v in (self.cfg["scale_plan"].get("templates") or {}).items()},
                 qty_presets=list(self.cfg.get("qty_presets") or [25, 50, 100, 200, 500, 1000]),
                 manage_presets=list(self.cfg.get("manage_presets") or [5, 10, 20]),
                 manage_option_presets=list(self.cfg.get("manage_option_presets") or [1, 2, 5]))
        return s
