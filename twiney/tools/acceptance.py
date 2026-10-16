#!/usr/bin/env python3
"""TED ladder acceptance checklist — runs against a RUNNING desk over its local API.

    python tools/acceptance.py --port 8787 --symbol AAPL          # IBKR paper (TWS paper login, port 7497)
    python tools/acceptance.py --port 8799 --symbol AAPL --demo   # the practice desk (no TWS needed)

Every step prints PASS / FAIL / BLOCKED with the reason. Orders are placed far from the market (never
marketable) and cancelled; the bracket is placed the same way. FLATTEN runs only when the account holds a
position in the symbol (and asks first unless --yes). LIVE accounts are refused: the desk itself locks live,
and this script checks the mode before touching anything.

Steps: connection · mode · ticker load · quotes · depth · limit place · modify · cancel · bracket (parent +
children) · symbol switch (no stale data) · flatten (if a position) · reconnect (manual: TWS File > Exit and
log back in while this script watches) · replay (a recording exists).
"""
import argparse
import json
import sys
import time
import urllib.request

RESULTS = []


def say(step, status, why=""):
    RESULTS.append((step, status, why))
    print(f"[{status:7}] {step}{(' — ' + why) if why else ''}", flush=True)


def api(base, path, body=None):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"content-type": "application/json"} if body is not None else {})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())


def wait_for(fn, seconds, every=0.5):
    end = time.time() + seconds
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(every)
    return None


def pane(base, sym, extra=True):
    st = api(base, f"/api/state?extra={sym}")
    for p in st.get("panes") or []:
        if p and p["symbol"] == sym:
            return st, p
    return st, (st.get("extra") or {}).get(sym)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--symbol", default="AAPL")
    ap.add_argument("--switch", default="MSFT", help="second ticker for the symbol-switch step")
    ap.add_argument("--demo", action="store_true", help="the practice desk: SIM mode expected")
    ap.add_argument("--yes", action="store_true", help="no questions (flatten runs if a position exists)")
    ap.add_argument("--reconnect", action="store_true", help="wait for you to restart TWS and watch the desk recover")
    ap.add_argument("--recordings", default="recordings", help="where the desk writes recordings")
    a = ap.parse_args()
    base = f"http://{a.host}:{a.port}"
    sym, sw = a.symbol.upper(), a.switch.upper()

    # 1. connection + mode
    try:
        st = api(base, "/api/state")
    except Exception as exc:
        say("desk reachable", "FAIL", f"{base}: {exc}")
        return finish()
    conn = st["connection"]["state"]
    mode = st["trading"]["mode"]
    if mode == "LIVE":
        say("trading mode", "FAIL", "LIVE mode: this checklist never runs against a live account")
        return finish()
    want = "DEMO" if a.demo else "CONNECTED"
    say("connection", "PASS" if conn == want else "FAIL", f"state {conn} (want {want})")
    say("trading mode", "PASS" if mode in ("SIM", "PAPER") else "BLOCKED", f"mode {mode}: {st['trading'].get('why_not') or 'orders allowed'}")
    if mode not in ("SIM", "PAPER"):
        return finish()

    # 2. ticker load
    api(base, "/api/play", {"symbol": sym, "action": "add"})
    api(base, "/api/play", {"symbol": sym, "action": "focus"})
    got = wait_for(lambda: pane(base, sym)[1], 20)
    say("ticker load", "PASS" if got else "FAIL", f"{sym} on the desk" if got else f"{sym} never showed a pane")
    if not got:
        return finish()

    # 3. quotes
    q = wait_for(lambda: (lambda p: p and p.get("bid") and p.get("ask") and p)(pane(base, sym)[1]), 30)
    say("quotes", "PASS" if q else "BLOCKED", f"bid {q['bid']} / ask {q['ask']} last {q.get('last')}" if q else
        "no bid / ask within 30 s: market closed, or no market-data subscription on this account (IBKR errors 354 / 10168 in MESSAGES)")
    if not q:
        return finish()
    tick = 0.01 if q["ask"] >= 1 else 0.0001

    # 4. depth
    d = wait_for(lambda: (lambda p: p and p.get("ladder") and p["ladder"].get("rows") and any(r.get("bid") or r.get("ask") for r in p["ladder"]["rows"]) and p)(pane(base, sym)[1]), 30)
    say("market depth", "PASS" if d else "BLOCKED", f"{sum(1 for r in d['ladder']['rows'] if r.get('bid') or r.get('ask'))} ladder rows with size" if d else
        "no depth rows within 30 s (depth needs a Level II subscription; the desk shows this as DEPTH off)")

    # 5. arm + place a far-off limit
    api(base, "/api/trade/arm", {"on": True})
    far = round(q["bid"] * 0.90 / tick) * tick
    out = api(base, "/api/trade/order", {"symbol": sym, "action": "BUY", "price": round(far, 4), "qty": 1, "type": "LMT", "tif": "DAY", "bracket": False, "nonce": f"acc{int(time.time())}"})
    say("limit order placed", "PASS" if out.get("ok") else "FAIL", out.get("sent") or out.get("reason", ""))
    oid = out.get("id")
    if oid is None:
        return finish()
    ack = wait_for(lambda: (lambda p: next((o for o in p.get("orders", []) if o.get("id") == oid), None))(pane(base, sym)[1]), 15)
    say("order on the ladder", "PASS" if ack else "FAIL", f"status {ack.get('status')}" if ack else "the order never showed in the pane's orders")

    # 6. modify
    newpx = round(far - 10 * tick, 4)
    out = api(base, "/api/trade/modify", {"id": oid, "price": newpx})
    moved = out.get("ok") and wait_for(lambda: (lambda p: next((o for o in p.get("orders", []) if o.get("id") == oid and abs((o.get("price") or 0) - newpx) < tick / 2), None))(pane(base, sym)[1]), 15)
    say("modify acknowledged", "PASS" if moved else "FAIL", f"now at {newpx}" if moved else (out.get("reason") or "the new price never showed on the order"))

    # 7. cancel
    out = api(base, "/api/trade/cancel", {"id": oid})
    gone = out.get("ok") and wait_for(lambda: (lambda p: not any(o.get("id") == oid for o in p.get("orders", [])))(pane(base, sym)[1]), 15)
    say("cancel acknowledged", "PASS" if gone else "FAIL", "" if gone else (out.get("reason") or "the order is still listed as working"))

    # 8. bracket: a far-off entry with the QUARTERS template so the children exist without a fill
    api(base, "/api/trade/bracket", {"on": True}); api(base, "/api/trade/bracket_template", {"name": "QUARTERS"})
    out = api(base, "/api/trade/order", {"symbol": sym, "action": "BUY", "price": round(far, 4), "qty": 3, "type": "LMT", "tif": "DAY", "bracket": True, "nonce": f"accb{int(time.time())}"})
    pid = out.get("id")
    fam = out.get("ok") and wait_for(lambda: (lambda p: [o for o in p.get("orders", []) if o.get("role") in ("stop", "target_1", "target_2", "target_3")])(pane(base, sym)[1]), 15)
    say("bracket parent + children", "PASS" if fam else "FAIL", f"parent #{pid} with {len(fam)} exit legs" if fam else (out.get("reason") or "no exit legs appeared"))
    api(base, "/api/trade/cancel_all", {"symbol": sym})
    api(base, "/api/trade/bracket_template", {"name": "PLAY"})
    clean = wait_for(lambda: (lambda p: not p.get("orders"))(pane(base, sym)[1]), 15)
    say("cancel all", "PASS" if clean else "FAIL", "" if clean else "working orders remain")

    # 9. symbol switch: the new pane carries its own quotes, none of the old symbol's
    api(base, "/api/play", {"symbol": sw, "action": "add"}); api(base, "/api/play", {"symbol": sw, "action": "focus"})
    p2 = wait_for(lambda: (lambda p: p and p.get("bid") and p)(pane(base, sw)[1]), 30)
    stale = p2 and p2.get("symbol") == sw and not any(o.get("symbol", sw) != sw for o in p2.get("orders", []))
    say("symbol switch, no stale data", "PASS" if stale else ("BLOCKED" if not p2 else "FAIL"), f"{sw} bid {p2['bid']} / ask {p2['ask']}" if p2 else f"{sw}: no quotes within 30 s")
    api(base, "/api/play", {"symbol": sym, "action": "focus"})

    # 10. flatten — only with a real position, and only when asked (the practice desk opens one share to test it)
    st, p = pane(base, sym)
    pos = (p or {}).get("position")
    if a.demo and a.yes and not (pos and pos.get("qty")):
        q2 = pane(base, sym)[1]
        api(base, "/api/trade/order", {"symbol": sym, "action": "BUY", "price": round(q2["ask"] + 5 * tick, 4), "qty": 1, "type": "LMT", "tif": "DAY", "bracket": False, "nonce": f"accf{int(time.time())}"})
        pos = wait_for(lambda: (lambda p: (p.get("position") or {}) if (p.get("position") or {}).get("qty") else None)(pane(base, sym)[1]), 20)
    if pos and pos.get("qty"):
        if a.yes or input(f"{sym} holds {pos['qty']} — FLATTEN it now? [y/N] ").strip().lower() == "y":
            out = api(base, "/api/trade/flatten", {"symbol": sym})
            flat = out.get("ok") and wait_for(lambda: (lambda p: not (p.get("position") or {}).get("qty"))(pane(base, sym)[1]), 30)
            say("flatten verified flat", "PASS" if flat else "FAIL", "" if flat else (out.get("reason") or "position still open after 30 s"))
        else:
            say("flatten", "BLOCKED", "skipped by you")
    else:
        say("flatten", "BLOCKED", f"no position in {sym} to flatten (open one in the ticket and rerun with --yes)")

    # 11. reconnect
    if a.reconnect and not a.demo:
        print("Now close TWS (File > Exit) and log back in. Watching the desk for DISCONNECTED -> RECONNECTING -> CONNECTED (up to 5 min)…")
        seen = set()
        end = time.time() + 300
        while time.time() < end:
            s_ = api(base, "/api/state")["connection"]["state"]; seen.add(s_)
            if "DISCONNECTED" in seen and s_ == "CONNECTED":
                break
            time.sleep(1)
        ok = "DISCONNECTED" in seen and s_ == "CONNECTED"
        say("reconnect", "PASS" if ok else "FAIL", f"states seen: {sorted(seen)}")
    else:
        say("reconnect", "BLOCKED", "run with --reconnect against IBKR paper and restart TWS when asked")

    # 12. replay: a recording on disk (the desk writes recordings/*.jsonl while REC is on; the replay engine
    #     plays one with start_replay.bat / --replay, with pause, play, speed, step, restart and scrub)
    import glob, os
    recs = [f for f in glob.glob(os.path.join(a.recordings, "*.jsonl")) if os.path.getsize(f) > 0]
    say("replay", "PASS" if recs else "BLOCKED", f"{len(recs)} recording(s) in {a.recordings} (start_replay.bat plays one)" if recs else f"no recording in {a.recordings} yet: REC a session first")
    return finish()


def finish():
    n = {"PASS": 0, "FAIL": 0, "BLOCKED": 0}
    for _s, st, _w in RESULTS:
        n[st] = n.get(st, 0) + 1
    print(f"\n{n['PASS']} passed · {n['FAIL']} failed · {n['BLOCKED']} blocked")
    return 1 if n["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
