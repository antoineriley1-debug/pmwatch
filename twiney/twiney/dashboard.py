"""Local dashboard: one HTML page polling /api/state.

Write routes: screen controls (pin, auto-rotate) and order entry (/api/trade/*),
which goes through trading.Trader -> TradingGate (paper-only lock, caps, ARM).
"""

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

from . import auth as _auth

STATIC = os.path.join(os.path.dirname(__file__), "static", "dashboard.html")
MARKET_PAGE = os.path.join(os.path.dirname(__file__), "static", "market.html")
SHOW_PAGE = os.path.join(os.path.dirname(__file__), "static", "show.html")


def _static_build():
    """The build stamp baked into dashboard.html; the page reloads itself when the server's build is newer."""
    try:
        with open(STATIC, "r", encoding="utf-8") as fh:
            head = fh.read(4000)
        i = head.find('name="build" content="')
        return head[i + 22:head.find('"', i + 22)] if i >= 0 else ""
    except OSError:
        return ""


BUILD = _static_build()


def _layouts_file(layout_path):
    base = os.path.dirname(os.path.abspath(layout_path or "layout.json"))
    return os.path.join(base, "layouts.json")


def _load_layouts(layout_path):
    fp = _layouts_file(layout_path)
    if os.path.exists(fp):
        try:
            with open(fp, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, json.JSONDecodeError):
            pass
    return {"layouts": {}, "last": None, "prefs": {}}


def _save_layouts(layout_path, body):
    """Named layouts + preferences (hotkeys, recent symbols, tabs) in layouts.json next to config.json."""
    data = _load_layouts(layout_path)
    act = body.get("action")
    name = str(body.get("name", "")).strip()[:40]
    if act == "save" and name:
        data["layouts"][name] = body.get("layout")
        data["last"] = name
    elif act == "delete" and name:
        data["layouts"].pop(name, None)
        if data.get("last") == name:
            data["last"] = None
    elif act == "rename" and name and body.get("to"):
        to = str(body["to"]).strip()[:40]
        if name in data["layouts"]:
            data["layouts"][to] = data["layouts"].pop(name)
            if data.get("last") == name:
                data["last"] = to
    elif act == "use" and name:
        data["last"] = name
    elif act == "prefs":
        data.setdefault("prefs", {}).update(body.get("prefs") or {})
    else:
        return {"ok": False, "reason": "bad action"}
    fp = _layouts_file(layout_path)
    tmp = fp + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1)
    os.replace(tmp, fp)
    return dict(data, ok=True)


class EngineRef:
    """Forwards to whichever engine is current (the replay desk restarts its engine on a backward jump)."""

    def __init__(self, box):
        self._box = box

    def __getattr__(self, name):
        return getattr(self._box["engine"], name)


_SNAP_LOCK = threading.Lock()
_SNAP_CACHE = {}
_DIFF_SEEN = {}        # client id -> {top-level key: hash of its last JSON}: what each page already holds


# with THE SIGN-IN on, these answer without a session: the sign-in page itself and the health check
OPEN_GET = {"/login", "/healthz"}
OPEN_POST = {"/api/login", "/api/auth/setup", "/api/logout"}


def make_handler(engine, clock, trader=None, desk=None, rec_dir=None, layout_path=None, config_path=None, hooks=None, auth=None):
    hooks = hooks if hooks is not None else {}
    class Handler(BaseHTTPRequestHandler):
        server_version = "TWINEY/1.0"

        def log_message(self, fmt, *args):  # keep the console for alerts
            pass

        def _local(self):
            """Only this computer's own page may talk to the desk. The Host header must name this machine
            (127.0.0.1 / localhost / [::1]) on the desk's port, so a website that re-points its own name at
            127.0.0.1 (DNS rebinding) is refused; a browser's Origin, when sent, must be one of those too."""
            port = self.server.server_address[1]
            names = ("127.0.0.1", "localhost", "[::1]")
            ok = {f"{h}:{port}" for h in names} | (set(names) if port == 80 else set())   # browsers drop :80
            host = (self.headers.get("Host") or "").strip().lower()
            if host and host not in ok:
                return False
            origin = (self.headers.get("Origin") or "").strip().lower()
            if origin and origin not in {f"http://{h}" for h in ok}:
                return False
            return True

        def _client(self):
            """Who is asking, for the wrong-password count: behind Tailscale / an SSH tunnel the peer is this machine,
            so the address the proxy added last."""
            peer = self.client_address[0] if self.client_address else ""
            xff = self.headers.get("X-Forwarded-For")
            if xff and peer in ("127.0.0.1", "::1", "::ffff:127.0.0.1"):
                return xff.split(",")[-1].strip() or peer
            return peer

        def _same_origin(self):
            """THE SIGN-IN guards the desk, so it may be reached by any name (Tailscale's address too), but a browser's
            Origin, when sent, must be the very address it is talking to: another website can never act on the desk."""
            origin = (self.headers.get("Origin") or "").strip().lower()
            if not origin:
                return True
            got = urlparse(origin).netloc
            names = {(self.headers.get("Host") or "").strip().lower(), (self.headers.get("X-Forwarded-Host") or "").strip().lower()}
            return bool(got) and got in names

        def _https(self):
            return (self.headers.get("X-Forwarded-Proto") or "").strip().lower() == "https"

        def _signed_in(self):
            return auth is None or auth.valid(_auth.cookie_from(self.headers.get("Cookie")))

        def _guard(self, post):
            """True when this request may go on; otherwise the answer is already sent."""
            path = self.path.split("?", 1)[0]
            if auth is None:
                if not self._local():
                    self._send(403, "forbidden", "text/plain")
                    return False
                return True
            if not self._same_origin():
                self._send(403, "forbidden", "text/plain")
                return False
            if path in (OPEN_POST if post else OPEN_GET) or self._signed_in():
                return True
            if post or path.startswith("/api/") or not (path in ("/", "/index.html", "/market", "/show")):
                self._send(401, json.dumps({"ok": False, "signin": True, "reason": "sign in first"}), "application/json")
            else:
                self._redirect("/login" + ("" if path in ("/", "/index.html") else "?next=" + quote(path)))
            return False

        def _redirect(self, where, cookie=None):
            self.send_response(303)
            self.send_header("Location", where)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", "0")
            if cookie is not None:
                self.send_header("Set-Cookie", cookie)
            self.end_headers()

        def _auth_post(self, path, body):
            """The sign-in routes. True when this was one of them (the answer is sent)."""
            if path not in ("/api/login", "/api/auth/setup", "/api/logout", "/api/auth/password"):
                return False
            who, life = self._client(), int(auth.session_s)
            if path == "/api/logout":
                if body.get("everywhere") and self._signed_in():
                    auth.sign_out_everywhere()
                self._send(200, json.dumps({"ok": True}), "application/json", cookie=_auth.set_cookie("", self._https(), 0))
                return True
            if path == "/api/login":
                tok, why = auth.login(str(body.get("password") or ""), who)
                if tok:
                    print(f"TED: signed in from {who}", flush=True)
            elif path == "/api/auth/setup":
                ok, why = auth.setup(body.get("code"), body.get("password"), body.get("confirm"), who)
                tok = auth.issue() if ok else None
                if ok:
                    print(f"TED: password created from {who}", flush=True)
            else:
                ok, why = auth.change_password(str(body.get("current") or ""), body.get("password"), body.get("confirm"), who)
                tok = auth.issue() if ok else None          # this browser stays signed in, every other one is out
            if tok:
                self._send(200, json.dumps({"ok": True}), "application/json", cookie=_auth.set_cookie(tok, self._https(), life))
            else:
                if path == "/api/login":
                    print(f"TED: refused sign-in from {who} ({why})", flush=True)
                # a refused password change answers 400: a 401 sends the desk to the sign-in page
                self._send(429 if "too many" in why else 400 if path == "/api/auth/password" else 401, json.dumps({"ok": False, "reason": why}), "application/json")
            return True

        def _open_trades(self):
            """What is open right now: shares, contracts, working orders. An update restarts TED, so it waits for flat."""
            out = []
            try:
                for sym in list(engine.syms):
                    pv = engine._position_view(sym, None)
                    if pv and pv.get("qty"):
                        out.append(f"{sym} {int(pv['qty']):+d} sh")
                    if engine._pending(sym):
                        out.append(f"{sym} working orders")
                for k, p in list(getattr(engine, "opt_positions", {}).items()):
                    if p.get("qty"):
                        out.append(f"{k} {int(p['qty']):+d} ct")
                    if engine._pending(k):
                        out.append(f"{k} working orders")
            except Exception:  # noqa: BLE001
                pass
            return out

        def _relay_update(self, method, body):
            """The practice desk's UPDATE: asked of the live desk on this machine, with the same sign-in."""
            import urllib.request
            qs = urlparse(self.path).query
            req = urllib.request.Request(hooks["update_relay"] + "/api/update" + ("?" + qs if qs else ""), method=method,
                                         data=json.dumps(body or {}).encode() if method == "POST" else None,
                                         headers={"Cookie": self.headers.get("Cookie") or "", "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=20) as r:
                    code, data = r.status, r.read()
            except urllib.error.HTTPError as e:
                code, data = e.code, e.read()
                if code == 401:                  # signed out over there: say so here, never send this page to sign in
                    code, data = 200, json.dumps({"ok": False, "enabled": False, "reason": "sign in on the live desk to update"}).encode()
            except Exception as e:
                code, data = 200, json.dumps({"ok": False, "enabled": False, "reason": f"the live desk did not answer ({e})"}).encode()
            self._send(code, data, "application/json")

        def _update(self, body):
            if hooks.get("update_relay") and not hooks.get("update"):
                self._relay_update("POST", body)
                return
            up = hooks.get("update")
            if up is None or not up.enabled():
                self._send(400, json.dumps({"ok": False, "reason": "updating from the desk works on the VPS install only"}), "application/json")
                return
            st = up.check(force=True)
            if not st.get("newer") and not body.get("same"):
                self._send(200, json.dumps({"ok": False, "reason": f"already on the newest build ({st.get('current')})"}), "application/json")
                return
            busy = self._open_trades()
            if busy:
                self._send(409, json.dumps({"ok": False, "reason": "close out first, an update restarts TED: " + ", ".join(busy[:6])}), "application/json")
                return

            def go():
                res = up.install()
                if res.get("ok") and hooks.get("restart"):
                    engine._message("info", f"UPDATE: build {res['build']} installed, TED restarting", clock())
                    time.sleep(0.8)
                    hooks["restart"]()
                elif not res.get("ok"):
                    engine._message("error", "UPDATE: " + res.get("reason", "failed"), clock())
            threading.Thread(target=go, name="ted-update", daemon=True).start()
            self._send(200, json.dumps({"ok": True, "started": True, "latest": st.get("latest")}), "application/json")

        def _send(self, code, body, ctype, cookie=None):
            data = body if isinstance(body, bytes) else body.encode("utf-8")
            # the desk polls a big snapshot a few times a second: gzip takes it down ~8x on the wire
            if len(data) > 2048 and "gzip" in str(self.headers.get("Accept-Encoding", "")) and ctype.startswith(("application/json", "text/")):
                import gzip as _gz
                data = _gz.compress(data, compresslevel=3)
                self.send_response(code)
                self.send_header("Content-Encoding", "gzip")
                self.send_header("Vary", "Accept-Encoding")
            else:
                self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Frame-Options", "DENY")                 # never shown inside another site's page
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            if cookie is not None:
                self.send_header("Set-Cookie", cookie)
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass                    # the page went away mid-answer (closed / reloaded): nothing to say

        def do_GET(self):
            if not self._guard(False):
                return
            path = self.path.split("?", 1)[0]
            if path == "/login":
                if auth is None or self._signed_in():
                    self._redirect("/")
                else:
                    self._send(200, _auth.login_page(not auth.has_password()), "text/html; charset=utf-8")
                return
            if path == "/api/auth":
                self._send(200, json.dumps({"ok": True, "sign_in": auth is not None, "signed_in": self._signed_in(),
                                            "session_hours": round(auth.session_s / 3600, 2) if auth else None}), "application/json")
                return
            if path == "/api/show":
                # THE SHOW page: the watchlist light, the charts in view full
                q = parse_qs(urlparse(self.path).query)
                view = [x.strip().upper() for x in q.get("view", [""])[0].split(",") if x.strip()][:6]
                full = {x.strip().upper() for x in q.get("full", [""])[0].split(",") if x.strip()}
                try:
                    out = engine.show_snapshot(clock(), view, full)
                except Exception as exc:  # noqa: BLE001
                    out = {"ok": False, "reason": str(exc)}
                out["build"] = BUILD
                self._send(200, json.dumps(out, default=str, separators=(",", ":")), "application/json")
                return
            if path == "/show":
                try:
                    with open(SHOW_PAGE, "rb") as fh:
                        self._send(200, fh.read(), "text/html; charset=utf-8")
                except OSError:
                    self._send(404, "the show page is not built: python page_src/build_page.py", "text/plain")
                return
            if path == "/api/callbook":
                # THE CALL BOOK: the cards (brief), one whole card (?id=), or THE WEEKLY REVIEW (?review=1)
                q = parse_qs(urlparse(self.path).query)
                cb = engine.callbook
                try:
                    days = max(1, min(400, int(q.get("days", ["7"])[0])))
                except ValueError:
                    days = 7
                cid = q.get("id", [""])[0]
                with engine.lock:
                    if cid:
                        c = cb.recent.get(cid) or cb._find(cid)
                        out = {"ok": c is not None, "card": c}
                    else:
                        cards = cb.read(days, clock() if engine.replay is None else None)
                        rv = cb.review(cards) if q.get("review") else None
                        if rv is not None:                 # how your own reads did over the same days
                            rv["my_reads"] = engine.myread.review(clock() - days * 86400)
                        out = {"ok": True, "days": days, "cards": [cb.brief(c) for c in cards[:300]], "review": rv}
                self._send(200, json.dumps(out, default=str, separators=(",", ":")), "application/json")
                return
            if path == "/api/phrases":
                # THE PHRASE LIST: every spoken call, its built-in line, the versions (pending / approved)
                self._send(200, json.dumps(dict(engine.phrases.view(), ok=True)), "application/json")
                return
            if path.startswith("/api/callbook/pic/"):
                p = engine.callbook.pic_path(path.rsplit("/", 1)[1])
                if p is None:
                    self._send(404, "not found", "text/plain")
                    return
                with open(p, "rb") as fh:
                    self._send(200, fh.read(), "image/png" if p.endswith(".png") else "image/jpeg")
                return
            if path == "/api/optmoney":
                # OPTION MONEY: which Quant Data tools this key opens (the CHECK), and THE ODDS from the scored calls
                feed = hooks.get("optmoney_feed")
                om = engine.optmoney
                self._send(200, json.dumps({"ok": True, "feed": feed is not None, "checked": om.checked,
                                            "status": {k: dict(v, name=_om_names().get(k, k)) for k, v in om.status.items()},
                                            "odds": engine.score.odds(), "src": engine.score.src}, default=str), "application/json")
                return
            if path == "/api/update" and hooks.get("update_relay") and not hooks.get("update"):
                self._relay_update("GET", None)
                return
            if path == "/api/update":
                up = hooks.get("update")
                q = parse_qs(urlparse(self.path).query)
                out = up.check(force=q.get("force", [""])[0] == "1") if up else {"ok": True, "enabled": False}
                self._send(200, json.dumps(out), "application/json")
                return
            if path in ("/", "/index.html"):
                with open(STATIC, "rb") as fh:
                    self._send(200, fh.read(), "text/html; charset=utf-8")
            elif path == "/market":
                # MARKET ANALYSIS DETAILED REPORT: its own page, opened from the desk's MARKET button
                try:
                    with open(MARKET_PAGE, "rb") as fh:
                        self._send(200, fh.read(), "text/html; charset=utf-8")
                except OSError:
                    self._send(404, "the market page is not built: python page_src/build_page.py", "text/plain")
            elif path == "/api/market":
                mk = getattr(engine, "macro", None)
                q = parse_qs(urlparse(self.path).query, keep_blank_values=True)
                if mk is None:
                    self._send(200, json.dumps({"ok": False, "reason": "the market report is off (SETTINGS > Market report)"}), "application/json")
                else:
                    snap = mk.snapshot(full=q.get("lite", [""])[0] != "1")
                    ai = getattr(engine, "ai", None)
                    snap["ai"] = ai.status() if ai is not None else None
                    snap["build"] = BUILD
                    snap["ok"] = True
                    self._send(200, json.dumps(snap, default=str, separators=(",", ":")), "application/json")
            elif path == "/api/stream":
                # STREAMING: the ticker on screen, pushed the moment its book, tape or quote changes (Server-Sent
                # Events). Checked every 40 ms, at most ~25 sends a second; the regular refresh carries the rest
                q = parse_qs(urlparse(self.path).query)
                sym = (q.get("sym", [""])[0] or "").strip().upper()
                if engine.stream_ver(sym) is None:
                    self._send(404, "unknown symbol", "text/plain")
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Accel-Buffering", "no")
                self.end_headers()
                seen, beat = None, time.monotonic()
                try:
                    while True:
                        v = engine.stream_ver(sym)
                        if v is None:
                            return
                        if v != seen:
                            seen = v
                            fp = engine.fast_pane(sym, clock())
                            if fp is not None:
                                self.wfile.write(b"data: " + json.dumps(fp, default=str, separators=(",", ":")).encode("utf-8") + b"\n\n")
                                self.wfile.flush()
                                beat = time.monotonic()
                        elif time.monotonic() - beat > 10.0:
                            self.wfile.write(b": alive\n\n"); self.wfile.flush(); beat = time.monotonic()
                        time.sleep(0.04)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    return
            elif path == "/api/state":
                q = parse_qs(urlparse(self.path).query, keep_blank_values=True)
                extra = [x.strip().upper() for x in (q.get("extra", [""])[0]).split(",") if x.strip()][:12]
                full = None
                if "full" in q:   # the page names the symbols it still needs history for; "" = none
                    full = {x.strip().upper() for x in q.get("full", [""])[0].split(",") if x.strip()}
                try:
                    tv = int(q.get("tv", [""])[0])
                except ValueError:
                    tv = None
                key = (tuple(extra), tuple(sorted(full)) if full is not None else None, tv)
                client = (q.get("c", [""])[0] or "")[:40]            # the page's own id: it gets only the keys that changed
                now = time.monotonic()
                with _SNAP_LOCK:
                    hit = _SNAP_CACHE.get(key)
                    if hit and now - hit[0] < 0.2:
                        parts, whole = hit[1]
                    else:
                        snap = engine.snapshot(clock(), extra, full, tv)
                        snap["build"] = BUILD
                        # every top-level key as its own JSON piece: a client that polled before gets only the pieces
                        # that changed, and the names of the ones it already holds
                        parts = {}
                        for k, v in snap.items():
                            if k == "panes" and isinstance(v, list):
                                # a pane field by field: the ladder and the tape move every tick, the studies, the
                                # story and the levels hardly at all
                                parts["panes/n"] = json.dumps(len(v))
                                for i, d in enumerate(v):
                                    for f, x in (d or {}).items():
                                        parts[f"panes/{i}/{f}"] = json.dumps(x, default=str)
                            else:
                                parts[k] = json.dumps(v, default=str)
                        _SNAP_CACHE.clear(); _SNAP_CACHE[key] = (now, (parts, json.dumps(snap, default=str)))
                        whole = _SNAP_CACHE[key][1][1]
                    if client:
                        seen = _DIFF_SEEN.setdefault(client, {})
                        keep, send = [], []
                        for k, js in parts.items():
                            h = hash(js)
                            if seen.get(k) == h:
                                keep.append(k)
                            else:
                                seen[k] = h
                                send.append(f"{json.dumps(k)}:{js}")
                        send.append(f'"_keep":{json.dumps(keep)}')
                        body = "{" + ",".join(send) + "}"
                        if len(_DIFF_SEEN) > 24:                        # pages come and go: the oldest forgotten
                            _DIFF_SEEN.pop(next(iter(_DIFF_SEEN)), None)
                    else:
                        body = whole
                self._send(200, body, "application/json")
            elif path == "/api/flow/symbol":
                q = parse_qs(urlparse(self.path).query, keep_blank_values=True)
                self._send(200, json.dumps(engine.symbol_flow(q.get("s", [""])[0], clock()), default=str), "application/json")
            elif path == "/api/options/chain":
                q = parse_qs(urlparse(self.path).query, keep_blank_values=True)
                sym = str(q.get("symbol", [""])[0]).upper()
                ch = engine.option_chain(sym, q.get("expiry", [None])[0] or None, q.get("right", ["C"])[0], clock())
                sess = getattr(engine, "session", None)
                if sess is not None and sym and ch.get("available") is False and ch.get("source") is None and hasattr(sess, "request_chain"):
                    sess.request_chain(sym)                 # live: ask IBKR once; the next poll has it
                if sess is not None and ch.get("available") and ch.get("source") == "IBKR" and hasattr(sess, "watch_option_quotes"):
                    spot = ch.get("spot")             # nearest the price first; no price yet = no quotes yet
                    near = sorted(ch["rows"], key=lambda r: abs(r["strike"] - spot)) if spot else []
                    sess.watch_option_quotes(sym, [r["key"] for r in near], ch.get("mult") or 100)
                self._send(200, json.dumps(ch, default=str), "application/json")
                return
            elif path == "/api/options/bars":
                q = parse_qs(urlparse(self.path).query, keep_blank_values=True)
                key = str(q.get("key", [""])[0])
                sess = getattr(engine, "session", None)
                if sess is not None and key and hasattr(sess, "chart_option"):
                    sess.chart_option(key)                  # live: quotes + today's MIDPOINT minutes from IBKR, once
                self._send(200, json.dumps(engine.option_bars(key, clock()), default=str), "application/json")
                return
            elif path == "/api/ps60/signals":
                from . import ps60 as _ps60
                q = parse_qs(urlparse(self.path).query, keep_blank_values=True)
                sym = str(q.get("symbol", [""])[0]).upper()
                self._send(200, json.dumps(_ps60.SignalProvider(engine).signals(sym), default=str), "application/json")
                return
            elif path == "/api/urgency":
                q = parse_qs(urlparse(self.path).query)
                sym = (q.get("symbol", [""])[0] or "").strip().upper()[:10]
                out = engine.urgency_for(sym, clock()) if sym else {"symbol": "", "live": [], "history": []}
                self._send(200, json.dumps(out, default=str), "application/json")
            elif path.startswith("/recordings/shots/") and rec_dir:
                name = os.path.basename(path)
                fp = os.path.join(rec_dir, "shots", name)
                if name.endswith(".png") and os.path.exists(fp):
                    with open(fp, "rb") as fh:
                        self._send(200, fh.read(), "image/png")
                else:
                    self._send(404, "not found", "text/plain")
            elif path.startswith("/recordings/voice/") and rec_dir:
                name = os.path.basename(path)
                fp = os.path.join(rec_dir, "voice", name)
                ctype = {"webm": "audio/webm", "ogg": "audio/ogg", "mp4": "audio/mp4", "m4a": "audio/mp4"}.get(name.rsplit(".", 1)[-1])
                if ctype and os.path.exists(fp):
                    with open(fp, "rb") as fh:
                        self._send(200, fh.read(), ctype)
                else:
                    self._send(404, "not found", "text/plain")
            elif path.startswith("/recordings/") and path.endswith(".journal.md") and rec_dir:
                fp = os.path.join(rec_dir, os.path.basename(path))
                if os.path.exists(fp):
                    with open(fp, "rb") as fh:
                        self._send(200, fh.read(), "text/plain; charset=utf-8")
                else:
                    self._send(404, "not found", "text/plain")
            elif path == "/api/settings":
                from . import settings as _settings
                self._send(200, json.dumps({"sections": _settings.schema(engine.cfg), "file": config_path,
                                            "can_restart": bool(hooks.get("restart"))}, default=str), "application/json")
            elif path == "/api/layouts":
                self._send(200, json.dumps(_load_layouts(layout_path)), "application/json")
            elif path == "/api/layout":
                lp = layout_path or "layout.json"
                if os.path.exists(lp):
                    with open(lp, encoding="utf-8") as fh:
                        self._send(200, json.dumps({"ok": True, "layout": json.load(fh)}), "application/json")
                else:
                    self._send(200, json.dumps({"ok": True, "layout": None}), "application/json")
            elif path == "/api/desk/trades.csv" and desk is not None:
                data = desk.trades_csv().encode("utf-8-sig")        # utf-8 with BOM: Excel opens it cleanly
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", f'attachment; filename="TED-journal-{time.strftime("%Y-%m-%d")}.csv"')
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            elif path == "/api/desk/export" and desk is not None:
                name = os.path.basename(parse_qs(urlparse(self.path).query).get("name", [""])[0])
                data = desk.export_bundle(name, clock())
                if data is None:
                    self._send(404, "not found", "text/plain")
                else:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/zip")
                    self.send_header("Content-Disposition", f'attachment; filename="{name[:-6]}.zip"')
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
            elif path == "/api/clips":
                from . import clips as _clips
                self._send(200, json.dumps(_clips.load(rec_dir or "recordings")), "application/json")
            elif path == "/api/datasource":
                tc = engine.cfg.get("trading") or {}
                recs = []
                rd = rec_dir or "recordings"
                if os.path.isdir(rd):
                    for n in sorted(os.listdir(rd), reverse=True):
                        rec = getattr(getattr(engine, "recorder", None), "path", None)   # never the file being written right now
                        if rec and os.path.basename(rec) == n:
                            continue
                        if n.endswith(".jsonl") and not n.endswith(".marks.jsonl") and "-" in n and n[0].isalpha() and os.path.getsize(os.path.join(rd, n)) > 20000:
                            recs.append({"name": n, "size_mb": round(os.path.getsize(os.path.join(rd, n)) / 1e6, 1)})
                self._send(200, json.dumps({"ok": True, "source": hooks.get("source"), "can_switch": bool(hooks.get("datasource")),
                                            "start_mode": tc.get("start_mode"), "sim_data": tc.get("sim_data"),
                                            "sim_recording": tc.get("sim_recording"), "recordings": recs[:30]}), "application/json")
            elif path == "/api/desk/list":
                self._send(200, json.dumps(desk.list_recordings() if desk else []), "application/json")
            elif path == "/api/tts/test":
                # TEST VOICE: one line straight from the voice service (not the cache): is ElevenLabs answering?
                from . import tts
                sc = engine.cfg.get("speech") or {}
                cache = os.path.join(os.path.dirname(os.path.abspath(engine.cfg.get("recording", {}).get("dir") or "recordings")), "voice_cache")
                out = {"engine": sc.get("engine") or "auto", "key_set": bool(str(sc.get("api_key") or "").strip()), "voice_set": bool(str(sc.get("voice_id") or "").strip())}
                if not out["key_set"] or not out["voice_set"]:
                    out.update(ok=False, reason="SETTINGS > Voice: " + " and ".join(x for x, ok in (("the API key", out["key_set"]), ("the voice ID", out["voice_set"])) if not ok) + " missing.")
                else:
                    try:
                        audio = tts.speak(engine.cfg, "Voice check. The desk is live.", cache, fresh=True)
                        out.update(ok=True, bytes=len(audio), voice_id=tts.voice_id(engine.cfg),
                                   reason="ElevenLabs answered: your voice is working and says every call."
                                   if tts.ready(engine.cfg) else "ElevenLabs answered, BUT Engine is set to browser: set Engine to auto or ElevenLabs to hear this voice on the calls.")
                    except tts.TTSError as e:
                        out.update(ok=False, reason=str(e))
                self._send(200, json.dumps(out), "application/json")
            elif path == "/api/tts":
                # THE DESK'S VOICE: this call's words in the cloud voice (cached on disk); 502 = use the browser's voice
                from . import tts
                q = parse_qs(urlparse(self.path).query, keep_blank_values=True)
                cache = os.path.join(os.path.dirname(os.path.abspath(engine.cfg.get("recording", {}).get("dir") or "recordings")), "voice_cache")
                try:
                    audio = tts.speak(engine.cfg, q.get("text", [""])[0], cache)
                    self._send(200, audio, "audio/mpeg")
                except tts.TTSError as e:
                    self._send(502, json.dumps({"ok": False, "reason": str(e)}), "application/json")
            elif path.startswith("/api/ai/"):
                # DESK AI: status (with a live check of Ollama), the latest answer for a job, the saved answers
                ai = getattr(engine, "ai", None)
                q = parse_qs(urlparse(self.path).query, keep_blank_values=True)
                if ai is None:
                    self._send(404, json.dumps({"ok": False, "reason": "DESK AI is not loaded"}), "application/json")
                elif path == "/api/ai/status":
                    ai.check(force=bool(q.get("force", [""])[0]))
                    self._send(200, json.dumps(dict(ai.status(), ok=True)), "application/json")
                elif path == "/api/ai/result":
                    r = ai.result(q.get("job", ["recap"])[0])
                    self._send(200, json.dumps({"ok": r is not None, "result": r, "busy": ai.busy}), "application/json")
                elif path == "/api/ai/list":
                    self._send(200, json.dumps({"ok": True, "files": ai.files()}), "application/json")
                elif path == "/api/ai/file":
                    text = ai.read(q.get("name", [""])[0])
                    if text is None:
                        self._send(404, "not found", "text/plain")
                    else:
                        self._send(200, text, "text/markdown; charset=utf-8")
                else:
                    self._send(404, "not found", "text/plain")
            elif path == "/healthz":
                self._send(200, json.dumps({"ok": True, "connection": engine.connection["state"]}),
                           "application/json")
            else:
                self._send(404, "not found", "text/plain")

        def do_POST(self):
            # only accept requests from this dashboard page (blocks other websites), signed in when THE SIGN-IN is on
            if not self._guard(True):
                return
            with _SNAP_LOCK:          # anything you do shows on the very next update, never a cached one from before it
                _SNAP_CACHE.clear()
            if self.path.split("?", 1)[0] == "/api/desk/mic_audio":
                self._mic_audio()
                return
            if self.path.split("?", 1)[0] == "/api/callbook/pic":
                self._callbook_pic()
                return
            if (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/json":
                self._send(415, "json only", "text/plain")
                return
            try:
                length = min(int(self.headers.get("Content-Length") or 0), 4096)
                body = json.loads(self.rfile.read(length) or b"{}")
            except (ValueError, json.JSONDecodeError):
                self._send(400, "bad json", "text/plain")
                return
            if not isinstance(body, dict):
                self._send(400, "bad json", "text/plain")
                return
            path = self.path.split("?", 1)[0]
            if auth is not None and self._auth_post(path, body):
                return
            if path == "/api/update":
                self._update(body)
                return
            if path == "/api/phrases":
                act, kind = str(body.get("action", "")), str(body.get("kind", ""))
                ph = engine.phrases
                if act == "write":                   # the DESK AI writes versions: they come back as PENDING
                    ai = getattr(engine, "ai", None)
                    out = ai.run("phrases", t=clock(), kind=kind) if ai is not None else {"ok": False, "reason": "DESK AI is not loaded"}
                elif act == "add":                   # Twiney's own line: approved as he writes it
                    row, why = ph.add(kind, body.get("text", ""), by="twiney")
                    out = {"ok": row is not None, "reason": why, "line": row}
                elif act in ("approved", "rejected", "pending", "removed"):
                    out = {"ok": ph.set_status(kind, body.get("id", 0), act)}
                else:
                    out = {"ok": False, "reason": "unknown action"}
                self._send(200, json.dumps(out, default=str), "application/json")
                return
            if path == "/api/myread":
                # MY READ: BULLISH / BEARISH / NEUTRAL / HANDS OFF on a stock, today or this week (read "" clears it)
                sym = str(body.get("symbol", "")).upper()
                with engine.lock:
                    st = engine.syms.get(sym)
                    try:
                        r = engine.myread.set(sym, body.get("read") or None, body.get("why", ""), bool(body.get("week")), clock(),
                                              st.price() if st is not None else None)
                        out = {"ok": True, "read": r}
                    except ValueError as exc:
                        out = {"ok": False, "reason": str(exc)}
                self._send(200, json.dumps(out), "application/json")
                return
            if path == "/api/callbook/rate":
                with engine.lock:
                    c = engine.callbook.rate(str(body.get("id", "")), body.get("thumb"), body.get("note"))
                self._send(200, json.dumps({"ok": c is not None}), "application/json")
                return
            if path == "/api/optmoney/check":
                feed = hooks.get("optmoney_feed")
                if feed is None:
                    self._send(200, json.dumps({"ok": False, "reason": "no Quant Data key on this desk (the practice market shows practice numbers)"}), "application/json")
                    return
                threading.Thread(target=feed.check, name="optmoney-check", daemon=True).start()
                self._send(200, json.dumps({"ok": True, "started": True}), "application/json")
                return
            if path == "/api/pin":
                ok = engine.set_pinned(str(body.get("symbol", "")).upper(), bool(body.get("pinned")), clock())
                self._send(200 if ok else 404, json.dumps({"ok": ok}), "application/json")
            elif path == "/api/autorotate":
                engine.set_auto_rotate(bool(body.get("on")), clock())
                self._send(200, json.dumps({"ok": True}), "application/json")
            elif path.startswith("/api/trade/"):
                self._trade(path[len("/api/trade/"):], body)
            elif path == "/api/ladder/clear":
                ok = engine.ladder_clear(str(body.get("symbol", "")).upper(), str(body.get("where", "all")), clock())
                self._send(200 if ok else 400, json.dumps({"ok": ok}), "application/json")
            elif path == "/api/level":
                sym = str(body.get("symbol", "")).upper()
                role = str(body.get("role", "extra"))
                if role == "trigger" and not body.get("confirm"):
                    # the pivot is locked: it moves only on an explicit, confirmed request (PLAY SETUP or the mark tool)
                    self._send(409, json.dumps({"ok": False, "reason": "the pivot is locked; change it in PLAY SETUP"}), "application/json")
                    return
                price = body.get("price") if body.get("on", True) else None
                tr_ = trader if trader is not None else getattr(engine, "trader", None)
                if body.get("trade_as") in ("stock", "option") and tr_ is not None:
                    # STOCK or OPTIONS, picked as the 2nd entry is drawn: set BEFORE the line, so the stock entry
                    # never goes in for a line meant for the contract
                    tro = tr_.set_trade_as(sym, body["trade_as"], body.get("opt_key"), body.get("opt_qty"), clock())
                    if not tro.get("ok"):
                        self._send(400, json.dumps(tro), "application/json")
                        return
                if body.get("side") in ("long", "short") and role in ("trigger", "second_entry", "target", "stop"):
                    ok = engine.set_side_level(sym, body["side"], role, price, clock(), source="chart")
                elif role.startswith("alt_") and role[4:] in ("trigger", "second_entry", "target", "stop"):
                    ok = engine.set_play_level(sym, role[4:], price, clock(), source="chart", alt=True)
                elif role in ("trigger", "second_entry", "target", "stop"):
                    ok = engine.set_play_level(sym, role, price, clock(), source="chart")
                elif role == "sneaky":
                    ok = (engine.add_level if body.get("on", True) else engine.remove_level)(sym, body.get("price"), clock(), kind="sneaky")
                else:
                    ok = (engine.add_level if body.get("on", True) else engine.remove_level)(sym, body.get("price"), clock())
                self._send(200 if ok else 400, json.dumps({"ok": ok}), "application/json")
            elif path == "/api/zone":
                ok = engine.set_zone(str(body.get("symbol", "")).upper(), body.get("lo"), body.get("hi"), bool(body.get("on", True)), clock())
                self._send(200 if ok else 400, json.dumps({"ok": ok}), "application/json")
            elif path == "/api/settings":
                from . import settings as _settings
                from .config import ConfigError
                try:
                    applied, restart = _settings.apply(engine.cfg, config_path, body.get("changes") or {})
                    if applied:     # recorded, so a replay changes the same setting at the same moment
                        engine._rec({"ev": "settings", "t": clock(), "changes": {p: _settings._get(engine.cfg, p) for p in applied
                                                                                  if p not in _settings.SECRET}})
                    engine._message("info", f"settings saved: {', '.join(applied)}" if applied else "settings: nothing changed", clock())
                    if any(p.startswith("speech.") for p in applied):
                        sc = engine.cfg.get("speech") or {}
                        if sc.get("api_key") and not sc.get("voice_id"):
                            engine._message("warn", "ElevenLabs: the key is saved; add the Voice ID too, or the browser voice keeps speaking", clock())
                        elif sc.get("api_key"):
                            engine._message("info", "ElevenLabs: key and voice saved in config.json; the voice uses them now and after every restart", clock())
                    if any(p.startswith("quantdata.") for p in applied) and hooks.get("flow_restart"):
                        hooks["flow_restart"]()        # the key you just saved is used now, no restart
                        engine._message("info", "Quant Data: key saved and the feed restarted with it" if engine.cfg["quantdata"].get("api_key")
                                        else "Quant Data: key removed, option flow off", clock())
                    self._send(200, json.dumps({"ok": True, "applied": applied, "restart": restart,
                                                "sections": _settings.schema(engine.cfg)}, default=str), "application/json")
                except (ConfigError, OSError, ValueError) as exc:
                    self._send(400, json.dumps({"ok": False, "reason": str(exc)}), "application/json")
                return
            elif path == "/api/datasource":
                # the SIM menu: PAPER / SIM on LIVE data / the PRACTICE market / a RECORDED day; saved, then TED restarts
                ds = hooks.get("datasource")
                if ds is None:
                    self._send(400, json.dumps({"ok": False, "reason": "this desk was started on a fixed feed (start_demo / --replay): close it and start TED normally to switch"}), "application/json")
                    return
                try:
                    out = ds(body.get("source"), body.get("recording"))
                except Exception as exc:
                    out = {"ok": False, "reason": str(exc)}
                self._send(200 if out.get("ok") else 400, json.dumps(out), "application/json")
                return
            elif path == "/api/practice":
                # THE PRACTICE DESK: start it (a second TED on the next port, on the practice market) and hand back
                # its address; stop it; or just its status
                pr = hooks.get("practice")
                if pr is None:
                    self._send(400, json.dumps({"ok": False, "reason": "the practice desk is started from the LIVE desk (this one is the practice desk, or a replay)"}), "application/json")
                    return
                act = str(body.get("action") or "status")
                out = pr.start() if act == "start" else pr.stop() if act == "stop" else dict(pr.status(), ok=True)
                self._send(200, json.dumps(out), "application/json")
                return
            elif path == "/api/restart":
                if not hooks.get("restart"):
                    self._send(400, json.dumps({"ok": False, "reason": "restart is not available here"}), "application/json")
                    return
                self._send(200, json.dumps({"ok": True}), "application/json")
                threading.Timer(0.4, hooks["restart"]).start()
                return
            elif path == "/api/flow":
                out = {"ok": True}
                if "scope" in body:
                    out["scope"] = engine.set_flow_scope(str(body.get("scope", "all")), clock())
                if "alerts" in body:
                    out["alerts"] = engine.set_flow_alerts(str(body.get("alerts", "watchlist")), clock())
                self._send(200, json.dumps(out), "application/json")
            elif path == "/api/ladder":
                if "half_rows" in body:                      # rows above / below the market
                    try:
                        engine.ladder_half_rows = max(4, min(60, int(body["half_rows"])))
                        ok = True
                    except (TypeError, ValueError):
                        ok = False
                else:
                    ok = engine.set_big_shares(str(body.get("symbol", "")).upper(), body.get("big_shares"), clock())
                self._send(200 if ok else 400, json.dumps({"ok": ok}), "application/json")
            elif path == "/api/grade":
                ok = engine.grade(str(body.get("key", "")), body.get("verdict"), clock())
                self._send(200 if ok else 400, json.dumps({"ok": ok}), "application/json")
            elif path == "/api/play":
                sym = str(body.get("symbol", "")).upper()
                if body.get("action") == "add":
                    play = engine.add_play(sym, clock())
                    ok = play is not None
                    if ok:
                        engine.set_focus(sym, clock())
                elif body.get("action") == "setup":
                    ok, reason = engine.set_play_setup(sym, body.get("fields") or {}, clock())
                    self._send(200 if ok else 400, json.dumps({"ok": ok, "reason": reason}), "application/json")
                    return
                elif body.get("action") == "side":
                    ok, warn = engine.set_side(sym, body.get("side"), clock())
                    self._send(200 if ok else 400, json.dumps({"ok": ok, "warnings": warn, "reason": None if ok else "; ".join(warn)}), "application/json")
                    return
                elif body.get("action") == "flip":
                    ok = engine.flip_side(sym, clock())
                elif body.get("action") == "focus":
                    ok = engine.set_focus(sym, clock())
                elif body.get("action") == "reactivate":
                    ok = engine.reactivate_play(sym, clock())
                elif body.get("action") == "retire":
                    ok = engine.retire_play(sym, "retired by you", clock())
                elif body.get("action") == "remove":
                    ok = engine.remove_play(sym, clock())
                elif body.get("action") == "clear":
                    ok = engine.clear_play(sym, clock())
                else:
                    ok = False
                self._send(200 if ok else 400, json.dumps({"ok": ok}), "application/json")
            elif path == "/api/alerts":
                if body.get("action") == "remove":
                    ok = engine.remove_user_alert(int(body.get("id", 0)), clock())
                    self._send(200 if ok else 400, json.dumps({"ok": ok}), "application/json")
                    return
                a, why = engine.add_user_alert(body.get("symbol"), body.get("kind"), clock(),
                                               **{k: body.get(k) for k in ("price", "when", "min_premium", "cp", "min_dollars", "repeat", "note") if k in body})
                self._send(200 if a else 400, json.dumps({"ok": a is not None, "reason": why, "alert": a}), "application/json")
            elif path == "/api/layouts":
                self._send(200, json.dumps(_save_layouts(layout_path, body)), "application/json")
            elif path == "/api/layout":
                lp = layout_path or "layout.json"
                lay = body.get("layout")
                try:
                    if lay is None:
                        if os.path.exists(lp):
                            os.remove(lp)
                    else:
                        tmp = lp + ".tmp"
                        with open(tmp, "w", encoding="utf-8") as fh:
                            json.dump(lay, fh, indent=1)
                        os.replace(tmp, lp)
                    self._send(200, json.dumps({"ok": True, "path": os.path.abspath(lp)}), "application/json")
                except OSError as exc:
                    self._send(200, json.dumps({"ok": False, "reason": str(exc)}), "application/json")
            elif path.startswith("/api/desk/"):
                self._desk(path[len("/api/desk/"):], body)
            elif path.startswith("/api/clips/"):
                from . import clips as _clips
                rd = rec_dir or "recordings"
                act = path[len("/api/clips/"):]
                try:
                    if act == "add":
                        # live: the last N seconds of the recording running now; replay: the IN / OUT points
                        if engine.replay is not None:
                            rec = engine.replay.get("file")
                            t0, t1 = body.get("t0"), body.get("t1")
                        else:
                            rec = desk.current_recording() if desk is not None else None
                            if not rec:
                                raise ValueError("start a recording first (REC) — a clip is a piece of a recording")
                            t1 = clock()
                            t0 = t1 - max(10.0, min(3600.0, float(body.get("seconds") or 120)))
                        out = {"ok": True, "clip": _clips.add(rd, rec, t0, t1, body.get("symbol"), body.get("note", ""))}
                    elif act == "delete":
                        out = {"ok": _clips.delete(rd, str(body.get("id", "")))}
                    elif act == "note":
                        out = {"ok": _clips.note(rd, str(body.get("id", "")), body.get("note", ""))}
                    else:
                        self._send(404, "not found", "text/plain")
                        return
                except (ValueError, TypeError, OSError) as exc:
                    out = {"ok": False, "reason": str(exc)}
                self._send(200, json.dumps(out), "application/json")
                return
            elif path == "/api/market/refresh":
                mk = getattr(engine, "macro", None)
                if mk is None:
                    self._send(200, json.dumps({"ok": False, "reason": "the market report is off"}), "application/json")
                    return
                if mk.mode == "live":
                    mk.request_refresh()
                    threading.Thread(target=lambda: (mk.load_fred(), mk.build()), daemon=True).start()
                    out = {"ok": True, "reason": "asking IBKR for any missing days and FRED for the economy numbers"}
                else:
                    mk.build_async()
                    out = {"ok": True, "reason": "rebuilt from " + ("the practice closes" if mk.mode == "practice" else "what is on disk")}
                self._send(200, json.dumps(out), "application/json")
                return
            elif path == "/api/market/members":
                mk = getattr(engine, "macro", None)
                try:
                    n = mk.refresh_members() if mk is not None and mk.mode == "live" else None
                    out = {"ok": n is not None, "reason": f"{n} S&P members saved; their daily bars load next" if n else "live desk only"}
                except Exception as exc:
                    out = {"ok": False, "reason": f"could not fetch the S&P list: {exc}"}
                self._send(200, json.dumps(out), "application/json")
                return
            elif path == "/api/dan/refresh":
                dan = getattr(engine, "dan", None)
                if dan is None:
                    self._send(404, json.dumps({"ok": False, "reason": "DAN'S DAILY is not loaded"}), "application/json")
                    return
                st = dan.refresh(clock())
                self._send(200, json.dumps({"ok": not st.get("error"), "status": st, "reason": st.get("error")}), "application/json")
            elif path == "/api/ai/run":
                # DESK AI: start a job (recap / explain / notes / study / ask) in the background; the page polls the result
                ai = getattr(engine, "ai", None)
                if ai is None:
                    self._send(404, json.dumps({"ok": False, "reason": "DESK AI is not loaded"}), "application/json")
                    return
                out = ai.run(str(body.get("job") or "recap"), t=clock(), symbol=body.get("symbol"), text=body.get("text"),
                             key=body.get("key"), days=body.get("days"))
                self._send(200, json.dumps(out), "application/json")
            elif path == "/api/replay":
                r = engine.replay
                if r is None:
                    self._send(404, json.dumps({"ok": False, "reason": "not replaying"}), "application/json")
                    return
                if "seek" in body:
                    try:
                        target = float(body["seek"])
                        if r.get("done") or (r.get("position") is not None and target < r["position"]):
                            r["restart_at"] = target   # backwards: the replay loop starts over and fast-forwards
                            r["stop"] = True
                        else:
                            r["seek"] = target
                    except (TypeError, ValueError):
                        pass
                if "paused" in body:
                    r["paused"] = bool(body["paused"])
                if body.get("step"):                # one event forward (stays paused)
                    r["paused"] = True
                    r["step"] = True
                if body.get("restart") and r.get("start") is not None:
                    r["restart_at"] = float(r["start"])
                    r["stop"] = True
                if "pause_at" in body:              # watching a clip: stop at its end
                    try:
                        r["pause_at"] = float(body["pause_at"]) if body["pause_at"] is not None else None
                    except (TypeError, ValueError):
                        pass
                if "speed" in body:
                    try:
                        r["speed"] = max(0.25, min(100.0, float(body["speed"])))
                    except (TypeError, ValueError):
                        pass
                tr = getattr(engine, "trainer", None)
                if tr is not None:                  # REPLAY TRAINING: on / off, your answer, or skip the question
                    if "train" in body:
                        tr.on = bool(body["train"])
                        if not tr.on:
                            tr.skip()
                    if body.get("answer"):
                        if tr.answer(body["answer"]):
                            r["paused"] = False     # answered: the replay goes on, the verdict comes five minutes later
                    if body.get("skip"):
                        tr.skip()
                        r["paused"] = False
                    if body.get("paused") is False and tr.quiz is not None:
                        tr.skip()                   # PLAY without answering: the question is dropped
                self._send(200, json.dumps({"ok": True, "replay": dict(r)}), "application/json")
            else:
                self._send(404, "not found", "text/plain")

        def _callbook_pic(self):
            """THE CALL BOOK: the page's picture of the chart, the T&S and the flow at a call (JPEG / PNG, up to 4 MB)."""
            ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            if ctype not in ("image/jpeg", "image/png") or not 0 < length <= 4 * 1024 * 1024:
                self._send(400, json.dumps({"ok": False, "reason": "not a picture"}), "application/json")
                return
            data = self.rfile.read(length)
            cid = parse_qs(urlparse(self.path).query).get("id", [""])[0]
            with engine.lock:
                name = engine.callbook.save_pic(cid, data)
            self._send(200, json.dumps({"ok": bool(name), "pic": name}), "application/json")

        def _mic_audio(self):
            """A voice note's audio (raw bytes from the browser's recorder), up to 30 MB."""
            from urllib.parse import parse_qs, urlparse
            ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            ext = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "m4a"}.get(ctype)
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            if desk is None or not ext or not 0 < length <= 30 * 1024 * 1024:
                self._send(400, json.dumps({"ok": False, "reason": "not a voice note"}), "application/json")
                return
            data = self.rfile.read(length)
            q = parse_qs(urlparse(self.path).query)
            try:
                m = desk.mic_audio(int(q.get("n", ["0"])[0]), data, ext, clock())
                out = {"ok": True, "mark": m}
            except (ValueError, OSError) as exc:
                out = {"ok": False, "reason": str(exc)}
            self._send(200, json.dumps(out, default=str), "application/json")

        def _desk(self, action, body):
            if desk is None:
                self._send(503, json.dumps({"ok": False, "reason": "no recording desk in replay"}), "application/json")
                return
            now = clock()
            sym = (str(body.get("symbol", "")).upper() or None)
            try:
                if action == "rec":
                    out = dict(desk.toggle(now), ok=True)
                elif action == "mark":
                    out = None
                    if desk.cfg.get("recording", {}).get("mark_screenshot", True):
                        shot = desk.screenshot(now, sym, str(body.get("note", "")))     # the mark, with the screen
                        if shot.get("ok"):
                            out = {"ok": True, "mark": shot["mark"], "shot": True}
                    if out is None:
                        out = {"ok": True, "mark": desk.mark(now, sym, str(body.get("note", "")))}
                elif action == "note":
                    out = {"ok": desk.set_note(int(body.get("n", 0)), str(body.get("note", "")))}
                elif action == "trade":
                    out = {"ok": desk.tag_trade(str(body.get("id", "")), body.get("setup"), body.get("grade"), body.get("note"), body.get("name"))}
                elif action == "save_trade":
                    name = desk.save_trade(str(body.get("id", "")))
                    out = {"ok": bool(name), "file": name, "dir": desk.journal_dir(), "reason": None if name else "that trade is not closed yet"}
                elif action == "journal":
                    out = {"ok": True, "notes": desk.add_note(now, str(body.get("text", "")), sym)}
                elif action == "shot":
                    out = desk.screenshot(now, sym, str(body.get("note", "")))
                elif action == "delete":
                    out = desk.delete_recording(str(body.get("name", "")))
                elif action == "flag":
                    out = {"ok": desk.flag(str(body.get("name", "")), bool(body.get("on", True)))}
                elif action == "mic_start":
                    out = {"ok": True, "mark": desk.mic_start(now, sym)}
                elif action == "mic_text":
                    out = {"ok": True, "mark": desk.mic_text(int(body.get("n", 0)), body.get("text", ""), now)}
                elif action == "replay":
                    port = self.server.server_address[1] + 1
                    out = desk.open_replay(str(body.get("name", "")), port, float(body.get("speed", 1) or 1),
                                           body.get("start"), body.get("end"))
                else:
                    self._send(404, "not found", "text/plain")
                    return
            except Exception as exc:
                out = {"ok": False, "reason": str(exc)}
            self._send(200, json.dumps(out, default=str), "application/json")

        def _trade(self, action, body):
            tr = trader if trader is not None else getattr(engine, "trader", None)
            if tr is None:
                self._send(503, json.dumps({"ok": False, "reason": "order entry not loaded"}), "application/json")
                return
            now = clock()
            sym = str(body.get("symbol", "")).upper()
            try:
                if action == "arm":
                    ok = tr.gate.arm(bool(body.get("on")))
                    out = {"ok": ok, "armed": tr.gate.armed, "reason": None if ok else tr.gate.why_not()}
                elif action == "unlock":
                    if tr.gate.mode == "LIVE" and tr.cfg.get("allow_live"):
                        out = {"ok": False, "reason": "a LIVE (real money) account's loss lock holds until tomorrow (or raise the limit in SETTINGS)"}
                    else:
                        tr.gate.unlock(by_hand=True)
                        out = {"ok": True, "can_trade": tr.gate.can_trade(), "why_not": tr.gate.why_not(), "mode": tr.gate.mode}
                elif action == "oneclick":
                    tr.gate.one_click = bool(body.get("on"))
                    out = {"ok": True}
                elif action == "size":
                    out = {"ok": tr.set_size(body.get("shares")), "default_shares": tr.default_shares}
                elif action == "bracket":
                    tr.bracket = bool(body.get("on"))
                    out = {"ok": True}
                elif action == "auto":
                    out = {"ok": tr.set_auto(bool(body.get("on")), sym or None, now)}
                elif action == "risk":
                    out = {"ok": tr.set_risk(body.get("dollars")), "risk_dollars": tr.risk_dollars}
                elif action == "scale":
                    tr.scale = bool(body.get("on"))
                    out = {"ok": True}
                elif action == "order":
                    out = tr.submit(sym, str(body.get("action", "")).upper(), body.get("price"),
                                    body.get("qty"), now, body.get("bracket"), str(body.get("type", "LMT")),
                                    body.get("aux"), str(body.get("tif", "DAY")), body.get("nonce"), flip=bool(body.get("flip")))
                elif action == "cancel":
                    out = tr.cancel(body.get("id"), now)
                elif action == "cancel_all":
                    out = tr.cancel_all(sym or None, now)
                elif action == "flatten":
                    out = tr.flatten(sym, now)
                elif action == "clear_symbol":
                    out = tr.clear_symbol(sym, now)
                elif action == "flat_symbol":
                    out = tr.flat_symbol(sym, now)
                elif action == "flatten_all":
                    out = tr.flatten_all(now)
                elif action == "mode":
                    out = tr.set_mode(body.get("mode"), now)
                    if out.get("ok") and body.get("remember", True) and config_path:
                        try:
                            from . import settings as _settings
                            _settings.apply(engine.cfg, config_path, {"trading.start_mode": "sim" if out.get("mode") == "SIM" else "paper"})
                        except Exception as exc:
                            out["remembered"] = str(exc)
                elif action == "reverse":
                    out = tr.reverse(sym, now)
                elif action == "cancel_side":
                    out = tr.cancel_side(sym, str(body.get("side", "")), now)
                elif action == "bracket_template":
                    out = tr.set_bracket_template(body.get("name"))
                elif action == "adjust":
                    out = tr.adjust(sym, body.get("shares"), str(body.get("mode", "")), now)
                elif action == "breakeven":
                    out = tr.breakeven(sym, now, body.get("plus") or 0)
                elif action == "partial":
                    out = tr.partial(sym, body.get("shares"), body.get("price"), now)
                elif action == "opt_open":
                    out = tr.opt_open(sym, str(body.get("expiry", "")), body.get("strike"), str(body.get("right", "C")),
                                      str(body.get("action", "BUY")), body.get("contracts"), body.get("price"), now)
                elif action == "opt_watch":
                    out = tr.opt_watch(sym, str(body.get("expiry", "")), body.get("strike"), str(body.get("right", "C")),
                                       str(body.get("action", "BUY")), body.get("contracts"), body.get("px"), str(body.get("when", "above")), now)
                elif action == "opt_partial_move":
                    out = tr.opt_partial_move(body.get("id"), body.get("px"), now)
                elif action == "opt_partial":
                    out = tr.opt_partial(str(body.get("key", "")), body.get("contracts"), body.get("px"), now)
                elif action == "opt_unwatch":
                    out = tr.opt_unwatch(body.get("id"), now)
                elif action == "opt_adjust":
                    out = tr.opt_adjust(str(body.get("key", "")), body.get("contracts"), str(body.get("mode", "")), body.get("price"), now)
                elif action == "modify":
                    out = tr.modify(body.get("id"), body.get("price"), now)
                elif action == "scale_plan":
                    out = (tr.clear_scale_plan(sym, now) if body.get("clear") else
                           tr.set_scale_plan(sym, body.get("kind"), body.get("rungs"), body.get("auto"), now))
                elif action == "stop":
                    out = tr.set_stop(sym, body.get("price"), now)
                elif action == "trade_as":
                    out = tr.set_trade_as(sym, str(body.get("mode", "stock")), body.get("opt_key"), body.get("opt_qty"), now)
                elif action == "opt_breakeven":
                    out = tr.opt_breakeven(str(body.get("key", "")), now, body.get("plus") or 0)
                elif action == "opt_stop":
                    out = tr.set_opt_stop(str(body.get("key", "")), body.get("price"), str(body.get("on", "stock")), now)
                elif action == "opt_level":
                    out = tr.set_opt_level(str(body.get("key", "")), str(body.get("role", "")), body.get("price"), body.get("n") or 1, now)
                elif action == "trail":
                    out = tr.set_trail(sym, body.get("dollars"), bool(body.get("on", True)), now)
                elif action == "scale_fire":
                    out = tr.fire_scale_rung(sym, body.get("i"), now)
                else:
                    self._send(404, json.dumps({"ok": False, "reason": f"unknown order action '{action}' — restart TED after an update"}), "application/json")
                    return
            except (TypeError, ValueError) as exc:          # a price / size that is not a number: a plain refusal, not a crash
                self._send(400, json.dumps({"ok": False, "reason": f"check the numbers on the order: {exc}"}), "application/json")
                return
            except Exception as exc:  # never let a broker error kill the dashboard
                out = {"ok": False, "reason": str(exc)}
            self._send(200, json.dumps(out, default=str), "application/json")

    return Handler


class Dashboard:
    def __init__(self, engine, host, port, clock=time.time, trader=None, desk=None, rec_dir=None, layout_path=None,
                 config_path=None, on_restart=None, auth=None):
        self.hooks = {"restart": on_restart}
        self.auth = auth
        try:
            self.httpd = ThreadingHTTPServer((host, port), make_handler(engine, clock, trader, desk, rec_dir, layout_path,
                                                                        config_path, self.hooks, auth))
        except OSError as exc:
            if getattr(exc, "errno", None) in (98, 48, 10048) or "in use" in str(exc).lower():
                raise OSError(f"TED is already running: another TED window is using {host}:{port}. "
                              "Close every black TED window, then start TED again.") from exc
            raise
        self.httpd.daemon_threads = True
        self.thread = None

    @property
    def url(self):
        host, port = self.httpd.server_address[:2]
        return f"http://{host}:{port}"

    def start(self):
        self.thread = threading.Thread(target=self.httpd.serve_forever, name="twiney-dashboard", daemon=True)
        self.thread.start()
        return self

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def _om_names():
    from .option_money import TOOL_NAMES
    return TOOL_NAMES

