"""Local dashboard: one HTML page polling /api/state.

Write routes: screen controls (pin, auto-rotate) and order entry (/api/trade/*),
which goes through trading.Trader -> TradingGate (paper-only lock, caps, ARM).
"""

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STATIC = os.path.join(os.path.dirname(__file__), "static", "dashboard.html")


def make_handler(engine, clock, trader=None):
    class Handler(BaseHTTPRequestHandler):
        server_version = "TWINEY/1.0"

        def log_message(self, fmt, *args):  # keep the console for alerts
            pass

        def _send(self, code, body, ctype):
            data = body if isinstance(body, bytes) else body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                with open(STATIC, "rb") as fh:
                    self._send(200, fh.read(), "text/html; charset=utf-8")
            elif path == "/api/state":
                snap = engine.snapshot(clock())
                self._send(200, json.dumps(snap, default=str), "application/json")
            elif path == "/healthz":
                self._send(200, json.dumps({"ok": True, "connection": engine.connection["state"]}),
                           "application/json")
            else:
                self._send(404, "not found", "text/plain")

        def do_POST(self):
            # only accept requests from this dashboard page (blocks other websites)
            origin = self.headers.get("Origin")
            host = self.headers.get("Host", "")
            if origin and origin not in (f"http://{host}", f"https://{host}"):
                self._send(403, "forbidden", "text/plain")
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
            path = self.path.split("?", 1)[0]
            if path == "/api/pin":
                ok = engine.set_pinned(str(body.get("symbol", "")).upper(), bool(body.get("pinned")), clock())
                self._send(200 if ok else 404, json.dumps({"ok": ok}), "application/json")
            elif path == "/api/autorotate":
                engine.set_auto_rotate(bool(body.get("on")), clock())
                self._send(200, json.dumps({"ok": True}), "application/json")
            elif path.startswith("/api/trade/"):
                self._trade(path[len("/api/trade/"):], body)
            elif path == "/api/level":
                sym = str(body.get("symbol", "")).upper()
                role = str(body.get("role", "extra"))
                if role in ("trigger", "second_entry", "target", "stop"):
                    ok = engine.set_play_level(sym, role, body.get("price") if body.get("on", True) else None, clock())
                else:
                    ok = (engine.add_level if body.get("on", True) else engine.remove_level)(sym, body.get("price"), clock())
                self._send(200 if ok else 400, json.dumps({"ok": ok}), "application/json")
            elif path == "/api/replay":
                r = engine.replay
                if r is None:
                    self._send(404, json.dumps({"ok": False, "reason": "not replaying"}), "application/json")
                    return
                if "paused" in body:
                    r["paused"] = bool(body["paused"])
                if "speed" in body:
                    try:
                        r["speed"] = max(0.25, min(100.0, float(body["speed"])))
                    except (TypeError, ValueError):
                        pass
                self._send(200, json.dumps({"ok": True, "replay": dict(r)}), "application/json")
            else:
                self._send(404, "not found", "text/plain")

        def _trade(self, action, body):
            if trader is None:
                self._send(503, json.dumps({"ok": False, "reason": "order entry not loaded"}), "application/json")
                return
            now = clock()
            sym = str(body.get("symbol", "")).upper()
            try:
                if action == "arm":
                    ok = trader.gate.arm(bool(body.get("on")))
                    out = {"ok": ok, "armed": trader.gate.armed, "reason": None if ok else trader.gate.why_not()}
                elif action == "oneclick":
                    trader.gate.one_click = bool(body.get("on"))
                    out = {"ok": True}
                elif action == "size":
                    out = {"ok": trader.set_size(body.get("shares")), "default_shares": trader.default_shares}
                elif action == "bracket":
                    trader.bracket = bool(body.get("on"))
                    out = {"ok": True}
                elif action == "order":
                    out = trader.submit(sym, str(body.get("action", "")).upper(), body.get("price"),
                                        body.get("qty"), now, body.get("bracket"))
                elif action == "cancel":
                    out = trader.cancel(body.get("id"), now)
                elif action == "cancel_all":
                    out = trader.cancel_all(sym or None, now)
                elif action == "flatten":
                    out = trader.flatten(sym, now)
                elif action == "adjust":
                    out = trader.adjust(sym, body.get("shares"), str(body.get("mode", "")), now)
                elif action == "modify":
                    out = trader.modify(body.get("id"), body.get("price"), now)
                else:
                    self._send(404, "not found", "text/plain")
                    return
            except Exception as exc:  # never let a broker error kill the dashboard
                out = {"ok": False, "reason": str(exc)}
            self._send(200, json.dumps(out, default=str), "application/json")

    return Handler


class Dashboard:
    def __init__(self, engine, host, port, clock=time.time, trader=None):
        self.httpd = ThreadingHTTPServer((host, port), make_handler(engine, clock, trader))
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
