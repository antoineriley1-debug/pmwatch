"""Config + PS60 play loading and validation."""

import copy
import ipaddress
import math
import json
import logging
import os

DEFAULTS = {
    "ibkr": {
        "host": "127.0.0.1",
        # 7497 TWS paper, 7496 TWS live, 4002 Gateway paper, 4001 Gateway live
        "port": 7497,
        "client_id": 61,
        # 1 live, 2 frozen, 3 delayed, 4 delayed-frozen
        "market_data_type": 1,
        "reconnect_initial_seconds": 2.0,
        "reconnect_max_seconds": 60.0,
        # IBKR's limit on market data lines open at once (100 on most accounts). TWS's own windows (watchlists,
        # charts) use lines too, so the desk keeps `lines_reserve` free for them and never asks for more
        "max_lines": 100,
        "lines_reserve": 15,
        # option chain: quote only this many strikes nearest the price (each one is a data line)
        "chain_quote_rows": 10,
        # Time & Sales refused (too many feeds, another session): ask again this often
        "tape_retry_seconds": 20.0,
        # on DELAYED data because another login took the live data: try live again this often
        "live_retry_seconds": 60.0,
    },
    "dashboard": {
        "host": "127.0.0.1",
        "port": 8765,
        "open_browser": True,
    },
    "depth": {
        # IBKR caps simultaneous market-depth subscriptions; TWINEY uses three.
        "slots": 3,
        # rows requested from IBKR per side. With SMART depth EVERY exchange quoting a price takes its own row, so a
        # busy name (TSLA: 6-10 venues on the inside) needs many rows to show more than 2-3 prices. 40 rows = about
        # 10+ real prices each side on a liquid stock
        "rows_requested": 40,
        # rows shown per side on the dashboard
        "rows_displayed": 5,
        "smart_depth": True,
        # a challenger must be this much closer (fraction) than the incumbent it replaces
        "rotate_hysteresis": 0.15,
        # an incumbent keeps its slot at least this long before it can be rotated out
        "min_hold_seconds": 20.0,
        # after IBKR rejects a depth request (e.g. error 309) skip the symbol this long
        "reject_cooldown_seconds": 30.0,
        # the contract on the OPTION CHART gets a real book too (each exchange's quote, like TWS BookTrader): it takes one
        # of the depth lines above while a contract is charted. Off = option Level II shows the top of book only
        "option_depth": True,
        # rotation leans toward symbols with a live reloader: a symbol's distance is cut by this fraction x its best
        # level's conviction (0 = distance only, 0.5 = a fully ACTIVE reloader reads as half as far away)
        "conviction_weight": 0.5,
        # ...and toward a symbol where SOMEBODY KNOWS SOMETHING (short-dated out-of-the-money flow at the ask): distance cut by this
        # fraction x the flow score
        "flow_weight": 0.3,
    },
    "reload": {
        # PS60 level matching band, in ticks either side of the level
        "level_band_ticks": 0,
        # evidence window for confirming a reload
        "window_seconds": 120.0,
        # the level must refill at least this many times after executions
        "min_refreshes": 2,
        # executed shares at the level inside the window must reach this...
        "min_absorbed_shares": 1000,
        # ...and this multiple of the largest size ever displayed there
        "absorbed_multiple": 1.5,
        # something must still be displayed at confirmation time
        "min_display_shares": 100,
        # when a confirmed reload vanishes, executions this far back count as consumption
        "consumed_exec_window_seconds": 5.0,
        # executed shares needed to call it consumed, as a fraction of last displayed size
        "consumed_min_exec_fraction": 0.5,
        # wait this long after a disappearance before calling PULLED (tape lags book)
        "pull_grace_seconds": 3.0,
        # a vanished level must stay gone this long, with price still through it, before CLEANED UP is called
        # (book flicker, or a poke through that comes straight back, is not a clear)
        "clear_confirm_seconds": 3.0,
        # price must trade through the level within this long to call CLEANED UP
        "through_timeout_seconds": 10.0,
        # ignore disappearances this long after a book (re)sync, e.g. error 317
        "resync_grace_seconds": 2.0,
        # auto-track big inside levels in addition to trigger / second entry
        "auto_levels": True,
        "max_auto_levels": 6,
        "auto_min_display_shares": 2000,
        "auto_idle_seconds": 90.0,
        # CONVICTION: how much to trust a proven reloader is still there. Volume does the work: once this many times
        # what he was putting back per reload has traded through with nothing replacing it, he reads NOT RELOADING
        "stale_multiple": 1.5,
        # time is the slow second bleed: untested this long, a proven level reads NOT RELOADING on its own (seconds)
        "stale_seconds": 2400.0,
        # conviction at or above this = RELOADING (bright on the ladder)
        "active_floor": 0.75,
        # conviction at or above this = STILL THERE; under it = NOT RELOADING (dim)
        "fading_floor": 0.25,
        # after a proven level is lost (cleaned up, pulled, or price went through with nothing there) the row keeps
        # a faint "was here" mark this long (seconds)
        "gone_show_seconds": 7200.0,
        # a reload buyer / seller who comes back to the SAME price within this long of being cleaned up or pulled
        # is the same participant (BACK ×2, ×3 …), never a new one: his visits and absorbed shares add up
        "return_window_seconds": 1200.0,
    },
    "tape": {
        "window_seconds": 30.0,
        "min_prints_for_read": 5,
        "control_ratio": 0.65,
        "large_print_shares": 5000,
        "keep_prints": 200,
        # the BIG TAPE: a second time & sales filtered to large orders and position builders
        "big_tape_shares": 10000,       # a print this big (shares) makes the big tape
        "big_tape_dollars": 1000000,    # ... or this much money in one print (a block)
        "big_tape_x_average": 20,       # ... and at least this many times the ticker's own average print (scales per name)
        "big_tape_minutes": 30,         # how far back it looks
        "build_window_seconds": 90,     # same side, same price, prints no further apart than this = one builder
        "build_prints": 5,              # a builder needs at least this many prints
        "build_dollars": 2000000,       # ... adding up to big_tape_shares, or this much money
    },
    "breaktrap": {
        "enabled": True,                # BREAK TRAPS: who got caught when price took out a key level and came back (the TRAPS box)
        "voice": True,                  # say TRAPPED / BREAK HELD / AT THEIR EXIT (the ticker you are on)
        "retrace_dollars": 0.30,        # TRAPPED: price back through the broken level by this much, no new extreme since
        "zone_dollars": 0.50,           # the breakout crowd = orders within this much of the level ...
        "count_minutes": 15,            # ... in this long after the break (not buyers hours later or dollars higher)
        "hod_min_age_seconds": 120,     # a high / low of day counts as a level once it has stood this long (not every tick of a run)
        "min_shares": 1000,             # call it (alert + voice) only when at least this many shares are caught (the box shows every one)
        "memory_minutes": 60,           # a break is forgotten after this long
        "max_breaks": 6,                # breaks kept per ticker
        "show": 3,                      # breaks shown in the box
    },
    "trap": {
        # aggressive prints (paid the offer / hit the bid) this far back that are now
        # underwater count as trapped
        "window_seconds": 600,
        # ignore below this many trapped shares
        "min_shares": 2000,
        # "heavy" when trapped shares reach this
        "heavy_shares": 10000,
        # TRAPPED on the day: the strong move that reversed. Shares bought above the current price since the open
        # (longs) or sold below it (shorts) as a share of the session's volume, and how far price has come off the
        # session high / low before it counts
        "session_lean_fraction": 0.20,
        "session_heavy_fraction": 0.35,
        "session_min_move_pct": 1.0,
        # ... and the crowd's average at least this far underwater, with the session extreme set at least this
        # many minutes ago (a move that reversed, not chop inside a range)
        "session_min_under_pct": 1.0,
        "session_min_minutes_since_extreme": 15,
        # the trapped crowd's average (their exit) stays a level on the chart this long after the call
        "session_exit_memory_seconds": 3600,
        "session_flow_min_dollars": 100000,
    },
    "health": {
        "l1_stale_seconds": 15.0,
        "depth_stale_seconds": 15.0,
        "tape_stale_seconds": 60.0,
    },
    "trading": {
        # Order entry from the ladder. PAPER ONLY unless allow_live is true.
        "enabled": True,
        # OFF: orders go only to a PAPER account (DU…), a live account is refused. ON: with TWS logged into your
        # live account (port 7496) orders are REAL MONEY and the status strip pulses LIVE TRADING. After RESTART NOW.
        "allow_live": False,
        "default_shares": 100,
        "max_shares_per_order": 500,
        "max_dollars_per_order": 25000,
        "max_orders_per_minute": 10,
        # attach the play's stop + target to every entry
        "bracket": True,
        # "Flatten" uses a limit this many ticks through the market
        "flatten_slip_ticks": 5,
        # biggest position (shares) TWINEY will let you build in one symbol
        "max_position_shares": 1000,
        # day P&L (realized + open) at or below -this disarms trading for the rest of the session
        "max_daily_loss": 500,
        # the daily loss lock guards a LIVE (real money) account. On paper / practice it locks only if you switch this on
        "loss_limit_on_paper": False,
        # (retired: an earlier switch for the same thing — ignored, kept so a saved config still loads)
        "loss_limit_live_only": True,
        # PS60 exits: cash-flow scale-outs, runner to the target (measured potential), stop to
        # breakeven after the first cash flow. Off = plain stop + target bracket.
        "scale_plan": {
            "enabled": False,
            "cash_flow": [{"fraction": 0.5, "dollars": 0.50}, {"fraction": 0.25, "dollars": 1.50}],
            "breakeven_after_cash_flow": True,
            # SCALE PLAN on a position: rungs measured from your average entry. move = dollars a share in your
            # favour; TAKE pct = that share of what is LEFT comes off at the touch; ADD pct = that share of the
            # position is added at the touch. MP = a measured-potential trade with room (Dan: a dollar, take a
            # quarter; two, take a third; let the rest ride to the target). CASH = a continuation / cash-flow
            # trade: the move is mostly made, so take more, sooner. BUILD = add on strength first, then scale out
            "templates": {
                "MP": [{"move": 1.0, "action": "TAKE", "pct": 25}, {"move": 2.0, "action": "TAKE", "pct": 33}, {"move": 4.0, "action": "TAKE", "pct": 50}],
                "CASH": [{"move": 0.5, "action": "TAKE", "pct": 33}, {"move": 1.0, "action": "TAKE", "pct": 50}, {"move": 2.0, "action": "TAKE", "pct": 100}],
                "BUILD": [{"move": 0.5, "action": "ADD", "pct": 50}, {"move": 1.5, "action": "TAKE", "pct": 33}, {"move": 3.0, "action": "TAKE", "pct": 50}],
            },
            "auto_default": True,
        },
        # stops go out as STOP-LIMIT (never a naked stop): limit this many ticks through the stop
        "stop_limit_ticks": 10,
        # quick size buttons on the ticket and the ladder bar
        "qty_presets": [25, 50, 100, 200, 500, 1000],
        # the SELL 5 / SELL 10 / SELL 20 buttons on a stock position (BUY on a short), and the same for option contracts
        "manage_presets": [5, 10, 20],
        "manage_option_presets": [1, 2, 5],
        # bracket templates: PLAY = the play's own stop + target (and PS60 exits when on); a template brackets from
        # the entry price instead: stop = entry -$0.25, targets at +$0.25 / +$0.50 / +$0.75 with these share shares.
        # Pick one on the ticket; add your own here. "trail" is not sent to IBKR yet (noted in docs).
        "bracket_template": "PLAY",
        "bracket_templates": {
            "QUARTERS": {"stop": 0.25, "targets": [{"offset": 0.25, "pct": 34}, {"offset": 0.50, "pct": 33}, {"offset": 0.75, "pct": 33}]},
            "HALF/ONE": {"stop": 0.50, "targets": [{"offset": 0.50, "pct": 50}, {"offset": 1.00, "pct": 50}]},
            "ONE/TWO": {"stop": 1.00, "targets": [{"offset": 1.00, "pct": 50}, {"offset": 2.00, "pct": 50}]},
        },
        # market and naked stop entries stay off unless you turn this on (Dan: limit ~99%)
        "allow_market": False,
        # AUTO 2ND ENTRY: the 2nd entry you draw becomes a stop-limit entry (limit this many ticks through it) with
        # the play's stop + target attached, sized from risk_dollars, placed while ARMED, one entry per drawn level
        "auto_second_entry": True,
        "auto_entry_limit_ticks": 10,
        # ...or this % of the price, whichever is more: the most past the 2nd entry the entry may fill (a cap, not
        # the fill price). Too tight and a fast print through the level leaves the order unfilled
        "auto_entry_max_slip_pct": 0.3,
        # drawing a 2nd entry while DISARMED arms the desk (paper / practice accounts only; never when locked)
        "auto_arm_on_second_entry": True,
        # a 2nd entry drawn with no stop on its side gets a STOP this many dollars away (under a long, over a short);
        # drag it where you want it. 0 = off
        "auto_stop_dollars": 1.0,
        "sim_options_after_hours": True,
        "outside_rth": True,            # stock limit / stop-limit orders work in the premarket and after hours too (IBKR outsideRth)
        "sim_options_force": False,
        # when an auto-entry trade goes flat (stopped out, target, flatten) its 2nd entry, stop and target lines go
        "clear_lines_when_flat": True,
        # CHART TRADING: on any open position the STOP / TARGET lines are its exit orders (draw = order in, drag = moved)
        "lines_are_exits": True,
        # the first start of each day comes up with clean charts (no pivot, 2nd entry, stop or target lines) — you draw today's; a restart later the same day keeps them
        "clean_chart_on_start": True,
        # a contract you hold is stopped out by the stock chart's STOP line (the side that hurts it) unless you set its own stop
        "option_stop_follows_chart": True,
        # BACKUP STOP at IBKR for a contract you hold: the desk fires your option stops itself (on the stock's price or
        # the contract's), so they need the desk running. This puts a real stop-limit order on the contract at IBKR,
        # at its price where your stop is (a little past it, so the desk's own stop goes first): it protects you with
        # the desk or the computer off. Sized to what you hold, it follows your stop, and comes off when you are out
        "option_backup_stop": True,
        # Backup stop: how far past the contract's price at your stop it sits (% of that price, at least a nickel)
        "option_backup_cushion_pct": 15,
        # Backup stop: once it triggers, how far it may sell down (buy up) to get you out (% of the trigger, at least a dime).
        # Wide on purpose: a contract can gap straight through a tight limit and never fill
        "option_backup_limit_pct": 50,
        # Backup stop: GTC stays at IBKR across days (until it fills or the desk takes it off); DAY ends at the close
        "option_backup_tif": "GTC",
        # A contract's TARGET (on the stock chart or the option chart) takes this % of your contracts (100 = all of them;
        # 50 = half at the target, the rest runs). At least one contract; with one contract it is all
        "option_target_take_pct": 100,
        # After a part comes off at the TARGET, the rest's stop goes to what you paid (breakeven) when the contract is over it
        "option_target_rest_be": True,
        # SELL TO OPEN (writing a contract you don't own: you are SHORT). Off: only covered calls (100 shares each). Your
        # IBKR account also needs the option level for it; a naked short call has no ceiling on the loss
        "allow_sell_to_open": False,
        # EXPIRATION DAY: contracts that expire today are called out at expiry_warn_at (New York time) and, with
        # expiry_auto_close on, closed at the touch at expiry_close_at so a long in-the-money one is never exercised
        # into shares overnight (and a short one is bought back before assignment)
        "expiry_auto_close": True,
        "expiry_warn_at": "15:30",
        "expiry_close_at": "15:50",
        # the FILLED chip on the 2nd entry line goes this many seconds after the fill
        "filled_chip_seconds": 90,
        "risk_dollars": 100,
    },
    "ps60": {
        # candle size the second entry is judged on (1 or 5); Dan: "always on a new candle"
        "second_entry_tf": 1,
        # a pullback counts as the retrace once it is this fraction of the pivot-to-new-high move (min 3 ticks)
        "min_retrace_fraction": 0.25,
        # after the second entry price should be going the right way within this long
        "build_seconds": 120,
        # your measured potential (plays.json "mp") vs your ATR ("atr"): CLEAR at or above this ratio, THIN below
        "clear_ratio": 0.5,
        # if a play has no "atr", compute one from IBKR daily bars (off: no ATR until you enter one)
        "atr_from_bars": False,
        "atr_days": 14,
        # sneaky pivots on the 60-minute: micro range height cap (x ATR), min candles, min MP $
        "sneaky_max_height_atr": 1.25,
        "sneaky_min_candles": 2,
        "sneaky_min_mp": 0.50,
        # remount / rejection calls at your levels: through the level and back within this window
        "remount_window_seconds": 1800,
        "remount_alerts": True,
    },
    "account": {
        # show your pending orders, positions and today's fills (read-only view)
        "show": True,
        "orders_refresh_seconds": 3.0,
        "fills_refresh_seconds": 10.0,
    },
    "chart": {
        # load the last days of 1-minute bars from IBKR at startup (chart context + 60-minute candles)
        "history": True,
        # False: the 1-minute history and the intraday charts include the premarket and after hours (the premarket
        # high / low / close are then measured off the 1-minute bars). VWAP still starts at 9:30, high / low of day
        # and the daily candle stay the regular session
        "regular_hours_only": False,
    },
    "voice": {
        # spoken call-outs: big size showing up at a price, and big size pulled / hit
        "min_shares": 5000,
        # don't repeat the same price on the same side within this many seconds
        "repeat_seconds": 20.0,
    },
    "quantdata": {
        # your Quant Data API key goes here and nowhere else (never in chat, recordings or exports)
        "api_key": "",
        "base_url": "https://api.quantdata.us",
        "flow_path": "/v1/options/tool/order-flow/consolidated",
        # equity prints (lit and dark venues): the day's big stock prints, shown in EQUITY FLOW
        "equity_enabled": True,
        "equity_path": "/v1/equities/tool/equity-prints",
        "equity_poll_seconds": 10,
        # equity prints under this many dollars are left out (the tape shows every print; this is the size that matters)
        "equity_min_dollars": 500000,
        "method": "POST",
        "poll_seconds": 5,
        "limit": 200,
        # "all" = the whole market's flow in the feed (the unusual call is still watchlist-only); "watchlist" = only your symbols
        "scope": "all",
        "extra_params": {},
    },
    "flow": {
        # BIG MONEY: option prints at least this big are remembered for big_money_days, with how their buyers are doing
        "big_money_min_premium": 500000,
        "big_money_days": 30,
        # UNUSUAL CALLS / PUTS: this much premium, in this many prints, bought at the ask, this far out of the money,
        # this close to expiry, inside this window, on a watchlist symbol. One call per symbol and side per repeat_minutes.
        "min_premium": 250000,
        "min_prints": 2,
        "otm_pct": 3.0,
        "max_dte": 30,
        "window_minutes": 10,
        "repeat_minutes": 20,
        # index products (SPY, QQQ, SPX, IWM ...) trade huge premium all day: they need far more to count as unusual
        "index_symbols": ["SPY", "QQQ", "SPX", "SPXW", "XSP", "NDX", "NDXP", "IWM", "RUT", "DIA", "VIX"],
        "index_min_premium": 5000000,
        "index_min_prints": 3,
        # "watchlist" = UNUSUAL alerts only for your watchlist; "all" = every ticker in the feed (switchable in the window)
        "alerts": "watchlist",
        # speak unusual flow for every watchlist symbol, not only the active tab
        "voice_all": True,
        # NO FLOW, NO DOUGH: a READY setup is held at WATCH until short-dated out-of-the-money money keeps coming in
        # on the play's side (calls for a long, puts for a short): dough_min_dollars bought at the ask across at
        # least dough_min_minutes separate minutes inside dough_window_minutes, the last of it inside
        # dough_fresh_minutes. Off = flow is shown but never holds the grade
        "no_flow_no_dough": True,
        # CONVICTION BOARD (Dan's option-flow timing, from the source-of-truth spec): the flow gate
        "of_premium_min": 100000,      # R2: premium meaningful, at least ~$100K (one print, or the cluster stacked)
        "of_dte_green": 10,            # R3: weeklies / next week = green
        "of_dte_max": 21,              # R3: still short-term; past this, months out is not the same trade
        "of_otm_min_pct": 1.0,         # R4: clearly out of the money; nearer the spot is not a directional bet
        "of_repeat_min": 2,            # R5: multiple repeat buyers on the same expiry series
        "of_fresh_minutes": 30,        # a cluster with nothing new for this long is FADING
        "of_hedge_updays": 3,          # R9: near-spot puts after this many up days = a hedge
        "of_session_minutes": 390,     # the prints the board looks back over (the session)
        "of_scan_cooldown_minutes": 30,  # market-wide FLOW WATCH (flow alerts on ALL): one call per ticker and side
        "dough_window_minutes": 30,
        "dough_min_dollars": 300000,
        "dough_min_minutes": 3,
        "dough_fresh_minutes": 10,
        "dough_max_dte": 7,
        "dough_min_otm_pct": 0.5,
        # a play whose flow leans hard the other way is held at WATCH instead of READY (0 turns this off)
        "against_bias": 0.6,
        "against_min_premium": 500000,
        # URGENT FLOW: a short-dated, out-of-the-money contract getting bought at the ask again and again. It makes the
        # list from one print; it gets CALLED once it has this many prints and dollars inside the window
        "urgency_window_minutes": 10,
        "urgency_min_prints": 3,
        "urgency_min_dollars": 250000,
        "urgency_max_dte": 7,
        "urgency_min_otm_pct": 0.5,
        "knows_min_minutes": 2,         # SOMEBODY KNOWS SOMETHING needs prints in at least this many separate minutes (one print is a guess)
        "urgency_cooldown_minutes": 15,
    },
    "demo": {
        # practice day type: null = a random one each session; or mixed, trend_up, trend_down, chop, capitulation, squeeze
        "scenario": None,
    },
    "orderflow": {
        # rolling delta windows and the pressure labels (see twiney/orderflow.py for the exact rules)
        "short_seconds": 5,
        "long_seconds": 15,
        "lean": 0.25,        # |delta| / (buy + sell) over the long window: BUYING / SELLING PRESSURE from here
        "strong": 0.60,      # ... STRONG from here
        "min_prints": 8,     # fewer prints than this in the long window: QUIET, no label
    },
    "ladder": {
        # THE BASKET LADDER: money on the outside, shares next in, PRICE + BASKET in the centre. The BASKET is every
        # confirmed trade at that price today (bought + sold + between), a running total that each trade adds to
        # once; a new trade drops into it from its side (sold = from the bid, bought = from the ask) with a pulse
        "basket_drop_ms": 250,          # animation speed: a drop takes this long (the pulse 150 ms at the default)
        "basket_merge_ms": 50,          # prints at one price inside this window drop in as ONE bigger drop, one pulse
        "basket_max_drops": 12,         # drops on screen at most; more are counted, not animated
        "basket_fast_pps": 25,          # FAST MODE above this many prints a second: only your levels and the PS60 rows animate
        "basket_full_x": 3,             # a FULL basket = this many times a price's normal volume today (heavy defense)
        "basket_animate": True,         # the drops
        "basket_pulse": True,           # the pulse (one per print, one per refill)
        "basket_glow": True,            # the glow (refill speed)
        "basket_flip_alerts": True,     # FLIP calls and the FLIP banner
        "basket_touch_counter": True,   # the small counter on the trigger / second entry rows (resets each touch)
        "basket_sequence": True,        # the PS60 SEQUENCE over the ladder
        "basket_manual_pop": True,      # your SECOND ENTRY / TAKE PROFIT / STOP rows pop (display only, never an order)
        "flip_min_shares": 1000,        # FLIP: at least this much size from the other side at the price ...
        "flip_hold_seconds": 2,         # ... held this long (a thin print never flips a level) ...
        "flip_mirror_seconds": 60,      # ... and not the other way at the same price within this long of one ending
        "flip_dead_seconds": 20,        # ... after the defender's refill died (no refill this long, or NOT RELOADING / CLEANED UP / PULLED)
        # the rows stay still while price moves inside them; they re-centre only when price comes within this many
        # rows of the top or bottom edge (bigger = re-centres sooner)
        "recenter_rows": 4,
        # SOLD / BOUGHT "this visit": a visit to a price ends when price trades this many ticks away from it (Jigsaw
        # resets on any tick away, which in a stock flickers the numbers to zero all day)
        "visit_away_ticks": 3,
        # PULL / STACK: seconds of size added (stacked) / pulled without trading, per price
        "stack_seconds": 60,
        # option flow STRIKES outlined on the ladder: a strike with at least this premium today (top 4)
        "strike_min_premium": 100000,
        "strike_max_dte": 7,
        "strike_otm_only": True,
        # rows above and below the market on the ladder (the COLS menu changes it live)
        "half_rows": 12,
        # a displayed size at or above this is "big": highlighted on the ladder, and counted every time it shows up
        # at that price. Adjustable per symbol from the LEVEL II window; that override wins over this default.
        "big_shares": 5000,
        # big × this = "huge": the strongest highlight
        "huge_multiple": 3.0,
        # option flow marks on the ladder: a print of at least this premium is marked on the row where the stock was
        # trading when it hit (index products need far more). Marks stay this many minutes. A strike that keeps getting
        # bought, expiring inside flow_short_dte days, is the hot one: it gets the ring, and a REPEAT FLOW call
        "flow_min_premium": 100000,
        "flow_index_min_premium": 1000000,
        "flow_window_minutes": 60,
        "flow_short_dte": 7,
        "flow_repeat_prints": 2,
        "flow_repeat_minutes": 30,
        "flow_repeat_cooldown_minutes": 15,
        # REAL or FAKE size: of the size that left a price, how much traded vs vanished. A drop that comes straight
        # back inside this many seconds is one venue re-quoting, not a pull
        "requote_seconds": 1.0,
        # the ladder only shows REAL / MIXED / FAKE at a price once this many shares have left it
        "real_min_shares": 2000,
        # how long a price keeps its REAL / FAKE record after the last change (seconds)
        "real_memory_seconds": 3600.0,
    },
    # the chart studies on the STOCK chart (never the option chart), ported from your TradingView scripts. Each
    # one switches off on its own; the numbers match TradingView: Wilder ATR, the chart's own EMAs / SMAs / BB
    # PACE OF TAPE: how fast each stock trades against its own normal (the last 20 minutes), and the calls at your
    # levels: STALLING INTO, PRESSING, BREAKOUT / BREAKDOWN WITH SPEED (+ FLOW when option flow backs it), BREAK WITHOUT SPEED
    "pace": {
        "enabled": True,                # read the pace of tape (ladder, T&S, calls)
        "alerts": True,                 # call the moments: stalling / pressing / breakout with speed / break without speed
        "voice": True,                  # say them out loud (when voice is on)
        "use_levels": True,             # read against your lines and the chart studies' levels
        "surge_ratio": 2.5,             # SURGE: at least this x its normal pace (and faster than 90% of the last 20 min)
        "fast_ratio": 1.6,              # FAST: at least this x its normal pace
        "slow_ratio": 0.6,              # SLOW: at most this x its normal pace
        "dry_ratio": 0.35,              # DRYING UP: at most this x its normal pace
        "stall_ratio": 0.8,             # STALLING INTO a level: within reach and the tape at most this x normal (or slowing)
        "break_ticks": 3,               # a BREAK: price at least this many ticks through the level
        "break_ratio": 1.8,             # BREAKOUT WITH SPEED: the tape at least this x normal through the level
        "aggress_pct": 60,              # ... and at least this % of the aggressive shares on the break's side
        "near_ticks": 5,                # within reach of a level: this many ticks ...
        "near_pct": 0.03,               # ... or this % of price, whichever is wider
        "flow_minutes": 15,             # + FLOW: option prints on the break's side in the last N minutes
        "flow_min_premium": 100000,     # + FLOW: at least this much premium bought at the ask
        "repeat_seconds": 120,          # a call at the same level is not repeated for this long
    },
    # THE DESK'S VOICE: the browser's own voice, or a cloud voice (ElevenLabs) that never changes: every call in it
    "speech": {
        "engine": "auto",               # auto = your ElevenLabs voice whenever a key and voice are in (else the browser's) · cloud · browser
        "api_key": "",                  # the voice service's API key (kept in your config only, never in recordings)
        "voice_id": "",                 # the voice's ID (ElevenLabs: My Voices > the voice > copy ID), or its exact name (dan)
        "model": "eleven_turbo_v2_5",   # the voice model (turbo: fast enough for live calls)
        "stability": 0.5,               # 0-1: steadier delivery (higher) or more expressive (lower)
        "similarity": 0.8,              # 0-1: how closely it holds to the voice
        "speed": 1.05,                  # 0.7-1.2: speaking speed
        "base_url": "https://api.elevenlabs.io",
        # The voice says a stock's name, never its ticker: about 590 built in (AAPL = Apple, NVDA = Nvidia, SPY = the S&P), else IBKR's company name. Your own names here win: AAPL=Apple, BRK B=Berkshire
        "names": "",
    },
    # INSTITUTIONAL FOOTPRINTS: a fund's large order sliced by an execution algo (VWAP / % of volume), read off the tape
    "inst": {
        "enabled": True,                # the INST strip, calls and voice
        "voice": True,                  # say new programs / fund-style reloaders / walking (the tab you are on)
        "min_slots": 8,                 # STEADY BUYING / SELLING: at least this many 5-minute slots today (40 min) before reading one
        "window_slots": 18,             # ... read over the last this many slots (90 minutes)
        "agree": 0.7,                   # ... the same side won at least this share of them
        "min_part": 0.06,               # ... and its net imbalance is at least this share of all volume
        "steady": 0.45,                 # ... at a steady share of each slot's volume in at least this share of them
        "call_score": 75,               # call it from this score (0-100)
        "fund_show": 50,                # FUND score per level (0-100): tag it on the ladder from this ...
        "fund_call": 70,                # ... and call it from this
        "same_size_min_refills": 4,     # same refill size: at least this many refills ...
        "same_size_share": 0.6,         # ... and this share of them showing the same size
        "walk_minutes": 20,             # WALKING: the same side's reloads within this many minutes ...
        "walk_steps": 3,                # ... stepping one way at least this many prices
        "child_minutes": 12,            # CHILD ORDERS: the same size again and again on one side at a steady clock, over the last this many minutes ...
        "child_min_prints": 25,         # ... at least this many prints of that size (the top one or two sizes)
        "child_max_gap": 20,            # ... typically one every this many seconds or less
        "child_min_span_minutes": 8,    # ... and the stream keeps going for at least this long, in every quarter of its span (a crowd chasing a push prints in a burst)
        "child_regular": 0.6,           # ... this share of the gaps on the algo's clock (within a third to three times the typical gap)
        "child_one_way": 0.4,           # ... the one side's EXCESS of that size over the other side (the crowd's baseline) is at least this share of its prints
        "child_score": 60,              # ... call it from this score (0-100)
        "repeat_seconds": 1200,         # the same call is not repeated for this long
        "every_seconds": 5,             # read every this many seconds
    },
    # DARK POOL: trades printed off the exchanges (FINRA / TRF / ADF / OTC), where funds route much of their size
    "dark": {
        "enabled": True,                # track large off-exchange orders (T&S L tag, LARGE ORDERS strip, ladder L $ at prices)
        "big_shares": 10000,            # a LARGE ORDER: at least this many shares ...
        "big_usd": 200000,              # ... or this many dollars
        "alert_usd": 2000000,           # call it out (alert + voice on the tab you are on) from this many dollars
        "call_gap_seconds": 120,        # ... at most one call per stock this often, unless a print is twice the last one called
        "voice": True,                  # say the big ones
    },
    "levels": {
        "enabled": True,                # KEY LEVELS WATCH: REJECTED / BOUNCED / BUYERS TOOK / SELLERS TOOK at the daily and session levels
        "voice": True,                  # say them (the ticker you are on)
        # FOLLOW-UP: after a bunch of calls at one level, say how it came out (defended, lost, broke through, reclaimed) in plain words
        "followup": True,
        # Follow-up: say it this many minutes after the back and forth started at the earliest ...
        "followup_min_minutes": 5,
        # ... and by this many minutes at the latest (it waits for a quiet minute in between)
        "followup_max_minutes": 7,
        # Follow-up: only after at least this many calls at that level (coming into it, at it, bounced, rejected, taken)
        "followup_min_alerts": 3,
        # Follow-up: a quiet stretch with no new call at the level before it is said (seconds)
        "followup_quiet_seconds": 60,
        # Follow-up: still sitting on the level when due: look again this many minutes later, then say it as it is
        "followup_recheck_minutes": 4,
        "near_ticks": 6,                # COMING INTO a level: within this many ticks and travelling toward it ...
        "near_atr_pct": 8,              # ... or this % of the daily ATR (the ladder lights the level's price from here too)
        "zone_ticks": 2,                # AT a level: within this many ticks ...
        "zone_atr_pct": 1,              # ... or this % of the daily ATR, whichever is wider (said exactly: on it, or N cents under / over)
        "test_ticks": 4,                # TESTED a level without printing on it: came within this many ticks ...
        "test_atr_pct": 3,              # ... or this % of the ATR, then turned back = BOUNCED (from above) / REJECTED (from below)
        "away_ticks": 8,                # REJECTED / BOUNCED: back the way it came at least this many ticks ...
        "away_atr_pct": 10,             # ... or this % of the ATR
        "hold_seconds": 60,             # TOOK: through it and held for this long
        "repeat_seconds": 300,          # the same call at the same level not again for this long
        "touch_minutes": 15,            # a touch that does nothing for this long is forgotten
    },
    "story": {
        "enabled": True,                # the PS60 STORY: Daily context + PS60 places + tape + Level II + option flow + price response
        "alerts": True,                 # put the big moments in CALLS (breaks, reloads consumed, flow confirming / conflicting, retests)
        "voice": True,                  # say the story's moments out loud (the levels taken, the averages, the Daily, the 60-minute candle): the tab you are on
        "whole_half_reloads_only": False,  # on: only reloads at x.00 / x.50 count for PS60. Off (default): every real reload counts, round numbers are just highlighted
        "draw_zones": True,             # shade the zones you drew on the stock chart (right-click the chart, ZONE)
        "near_ticks": 8,                # HIGH ATTENTION: price within this many ticks of a place ...
        "near_atr_pct": 12,             # ... or this % of the daily ATR ...
        "near_pct": 0.15,               # ... or this % of price, whichever is widest
        "confluence_atr_pct": 6,        # places within this % of the ATR of each other are one place
        "major_score": 6,               # MAJOR confluence: weight at least this (pivot / 2nd entry / your line 3, day / week / month 2, whole dollar 1)
        "flow_minutes": 20,             # option flow read over the last N minutes
        "flow_max_dte": 7,              # ... only contracts expiring within this many days (same week: the same rule as SOMEBODY KNOWS SOMETHING)
        "deep_otm_pct": 5.0,            # DEEP OTM: at least this % out of the money (counts 1.5x; near the money counts less)
        "develop_premium": 50000,       # DEVELOPING: at least this much (weighted) premium bought at the ask on the move's side
        "confirm_premium": 250000,      # CONFIRMED: at least this much ...
        "confirm_repeats": 2,           # ... in at least this many separate minutes (one order split in two is one buyer)
        "response_minutes": 5,          # PRICE RESPONSE: what price did over the last N minutes
        "retest_minutes": 30,           # a retest is watched for this long after a break
        "fw_daily_type": "SMA",         # MA FRAMEWORK: the daily 5 / 10 (who controls the 5, the 10 is the birth of the trade): SMA or EMA
        "fw_60m_type": "SMA",           # ... the 60m 5 / 10 (rising 60-minute support / falling 60-minute resistance): SMA or EMA
        "fw_daily_mas": "SMA 5, SMA 10, SMA 20, SMA 50, SMA 100, SMA 150, SMA 200, EMA 5, EMA 10, EMA 20, EMA 50, EMA 100, EMA 150, EMA 200, EMA 34, EMA 65, EMA 89",   # the daily averages whose bounce / reject / close through is called out (the chart's; 34 / 65 / 89 EMA daily only)
        "fw_60m_mas": "SMA 5, SMA 10, SMA 20, SMA 50, SMA 100, SMA 150, SMA 200, EMA 5, EMA 10, EMA 20, EMA 50, EMA 100, EMA 150, EMA 200",       # ... the 60-minute ones (the chart's)
        "ma_repeat_seconds": 600,       # one average: a new call at it at most this often
        "ma_touch_minutes": 20,         # ... a test of it is watched this long for the bounce / reject / close through
        "retrace_repeat_minutes": 30,   # the 60-minute retrace into rising support (pop into falling resistance): said at most this often
        "rule57_min": 5,                # THE 5-7 MINUTE RULE: your trade not moving your way between these minutes after the entry ...
        "rule57_max": 7,                # ... a reload buyer / seller may be sitting there: think about the scratch
        "first_move_dollars": 0.25,     # FINANCE THE TRADE: the first move (at least this, or your risk): pay yourself, stop to breakeven
        "trade_update_seconds": 90,     # YOUR TRADE working: how much MP / airspace is left, said at most this often (and only when it changed)
        "mp_merge_atr_pct": 8,          # MP: averages / levels within this % of the ATR of each other are ONE supply / demand (MP to its far edge)
        "trade_weak_seconds": 180,      # YOUR TRADE in profit, a COMPLETE BREAKDOWN only: the tape one-sided against you AND the market the other way AND tremendous option flow against you, all held this long -> think about paying yourself. A pullback never fires it
        "trade_weak_tape_pct": 75,      # ... the tape one-sided against you: at least this % hitting the other side, and fast
        "trade_weak_flow_min": 250000,  # ... tremendous flow: at least this much premium on the other side in the last couple of minutes, 4x what is with you
        "trade_weak_repeat_seconds": 600,  # ... said at most this often
        "daily_repeat_minutes": 45,     # THE DAILY BRIEF (the brain of the trade): said at the open and again when it changes, else at most this often
        "trade_repeat_seconds": 120,    # YOUR TRADE: close to your stop / at your target, said at most this often
        "close_minutes": 1,             # a place is TAKEN only when a candle of this many minutes CLOSES through it (trading through it is pressing, not a break)
        "mp_min_atr": 0.5,              # ROOM: the measured potential to the next supply (above the 50) / demand (below) is THIN under this many ATRs
        "memory_minutes": 120,          # unusual flow with no PS60 pivot in play is remembered this long
        "play_by_play": True,           # PLAY-BY-PLAY at a place: where price is, who is stepping up, the reload buyer / seller, calls / puts being bought, what it adds up to
        "voice_play_by_play": True,     # say the play-by-play out loud when it changes (voice on)
        "pbp_seconds": 30,              # play-by-play: a new line on the story at most this often
        "pbp_repeat_seconds": 90,       # ... the same read again only after this long
        "pbp_say_seconds": 60,          # ... said out loud at most this often, and only when the read changes
        "pbp_flow_seconds": 120,        # ... calls / puts bought over the last N seconds
        "pbp_flow_min": 25000,          # ... option premium under this is no real flow
        "pbp_quiet": False,             # off: when nothing is going on at the place (no tape, no book, no option flow) the chart stays quiet
        "hype": True,                   # THE EXCITEMENT: deep out-of-the-money calls / puts hit, or one strike pounded again and again ("they're pounding the 300s non stop!")
        "voice_hype": True,             # say it out loud (voice on)
        "hype_min_premium": 75000,      # ... at least this much on that one strike in the last couple of minutes
        "hype_pound_prints": 4,         # ... POUNDED: at least this many prints on the one strike
        "hype_repeat_seconds": 180,     # ... the same strike again only when it grows, and not before this long
        "coach": True,                  # THE COACH at a place: stay patient, before 10 o'clock give it time, the first pivot of the day wants more context
        "voice_coach": True,            # say the coach's words out loud (voice on)
        "coach_wait_until_hour": 10,    # before this hour (New York), the coach says give it until then
        "coach_patience_seconds": 90,   # a fight with no side winning this long: stay patient, hang in there
        "coach_seconds": 180,           # the patience words at most this often
        "coach_reload_repeat_seconds": 120,  # a reload buyer / seller at the place: be careful, said again this often while he is STILL THERE
    },
    "studies": {
        "gas": True,                    # GAS + ATR (new PS60 Gas + ATR)
        "airspace": True,               # AIRSPACE (PS60 MP Airspace)
        "unvisited": True,              # UNVISITED HIGHS / LOWS (new Unvisited Highs Lows)
        # THE LOOK: labels and lines (live: SAVE and the chart redraws)
        "lbl_size": 9,                  # label text size (px)
        "lbl_gap_bars": 2,              # labels start this many bars after the line ends
        "line_back_bars": 8,            # lines start this many bars left of the last candle
        "line_fwd_bars": 3,             # lines run this many bars past the last candle (labels never touch a candle)
        "lbl_space_pct": 40,            # the label area may take up to this % of the chart's width
        "lbl_price": True,              # the price in each label
        "lbl_color_mode": "line",       # label text: the line's colour, or one colour for every label
        "col_label": "#111111",         # label text colour when one colour for every label
        "lw_pd": 2,                     # line width: prev day high / low, old supply / demand
        "lw_atr": 2,                    # line width: 1 ATR (2 / 3 ATR are one thinner)
        "lw_levels": 1,                 # line width: the other GAS levels
        "lw_bounce": 2,                 # line width: Bounce / Reject
        "lw_mt": 3,                     # line width: MT supply / demand
        "lw_uv": 1,                     # line width: unvisited highs / lows (a merged line is 2 thicker)
        "zone_opacity": 18,             # ATR zone colours: opacity (%)
        "col_pd": "#e91e8c",            # colour: prev day high / low
        "col_pdc": "#e91e8c",           # colour: prev day close
        "col_pm": "#e91e8c",            # colour: premarket high / low
        "col_ah": "#ef6c00",            # colour: after-hours high / low
        "col_open": "#607d8b",          # colour: today's open
        "col_hl": "#757575",            # colour: high / low of day
        "col_old_supply": "#c62828",    # colour: old supply
        "col_old_demand": "#2e7d32",    # colour: old demand
        "col_atr_live": "#26a69a",      # colour: ATR level still reachable
        "col_atr_spent": "#ef5350",     # colour: ATR level traveled
        "col_zone1": "#26a69a",         # colour: zone range to 1 ATR
        "col_zone2": "#ffd500",         # colour: zone 1 to 2 ATR
        "col_zone3": "#8a00ff",         # colour: zone 2 to 3 ATR
        "col_zone_spent": "#ef5350",    # colour: zone eaten (ATR traveled)
        "col_whole": "#9e9e9e",         # colour: whole numbers
        "col_box": "#42a5f5",           # colour: daily box
        "col_tight_box": "#f5a623",     # colour: tight box
        "col_earnings": "#00bcd4",      # colour: earnings reaction high / low
        "col_2nd": "#6a1b9a",           # colour: second entry
        "col_bounce": "#26a69a",        # colour: Bounce
        "col_reject": "#ef5350",        # colour: Reject
        "col_mt_supply": "#e91e63",     # colour: MT supply Nx
        "col_mt_demand": "#00b8d4",     # colour: MT demand Nx
        "col_uv_high": "#ef5350",       # colour: unvisited high
        "col_uv_low": "#26a69a",        # colour: unvisited low
        "col_uv_high_cluster": "#ff9800",   # colour: merged unvisited highs
        "col_uv_low_cluster": "#00bcd4",    # colour: merged unvisited lows
        # GAS + ATR
        "atr_len": 14,                  # ATR length (days)
        "atr_smoothing": "RMA",         # RMA (Wilder, TradingView's ATR), EMA, SMA or WMA
        "gas_readout": True,            # the gas tank readout (bottom right)
        "atr_levels": True,             # 1 / 2 / 3 ATR levels off today's range
        "atr_zones": True,              # THE ATR LADDER: quarter-ATR rungs, the part price has eaten coloured hotter as the tank empties
        "atr_ladder_step": 0.25,        # ATR ladder: one rung every this many ATRs
        "atr_ladder_max": 3.0,          # ATR ladder: rungs up to this many ATRs (3 ATR like the GAS script)
        "atr_ladder_opacity": 32,       # ATR ladder: how strong the part price HAS eaten is coloured (0-100)
        "atr_ladder_left_opacity": 4,   # ATR ladder: how faint the part price has NOT eaten yet is (0-100)
        "atr_one_side": True,           # the ATR ladder only on the side the day is moving
        "atr_halves": False,            # 1.5 / 2.5 ATR too
        "open_line": True,              # today's 9:30 open (locked)
        "prev_day": True,               # prev day high / low / close
        "premarket": True,              # premarket high / low / close (locked at 9:30, from the 1-minute bars)
        "after_hours": True,            # the last completed after-hours high / low / close
        "old_supply_demand": True,      # last finished month's high (old supply) / low (old demand)
        "whole_numbers": False,         # whole-number lines
        "whole_above": 3,               # whole numbers above price
        "whole_below": 3,               # whole numbers below price
        "whole_step": 0.0,              # whole-number step (0 = auto: $5 over 200, $1 over 80, else $0.50)
        "daily_box": False,             # the daily box (last N days)
        "box_len": 10,                  # daily box lookback (days)
        "box_tight_only": True,         # only draw the box when it is tight
        "box_tight_x": 4.0,             # tight = box range up to this x ATR
        "tight_box": False,             # TIGHT BOX master: replaces the daily box, its edges become the 2nd-entry pivots
        "tb_window": 10,                # tight box window (completed days)
        "tb_max_x": 2.0,                # a real tight box is at most this x ATR tall
        "tb_reject_wild": True,         # no wild bars allowed in the tight box
        "tb_wild_x": 1.8,               # wild bar = range over this x the window's average
        "second_entry": True,           # second-entry helper (pivot = your pivot on the chart, or the tight box)
        "se_retrace_pct": 30.0,         # 2nd entry: retrace % of the first push
        "se_min_retrace_x": 0.3,        # 2nd entry: and at least this x ATR
        "se_near_x": 0.15,              # 2nd entry: NEAR within this x ATR
        "se_hour_reset": True,          # 2nd entry: miss the 60, need a new second
        "h60_on_hour": True,            # 60-minute candles on the hour (9:00, 10:00 ...) with premarket / after hours, like your TradingView 1h chart (off: from 9:30, regular hours)
        "cont_odds": True,              # continuation odds (similar days, 30-minute sample)
        "cont_tol": 0.15,               # similar day = within this x ATR of today
        "cont_t1": 1.0,                 # odds target #1 (x ATR)
        "cont_t2": 1.5,                 # odds target #2 (x ATR)
        "cont_max_days": 300,           # days in the odds sample
        "cont_min_days": 20,            # days needed before the odds print
        "day_after": True,              # day-after stats (exhaustion read)
        "next_stop": False,             # NEXT STOP lines in the readout
        "earnings_date": "",            # earnings release date YYYY-MM-DD for the reaction bar (blank = off)
        "earnings_next_session": True,  # reaction bar = the next session (after-close report); off = same day
        "label_merge_pct": 0.15,        # (retired: labels now sit at their own line, nudged right when they would touch)
        # AIRSPACE
        "air_board": True,              # the AIRSPACE lights board (top right)
        "air_atr_live": True,           # Airspace ATR distances on the LIVE day's ATR (TradingView Airspace); off = the GAS tank ATR
        "air_min_air": 5.0,             # min MP air ($)
        "air_stack_dollars": 1.0,       # stack levels within $
        "air_stack_atr": 0.20,          # stack levels x ATR (gap limit = the larger)
        "air_bounce_reject": True,      # Bounce / Reject stubs
        "air_bb": True,                 # Bollinger upper / lower count as levels
        "air_range_structure": True,    # range / pivot highs-lows feed the MP band
        "air_rng_lookback": 15,         # range lookback (days)
        "air_pivot_bars": 3,            # pivot bars each side
        "air_weekly_fallback": True,    # Weekly nearest when the Daily is blank
        "air_mt_supply": True,          # MT SUPPLY Nx line
        "air_mt_demand": True,          # MT DEMAND Nx line
        "air_mt_lookback": 80,          # MT lookback (days)
        "air_mt_touches": 3,            # MT min touches
        "air_mt_cluster_dollars": 3.0,  # MT cluster within $
        "air_mt_cluster_atr": 0.10,     # MT cluster x ATR
        "air_mt_takeout_atr": 0.15,     # MT taken out = this x ATR through
        "air_merge_tol": 0.50,          # Bounce / Reject: a chart MA within this $ = confluence
        # UNVISITED HIGHS / LOWS
        "uv_highs": True,               # unvisited highs (supply)
        "uv_lows": True,                # unvisited lows (demand)
        "uv_left": 5,                   # daily pivot left bars
        "uv_right": 5,                  # daily pivot right bars
        "uv_max": 12,                   # max levels each side
        "uv_reach_pct": 0.25,           # within reach % of price = a touch
        "uv_soft_touch": True,          # soft touch: a touch dashes the line, only a daily close through clears
        "uv_cluster_pct": 0.50,         # levels within this % merge into one line
        "uv_age": True,                 # show the age (trading days since the high / low formed) on the label
    },
    "recording": {
        "enabled": True,
        "dir": "recordings",
        # every MARK (M) also takes a screenshot of the screen into recordings/shots (Windows / Mac, needs Pillow)
        "mark_screenshot": True,
    },
}


class ConfigError(ValueError):
    pass


def _merge(base, override, path=""):
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if key.startswith("_"):
            continue  # comment keys such as "_note"
        if key not in base:
            raise ConfigError(f"unknown config key: {path}{key}")
        if isinstance(base[key], dict):
            if not isinstance(value, dict):
                raise ConfigError(f"config key {path}{key} must be an object")
            out[key] = _merge(base[key], value, f"{path}{key}.")
        else:
            out[key] = value
    return out


# settings that must be above zero: a 0 here would switch a safety off or make no sense
POSITIVE = {"trading.default_shares", "trading.max_shares_per_order", "trading.max_dollars_per_order",
            "trading.max_orders_per_minute", "trading.max_position_shares", "trading.max_daily_loss",
            "trading.stop_limit_ticks", "depth.slots", "depth.rows_requested", "depth.rows_displayed"}


def _check_values(cfg):
    """Every number is a real, finite number of the right kind and not negative; the caps and the day loss
    limit are above zero; the scale plan can never exit more shares than the entry or price a leg at <= 0."""
    def walk(d, base, prefix=""):
        for k, dv in base.items():
            path, v = prefix + k, d.get(k)
            if isinstance(dv, dict):
                if path != "quantdata.extra_params":
                    walk(v, dv, path + ".")
                continue
            if isinstance(dv, bool):
                if not isinstance(v, bool):
                    raise ConfigError(f"{path} must be true or false")
                continue
            if isinstance(dv, (int, float)):
                if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                    raise ConfigError(f"{path} must be a number")
                if v < 0:
                    raise ConfigError(f"{path} cannot be negative")
                if isinstance(dv, int) and v != int(v):
                    raise ConfigError(f"{path} must be a whole number")
                if isinstance(dv, int):
                    d[k] = int(v)          # 2.0 in the file is the whole number 2
                if path in POSITIVE and v <= 0:
                    raise ConfigError(f"{path} must be above 0")
    walk(cfg, DEFAULTS)
    legs = cfg["trading"]["scale_plan"]["cash_flow"]
    if not isinstance(legs, list):
        raise ConfigError("trading.scale_plan.cash_flow must be a list of {fraction, dollars}")
    total = 0.0
    for i, leg in enumerate(legs):
        if not isinstance(leg, dict):
            raise ConfigError(f"trading.scale_plan.cash_flow[{i}] must be {{fraction, dollars}}")
        f, d = leg.get("fraction"), leg.get("dollars")
        if isinstance(f, bool) or isinstance(d, bool):
            raise ConfigError(f"trading.scale_plan.cash_flow[{i}]: fraction and dollars must be numbers")
        if not isinstance(f, (int, float)) or not 0 < f < 1:
            raise ConfigError(f"trading.scale_plan.cash_flow[{i}].fraction must be between 0 and 1")
        if not isinstance(d, (int, float)) or not math.isfinite(d) or d <= 0:
            raise ConfigError(f"trading.scale_plan.cash_flow[{i}].dollars must be above 0")
        total += f
    if total > 1 + 1e-9:
        raise ConfigError("trading.scale_plan.cash_flow fractions add up to more than the whole position")
    tpls = cfg["trading"]["scale_plan"].get("templates") or {}
    if not isinstance(tpls, dict):
        raise ConfigError("trading.scale_plan.templates must be {NAME: [{move, action, pct}]}")
    for name, rungs in tpls.items():
        for i, r in enumerate(rungs if isinstance(rungs, list) else []):
            if not isinstance(r, dict) or not isinstance(r.get("move"), (int, float)) or r["move"] <= 0 \
                    or str(r.get("action", "")).upper() not in ("TAKE", "ADD") or not isinstance(r.get("pct"), (int, float)) or not 0 < r["pct"] <= 100:
                raise ConfigError(f"trading.scale_plan.templates.{name}[{i}] must be {{move > 0, action TAKE|ADD, pct 1-100}}")
        if not isinstance(rungs, list) or not rungs:
            raise ConfigError(f"trading.scale_plan.templates.{name} must be a non-empty list")


def build_config(raw=None):
    cfg = _merge(DEFAULTS, raw or {})
    if cfg["depth"]["slots"] < 1:
        raise ConfigError("depth.slots must be >= 1")
    if cfg["depth"]["rows_displayed"] > cfg["depth"]["rows_requested"]:
        raise ConfigError("depth.rows_displayed cannot exceed depth.rows_requested")
    _check_values(cfg)
    if cfg["quantdata"].get("flow_path") == "/v1/options/flow":
        # the old placeholder path, saved before Quant Data's API docs were known: use the documented one
        cfg["quantdata"]["flow_path"] = DEFAULTS["quantdata"]["flow_path"]
    host = cfg["dashboard"]["host"]
    # this computer's own address only (the page checks every request names it)
    loopback = str(host).strip().lower() in ("127.0.0.1", "localhost", "::1")
    if not loopback:
        raise ConfigError("dashboard.host must be a loopback address; TWINEY is a local-only workstation")
    return cfg


def load_config(path):
    if not os.path.exists(path):
        raise ConfigError(f"{path} not found — copy config.example.json to {path}")
    with open(path, encoding="utf-8") as fh:
        return build_config(json.load(fh))


LOAD_WARNINGS = []   # level problems found in plays.json on the last load: said on the desk, never a refusal to start


def _alt_side(raw):
    """A play's OTHER SIDE from plays.json: its own pivot / 2nd entry / stop / target (numbers or nothing)."""
    if not isinstance(raw, dict):
        return None
    out = {}
    for k_in, k in (("pivot", "trigger"), ("trigger", "trigger"), ("second_entry", "second_entry"), ("stop", "stop"), ("target", "target")):
        v = raw.get(k_in)
        try:
            v = float(v) if v not in (None, "") else None
        except (TypeError, ValueError):
            v = None
        if v and v > 0 and out.get(k) is None:
            out[k] = v
    if not out:
        return None
    out["auto"] = bool(raw.get("auto", True))
    return out


def validate_plays(raw):
    items = raw.get("plays") if isinstance(raw, dict) else raw
    if not isinstance(items, list) or not items:
        raise ConfigError("plays file must contain a non-empty list of plays")
    plays, seen = [], set()
    LOAD_WARNINGS.clear()
    for i, item in enumerate(items):
        where = f"play #{i + 1}"
        if not isinstance(item, dict):
            raise ConfigError(f"{where} must be an object")
        sym = str(item.get("symbol", "")).strip().upper()
        if not sym:
            raise ConfigError(f"{where}: symbol is required")
        where = f"play {sym}"
        if sym in seen:
            raise ConfigError(f"{where}: duplicate symbol")
        seen.add(sym)
        side = str(item.get("side", "long")).strip().lower()
        if side not in ("long", "short"):
            raise ConfigError(f"{where}: side must be 'long' or 'short'")

        def num(key, required):
            v = item.get(key)
            if v is None:
                if required:
                    raise ConfigError(f"{where}: {'pivot' if key == 'trigger' else key} is required")
                return None
            try:
                v = float(v)
            except (TypeError, ValueError):
                raise ConfigError(f"{where}: {key} must be a number")
            if v <= 0:
                raise ConfigError(f"{where}: {key} must be > 0")
            return v

        extra = []
        for v in item.get("extra_levels") or []:
            try:
                fv = float(v)
            except (TypeError, ValueError):
                raise ConfigError(f"{where}: extra_levels must be numbers")
            if fv <= 0:
                raise ConfigError(f"{where}: extra_levels must be > 0")
            extra.append(fv)

        if item.get("pivot") is not None and item.get("trigger") is None:
            item = dict(item, trigger=item["pivot"])
        # a ticker with no pivot yet (typed in, or a clean chart) is watch-only: never an error that stops TED starting
        watch = bool(item.get("watch", False)) or item.get("trigger") in (None, "")
        trigger, second = num("trigger", not watch), num("second_entry", False)
        if trigger is None and not watch:
            raise ConfigError(f"{where}: pivot is required")
        if second is not None and trigger is not None:
            # PS60: the 2nd entry is normally beyond the pivot (the new high / low after the break). Levels drawn on
            # the desk are saved as drawn, so a 2nd entry behind the pivot is said on the desk, never a reason the
            # desk will not start
            if (side == "long" and second <= trigger) or (side == "short" and second >= trigger):
                LOAD_WARNINGS.append(f"{sym}: 2nd entry {second:g} is {'under' if side == 'long' else 'over'} the pivot "
                                     f"{trigger:g} for a {side} — kept as you drew it; check the side or the pivot")
        mp_level = num("mp", False) or num("target", False)
        if mp_level and trigger and mp_level < 0.5 * trigger:
            # an old file with mp in dollars: turn it into the level it meant
            mp_level = round(trigger + mp_level if side == "long" else trigger - mp_level, 4)
        if mp_level and trigger and ((side == "long" and mp_level <= trigger) or (side == "short" and mp_level >= trigger)):
            LOAD_WARNINGS.append(f"{sym}: target {mp_level:g} is {'under' if side == 'long' else 'over'} the pivot "
                                 f"{trigger:g} for a {side} — kept as you drew it; check the side or the pivot")
        plays.append({
            "symbol": sym,
            "side": side,
            "trigger": trigger,
            "second_entry": second,
            "target": mp_level,
            "stop": num("stop", False),
            # mp = your measured potential LEVEL (the price the move can run to): it is the target.
            # atr is optional; when given the MP room is compared against it (CLEAR / THIN).
            "mp": mp_level,
            "atr": num("atr", False),
            "extra_levels": extra,
            "sneaky_levels": [float(v) for v in (item.get("sneaky_levels") or []) if isinstance(v, (int, float)) and v > 0],
            "zones": [sorted([float(z[0]), float(z[1])]) for z in (item.get("zones") or [])
                      if isinstance(z, (list, tuple)) and len(z) == 2 and all(isinstance(v, (int, float)) and v > 0 for v in z)],
            "notes": str(item.get("notes", "")),
            "setup": str(item.get("setup", "") or ""),
            "active": bool(item.get("active", True)),
            "watch": watch,
            "auto": bool(item.get("auto", True)),
            "side_set": bool(item.get("side_set", False)),
            # the chart's lines trade the STOCK, or the option contract linked from the OPTION CHART (opt_key, opt_qty)
            "trade_as_set": bool(item.get("trade_as_set", False)),
            "trade_as": "option" if str(item.get("trade_as", "")).lower() == "option" and item.get("opt_key") else "stock",
            **({"opt_key": str(item["opt_key"]), "opt_qty": max(1, int(item.get("opt_qty") or 1))}
               if str(item.get("trade_as", "")).lower() == "option" and item.get("opt_key") else {}),
            **({"alt": _alt_side(item.get("alt"))} if _alt_side(item.get("alt")) else {}),
            "exchange": str(item.get("exchange", "SMART")).upper(),
            "primary_exchange": str(item.get("primary_exchange", "")).upper(),
            "currency": str(item.get("currency", "USD")).upper(),
        })
    if not any(p["active"] for p in plays):
        raise ConfigError("no active plays")
    return plays


PLACEHOLDERS_STRIPPED = []   # symbols whose example prices were dropped on the last load (the desk says so)


def strip_placeholders(plays, example_path="plays.example.json"):
    """A plays.json copied from the example carries the example's made-up prices. Those are not your levels:
    a play whose pivot / 2nd entry / target / stop all equal the example's becomes a blank, watch-only play,
    so every chart starts empty and YOU put the stop, target and 2nd entry on it."""
    stripped = []
    if not os.path.exists(example_path):
        return plays, stripped
    keep = list(LOAD_WARNINGS)                # checking the example file must not wipe what YOUR file said
    try:
        with open(example_path, encoding="utf-8") as fh:
            ex = {p["symbol"]: p for p in validate_plays(json.load(fh))}
    except (ConfigError, ValueError, OSError):
        return plays, stripped
    finally:
        LOAD_WARNINGS[:] = keep
    for p in plays:
        e = ex.get(p["symbol"])
        if e is None or p["trigger"] is None:
            continue
        same = all(p.get(k) == e.get(k) for k in ("side", "trigger", "second_entry", "target", "stop"))
        if same:
            p.update(trigger=None, second_entry=None, target=None, mp=None, stop=None, extra_levels=[], watch=True)
            stripped.append(p["symbol"])
    return plays, stripped


def load_plays(path):
    if not os.path.exists(path):
        raise ConfigError(f"{path} not found — copy plays.example.json to {path}")
    with open(path, encoding="utf-8") as fh:
        plays = validate_plays(json.load(fh))
    if os.path.basename(path) == "plays.example.json":
        return plays
    example = os.path.join(os.path.dirname(os.path.abspath(path)), "plays.example.json")
    plays, stripped = strip_placeholders(plays, example)
    PLACEHOLDERS_STRIPPED[:] = stripped
    if stripped:
        logging.getLogger("twiney").warning("%s: example placeholder prices dropped for %s — those charts start blank",
                                            path, ", ".join(stripped))
    return plays
