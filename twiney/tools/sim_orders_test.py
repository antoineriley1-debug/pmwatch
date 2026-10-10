"""End-to-end order test against a running TWINEY demo (python run_twiney.py --demo --port 8799): arm, limit, cancel,
marketable + bracket, scale, flatten, short, reverse, stop-limit, cancel side, caps, option chain + order, settings, play side."""
import json, time, urllib.request, urllib.error
RUN = str(int(time.time()))
B = "http://localhost:8799"
def get(p):
    return json.load(urllib.request.urlopen(B + p, timeout=10))
def post(p, body):
    r = urllib.request.Request(B + p, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    try:
        return json.load(urllib.request.urlopen(r, timeout=10))
    except urllib.error.HTTPError as e:
        try: return json.load(e)
        except Exception: return {"ok": False, "reason": f"HTTP {e.code}"}
res = []
def check(name, ok, detail=""):
    res.append((name, bool(ok), detail)); print(("PASS " if ok else "FAIL ") + name + (" — " + str(detail)[:140] if detail else ""))
def pane(sym):
    s = get("/api/state?extra=" + sym + "&full=")
    for p in (s.get("panes") or []) + list((s.get("extra") or {}).values()):
        if p and p.get("symbol") == sym: return s, p
    return s, None
s, p = pane("TSLA"); check("state + TSLA pane", p is not None and p.get("last"), p and p.get("last"))
last = float(p["last"]); bid, ask = float(p["bid"]), float(p["ask"])
check("arm", post("/api/trade/arm", {"on": True}).get("ok"))
post("/api/trade/cancel_all", {"symbol": "TSLA"}); post("/api/trade/flatten", {"symbol": "TSLA"}); time.sleep(2.0)
check("size 100", post("/api/trade/size", {"shares": 100}).get("ok"))
o = post("/api/trade/order", {"symbol": "TSLA", "action": "BUY", "price": round(last - 5, 2), "qty": 100, "type": "LMT", "bracket": False, "nonce": RUN + "n1"})
check("limit buy far away accepted", o.get("ok"), o); oid = o.get("id") or o.get("order_id")
time.sleep(0.6); s, p = pane("TSLA"); mine = [x for x in (p.get("orders") or [])]
check("order shows on the pane", any(abs(float(x.get("price") or x.get("lmt") or 0) - round(last - 5, 2)) < 0.011 for x in mine), [(x.get("price") or x.get("lmt"), x.get("status")) for x in mine])
c = post("/api/trade/cancel_all", {"symbol": "TSLA"}); check("cancel all", c.get("ok"), c)
time.sleep(0.6); s, p = pane("TSLA"); check("no working orders after cancel", not [x for x in (p.get("orders") or []) if x.get("status") not in ("Cancelled", "Filled", "Inactive")], [x.get("status") for x in (p.get("orders") or [])])
# a marketable limit: fills in the simulator, with a bracket (stop + target from the play)
post("/api/trade/bracket", {"on": True})
post("/api/play", {"symbol": "TSLA", "action": "clear"})
post("/api/play", {"symbol": "TSLA", "action": "setup", "fields": {"stop": round(last - 3, 2), "target": round(last + 6, 2)}})
o = post("/api/trade/order", {"symbol": "TSLA", "action": "BUY", "price": round(ask + 0.5, 2), "qty": 100, "type": "LMT", "bracket": True, "nonce": RUN + "n2"})
check("marketable limit buy with bracket accepted", o.get("ok"), o)
time.sleep(1.5); s, p = pane("TSLA"); pos = p.get("position")
if not (pos and float(pos.get("qty") or 0) > 0):
    time.sleep(3); s, p = pane("TSLA"); pos = p.get("position")
check("position opened in the simulator", pos and float(pos.get("qty") or 0) > 0, (pos, [(x.get("type"), x.get("action"), x.get("price"), x.get("status")) for x in (p.get("orders") or [])], p.get("bid"), p.get("ask")))
kids = [x for x in (p.get("orders") or []) if x.get("status") not in ("Cancelled", "Filled", "Inactive")]
check("bracket exits working", len(kids) >= 1, [(x.get("type"), x.get("price") or x.get("aux"), x.get("status")) for x in kids])
a = post("/api/trade/adjust", {"symbol": "TSLA", "shares": 50, "mode": "close"}); check("scale out 50 accepted", a.get("ok"), a)
time.sleep(1.2); s, p = pane("TSLA"); pos = p.get("position"); check("position reduced", pos and 0 < float(pos.get("qty") or 0) <= 100, pos)
f = post("/api/trade/flatten", {"symbol": "TSLA"}); check("flatten accepted", f.get("ok"), f)
time.sleep(1.5); s, p = pane("TSLA"); pos = p.get("position"); check("flat after flatten", not pos or float(pos.get("qty") or 0) == 0, pos)
check("no exits left after flatten", not [x for x in (p.get("orders") or []) if x.get("status") not in ("Cancelled", "Filled", "Inactive")], [x.get("status") for x in (p.get("orders") or [])])
# short side + reverse
o = post("/api/trade/order", {"symbol": "TSLA", "action": "SELL", "price": round(bid - 0.5, 2), "qty": 100, "type": "LMT", "bracket": False, "nonce": RUN + "n3"}); check("marketable short accepted", o.get("ok"), o)
for _ in range(8):
    time.sleep(0.6); s, p = pane("TSLA"); pos = p.get("position")
    if pos and float(pos.get("qty") or 0) < 0: break
check("short position", pos and float(pos.get("qty") or 0) < 0, pos)
r = post("/api/trade/reverse", {"symbol": "TSLA"}); check("reverse accepted", r.get("ok"), r)
time.sleep(1.5); s, p = pane("TSLA"); pos = p.get("position"); check("now long after reverse", pos and float(pos.get("qty") or 0) > 0, pos)
post("/api/trade/flatten", {"symbol": "TSLA"}); time.sleep(1.2)
# stop-limit and cancel one side
o = post("/api/trade/order", {"symbol": "TSLA", "action": "BUY", "price": round(last + 3.1, 2), "qty": 100, "type": "STP LMT", "aux": round(last + 3, 2), "bracket": False, "nonce": RUN + "n4"}); check("stop-limit accepted", o.get("ok"), o)
cs = post("/api/trade/cancel_side", {"symbol": "TSLA", "side": "BUY"}); check("cancel side BUY", cs.get("ok"), cs)
# caps: too big is refused
o = post("/api/trade/order", {"symbol": "TSLA", "action": "BUY", "price": round(last - 5, 2), "qty": 5000, "type": "LMT", "bracket": False, "nonce": RUN + "n5"}); check("5000 shares refused by the cap", not o.get("ok"), o.get("reason"))
o = post("/api/trade/order", {"symbol": "TSLA", "action": "BUY", "price": None, "qty": 100, "type": "MKT", "bracket": False, "nonce": RUN + "n6"}); check("market order refused (limit only)", not o.get("ok"), o.get("reason"))
# options: chain + open + close
ch = get("/api/options/chain?symbol=TSLA&right=C"); rows = ch.get("rows") or ch.get("chain") or []
check("option chain has rows with quotes", len(rows) > 0 and any(r.get("ask") for r in rows), (len(rows), rows[:1]))
exp = ch.get("expiry") or (ch.get("expiries") or [None])[0]; row = next((r for r in rows if r.get("ask")), None)
if row:
    o = post("/api/trade/opt_open", {"symbol": "TSLA", "expiry": exp or row.get("expiry"), "strike": row["strike"], "right": "C", "action": "BUY", "contracts": 2, "price": row["ask"]})
    check("option order accepted", o.get("ok"), o)
    time.sleep(4); s = get("/api/state?extra=TSLA&full="); acct = s.get("account") or {}
    opos = acct.get("opt_positions") or []
    check("option position on the desk", len(opos) > 0 and any("TSLA" in str(x.get("key") or x.get("symbol")) for x in opos), (opos[:1], [(o.get("symbol"), o.get("state")) for o in acct.get("pending", [])][:3]))
    if opos:
        oa = post("/api/trade/opt_adjust", {"symbol": "TSLA", "key": opos[0].get("key"), "contracts": 1, "mode": "close"}); check("option scale out 1 accepted", oa.get("ok"), oa)
# settings round trip
st = get("/api/settings"); check("settings schema", st.get("sections"))
sv = post("/api/settings", {"changes": {"tape.big_tape_x_average": 25}}); check("settings save live", sv.get("ok"), sv.get("applied"))
sv = post("/api/settings", {"changes": {"tape.big_tape_x_average": 20}})
# play setup: side from levels, levels on the chart
post("/api/play", {"symbol": "TSLA", "action": "clear"})
pl = post("/api/play", {"symbol": "TSLA", "action": "setup", "fields": {"stop": round(last + 3, 2), "target": round(last - 6, 2)}}); check("play levels saved", pl.get("ok"), pl)
time.sleep(0.4); s, p = pane("TSLA"); check("side inferred SHORT from stop above / target below", (p.get("play") or {}).get("side") == "short", (p.get("play") or {}).get("side"))
post("/api/play", {"symbol": "TSLA", "action": "clear"})
# big tape, day trap, order flow present
check("bigtape in pane", "bigtape" in p and "builders" in (p.get("bigtape") or {}))
check("orderflow in pane", "orderflow" in p); check("daytrap in pane", "daytrap" in p)
check("ladder half rows api", get("/api/ladder").get("half_rows") is not None) if False else None
post("/api/trade/arm", {"on": False})
n = sum(1 for r in res if not r[1]); print(f"\n{len(res) - n} passed · {n} failed")
