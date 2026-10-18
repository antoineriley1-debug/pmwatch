"""THE TRADE BOT: once you are in, it manages the trade the PS60 way. Paper only.

It takes over a position you opened (the second entry, by hand or by the AUTO 2ND ENTRY) when the bot is on for that
stock. At the start it reads the Daily chart and puts the trade in one of two kinds (you can flip it any time):

  GIVE IT ROOM        price spent consolidate_days+ daily candles inside a range before this break, and the MP to the
                      next Daily supply (demand for a short) is room_mp_atr+ ATR. No early pay-yourself: the stop
                      stays at max pain until the trade has gone be_atr ATR your way, then break even; pay yourself
                      only in the last room_pay_last_pct of the way to the MP.
  PAY YOURSELF EARLY  everything else (a continuation move): pay_pct of the position comes off at a quarter of the
                      daily ATR, never under pay_min nor over pay_max dollars (or the play's own PAY AT), then break
                      even.

After break even the runner's stop trails under the lows (over the highs for a short) of the last finished 5-minute
or 60-minute candle: the 5 | 60 switch. It gets out early when the level it broke is graded LOST, when a reload buyer
(seller, for a short) is CLEANED UP against it, or when price hits supply and a 5-minute candle closes back under the
pivot (over it for a short). It never adds back after getting out. TAKE BACK hands the trade back to you: nothing is
moved after that.

It acts only on PAPER / the practice desk (trading.bot.allow_live stays off). Every step is in the trade's card in
THE CALL BOOK and in the desk's notes. Builds and its own entries come later, once the managing has proven itself.
"""

import time

from . import ps60

ROOM, EARLY = "GIVE IT ROOM", "PAY YOURSELF EARLY"


class TradeBot:
    def __init__(self, trader):
        self.trader = trader
        self.armed = {}        # symbol -> {"trail": 5 | 60, "mode": None | ROOM | EARLY, "pay_at": None | dollars}
        self.trades = {}       # symbol -> the trade it is managing (see _attach)
        self.done = []         # finished trades, newest last (today's)
        self.losses = {}       # day -> losing trades the bot managed

    # ---- settings ---------------------------------------------------------------------------------------------
    @property
    def c(self):
        return self.trader.cfg.get("bot") or {}

    def _may_act(self):
        """Paper and the practice desk only, unless allow_live (never switched on by the desk)."""
        return self.trader.gate.mode in ("PAPER", "SIM") or bool(self.c.get("allow_live"))

    # ---- your switches -------------------------------------------------------------------------------------------
    def arm(self, symbol, on=True, trail=None, mode=None, pay_at=None, now=None):
        """BOT ON for a stock: it manages the next position there (or the one you hold now). Off = TAKE BACK."""
        symbol = str(symbol or "").upper()
        now = now or time.time()
        if not on:
            self.armed.pop(symbol, None)
            for tr in [t for t in self.trades.values() if t["symbol"] == symbol]:
                self._step(tr, now, "TAKE BACK: you manage it from here; the bot moves nothing more")
                self._finish(tr, now, "TAKEN BACK")
            return {"ok": True, "on": False}
        a = self.armed.setdefault(symbol, {"trail": int(self.c.get("trail_default", 5)), "mode": None, "pay_at": None})
        if trail is not None:
            a["trail"] = 60 if int(trail) == 60 else 5
        if mode is not None:
            a["mode"] = mode if mode in (ROOM, EARLY) else None
        if pay_at is not None:
            try:
                a["pay_at"] = round(float(pay_at), 2) if float(pay_at) > 0 else None
            except (TypeError, ValueError):
                a["pay_at"] = None
        for tr in [t for t in self.trades.values() if t["symbol"] == symbol]:     # flipped mid-trade: from now
            if trail is not None and tr["trail"] != a["trail"]:
                tr["trail"] = a["trail"]
                self._step(tr, now, f"trail switched to the {a['trail']}-minute candles")
            if mode is not None and a["mode"] and a["mode"] != tr["mode"]:
                tr["mode"], tr["mode_by"] = a["mode"], "you"
                self._step(tr, now, f"switched to {a['mode']} by you")
            if pay_at is not None:
                tr["pay_at"] = a["pay_at"] or tr["pay_at_auto"]
        return {"ok": True, "on": True, "armed": dict(a)}

    # ---- the Daily read at the start -----------------------------------------------------------------------------
    def _atr(self, st):
        eng = self.trader.engine
        a = (st.__dict__.get("_story_atr") or {}).get("v") or st.play.get("atr")
        if not a:
            try:
                a = eng._atr(st, st.bar_list(3000))
            except Exception:
                a = None
        return float(a) if a else None

    @staticmethod
    def consolidation_days(daily, atr, width_atr):
        """How many daily candles, counting back from the last finished one, stayed inside one range no wider than
        width_atr × the ATR. daily: [[t, o, h, l, c], ...] oldest first, finished days only."""
        if not daily or not atr:
            return 0
        hi, lo, n = -1e18, 1e18, 0
        for row in reversed(daily):
            h, l = max(hi, row[2]), min(lo, row[3])
            if h - l > width_atr * atr:
                break
            hi, lo, n = h, l, n + 1
        return n

    def classify(self, st, side, entry, now):
        """(mode, why, days, mp_atr) for a trade starting now."""
        atr = self._atr(st)
        from . import studies
        today = studies.day_key(now)
        daily = [[k] + list(st.daily[k][:4]) for k in sorted(getattr(st, "daily", {}) or {}) if studies.day_key(k + 43200) != today]
        days = self.consolidation_days(daily, atr, float(self.c.get("range_width_atr", 2.5)))
        mp = st.play.get("target") or st.play.get("mp")
        long_ = side == "long"
        mp_atr = None
        if mp and atr and ((mp - entry) * (1 if long_ else -1)) > 0:
            mp_atr = abs(mp - entry) / atr
        room = days >= int(self.c.get("consolidate_days", 15)) and (mp_atr or 0) >= float(self.c.get("room_mp_atr", 2.0))
        why = (f"{days} daily candles in one range before the break, MP {mp_atr:.1f} ATR" if mp_atr is not None
               else f"{days} daily candles in one range before the break, no MP on the chart")
        return (ROOM if room else EARLY), why, days, mp_atr

    def pay_at_auto(self, atr):
        """PAY YOURSELF EARLY: a quarter of the daily ATR, between pay_min and pay_max dollars."""
        lo, hi = float(self.c.get("pay_min", 0.5)), float(self.c.get("pay_max", 1.0))
        if not atr:
            return lo
        return round(min(hi, max(lo, float(self.c.get("pay_atr_frac", 0.25)) * atr)), 2)

    # ---- the candles ---------------------------------------------------------------------------------------------
    @staticmethod
    def last_finished(st, minutes, now):
        """The last FINISHED candle of 5 or 60 minutes (60s from 9:30, the PS60 way): [t0, o, h, l, c, v] or None."""
        bars = ps60.session_bars(st.bar_list(900))
        rows = ps60.aggregate(bars, minutes)
        done = [r for r in rows if r[0] + minutes * 60 <= now]
        return done[-1] if done else None

    def max_pain(self, st, side, now):
        """The prior 5-minute low (high for a short): where you are wrong."""
        c = self.last_finished(st, 5, now)
        if not c:
            return None
        return c[3] if side == "long" else c[2]

    # ---- the trade ---------------------------------------------------------------------------------------------
    def _legs(self, symbol):
        """Every position on the stock: the shares, and each contract (a call / short put = long, a put / short call =
        short). Shares and contracts at the same time are managed side by side, each on its own."""
        tr = self.trader
        out = []
        q = int(tr.broker.position(symbol) or 0)
        if q:
            out.append(("stock", q, None))
        for key, p in list((tr.engine.opt_positions or {}).items()):
            if p.get("symbol") == symbol and p.get("qty"):
                bull = (p.get("right") == "C") == (p["qty"] > 0)
                out.append(("option", abs(int(p["qty"])) if bull else -abs(int(p["qty"])), key))
        return out

    def _leg_qty(self, tr):
        """(kind, qty, key) of this trade's own leg now (qty 0 when it is gone)."""
        for kind, q, key in self._legs(tr["symbol"]):
            if kind == tr["kind"] and key == tr["key"]:
                return kind, q, key
        return tr["kind"], 0, tr["key"]

    @staticmethod
    def lid(symbol, key):
        return key or symbol

    def _attach(self, symbol, kind, qty, key, now):
        eng = self.trader.engine
        st = eng.syms.get(symbol)
        last = st.price() if st else None
        if st is None or not last:
            return None
        side = "long" if qty > 0 else "short"
        entry = (self.trader._avg_cost(symbol) if kind == "stock" else None) or last
        a = self.armed.get(symbol) or {}
        mode, why, days, mp_atr = self.classify(st, side, entry, now)
        atr = self._atr(st)
        pay_auto = self.pay_at_auto(atr)
        tr = {"id": self.lid(symbol, key), "symbol": symbol, "kind": kind, "key": key, "side": side, "entry": float(entry), "qty0": abs(qty), "t0": now,
              "mode": a.get("mode") or mode, "mode_by": "you" if a.get("mode") else "bot", "mode_why": why, "days": days,
              "mp_atr": mp_atr, "atr": atr, "mp": st.play.get("target") or st.play.get("mp"), "trail": a.get("trail", 5),
              "pay_at_auto": pay_auto, "pay_at": a.get("pay_at") or st.play.get("pay_at") or pay_auto,
              "pivot": st.play.get("trigger"), "stop": None, "be": False, "paid": False, "steps": [], "card": None,
              "trail_t": None, "seen_alert": now}
        self.trades[tr["id"]] = tr
        self._step(tr, now, f"took over {abs(qty)} {'shares' if kind == 'stock' else 'contracts of ' + key} {side.upper()} at {entry:.2f}: "
                            f"{tr['mode']} ({why}{', switched by you' if tr['mode_by'] == 'you' else ''})")
        # the card in THE CALL BOOK
        try:
            cb = eng.callbook
            row = {"t": now, "symbol": symbol, "kind": "BOT TRADE", "dir": 1 if side == "long" else -1, "p0": float(last),
                   "atr": atr, "src": "practice" if self.trader.gate.mode == "SIM" else "live"}
            card = cb.add(row, {"label": "BOT TRADE", "text": tr["steps"][0]["text"]}, eng._callbook_ctx(st, now))
            if card is not None:
                card["steps"] = list(tr["steps"])
                tr["card"] = card["id"]
        except Exception:
            pass
        # a stop you set on the contract's own price stays: the bot does not swap it for its own until break even
        if kind == "option":
            os_ = self.trader.opt_stops.get(key) or {}
            if os_.get("on") == "option" and os_.get("price"):
                tr["your_stop"] = os_["price"]
                self._step(tr, now, f"keeps your stop on the contract at {os_['price']:.2f} (it takes over the stop at break even)")
                return tr
        # the stop at max pain, unless yours is already tighter
        mpain = self.max_pain(st, side, now)
        cur = self._cur_stop(tr, st)
        want = mpain
        if want is not None and cur is not None:
            want = max(want, cur) if side == "long" else min(want, cur)
        if want is not None and want != cur:
            self._set_stop(tr, st, want, now, "stop at max pain, the prior 5-minute " + ("low" if side == "long" else "high"))
        elif cur is not None:
            tr["stop"] = cur
        return tr

    def _cur_stop(self, tr, st):
        if tr["kind"] == "option":
            s = (self.trader.opt_stops.get(tr["key"]) or {})
            return s.get("price") if s.get("on") == "stock" else None
        alt = bool(st.play.get("alt")) and tr["side"] != st.play.get("side", "long")
        return self.trader._side_levels(st.play, alt=alt).get("stop")

    def _set_stop(self, tr, st, price, now, why):
        from .trading import snap
        long_ = tr["side"] == "long"
        price = snap(price, -1 if long_ else +1, tr["symbol"])
        last = st.price()
        if last is not None and ((long_ and price >= last) or (not long_ and price <= last)):
            return False                                    # through the market: it would fire at once
        if tr["kind"] == "option":
            out = self.trader.set_opt_stop(tr["key"], price, on="stock", now=now)
            ok = out.get("ok")
        else:
            alt = bool(st.play.get("alt")) and tr["side"] != st.play.get("side", "long")
            self.trader.engine.set_play_level(tr["symbol"], "stop", price, now, source="bot", alt=alt)
            ok = True
        if ok:
            tr["stop"] = price
            self._step(tr, now, f"{why}: stop {price:.2f}")
        return ok

    def _pay(self, tr, st, now, why):
        """Pay yourself: pay_pct of what is held comes off now (a limit at the touch)."""
        kind, qty, key = self._leg_qty(tr)
        n = int(round(abs(qty) * float(self.c.get("pay_pct", 50)) / 100.0))
        if n <= 0 or n >= abs(qty) and abs(qty) > 1:
            n = max(1, abs(qty) // 2)
        if kind == "option":
            out = self.trader.opt_adjust(key, n, "close", now=now)
        else:
            # through the spread a few ticks, like CLOSE: paying yourself fills now, it does not rest at the bid
            from .trading import tick_size
            bid, ask = st.bbo()
            ref = (bid if qty > 0 else ask) or st.price()
            tk = tick_size(ref, tr["symbol"]) * int(self.c.get("pay_through_ticks", 5))
            px = round(ref - tk if qty > 0 else ref + tk, 2)
            out = self.trader._partial_unlocked(tr["symbol"], n, px, now)
        tr["paid"] = True
        self._step(tr, now, f"{why}: paid yourself {n} of {abs(qty)}" + ("" if out.get("ok") else f" (refused: {out.get('reason')})"))
        return out.get("ok")

    def _out(self, tr, st, now, why):
        kind, qty, key = self._leg_qty(tr)
        if not qty:
            out = {"ok": True}
        elif kind == "option":
            out = self.trader.opt_adjust(key, 0, "close", now=now)
        elif kind == "stock":
            out = self.trader._flatten_unlocked(tr["symbol"], now)
        else:
            out = {"ok": True}
        self._step(tr, now, f"OUT: {why}" + ("" if out.get("ok") else f" (refused: {out.get('reason')})"))
        tr["out"] = why
        # never adds back: the AUTO 2ND ENTRY for this stock goes off
        try:
            if st.play.get("auto", True):
                st.play["auto"] = False
                self.trader.engine._save_plays()
                self._step(tr, now, "AUTO 2ND ENTRY off on this stock: no adding back after getting out")
        except Exception:
            pass

    # ---- every tick (inside the trader's lock) ----------------------------------------------------------------
    def tick(self, now):
        if not self.armed and not self.trades:
            return
        if not self._may_act():
            return
        eng = self.trader.engine
        symbols = set(self.armed) | {t["symbol"] for t in self.trades.values()}
        for symbol in symbols:
            legs = {self.lid(symbol, key): (kind, qty, key) for kind, qty, key in self._legs(symbol)}
            # a leg that closed (or flipped): its trade is done
            for tid, tr in [(i, t) for i, t in self.trades.items() if t["symbol"] == symbol]:
                leg = legs.get(tid)
                if not leg or ("long" if leg[1] > 0 else "short") != tr["side"]:
                    self._finish(tr, now, tr.get("out") or "CLOSED")
            st = eng.syms.get(symbol)
            last = st.price() if st else None
            for tid, (kind, qty, key) in legs.items():
                tr = self.trades.get(tid)
                if tr is None:
                    if symbol not in self.armed or tid in self.armed[symbol].get("done_legs", ()):
                        continue
                    day = time.strftime("%Y%m%d", time.localtime(now))
                    if self.losses.get(day, 0) >= int(self.c.get("max_losses_day", 3)):
                        continue                              # the bot's losses for today: it takes nothing new
                    tr = self._attach(symbol, kind, qty, key, now)
                    if tr is None:
                        continue
                if last:
                    self._manage(tr, st, last, now)

    # ---- ROAD BLOCKS: what is in the way between price and the MP ------------------------------------------------
    def road_blocks(self, st, side, last, mp, now, limit=6):
        """Every level between price and the MP the trade has to get through, nearest first, even with the Daily
        airspace clear: the Daily supply / demand and the key levels (prior-day high / low / close, premarket and
        after-hours, the open, VWAP, the 50-day, old Daily highs / lows), your sneaky pivots and extra levels, and the
        60-minute moving averages (20 and slower) ahead of price: a long running into the 20 on the 60 is price
        meeting supply on the 60, a short running down into it is demand on the 60. [{"price", "name", "kind"}]"""
        long_ = side == "long"
        far = mp if mp else (last + 3 * (self._atr(st) or last * 0.02) * (1 if long_ else -1))
        lo, hi = (last, far) if long_ else (far, last)
        tk = 0.005 * last / 100 if last else 0.01
        out = []
        ahead = lambda p: p is not None and lo + tk < float(p) < hi - tk
        try:
            for L in self.trader.engine.key_levels(st, now):
                if ahead(L.get("price")):
                    out.append({"price": float(L["price"]), "name": L.get("name") or L.get("code"), "kind": "DAILY / KEY"})
        except Exception:
            pass
        for k, nm in (("sneaky_levels", "SNEAKY PIVOT"), ("extra_levels", "YOUR LEVEL")):
            for v in st.play.get(k) or []:
                p = v.get("price") if isinstance(v, dict) else v
                if ahead(p):
                    out.append({"price": float(p), "name": nm, "kind": "YOURS"})
        # the 60-minute moving averages ahead of price: with the Daily airspace clear, a long running into the 20 on the
        # 60 is price meeting supply on the 60 (a short running down into it: demand on the 60)
        mas = (st.__dict__.get("_story_mas") or {}).get("hpack") or []
        least = int(self.c.get("h60_ma_min", 20))
        for name, v in mas:
            try:
                n = int(str(name).split()[-1])
            except ValueError:
                continue
            if n >= least and ahead(v):
                out.append({"price": float(v), "name": f"60-MIN {name} ({'supply' if long_ else 'demand'} on the 60)", "kind": "60-MIN MA"})
        # one per price (a tick apart is one level), nearest first
        out.sort(key=lambda x: abs(x["price"] - last))
        merged = []
        for x in out:
            if merged and abs(merged[-1]["price"] - x["price"]) <= max(0.02, last * 0.0005):
                if x["kind"] not in merged[-1]["kind"]:
                    merged[-1]["kind"] += " + " + x["kind"]; merged[-1]["name"] += " / " + x["name"]
                continue
            merged.append(dict(x))
        return merged[:limit]

    # ---- in tune: the plan, what it expects, what the market and you are saying ---------------------------------
    def read(self, tr, st, last, now):
        """The bot's read of the trade, every few seconds: THE PLAN (the setup, the pivot, the 2nd entry, the stop, the
        MP), WHAT IT EXPECTS (the way to the MP), and WHAT IT SEES NOW, each read with the trade or against it:
        who is in control (the story), the option flow on the trade's side, MY READ, price against VWAP."""
        eng = self.trader.engine
        p = st.play
        long_ = tr["side"] == "long"
        sg = 1 if long_ else -1
        mp = p.get("target") or p.get("mp") or tr["mp"]
        stop = tr["stop"]
        risk = (tr["entry"] - stop) * sg if stop is not None else None
        rr = ((mp - tr["entry"]) * sg / risk) if (mp and risk and risk > 0) else None
        setup = p.get("setup") or ("second entry" if p.get("second_entry") else "PS60 pivot")
        plan = (f"{tr['side'].upper()} {setup}: pivot {p['trigger']:.2f}" if p.get("trigger") else f"{tr['side'].upper()} {setup}") + \
               (f", 2nd entry {p['second_entry']:.2f}" if p.get("second_entry") else "") + \
               (f", stop {stop:.2f}" if stop is not None else "") + (f", MP {mp:.2f}" if mp else ", no MP on the chart") + \
               (f", {rr:.1f} to 1" if rr else "")
        if mp:
            way = abs(mp - tr["entry"])
            done = max(0.0, min(1.0, (last - tr["entry"]) * sg / way)) if way else 0.0
            expect = f"price working to the MP {mp:.2f}: ${abs(mp - last):.2f} away, {done * 100:.0f}% of the way done"
        else:
            expect = f"no MP on the chart: paying yourself at ${tr['pay_at']:.2f}, the runner trails the {tr['trail']}-minute candles"
        w, a = [], []
        ln = (getattr(st, "storybook", None) and st.storybook.__dict__.get("lean")) or {}
        side = ln.get("side")
        if side in ("bull", "bear"):
            (w if (side == "bull") == long_ else a).append("buyers in control" if side == "bull" else "sellers in control")
        try:
            idx = st.symbol in set((eng.cfg.get("flow") or {}).get("index_symbols", ()))
            fl = eng.flow.dough(st.symbol, "C" if long_ else "P", now, idx)
            state = fl.get("state")
            if state == "FLOW CONFIRMED":
                w.append(f"option flow confirmed ({'calls' if long_ else 'puts'})")
            elif state == "FLOW AGAINST":
                a.append(f"option flow against ({'puts' if long_ else 'calls'} out in front)")
        except Exception:
            pass
        mr = eng.myread.get(st.symbol, now) if getattr(eng, "myread", None) else None
        if mr:
            if mr["read"] == "HANDS OFF":
                a.append("your read is HANDS OFF")
            elif mr["read"] in ("BULLISH", "BEARISH"):
                (w if (mr["read"] == "BULLISH") == long_ else a).append(f"your read is {mr['read']}")
        try:
            vw = next((L["price"] for L in eng.key_levels(st, now) if L.get("code") == "VWAP"), None)
            if vw:
                ((w if (last > vw) == long_ else a)).append(f"{'over' if last > vw else 'under'} VWAP {vw:.2f}")
        except Exception:
            pass
        # INSIDE THE TRADE: where it is against the entry, the best and the worst so far, the stop in R
        now_ps = (last - tr["entry"]) * sg
        best, worst = tr.get("best", now_ps), tr.get("worst", now_ps)
        r1 = (f", {now_ps / risk:+.1f} R" if risk and risk > 0 else "")
        unit = "a share" if tr["kind"] == "stock" else "on the stock"
        inside = (f"{now_ps:+.2f} {unit} from {'the entry' if tr['kind'] == 'stock' else 'where the bot took over'} {tr['entry']:.2f}{r1} · best {best:+.2f}, worst {worst:+.2f}"
                  + (f" · stop {stop:.2f} ({(last - stop) * sg:.2f} away)" if stop is not None else
                     f" · your stop on the contract {tr['your_stop']:.2f}" if tr.get("your_stop") else " · no stop yet")
                  + (" · paid yourself" if tr["paid"] else "") + (" · break even done" if tr["be"] else ""))
        # THE DESIRED OUTCOME: the MP, in dollars a share and in R; without one, paying yourself and the runner
        if mp:
            goal = (f"reach the MP {mp:.2f}: {(mp - tr['entry']) * sg:+.2f} a share"
                    + (f", {rr:.1f} R" if rr else "") + (", the runner rides there" if tr["mode"] == ROOM else ", paid along the way, the runner rides there"))
        else:
            goal = f"pay yourself at {tr['pay_at']:+.2f} a share, then let the runner work under the {tr['trail']}-minute candles"
        try:
            rb = self.road_blocks(st, tr["side"], last, mp, now)
        except Exception:
            rb = []
        tr["blocks"] = rb
        stance = "CAREFUL" if len(a) >= 2 and len(a) > len(w) else "ON PLAN"
        prev = tr.get("read") or {}
        if stance != prev.get("stance"):
            tr["careful_since"] = now if stance == "CAREFUL" else None
            if prev:
                self._step(tr, now, f"{stance}: " + ("; ".join(a) if stance == "CAREFUL" else "back on plan" + (": " + "; ".join(w) if w else "")))
        blocks = ("ROAD BLOCKS to the " + ("MP" if mp else "next 3 ATR") + ": " +
                  " · ".join(f"{x['name']} {x['price']:.2f} (${abs(x['price'] - last):.2f})" for x in rb)) if rb else \
                 ("the way to the MP is clear: no level in between" if mp else "")
        tr["read"] = {"blocks": blocks, "plan": plan, "goal": goal, "expect": expect, "inside": inside, "with": w, "against": a, "stance": stance, "t": round(now)}
        return tr["read"]

    def _manage(self, tr, st, last, now):
        long_ = tr["side"] == "long"
        sg = 1 if long_ else -1
        gain = (last - tr["entry"]) * sg
        atr = tr["atr"] or 0
        tr["best"] = round(max(tr.get("best", gain), gain), 4)
        tr["worst"] = round(min(tr.get("worst", gain), gain), 4)
        if now - (tr.get("read") or {}).get("t", -1e9) >= float(self.c.get("read_seconds", 5)):
            try:
                self.read(tr, st, last, now)
            except Exception:
                pass
        # INTO A ROAD BLOCK (a level in the way, within a tenth of the ATR of it) and green: the stop tightens to the
        # last finished 5-minute candle, once per block: the PS60 way, pay attention into supply
        nb = (tr.get("blocks") or [None])[0]
        if nb and gain > 0 and atr and abs(nb["price"] - last) <= float(self.c.get("block_atr", 0.1)) * atr \
                and tr.get("block_done") != round(nb["price"], 2):
            tr["block_done"] = round(nb["price"], 2)
            c5 = self.last_finished(st, 5, now)
            want = (c5[3] if long_ else c5[2]) if c5 else None
            if want is not None and (tr["stop"] is None or (long_ and want > tr["stop"]) or (not long_ and want < tr["stop"])):
                self._set_stop(tr, st, want, now, f"into a road block, {nb['name']} {nb['price']:.2f}: tightened")
            else:
                self._step(tr, now, f"into a road block, {nb['name']} {nb['price']:.2f}: the stop is already tight")
        # CAREFUL for a while (the market turned against the trade) and the trade is green: the stop tightens to the
        # last finished 5-minute candle (never loosens)
        cs = tr.get("careful_since")
        if cs and gain > 0 and now - cs >= float(self.c.get("tighten_seconds", 120)):
            c5 = self.last_finished(st, 5, now)
            if c5 and tr.get("tight_t") != c5[0]:
                tr["tight_t"] = c5[0]
                want = c5[3] if long_ else c5[2]
                if tr["stop"] is None or (long_ and want > tr["stop"]) or (not long_ and want < tr["stop"]):
                    self._set_stop(tr, st, want, now, "tightened, the market turned against it (" + "; ".join((tr.get("read") or {}).get("against", [])) + ")")
        # the early outs, newest calls first
        why = self._danger(tr, st, now)
        if why:
            self._out(tr, st, now, why)
            return
        if tr.get("out"):
            return
        if tr["mode"] == ROOM:
            if not tr["be"] and atr and gain >= float(self.c.get("be_atr", 1.0)) * atr:
                self._breakeven(tr, st, now, f"{self.c.get('be_atr', 1.0):g} ATR your way")
            if not tr["paid"] and tr["mp"]:
                to_mp = abs(tr["mp"] - tr["entry"])
                if to_mp > 0 and gain >= to_mp * (1 - float(self.c.get("room_pay_last_pct", 10)) / 100.0):
                    self._pay(tr, st, now, f"in the last {self.c.get('room_pay_last_pct', 10):g}% to the MP {tr['mp']:.2f}")
        else:
            if not tr["paid"] and gain >= tr["pay_at"]:
                if self._pay(tr, st, now, f"${tr['pay_at']:.2f} your way"):
                    self._breakeven(tr, st, now, "paid yourself")
            elif tr["paid"] and not tr["be"]:
                self._breakeven(tr, st, now, "paid yourself")
        if tr["be"]:
            self._trail(tr, st, now)

    def _breakeven(self, tr, st, now, why):
        if self._set_stop(tr, st, tr["entry"], now, f"{why}: stop to break even"):
            tr["be"] = True

    def _trail(self, tr, st, now):
        c = self.last_finished(st, tr["trail"], now)
        if not c or tr["trail_t"] == c[0]:
            return
        tr["trail_t"] = c[0]
        long_ = tr["side"] == "long"
        want = c[3] if long_ else c[2]
        cur = tr["stop"]
        if cur is not None and ((long_ and want <= cur) or (not long_ and want >= cur)):
            return                                          # only ever in your favour
        self._set_stop(tr, st, want, now, f"runner: {'under' if long_ else 'over'} the last {tr['trail']}-minute {'low' if long_ else 'high'}")

    def _danger(self, tr, st, now):
        """Why to get out now, or None: the level graded LOST, a reload CLEANED UP against the trade, or price hit
        supply (demand) and a 5-minute candle closed back through the pivot."""
        long_ = tr["side"] == "long"
        for a in list(self.trader.engine.alerts)[:60]:
            if a.get("t", 0) <= tr["seen_alert"] or a.get("symbol") != tr["symbol"]:
                continue
            lab = str(a.get("label") or "")
            if lab == ("BUYERS TOOK · LOST" if long_ else "SELLERS TOOK · LOST"):
                return f"the level it broke is LOST ({a.get('text', '')[:80]})"
            if lab == "CLEANED UP" and a.get("side") == ("bid" if long_ else "ask"):
                return f"the reload {'buyer' if long_ else 'seller'} under it is CLEANED UP"
        tr["seen_alert"] = max([tr["seen_alert"]] + [a.get("t", 0) for a in list(self.trader.engine.alerts)[:60]
                                                      if a.get("symbol") == tr["symbol"]])
        pv = tr["pivot"]
        if pv:
            c = self.last_finished(st, 5, now)
            if c and c[0] >= tr["t0"] - 300 and ((long_ and c[4] < pv) or (not long_ and c[4] > pv)):
                return (f"price hit {'supply' if long_ else 'demand'}: a 5-minute candle closed back "
                        f"{'under' if long_ else 'over'} the pivot {pv:.2f}")
        return None

    # ---- the record ------------------------------------------------------------------------------------------
    def _step(self, tr, now, text):
        tr["steps"].append({"t": round(now, 1), "text": text})
        try:
            self.trader._note(now, f"BOT {tr['symbol']}: {text}", True)
        except Exception:
            pass
        cid = tr.get("card")
        if cid:
            try:
                self.trader.engine.callbook.step(cid, now, text)
            except Exception:
                pass

    def _finish(self, tr, now, how):
        self.trades.pop(tr["id"], None)
        st = self.trader.engine.syms.get(tr["symbol"])
        last = st.price() if st else None
        res = round((last - tr["entry"]) * (1 if tr["side"] == "long" else -1), 2) if last else None
        tr["end"] = {"t": now, "how": how, "price": last, "per_share": res}
        if res is not None and res < 0 and how != "TAKEN BACK":
            day = time.strftime("%Y%m%d", time.localtime(now))
            self.losses[day] = self.losses.get(day, 0) + 1
        if how != "TAKEN BACK":
            self._step(tr, now, f"done: {how}" + (f", {res:+.2f} a share from the entry" if res is not None else ""))
        self.done.append(tr)
        del self.done[:-30]
        # one trade per arming: a leg it has finished is not taken over again; with nothing left on, the bot is off
        a = self.armed.get(tr["symbol"])
        if a is not None:
            a.setdefault("done_legs", []).append(tr["id"])
            if not any(t["symbol"] == tr["symbol"] for t in self.trades.values()):
                self.armed.pop(tr["symbol"], None)

    def view(self, now=None):
        now = now or time.time()
        day = time.strftime("%Y%m%d", time.localtime(now))
        keep = ("id", "symbol", "kind", "key", "read", "your_stop", "side", "entry", "mode", "mode_by", "mode_why", "days", "mp_atr", "mp", "trail", "pay_at",
                "stop", "be", "paid", "out", "steps", "t0")
        armed = {}
        for s, a in self.armed.items():          # before the trade: which kind it would be, at today's price
            row = dict(a)
            st = self.trader.engine.syms.get(s)
            if st is not None and st.price() and not any(t["symbol"] == s for t in self.trades.values()):
                try:
                    side = st.play.get("side", "long")
                    mode, why, _d, _m = self.classify(st, side, st.price(), now)
                    row.update(preview=mode, preview_why=why, pay_at_auto=self.pay_at_auto(self._atr(st)))
                except Exception:
                    pass
            row.pop("done_legs", None)
            armed[s] = row
        return {"on": bool(self.c.get("enabled", True)), "may_act": self._may_act(),
                "armed": armed,
                "trades": {i: {k: tr.get(k) for k in keep} for i, tr in self.trades.items()},
                "done": [{k: tr.get(k) for k in keep + ("end",)} for tr in self.done[-10:]][::-1],
                "losses_today": self.losses.get(day, 0), "max_losses": int(self.c.get("max_losses_day", 3))}
