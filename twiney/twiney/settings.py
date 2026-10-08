"""Every setting in config.json, editable from the desk.

``schema(cfg)`` describes each setting (section, label, help, type, current value, live or restart);
``apply(cfg, path, changes)`` validates the changes, applies them to the running config in place (so the
parts of the desk that read settings at use time pick them up at once) and writes config.json for you.

The help text is read from the comments in ``config.py`` so it can never drift from the defaults.
One thing is deliberately not editable here:
dashboard.host (the desk only listens on this computer).
"""

import copy
import json
import math
import os
import re

from .config import DEFAULTS, ConfigError, build_config

SECTIONS = [
    ("trading", "Trading", "Order entry, sizes, caps, the day loss lock, PS60 exits."),
    ("flow", "Option flow alerts", "When option flow counts as UNUSUAL, index products, voice."),
    ("quantdata", "Quant Data", "Your option flow data feed."),
    ("reload", "Reload detection", "When a buyer or seller counts as a reload, cleared out, or pulled."),
    ("ladder", "Level II", "Big and huge size on the ladder."),
    ("voice", "Voice", "Spoken call-outs."),
    ("ps60", "PS60", "Second entry, measured potential, sneaky pivots, remount and rejection calls."),
    ("tape", "Time & Sales", "How the tape is read."),
    ("orderflow", "Order flow", "5 / 15 second delta windows and the pressure labels (estimated from the tape)."),
    ("trap", "Trapped traders", "Aggressive prints now underwater."),
    ("depth", "Market depth", "IBKR depth subscriptions and rotation."),
    ("chart", "Chart history", "History loaded at startup."),
    ("speech", "Voice", "The voice that says every call: the browser's own, or a cloud voice (ElevenLabs) with your API key and voice ID, so it never changes. Each phrase is kept, so repeats play at once."),
    ("inst", "Institutional footprints", "A fund's order sliced by an execution algo: a steady buy / sell PROGRAM (VWAP / % of volume), fund-style reloaders (the same refill size), a side walking the price, volume against its normal for the time of day."),
    ("dark", "Dark pool", "Off-exchange prints (FINRA / TRF / ADF): the big ones called and listed, dark dollars by price on the ladder, the dark share of the day's volume."),
    ("levels", "Key levels", "The daily chart's and the session's levels (prior day open / high / low / close, premarket and after-hours high / low / close, today's open, daily reject / bounce, prior highs and lows): what price does there, REJECTED / BOUNCED / BUYERS TOOK / SELLERS TOOK, called and said."),
    ("pace", "Pace of tape", "How fast each stock trades against its own normal, and the calls at your levels: stalling, pressing, breakout with speed (+ flow)."),
    ("story", "PS60 story", "The Daily chart, your PS60 places, zones, the tape, reload buyers / sellers, option flow and price response told as one running story."),
    ("studies", "Chart studies", "GAS + ATR, AIRSPACE and UNVISITED HIGHS / LOWS on the stock chart (never the option chart). Each switches off on its own."),
    ("account", "Account", "Orders, positions and fills."),
    ("health", "Feed health", "When a feed counts as stale."),
    ("demo", "Practice", "The practice market."),
    ("recording", "Recording", "Session recordings."),
    ("ibkr", "IBKR connection", "TWS / Gateway connection."),
    ("dashboard", "Desk", "The desk itself."),
]

# settings that are read once at startup: saved at once, used after RESTART
RESTART = ("ibkr.", "dashboard.", "depth.slots", "depth.rows_requested", "depth.smart_depth", "recording.",
           "chart.", "account.", "quantdata.", "demo.", "trading.enabled", "trading.allow_live", "trading.clean_chart_on_start")

LOCKED = {
    "dashboard.host": "Locked: the desk only listens on this computer.",
}

SECRET = {"quantdata.api_key", "speech.api_key"}

CHOICES = {
    "ibkr.port": [(7497, "7497 · TWS paper"), (7496, "7496 · TWS live"), (4002, "4002 · Gateway paper"), (4001, "4001 · Gateway live")],
    "ibkr.market_data_type": [(1, "1 · live"), (2, "2 · frozen"), (3, "3 · delayed"), (4, "4 · delayed frozen")],
    "quantdata.method": [("POST", "POST"), ("GET", "GET")],
    "speech.engine": [("browser", "browser · this computer's voice"), ("cloud", "cloud · the voice ID below (ElevenLabs)")],
    "quantdata.scope": [("all", "whole market"), ("watchlist", "watchlist only")],
    "flow.alerts": [("watchlist", "watchlist only"), ("all", "every ticker")],
    "demo.scenario": [(None, "random each session"), ("mixed", "mixed"), ("trend_up", "trend up"), ("trend_down", "trend down"),
                      ("chop", "chop"), ("capitulation", "capitulation"), ("squeeze", "squeeze")],
    "ps60.second_entry_tf": [(1, "1 minute"), (5, "5 minutes")],
    "studies.lbl_color_mode": [("line", "the line's colour"), ("one", "one colour for every label")],
    "studies.atr_smoothing": [("RMA", "RMA · Wilder (TradingView ATR)"), ("EMA", "EMA"), ("SMA", "SMA"), ("WMA", "WMA")],
}

LABELS = {
    "min_premium": "Min premium ($)", "index_min_premium": "Index min premium ($)", "otm_pct": "Min % out of the money",
    "max_dte": "Max days to expiry", "api_key": "API key", "base_url": "API address", "flow_path": "Flow endpoint",
    "max_dollars_per_order": "Max $ per order", "max_daily_loss": "Day loss limit ($)", "allow_market": "Allow market / naked stop orders",
    "stop_limit_ticks": "Stop-limit ticks", "of_premium_min": "Board: premium floor ($, R2)", "of_dte_green": "Board: weeklies = green up to (days, R3)", "of_dte_max": "Board: short-term up to (days, R3)", "of_otm_min_pct": "Board: out of the money from (%, R4)", "of_repeat_min": "Board: repeats needed on one expiry (R5)", "of_fresh_minutes": "Board: flow is FADING after (min)", "of_hedge_updays": "Board: near-spot puts after N up days = hedge (R9)", "of_session_minutes": "Board: minutes of prints looked back", "no_flow_no_dough": "NO FLOW, NO DOUGH: hold READY until flow confirms the play's side", "dough_window_minutes": "Flow confirmation: minutes looked back", "dough_min_dollars": "Flow confirmation: premium needed ($)", "dough_min_minutes": "Flow confirmation: separate minutes with prints", "dough_fresh_minutes": "Flow confirmation: last print within (min)", "dough_max_dte": "Flow confirmation: max days to expiry", "dough_min_otm_pct": "Flow confirmation: min % out of the money", "big_money_min_premium": "BIG MONEY: remember option prints of at least ($)", "big_money_days": "BIG MONEY: days to remember", "auto_second_entry": "Auto 2nd entry (drawn 2nd entry = stop-limit entry with stop + target)", "auto_entry_limit_ticks": "Auto entry: min ticks past the 2nd entry it may fill", "auto_entry_max_slip_pct": "Auto entry: max slip % past the 2nd entry (cap, not the fill)", "auto_arm_on_second_entry": "Drawing a 2nd entry ARMS the desk (paper / practice only)", "auto_stop_dollars": "Stop placed with a new 2nd entry: $ away (0 = off)", "clear_lines_when_flat": "Clear the 2nd entry, stop and target when the trade goes flat", "filled_chip_seconds": "Seconds the FILLED chip stays on the chart", "risk_dollars": "Risk $ per trade (auto entry size)", "mp": "MP", "atr_days": "ATR days", "atr_from_bars": "ATR from daily bars",
    "big_shares": "Big size (shares)", "huge_multiple": "Huge = big ×", "sim_options_after_hours": "PAPER after hours: simulated option chain / chart / L2 / T&S (yellow SIM light)", "sim_options_force": "Simulated options NOW too (paper only, for practice in market hours)", "loss_limit_on_paper": "Daily loss lock on PAPER too (off: paper never locks — only a LIVE account does)", "mark_screenshot": "Each MARK takes a screenshot too", "option_depth": "Option LEVEL II: real book for the charted contract (uses 1 depth line)", "visit_away_ticks": "Ladder: a visit ends when price is this many ticks away", "stack_seconds": "Ladder: PULL / STACK looks back (seconds)", "strike_min_premium": "Ladder: outline option strikes with at least this premium ($)", "strike_max_dte": "Ladder strikes: only expirations within (days)", "strike_otm_only": "Ladder strikes: out-of-the-money calls / puts only (bought at the ask)", "min_shares": "Min shares",
    "voice_all": "Speak flow for every watchlist symbol", "against_bias": "Hold at WATCH when flow leans against (0-1)",
    "against_min_premium": "…and at least this premium ($)", "smart_depth": "SMART depth", "dir": "Folder",
    "urgency_window_minutes": "Urgent flow window (min)", "urgency_min_prints": "Urgent = prints in the window",
    "urgency_min_dollars": "…and dollars ($)", "urgency_max_dte": "…days to expiry at most", "urgency_min_otm_pct": "…% out of the money at least",
    "urgency_cooldown_minutes": "Urgent call cooldown (min)",
    "equity_enabled": "Equity flow on", "equity_path": "Equity prints endpoint", "equity_poll_seconds": "Equity poll seconds",
    "equity_min_dollars": "Equity print min $", "flow_min_premium": "Ladder flow mark min premium ($)",
    "flow_index_min_premium": "…index products ($)", "flow_window_minutes": "Ladder flow marks stay (min)",
    "flow_short_dte": "Short-dated = days to expiry ≤", "flow_repeat_prints": "Repeat = prints on one strike",
    "flow_repeat_minutes": "…inside (min)", "flow_repeat_cooldown_minutes": "Repeat call cooldown (min)",
    "stale_seconds": "NOT RELOADING on time alone (s)",
    "stale_multiple": "NOT RELOADING = traded through × what he puts back per reload",
    "active_floor": "RELOADING at conviction ≥", "fading_floor": "STILL THERE at conviction ≥ (NOT RELOADING under)", "gone_show_seconds": "CLEANED UP / PULLED mark stays (s)",
    "requote_seconds": "Re-quote window (s)", "real_min_shares": "REAL / FAKE needs shares left", "real_memory_seconds": "REAL / FAKE memory (s)",
    "conviction_weight": "Rotation: pull a live reloader closer (0-1)", "flow_weight": "Rotation: pull SOMEBODY KNOWS SOMETHING flow closer (0-1)",
}


def _label(key):
    return LABELS.get(key) or key.replace("_", " ").capitalize()


def _help_from_source():
    """Map dotted path -> the comment lines written above it in config.py's DEFAULTS."""
    src = open(os.path.join(os.path.dirname(__file__), "config.py"), encoding="utf-8").read()
    start = src.index("DEFAULTS = {")
    lines = src[start:].splitlines()[1:]
    stack, pending, out = [], [], {}
    for raw in lines:
        line = raw.strip()
        if line.startswith("#"):
            pending.append(line.lstrip("# ").strip())
            continue
        m = re.match(r'"([a-z_0-9]+)":\s*(.*)$', line)
        if m:
            key, rest = m.group(1), m.group(2)
            path = ".".join(stack + [key])
            tail = re.search(r',\s*#\s*(.+)$', rest)       # a comment on the same line names the setting
            if tail:
                INLINE[path] = tail.group(1).strip()
            if pending:
                out[path] = " ".join(pending)
            pending = []
            if rest.endswith("{"):
                stack.append(key)
            continue
        if line.startswith("}"):
            if not stack:
                break
            stack.pop()
            pending = []
    return out


INLINE = {}
HELP = _help_from_source()


def _get(d, path):
    for k in path.split("."):
        d = d[k]
    return d


def _set(d, path, value):
    keys = path.split(".")
    for k in keys[:-1]:
        d = d.setdefault(k, {})
    d[keys[-1]] = value


def _leaves(d, prefix=""):
    for k, v in d.items():
        p = prefix + k
        if isinstance(v, dict) and p not in ("quantdata.extra_params",):
            yield from _leaves(v, p + ".")
        else:
            yield p, v


def _kind(path, default):
    if path.startswith("studies.col_"):
        return "color"
    if path in SECRET:
        return "secret"
    if path in CHOICES:
        return "select"
    if isinstance(default, bool):
        return "bool"
    if isinstance(default, int):
        return "int"
    if isinstance(default, float):
        return "float"
    if isinstance(default, list) and all(isinstance(x, str) for x in default):
        return "list"
    if isinstance(default, (list, dict)):
        return "json"
    return "text"


RETIRED = {"trading.loss_limit_live_only", "studies.label_merge_pct"}


def schema(cfg):
    sections = []
    for key, title, blurb in SECTIONS:
        fields = []
        for path, default in _leaves(DEFAULTS[key], key + "."):
            if path in RETIRED:
                continue                          # an old setting kept only so saved configs still load
            kind = _kind(path, default)
            value = _get(cfg, path)
            f = {"path": path, "label": INLINE[path] if path.startswith(("studies.", "pace.", "story.")) and path in INLINE else _label(path.split(".")[-1]), "help": HELP.get(path, ""), "type": kind,
                 "restart": path.startswith(RESTART) or any(path == r for r in RESTART), "locked": LOCKED.get(path)}
            if kind == "secret":
                f["value"] = ""
                f["set"] = bool(value)
                f["hint"] = ("…" + str(value)[-4:]) if value else ""
            elif kind == "json":
                f["value"] = json.dumps(value)
            elif kind == "list":
                f["value"] = ", ".join(value)
            else:
                f["value"] = value
            if kind == "select":
                f["choices"] = [{"value": v, "label": lbl} for v, lbl in CHOICES[path]]
            fields.append(f)
        sections.append({"key": key, "title": title, "blurb": blurb, "fields": fields})
    return sections


def _coerce(path, raw):
    default = _get(DEFAULTS, path)
    kind = _kind(path, default)
    try:
        if kind == "bool":
            return raw if isinstance(raw, bool) else str(raw).strip().lower() in ("1", "true", "on", "yes")
        if kind == "int":
            v = float(raw)
            if not math.isfinite(v):
                raise ValueError("must be a finite number")
            return int(v)
        if kind == "float":
            v = float(raw)
            if not math.isfinite(v):
                raise ValueError("must be a finite number")
            return v
        if kind == "list":
            items = raw if isinstance(raw, list) else str(raw).split(",")
            return [str(x).strip().upper() for x in items if str(x).strip()]
        if kind == "json":
            return raw if isinstance(raw, (list, dict)) else json.loads(raw)
        if kind == "color":
            v = str(raw or "").strip()
            if not re.match(r"^#[0-9a-fA-F]{6}$", v):
                raise ValueError("must be a colour like #26a69a")
            return v.lower()
        if kind == "select":
            allowed = [v for v, _l in CHOICES[path]]
            v = None if raw in (None, "", "null") else raw
            if v not in allowed:
                v = type(allowed[-1])(v) if allowed[-1] is not None else v
            if v not in allowed:
                raise ValueError(f"must be one of {', '.join(str(a) for a in allowed)}")
            return v
        return "" if raw is None else str(raw)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ConfigError(f"{path}: {exc}" if str(exc) else f"{path}: not a valid {kind}")


LEAVES = {p for p, _v in _leaves(DEFAULTS)}


def apply(cfg, config_path, changes):
    """Validate ``changes`` ({path: value}), apply them to ``cfg`` in place and save config.json.
    Returns (applied paths, paths that take effect after a restart)."""
    if not isinstance(changes, dict):
        raise ConfigError("changes must be an object of setting: value")
    clean = {}
    for path, raw in changes.items():
        # one setting at a time, never a whole section: a section would get around the locks
        if not isinstance(path, str) or path not in LEAVES:
            raise ConfigError(f"unknown setting {path}")
        if path in LOCKED or any(l.startswith(path + ".") for l in LOCKED):
            raise ConfigError(LOCKED.get(path, "Locked."))
        if path in SECRET and (raw is None or raw == ""):
            continue                       # empty box = keep the key you have
        if path in SECRET and raw == "__clear__":
            raw = ""
        clean[path] = _coerce(path, raw)
    if not clean:
        return [], []
    # the file as you have it (comment keys and all), with the changes on top
    raw_file = {}
    if config_path and os.path.exists(config_path):
        with open(config_path, encoding="utf-8") as fh:
            raw_file = json.load(fh)
    new_file = copy.deepcopy(raw_file)
    for path, value in clean.items():
        _set(new_file, path, value)
    build_config(new_file)                 # the same checks as startup: nothing invalid gets saved
    for path in clean:                     # and nothing that would switch live trading on, however it is sent
        if path in LOCKED:
            raise ConfigError(LOCKED[path])
    if config_path:
        tmp = config_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(new_file, fh, indent=2)
            fh.write("\n")
        os.replace(tmp, config_path)
    for path, value in clean.items():      # in place: the running desk sees it at once
        _set(cfg, path, value)
    restart = [p for p in clean if p.startswith(RESTART) or p in RESTART]
    return sorted(clean), restart


def redacted(cfg):
    """A copy safe to write into recordings and exports: secrets blanked."""
    out = copy.deepcopy(cfg)
    for path in SECRET:
        try:
            if _get(out, path):
                _set(out, path, "***")
        except (KeyError, TypeError):
            pass
    return out
