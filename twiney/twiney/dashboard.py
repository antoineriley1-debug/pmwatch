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


def make_handler(engine, clock, trader=None, desk=None, rec_dir=None, layout_path=None):
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
                from urllib.parse import parse_qs, urlparse
                q = parse_qs(urlparse(self.path).query)
                extra = [x.strip().upper() for x in (q.get("extra", [""])[0]).split(",") if x.strip()][:12]
                snap = engine.snapshot(clock(), extra)
                snap["build"] = BUILD
                self._send(200, json.dumps(snap, default=str), "application/json")
            elif path.startswith("/recordings/shots/") and rec_dir:
                name = os.path.basename(path)
                fp = os.path.join(rec_dir, "shots", name)
                if name.endswith(".png") and os.path.exists(fp):
                    with open(fp, "rb") as fh:
                        self._send(200, fh.read(), "image/png")
                else:
                    self._send(404, "not found", "text/plain")
            elif path.startswith("/recordings/") and path.endswith(".journal.md") and rec_dir:
                fp = os.path.join(rec_dir, os.path.basename(path))
                if os.path.exists(fp):
                    with open(fp, "rb") as fh:
                        self._send(200, fh.read(), "text/plain; charset=utf-8")
                else:
                    self._send(404, "not found", "text/plain")
            elif path == "/api/layouts":
                self._send(200, json.dumps(_load_layouts(layout_path)), "application/json")
            elif path == "/api/layout":
                lp = layout_path or "layout.json"
                if os.path.exists(lp):
                    with open(lp, encoding="utf-8") as fh:
                        self._send(200, json.dumps({"ok": True, "layout": json.load(fh)}), "application/json")
                else:
                    self._send(200, json.dumps({"ok": True, "layout": None}), "application/json")
            elif path == "/api/desk/export" and desk is not None:
                from urllib.parse import parse_qs, urlparse
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
            elif path == "/api/desk/list":
                self._send(200, json.dumps(desk.list_recordings() if desk else []), "application/json")
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
            elif path == "/api/ladder":
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
                elif body.get("action") == "flip":
                    ok = engine.flip_side(sym, clock())
                elif body.get("action") == "focus":
                    ok = engine.set_focus(sym, clock())
                elif body.get("action") == "reactivate":
                    ok = engine.reactivate_play(sym, clock())
                elif body.get("action") == "retire":
                    ok = engine.retire_play(sym, "retired by you", clock())
                else:
                    ok = False
                self._send(200 if ok else 400, json.dumps({"ok": ok}), "application/json")
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
                if "speed" in body:
                    try:
                        r["speed"] = max(0.25, min(100.0, float(body["speed"])))
                    except (TypeError, ValueError):
                        pass
                self._send(200, json.dumps({"ok": True, "replay": dict(r)}), "application/json")
            else:
                self._send(404, "not found", "text/plain")

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
                    out = {"ok": True, "mark": desk.mark(now, sym, str(body.get("note", "")))}
                elif action == "note":
                    out = {"ok": desk.set_note(int(body.get("n", 0)), str(body.get("note", "")))}
                elif action == "journal":
                    out = {"ok": True, "notes": desk.add_note(now, str(body.get("text", "")), sym)}
                elif action == "shot":
                    out = desk.screenshot(now, sym, str(body.get("note", "")))
                elif action == "delete":
                    out = desk.delete_recording(str(body.get("name", "")))
                elif action == "replay":
                    port = self.server.server_address[1] + 1
                    out = desk.open_replay(str(body.get("name", "")), port, float(body.get("speed", 1) or 1))
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
                elif action == "oneclick":
                    tr.gate.one_click = bool(body.get("on"))
                    out = {"ok": True}
                elif action == "size":
                    out = {"ok": tr.set_size(body.get("shares")), "default_shares": tr.default_shares}
                elif action == "bracket":
                    tr.bracket = bool(body.get("on"))
                    out = {"ok": True}
                elif action == "scale":
                    tr.scale = bool(body.get("on"))
                    out = {"ok": True}
                elif action == "order":
                    out = tr.submit(sym, str(body.get("action", "")).upper(), body.get("price"),
                                    body.get("qty"), now, body.get("bracket"), str(body.get("type", "LMT")),
                                    body.get("aux"), str(body.get("tif", "DAY")), body.get("nonce"))
                elif action == "cancel":
                    out = tr.cancel(body.get("id"), now)
                elif action == "cancel_all":
                    out = tr.cancel_all(sym or None, now)
                elif action == "flatten":
                    out = tr.flatten(sym, now)
                elif action == "adjust":
                    out = tr.adjust(sym, body.get("shares"), str(body.get("mode", "")), now)
                elif action == "modify":
                    out = tr.modify(body.get("id"), body.get("price"), now)
                else:
                    self._send(404, "not found", "text/plain")
                    return
            except Exception as exc:  # never let a broker error kill the dashboard
                out = {"ok": False, "reason": str(exc)}
            self._send(200, json.dumps(out, default=str), "application/json")

    return Handler


class Dashboard:
    def __init__(self, engine, host, port, clock=time.time, trader=None, desk=None, rec_dir=None, layout_path=None):
        self.httpd = ThreadingHTTPServer((host, port), make_handler(engine, clock, trader, desk, rec_dir, layout_path))
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
