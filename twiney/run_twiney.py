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
from twiney.bigmoney import BigMoney
from twiney.config import LOAD_WARNINGS, PLACEHOLDERS_STRIPPED, ConfigError, build_config, load_config, load_plays
from twiney.dashboard import Dashboard, EngineRef
from twiney.desk import Desk
from twiney.engine import Engine
from twiney.recorder import Recorder
from twiney.replay import compare, replay, session_header, span
from twiney.trading import IbkrBroker, SimBroker, Trader, TradingGate


def console_alert(alert):
    stamp = time.strftime("%H:%M:%S", time.localtime(alert["t"]))
    print(f"{stamp}  {alert['symbol']:<6} {alert['label']:<24} @ {alert['price']}  "
          f"({alert['side']} · {alert['role']} · absorbed {alert['absorbed']:,})", flush=True)


def _rec_dir(cfg):
    """Recordings live in the data folder (unless config.json gives an absolute path)."""
    from twiney import paths as _paths
    d = _paths.recordings_dir(cfg["recording"]["dir"])
    cfg["recording"]["dir"] = d          # everything downstream (clips, replay lists, exports) reads the same place
    return d


def layout_file(args):
    """layout.json lives next to config.json (the TWINEY folder)."""
    return os.path.join(os.path.dirname(os.path.abspath(args.config)), "layout.json")


def restart_process(stop=None):
    """RESTART from the desk: stop cleanly (IBKR session, recording), then start again with the same arguments.
    The browser tab stays and reconnects by itself."""
    print("Restarting TED to apply settings...", flush=True)
    try:
        if stop:
            stop()
    except Exception:
        pass
    os.environ["TWINEY_RESTARTED"] = "1"
    args = [sys.executable] + sys.argv
    if os.name == "nt":
        import subprocess
        subprocess.Popen(args)
        os._exit(0)
    os.execv(sys.executable, args)


def open_dashboard(dash, cfg, args):
    print(f"Dashboard: {dash.url}", flush=True)
    if os.environ.get("TWINEY_RESTARTED"):
        return                      # restarted from the desk: the tab is already open
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
        recorder = Recorder(_rec_dir(cfg))
        recorder.write(session_header(plays, cfg, __version__))
        print(f"Recording raw events to {recorder.path}", flush=True)
    engine = Engine(plays, cfg, recorder)
    engine.study_async = True          # chart studies off the engine lock: the book and the tape never wait on them
    engine.plays_path = args.plays
    engine.grades_path = os.path.join(_rec_dir(cfg), "grades.jsonl")
    engine.jlog_path = os.path.join(_rec_dir(cfg), "desk.log")   # structured JSON lines: connections, orders, fills, errors
    engine.load_user_alerts(os.path.join(os.path.dirname(os.path.abspath(args.plays)), "alerts.json"))
    engine.listeners.append(console_alert)
    note_stripped(engine, args)
    if CLEANED[0]:
        engine._save_plays()
        engine._message("info", "Clean chart: yesterday's lines are off — draw today's pivot, 2nd entry, stop and target "
                                "(SETTINGS, Trading, clean chart on start)", time.time())
    engine.bigmoney = BigMoney(cfg["flow"], os.path.join(cfg["recording"]["dir"], "big_money.jsonl"))
    gate = TradingGate(cfg)
    session = MarketDataSession(engine, cfg, plays, factory, gate=gate)
    engine.session = session
    engine.play_listeners.append(session.add_play)
    engine.remove_listeners.append(session.remove_play)
    trader = Trader(engine, cfg, IbkrBroker(engine, session), gate) if cfg["trading"]["enabled"] else None
    engine.trader = trader
    start_watchdog(lambda: trader)
    desk = Desk(engine, cfg, plays, __version__, prefix="twiney", base_dir=os.path.dirname(os.path.abspath(__file__)))
    if recorder:
        desk.started = time.time()
    dash = Dashboard(engine, cfg["dashboard"]["host"], cfg["dashboard"]["port"], trader=trader, desk=desk,
                     rec_dir=_rec_dir(cfg), layout_path=layout_file(args), config_path=args.config).start()
    ib = cfg["ibkr"]
    mode = "order entry PAPER-ONLY" if trader and not cfg["trading"]["allow_live"] else \
        "order entry LIVE ALLOWED" if trader else "view only"
    print(f"TWINEY {__version__} · {mode} · connecting to {ib['host']}:{ib['port']} "
          f"(client id {ib['client_id']}) · {len(plays)} plays · {cfg['depth']['slots']} depth slots", flush=True)
    session.start()
    flow = [None]

    def start_flow():
        """The Quant Data feed runs whenever a key is in config.json: at start, and again the moment one is saved in SETTINGS."""
        if flow[0]:
            flow[0].stop()
            flow[0] = None
        if cfg.get("quantdata", {}).get("api_key"):
            from twiney.flow import QuantDataFeed
            flow[0] = QuantDataFeed(engine, cfg, [p["symbol"] for p in plays]).start()
            print("Option flow: Quant Data (key from config.json)" + (" · equity prints on" if cfg["quantdata"].get("equity_enabled") else ""), flush=True)
        else:
            engine.flow_status.update(source="off", state="off", detail="no Quant Data key: paste it in SETTINGS > Quant Data")
            print("Option flow: off (add your Quant Data key in SETTINGS on the desk)", flush=True)
    start_flow()
    dash.hooks["flow_restart"] = start_flow
    open_dashboard(dash, cfg, args)

    def stop():
        if flow[0]:
            flow[0].stop()
        session.stop()
        dash.stop()
        desk.stop()
    dash.hooks["restart"] = lambda: restart_process(stop)
    wait_forever(stop)
    return 0


CLEANED = [0]
LINE_KEYS = ("trigger", "second_entry", "stop", "target", "mp")


def clean_chart(plays, cfg, path=None, today=None):
    """The first start of a new day comes up with clean charts (SETTINGS, Trading, clean chart on start): the pivot,
    2nd entry, stop and target lines from an earlier day are gone, the tickers stay. A restart later the same day keeps
    the lines you drew today. Returns how many tickers had lines taken off."""
    if not cfg.get("trading", {}).get("clean_chart_on_start", True):
        return 0
    if path and os.path.exists(path):
        marker = os.path.join(os.path.dirname(os.path.abspath(path)), ".clean_chart_v1")
        first = not os.path.exists(marker)      # this build's first start: the old saved lines go, whatever their date
        if first:
            try:
                open(marker, "w").close()
            except OSError:
                pass
        saved = time.strftime("%Y%m%d", time.localtime(os.path.getmtime(path)))
        if not first and saved == (today or time.strftime("%Y%m%d")):
            return 0        # drawn today: keep them
    n = 0
    for p in plays:
        if any(p.get(k) for k in LINE_KEYS) or p.get("alt"):
            n += 1
        for k in LINE_KEYS:
            if k in p:
                p[k] = None
        p.pop("alt", None)
        p["watch"] = True           # no pivot: a watch-only ticker until you draw one
    return n


def note_stripped(engine, args):
    """plays.json still carried the example's made-up prices for these tickers: they start blank, and the desk says so."""
    for w in LOAD_WARNINGS:
        engine._message("warn", w, time.time())
    if PLACEHOLDERS_STRIPPED:
        syms = ", ".join(PLACEHOLDERS_STRIPPED)
        engine._message("warn", f"{syms}: the example placeholder levels in {os.path.basename(args.plays)} were dropped — "
                                f"those charts start blank; draw your own stop, target and 2nd entry", time.time())


def start_watchdog(get_trader, clock=time.time, every=0.5):
    """The loss lock, breakeven stops and the exit guard run on their own clock, browser open or not."""
    def run():
        while True:
            tr = get_trader()
            if tr is not None:
                try:
                    tr.watchdog(clock())
                except Exception as exc:
                    logging.getLogger("twiney").exception("watchdog failed")
                    try:
                        tr.engine._message("error", f"order watchdog error: {exc}", clock())
                    except Exception:
                        pass
            time.sleep(every)
    threading.Thread(target=run, name="twiney-watchdog", daemon=True).start()

    def fast():
        """Woken by every price update: option stops fire on the tick that crosses them."""
        while True:
            tr = get_trader()
            evt = getattr(getattr(tr, "engine", None), "price_evt", None)
            if evt is None:
                time.sleep(every)
                continue
            evt.wait(every)
            evt.clear()
            try:
                if any(p.get("qty") for p in list(tr.engine.opt_positions.values())):
                    tr.fast_stops(clock())
            except Exception:
                logging.getLogger("twiney").exception("fast stops failed")
    threading.Thread(target=fast, name="twiney-fast-stops", daemon=True).start()


def run_demo(cfg, plays, args):
    from twiney.sim import DemoFeed
    recorder = None
    if cfg["recording"]["enabled"]:
        recorder = Recorder(_rec_dir(cfg), time.strftime("demo-%Y%m%d-%H%M%S.jsonl"))
        recorder.write(session_header(plays, cfg, __version__))
        print(f"Recording the demo to {recorder.path} (replay it or grade its calls for tune.py)", flush=True)
    engine = Engine(plays, cfg, recorder)
    engine.study_async = True          # chart studies off the engine lock: the book and the tape never wait on them
    engine.plays_path = args.plays if os.path.exists(args.plays) and not args.plays.endswith("plays.example.json") else None
    engine.grades_path = os.path.join(_rec_dir(cfg), "grades.jsonl")
    engine.jlog_path = os.path.join(_rec_dir(cfg), "desk.log")   # structured JSON lines: connections, orders, fills, errors
    engine.load_user_alerts(os.path.join(os.path.dirname(os.path.abspath(args.plays)), "alerts.json"))
    engine.listeners.append(console_alert)
    note_stripped(engine, args)
    if CLEANED[0]:
        engine._save_plays()
        engine._message("info", "Clean chart: yesterday's lines are off — draw today's pivot, 2nd entry, stop and target "
                                "(SETTINGS, Trading, clean chart on start)", time.time())
    # practice flow is made up and the demo price starts fresh every launch: its big prints live in memory
    # only, so the real 30-day memory (recordings/big_money.jsonl) never carries practice prints
    engine.bigmoney = BigMoney(cfg["flow"], None)
    feed = DemoFeed(engine, plays, seed=None, scenario=cfg.get("demo", {}).get("scenario"))
    feed.start(time.time())
    print(f"Practice session · day type: {feed.scenario}  (not shown on the desk; set demo.scenario in config.json to pick one)", flush=True)
    gate = TradingGate(cfg)
    gate.set_sim()
    sim = SimBroker(engine)
    engine.sim_broker = sim
    trader = Trader(engine, cfg, sim, gate)
    engine.trader = trader
    desk = Desk(engine, cfg, plays, __version__, prefix="demo", base_dir=os.path.dirname(os.path.abspath(__file__)))
    if recorder:
        desk.started = time.time()
    dash = Dashboard(engine, cfg["dashboard"]["host"], cfg["dashboard"]["port"], trader=trader, desk=desk,
                     rec_dir=_rec_dir(cfg), layout_path=layout_file(args), config_path=args.config).start()
    print(f"TWINEY {__version__} · DEMO FEED (synthetic, not market data) · practice orders fill in the simulator",
          flush=True)
    open_dashboard(dash, cfg, args)
    stop_evt = threading.Event()

    from twiney.flow import SimFlow
    sim_flow = SimFlow(engine, [p["symbol"] for p in plays], market=feed)
    engine.play_listeners.append(lambda p: sim_flow.symbols.append(p["symbol"]))

    def loop():
        log = logging.getLogger("twiney.demo")
        while not stop_evt.is_set():
            now = time.time()
            try:                     # one bad step is logged and the practice market keeps going
                feed.step(now)
                sim_flow.step(now)
                engine.practice_opt_tick(now)     # contracts you hold / have orders on / chart move with the stock
            except Exception as exc:
                log.exception("practice market step failed")
                engine._message("error", f"practice market step failed: {exc}", now)
            stop_evt.wait(0.25)
    threading.Thread(target=loop, daemon=True).start()
    start_watchdog(lambda: trader)
    dash.hooks["restart"] = lambda: restart_process(lambda: (stop_evt.set(), dash.stop(), desk.stop()))
    wait_forever(lambda: (stop_evt.set(), dash.stop(), desk.stop()))
    return 0


def run_replay(cfg, plays, args):
    box = {}
    dash = None
    ref = EngineRef(box)

    control = {"paused": False, "speed": args.speed, "position": None, "file": os.path.basename(args.replay)}
    try:                                   # the scrubber's range: first and last market time in the file
        control["start"], control["end"] = span(args.replay)
    except OSError:
        pass
    if args.start:                         # open at a clip: jump to its start, pause at its end
        control["seek"] = float(args.start)
    if args.end:
        control["pause_at"] = float(args.end)

    def ready(engine):
        box["engine"] = engine
        engine.connection.update(state="REPLAY", detail=args.replay)
        nonlocal dash
        if args.speed > 0:
            engine.replay = control
            # practice orders fill against the replayed book, exactly like the demo
            gate = TradingGate(cfg)
            gate.set_sim()
            sim = SimBroker(engine)
            engine.sim_broker = sim
            engine.trader = Trader(engine, cfg, sim, gate)
            if dash is None:
                dash = Dashboard(ref, cfg["dashboard"]["host"], cfg["dashboard"]["port"],
                                 clock=lambda: box["engine"].last_t, trader=None, rec_dir=_rec_dir(cfg),
                                 layout_path=layout_file(args)).start()
                open_dashboard(dash, cfg, args)
            dash.trader = engine.trader
            if not control.get("_watchdog"):
                control["_watchdog"] = True
                start_watchdog(lambda: getattr(box.get("engine"), "trader", None), clock=lambda: box["engine"].last_t)

    use_file_settings = not args.override
    try:
        while True:
            engine, recorded = replay(args.replay,
                                      plays=None if use_file_settings else plays,
                                      cfg=None if use_file_settings else cfg,
                                      speed=args.speed, on_alert=console_alert, engine_ready=ready,
                                      control=control if args.speed > 0 else None)
            if control.get("restart_at") is None:
                control["done"] = True
                if engine is None:
                    print("recording is empty", file=sys.stderr)
                    return 1
                got, want = compare(engine, recorded)
                print(f"\nReplay finished: {sum(got.values())} alerts replayed, {sum(want.values())} recorded.")
                for key in sorted(set(got) | set(want)):
                    g, w = got.get(key, 0), want.get(key, 0)
                    mark = "ok " if g == w else "DIFF"
                    print(f"  {mark} {key[0]:<6} {key[1]:<24} @ {key[2]}  replay {g} / recorded {w}")
                if dash is None:
                    return 0
                print("Replay done; dashboard stays up. Click a marker to jump back. Ctrl+C to exit.")
                while control.get("restart_at") is None:
                    time.sleep(0.3)
            # jumped backwards (or the replay had finished): start over and fast-forward to that moment
            control.update(stop=False, done=False, seek=control.pop("restart_at"), position=None)
    except KeyboardInterrupt:
        print("\nStopping TWINEY.", flush=True)
        if dash is not None:
            dash.stop()
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="TWINEY — read-only IBKR order-flow workstation (PS60)")
    ap.add_argument("--config", default=None, help="settings file (default: config.json in your TWINEY data folder)")
    ap.add_argument("--plays", default=None, help="plays file (default: plays.json in your TWINEY data folder)")
    ap.add_argument("--demo", action="store_true", help="synthetic feed; no IBKR connection")
    ap.add_argument("--replay", metavar="FILE", help="replay a JSONL recording")
    ap.add_argument("--speed", type=float, default=0.0, help="replay pacing multiple (0 = as fast as possible)")
    ap.add_argument("--override", action="store_true",
                    help="replay with current config.json/plays.json instead of the recording's own")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--start", type=float, help="replay: jump to this time first (a clip's start)")
    ap.add_argument("--end", type=float, help="replay: pause at this time (a clip's end)")
    ap.add_argument("--port", type=int, help="dashboard port (overrides config.json)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    # your files live in the data folder (C:\Users\you\TWINEY), never in the program folder a new zip replaces
    from twiney import paths as _paths
    program_dir = os.path.dirname(os.path.abspath(__file__))
    if args.config is None:
        args.config = _paths.ensure_config(program_dir)
    if args.plays is None:
        args.plays = _paths.ensure_plays(program_dir)
    print(f"Your settings, key, plays and layout: {os.path.dirname(os.path.abspath(args.config))}", flush=True)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    try:
        if args.demo:
            cfg = load_config(args.config) if os.path.exists(args.config) else build_config({})
            if args.port: cfg["dashboard"]["port"] = args.port
            plays = load_plays(args.plays) if os.path.exists(args.plays) else load_plays("plays.example.json")
            # PRACTICE starts from a clean slate EVERY launch: its price is made up fresh each time, so a line drawn in an
            # earlier practice session sits at a meaningless price. Lines you draw now stay until you move or delete them
            CLEANED[0] = clean_chart(plays, {"trading": {"clean_chart_on_start": True}})
            for p in plays:
                p["extra_levels"], p["sneaky_levels"], p["zones"] = [], [], []
            return run_demo(cfg, plays, args)
        if args.replay:
            cfg = load_config(args.config) if os.path.exists(args.config) else build_config({})
            if args.port: cfg["dashboard"]["port"] = args.port
            plays = load_plays(args.plays) if args.override else None
            return run_replay(cfg, plays, args)
        cfg = load_config(args.config)
        if args.port: cfg["dashboard"]["port"] = args.port
        plays = load_plays(args.plays)
        CLEANED[0] = clean_chart(plays, cfg, args.plays)
        return run_live(cfg, plays, args)
    except ConfigError as exc:
        print(f"CONFIG ERROR: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
