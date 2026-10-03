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
    },
    "dashboard": {
        "host": "127.0.0.1",
        "port": 8765,
        "open_browser": True,
    },
    "depth": {
        # IBKR caps simultaneous market-depth subscriptions; TWINEY uses three.
        "slots": 3,
        # rows requested from IBKR (extra rows make "out of view" detection honest)
        "rows_requested": 10,
        # rows shown per side on the dashboard
        "rows_displayed": 5,
        "smart_depth": True,
        # a challenger must be this much closer (fraction) than the incumbent it replaces
        "rotate_hysteresis": 0.15,
        # an incumbent keeps its slot at least this long before it can be rotated out
        "min_hold_seconds": 20.0,
        # after IBKR rejects a depth request (e.g. error 309) skip the symbol this long
        "reject_cooldown_seconds": 30.0,
        # rotation leans toward symbols with a live reloader: a symbol's distance is cut by this fraction x its best
        # level's conviction (0 = distance only, 0.5 = a fully ACTIVE reloader reads as half as far away)
        "conviction_weight": 0.5,
        # ...and toward a symbol where SOMEBODY KNOWS (short-dated out-of-the-money flow at the ask): distance cut by this
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
        # when an auto-entry trade goes flat (stopped out, target, flatten) its 2nd entry, stop and target lines go
        "clear_lines_when_flat": True,
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
        "regular_hours_only": True,
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
        # the rows stay still while price moves inside them; they re-centre only when price comes within this many
        # rows of the top or bottom edge (bigger = re-centres sooner)
        "recenter_rows": 4,
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
    "recording": {
        "enabled": True,
        "dir": "recordings",
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
        watch = bool(item.get("watch", False))          # a ticker you typed in: no pivot yet
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
            "notes": str(item.get("notes", "")),
            "setup": str(item.get("setup", "") or ""),
            "active": bool(item.get("active", True)),
            "watch": watch,
            "auto": bool(item.get("auto", True)),
            "side_set": bool(item.get("side_set", False)),
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
