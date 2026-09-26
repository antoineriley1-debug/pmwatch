"""Local dashboard: one HTML page polling /api/state.

The only write routes are screen controls (pin a symbol to a ladder, turn
auto-rotation on/off). Nothing here can reach an order path.
"""

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STATIC = os.path.join(os.path.dirname(__file__), "static", "dashboard.html")


def make_handler(engine, clock):
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
            else:
                self._send(404, "not found", "text/plain")

    return Handler


class Dashboard:
    def __init__(self, engine, host, port, clock=time.time):
        self.httpd = ThreadingHTTPServer((host, port), make_handler(engine, clock))
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
