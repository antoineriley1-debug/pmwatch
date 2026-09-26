"""Config + PS60 play loading and validation."""

import copy
import ipaddress
import json
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
        "pull_grace_seconds": 1.5,
        # price must trade through the level within this long to call CLEANED UP
        "through_timeout_seconds": 10.0,
        # ignore disappearances this long after a book (re)sync, e.g. error 317
        "resync_grace_seconds": 2.0,
        # auto-track big inside levels in addition to trigger / second entry
        "auto_levels": True,
        "max_auto_levels": 6,
        "auto_min_display_shares": 2000,
        "auto_idle_seconds": 90.0,
    },
    "tape": {
        "window_seconds": 30.0,
        "min_prints_for_read": 5,
        "control_ratio": 0.65,
        "large_print_shares": 5000,
        "keep_prints": 200,
    },
    "health": {
        "l1_stale_seconds": 15.0,
        "depth_stale_seconds": 15.0,
        "tape_stale_seconds": 60.0,
    },
    "account": {
        # show your pending orders, positions and today's fills (read-only view)
        "show": True,
        "orders_refresh_seconds": 3.0,
        "fills_refresh_seconds": 10.0,
    },
    "chart": {
        # load today's 1-minute bars from IBKR at startup so the chart has context
        "history": True,
        "regular_hours_only": True,
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


def build_config(raw=None):
    cfg = _merge(DEFAULTS, raw or {})
    if cfg["depth"]["slots"] < 1:
        raise ConfigError("depth.slots must be >= 1")
    if cfg["depth"]["rows_displayed"] > cfg["depth"]["rows_requested"]:
        raise ConfigError("depth.rows_displayed cannot exceed depth.rows_requested")
    host = cfg["dashboard"]["host"]
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = host == "localhost"
    if not loopback:
        raise ConfigError("dashboard.host must be a loopback address; TWINEY is a local-only workstation")
    return cfg


def load_config(path):
    if not os.path.exists(path):
        raise ConfigError(f"{path} not found — copy config.example.json to {path}")
    with open(path, encoding="utf-8") as fh:
        return build_config(json.load(fh))


def validate_plays(raw):
    items = raw.get("plays") if isinstance(raw, dict) else raw
    if not isinstance(items, list) or not items:
        raise ConfigError("plays file must contain a non-empty list of plays")
    plays, seen = [], set()
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
                    raise ConfigError(f"{where}: {key} is required")
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

        plays.append({
            "symbol": sym,
            "side": side,
            "trigger": num("trigger", True),
            "second_entry": num("second_entry", False),
            "target": num("target", False),
            "stop": num("stop", False),
            "extra_levels": extra,
            "notes": str(item.get("notes", "")),
            "active": bool(item.get("active", True)),
            "exchange": str(item.get("exchange", "SMART")).upper(),
            "primary_exchange": str(item.get("primary_exchange", "")).upper(),
            "currency": str(item.get("currency", "USD")).upper(),
        })
    if not any(p["active"] for p in plays):
        raise ConfigError("no active plays")
    return plays


def load_plays(path):
    if not os.path.exists(path):
        raise ConfigError(f"{path} not found — copy plays.example.json to {path}")
    with open(path, encoding="utf-8") as fh:
        return validate_plays(json.load(fh))
