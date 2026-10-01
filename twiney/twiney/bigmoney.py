"""BIG MONEY: every large option print for 30 days, and how the people who paid for it are doing NOW.

Facts only, from what the desk knows: the premium paid, contracts, price per contract, strike, expiry,
the stock price then and now (and the stock's close on expiry day once a contract has expired).

  breakeven    = strike + price paid (calls) / strike - price paid (puts)
  intrinsic    = what the contracts are worth on exercise at today's stock price (0 when out of the money)
  open:        the contracts are worth AT LEAST the intrinsic value (plus time value we can't see without
               live option quotes, so it is never added in)
  expired:     worth exactly the intrinsic value at expiry: worthless when out of the money

A print bought at the ask is BUYERS paying; one sold at the bid is SELLERS collecting — their side wins when
the buyers' side loses. Saved to a file, so it survives restarts.
"""

import datetime as _dt
import json
import os
import time

try:
    from zoneinfo import ZoneInfo
    _NY = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover
    _NY = None


def usd(v):
    v = float(v or 0)
    a = abs(v)
    s = f"${a / 1e6:.1f}M" if a >= 1e6 else f"${round(a / 1e3):,.0f}K" if a >= 1e4 else f"${a:,.0f}"
    return ("-" if v < 0 else "") + s


def _exp_date(exp):
    try:
        return _dt.date.fromisoformat(str(exp)[:10])
    except (TypeError, ValueError):
        return None


def _expired(exp, now):
    """Past 4 pm New York on its expiry date."""
    d = _exp_date(exp)
    if d is None:
        return False
    if _NY is not None:
        close = _dt.datetime(d.year, d.month, d.day, 16, 0, tzinfo=_NY).timestamp()
    else:
        close = _dt.datetime(d.year, d.month, d.day, 20, 0, tzinfo=_dt.timezone.utc).timestamp()
    return now >= close


class BigMoney:
    def __init__(self, cfg, path=None):
        self.min_premium = float(cfg.get("big_money_min_premium", 500000))
        self.days = float(cfg.get("big_money_days", 30))
        self.path = path
        self.items = []
        self.keys = set()
        self._load()

    # ---- memory ---------------------------------------------------------------------------------
    def _key(self, p):
        return p.get("vid") or f"{round(p['t'], 1)}|{p['symbol']}|{p['cp']}|{p['strike']}|{p.get('expiry')}|{round(p['premium'])}"

    def _load(self):
        if not self.path or not os.path.exists(self.path):
            return
        cut = time.time() - self.days * 86400
        try:
            with open(self.path, encoding="utf-8") as fh:
                for line in fh:
                    try:
                        p = json.loads(line)
                    except ValueError:
                        continue
                    if p.get("t", 0) >= cut and self._key(p) not in self.keys:
                        self.keys.add(self._key(p))
                        self.items.append(p)
        except OSError:
            return
        self._compact()

    def _compact(self):
        """Rewrite the file with only the last 30 days."""
        if not self.path:
            return
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.path)) or ".", exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                for p in self.items:
                    fh.write(json.dumps(p) + "\n")
            os.replace(tmp, self.path)
        except OSError:
            pass

    def add(self, p, now=None):
        """One option print: kept if it is big enough and readable (call / put, strike, expiry, contracts)."""
        if not p or (p.get("premium") or 0) < self.min_premium or p.get("cp") not in ("C", "P"):
            return False
        if not p.get("strike") or not _exp_date(p.get("expiry")) or not p.get("size"):
            return False
        k = self._key(p)
        if k in self.keys:
            return False
        keep = {f: p.get(f) for f in ("t", "symbol", "cp", "strike", "expiry", "size", "price", "premium", "spot", "side", "kind", "vid")}
        self.keys.add(k)
        self.items.append(keep)
        cut = (now or time.time()) - self.days * 86400
        if self.items and self.items[0].get("t", 0) < cut:
            self.items = [x for x in self.items if x.get("t", 0) >= cut]
            self.keys = {self._key(x) for x in self.items}
            self._compact()
        elif self.path:
            try:
                os.makedirs(os.path.dirname(os.path.abspath(self.path)) or ".", exist_ok=True)
                with open(self.path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(keep) + "\n")
            except OSError:
                pass
        return True

    # ---- the scorecard --------------------------------------------------------------------------
    @staticmethod
    def judge(p, spot, now, close_on=None):
        """How the people who traded this print are doing, in facts. spot = the stock now."""
        cp, k, n = p["cp"], float(p["strike"]), int(p["size"])
        paid = float(p["premium"])
        per = float(p.get("price") or (paid / (100.0 * n)))
        be = k + per if cp == "C" else k - per
        expired = _expired(p.get("expiry"), now)
        s = None
        settle = False
        if expired and close_on is not None:
            s = close_on(p.get("expiry"))
            settle = s is not None
        if s is None:
            s = spot
        buyers = p.get("side") != "bid"          # at the ask (or unknown): buyers paid · at the bid: sellers collected
        who = "BUYERS" if buyers else "SELLERS"
        out = {"t": p["t"], "symbol": p["symbol"], "cp": cp, "strike": k, "expiry": p.get("expiry"), "size": n,
               "price": round(per, 2), "premium": round(paid), "spot_then": p.get("spot"), "side": p.get("side"),
               "breakeven": round(be, 2), "expired": expired, "who": who, "age_days": round((now - p["t"]) / 86400, 1)}
        if s is None:
            out.update(status="NO PRICE", text="no stock price yet to judge it", value=None, pnl=None, good=None)
            return out
        intr = max(0.0, s - k) if cp == "C" else max(0.0, k - s)
        value = intr * 100 * n
        pnl = value - paid                         # for the buyers (a floor while open: time value not counted)
        out.update(spot=round(s, 2), value=round(value), pnl=round(pnl))
        kind = "calls" if cp == "C" else "puts"
        lbl = f"{usd(paid)} {kind}"
        if expired:
            if value <= 0:
                st = "EXPIRED WORTHLESS"
                txt = f"{lbl} expired worthless — the buyers lost all {usd(paid)}" if buyers else \
                      f"{lbl} expired worthless — the sellers kept all {usd(paid)}"
            elif pnl >= 0:
                st = "EXPIRED IN PROFIT" if buyers else "EXPIRED: SELLERS LOST"
                txt = (f"{lbl} expired in the money at {s:.2f} — worth {usd(value)}, the buyers made {usd(pnl)}" if buyers else
                       f"{lbl} expired in the money at {s:.2f} — the sellers owe {usd(value)}, down {usd(pnl)}")
            else:
                st = "EXPIRED UNDERWATER" if buyers else "EXPIRED: SELLERS WON"
                txt = (f"{lbl} expired at {s:.2f} worth {usd(value)} — the buyers got back {usd(value)} of {usd(paid)}, lost {usd(-pnl)}" if buyers else
                       f"{lbl} expired at {s:.2f} worth {usd(value)} — the sellers kept {usd(-pnl)} of the {usd(paid)}")
            if not settle:
                txt += " (judged at the last price: no close for expiry day)"
        else:
            beyond = s > be if cp == "C" else s < be
            itm = intr > 0
            dir_ = "above" if cp == "C" else "below"
            if beyond:
                st = "BUYERS IN PROFIT" if buyers else "SELLERS UNDERWATER"
                txt = (f"{lbl}: stock {s:.2f} is {dir_} the {be:.2f} breakeven — worth at least {usd(value)}, buyers up {usd(pnl)}+" if buyers else
                       f"{lbl} sold: stock {s:.2f} is {dir_} the {be:.2f} breakeven — the sellers are down at least {usd(pnl)}")
            elif itm:
                st = "BUYERS UNDERWATER" if buyers else "SELLERS AHEAD"
                txt = (f"{lbl}: in the money but under the {be:.2f} breakeven — intrinsic {usd(value)} of {usd(paid)} paid" if buyers else
                       f"{lbl} sold: in the money, under the {be:.2f} breakeven — the sellers still ahead")
            else:
                st = "BUYERS UNDERWATER" if buyers else "SELLERS AHEAD"
                need = f"needs {'above' if cp == 'C' else 'below'} {k:g} strike, {be:.2f} to break even"
                txt = (f"{lbl}: out of the money ({need}) — stock {s:.2f}" if buyers else
                       f"{lbl} sold: out of the money, stock {s:.2f} — the sellers keep it all if it stays there")
            d = _exp_date(p.get("expiry"))
            if d is not None:
                left = (d - _dt.date.fromtimestamp(now)).days
                txt += f" · {max(0, left)}d left"
        out.update(status=st, text=txt, good=pnl >= 0 if buyers else pnl < 0)
        return out

    def for_symbol(self, symbol, spot, now, close_on=None, limit=12):
        mine = [p for p in self.items if p["symbol"] == symbol and now - p["t"] <= self.days * 86400]
        mine.sort(key=lambda p: -p["premium"])
        return [self.judge(p, spot, now, close_on) for p in mine[:limit]]

    def symbols(self):
        return sorted({p["symbol"] for p in self.items})
