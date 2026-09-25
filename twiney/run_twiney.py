#!/usr/bin/env python3
"""TWINEY — read-only IBKR order-flow workstation built around PS60 levels.

    python run_twiney.py                      live: TWS / IB Gateway market data
    python run_twiney.py --demo               synthetic feed, no IBKR needed
    python run_twiney.py --replay FILE.jsonl  re-run a recording (audit / tuning)

Market data only. There is no order-placement path.
"""

import argparse
import logging
import os
import sys
import threading
import time
import webbrowser

from twiney import __version__
from twiney.config import ConfigError, build_config, load_config, load_plays
from twiney.dashboard import Dashboard
from twiney.engine import Engine
from twiney.recorder import Recorder
from twiney.replay import compare, replay, session_header


def console_alert(alert):
    stamp = time.strftime("%H:%M:%S", time.localtime(alert["t"]))
    print(f"{stamp}  {alert['symbol']:<6} {alert['label']:<24} @ {alert['price']}  "
          f"({alert['side']} · {alert['role']} · absorbed {alert['absorbed']:,})", flush=True)


def open_dashboard(dash, cfg, args):
    print(f"Dashboard: {dash.url}", flush=True)
    if cfg["dashboard"]["open_browser"] and not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(dash.url)).start()


def wait_forever(stop=None):
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopping TWINEY.", flush=True)
        if stop:
            stop()


def run_live(cfg, plays, args):
    try:
        from twiney.ibkr import MarketDataSession, ibapi_app_factory
        factory = ibapi_app_factory()
    except ImportError:
        print("ERROR: the IBKR TWS API Python package (ibapi) is not installed.\n"
              "Download the TWS API from IBKR, then from its source/pythonclient folder run:\n"
              "    python -m pip install .\n"
              "(Use --demo to try the dashboard without IBKR.)", file=sys.stderr)
        return 2
    recorder = None
    if cfg["recording"]["enabled"]:
        recorder = Recorder(cfg["recording"]["dir"])
        recorder.write(session_header(plays, cfg, __version__))
        print(f"Recording raw events to {recorder.path}", flush=True)
    engine = Engine(plays, cfg, recorder)
    engine.listeners.append(console_alert)
    dash = Dashboard(engine, cfg["dashboard"]["host"], cfg["dashboard"]["port"]).start()
    session = MarketDataSession(engine, cfg, plays, factory)
    ib = cfg["ibkr"]
    print(f"TWINEY {__version__} · READ-ONLY · connecting to {ib['host']}:{ib['port']} "
          f"(client id {ib['client_id']}) · {len(plays)} plays · {cfg['depth']['slots']} depth slots", flush=True)
    session.start()
    open_dashboard(dash, cfg, args)

    def stop():
        session.stop()
        dash.stop()
        if recorder:
            recorder.close()
    wait_forever(stop)
    return 0


def run_demo(cfg, plays, args):
    from twiney.sim import DemoFeed
    engine = Engine(plays, cfg)
    engine.listeners.append(console_alert)
    feed = DemoFeed(engine, plays)
    feed.start(time.time())
    dash = Dashboard(engine, cfg["dashboard"]["host"], cfg["dashboard"]["port"]).start()
    print(f"TWINEY {__version__} · DEMO FEED (synthetic, not market data)", flush=True)
    open_dashboard(dash, cfg, args)
    stop_evt = threading.Event()

    def loop():
        while not stop_evt.is_set():
            feed.step(time.time())
            stop_evt.wait(0.25)
    threading.Thread(target=loop, daemon=True).start()
    wait_forever(lambda: (stop_evt.set(), dash.stop()))
    return 0


def run_replay(cfg, plays, args):
    box = {}
    dash = None

    def ready(engine):
        box["engine"] = engine
        engine.connection.update(state="REPLAY", detail=args.replay)
        nonlocal dash
        if args.speed > 0:
            dash = Dashboard(engine, cfg["dashboard"]["host"], cfg["dashboard"]["port"],
                             clock=lambda: engine.last_t).start()
            open_dashboard(dash, cfg, args)

    use_file_settings = not args.override
    engine, recorded = replay(args.replay,
                              plays=None if use_file_settings else plays,
                              cfg=None if use_file_settings else cfg,
                              speed=args.speed, on_alert=console_alert, engine_ready=ready)
    if engine is None:
        print("recording is empty", file=sys.stderr)
        return 1
    got, want = compare(engine, recorded)
    print(f"\nReplay finished: {sum(got.values())} alerts replayed, {sum(want.values())} recorded.")
    for key in sorted(set(got) | set(want)):
        g, w = got.get(key, 0), want.get(key, 0)
        mark = "ok " if g == w else "DIFF"
        print(f"  {mark} {key[0]:<6} {key[1]:<24} @ {key[2]}  replay {g} / recorded {w}")
    if dash is not None:
        print("Replay done; dashboard stays up on the final state. Ctrl+C to exit.")
        wait_forever(dash.stop)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="TWINEY — read-only IBKR order-flow workstation (PS60)")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--plays", default="plays.json")
    ap.add_argument("--demo", action="store_true", help="synthetic feed; no IBKR connection")
    ap.add_argument("--replay", metavar="FILE", help="replay a JSONL recording")
    ap.add_argument("--speed", type=float, default=0.0, help="replay pacing multiple (0 = as fast as possible)")
    ap.add_argument("--override", action="store_true",
                    help="replay with current config.json/plays.json instead of the recording's own")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    try:
        if args.demo:
            cfg = load_config(args.config) if os.path.exists(args.config) else build_config({})
            plays = load_plays(args.plays) if os.path.exists(args.plays) else load_plays("plays.example.json")
            return run_demo(cfg, plays, args)
        if args.replay:
            cfg = load_config(args.config) if os.path.exists(args.config) else build_config({})
            plays = load_plays(args.plays) if args.override else None
            return run_replay(cfg, plays, args)
        return run_live(load_config(args.config), load_plays(args.plays), args)
    except ConfigError as exc:
        print(f"CONFIG ERROR: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
