"""DESK AI: the Ollama client, the packets the model is given, the jobs, the dashboard routes, the close recap on
its own, the language lock. A fake Ollama answers on a local port (nothing here needs the real one)."""

import json
import os
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

from helpers import cfg, plays
from twiney import ai as ai_mod
from twiney import studies
from twiney.ai import DeskAI, Ollama, language
from twiney.dashboard import Dashboard
from twiney.engine import Engine


class FakeOllama:
    """Answers /api/tags and /api/generate like Ollama; keeps every prompt it was sent."""

    def __init__(self, models=("llama3.1:8b",), reply=None, fail=False):
        self.models, self.reply, self.fail = list(models), reply, fail
        self.prompts = []
        srv = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _json(self, code, body):
                data = json.dumps(body).encode()
                self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

            def do_GET(self):
                if self.path == "/api/tags":
                    self._json(200, {"models": [{"name": m} for m in srv.models]})
                else:
                    self._json(404, {"error": "no"})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                srv.prompts.append(body)
                if srv.fail:
                    self._json(200, {"error": "model 'x' not found"})
                    return
                text = srv.reply(body) if callable(srv.reply) else (srv.reply or f"READ: {len(body.get('prompt', ''))} chars. Resistance at 10 is supply.")
                self._json(200, {"model": body.get("model"), "response": text, "done": True})
        self.http = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.http.server_address[1]}"
        threading.Thread(target=self.http.serve_forever, daemon=True).start()

    def stop(self):
        self.http.shutdown()


def wait_for(fn, timeout=5.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if fn():
            return True
        time.sleep(0.02)
    return False


class OllamaClientTests(unittest.TestCase):
    def setUp(self):
        self.srv = FakeOllama()

    def tearDown(self):
        self.srv.stop()

    def test_models_and_generate(self):
        c = Ollama(self.srv.url, "llama3.1:8b", timeout=5)
        self.assertEqual(c.models(), ["llama3.1:8b"])
        out = c.generate("SYSTEM", "hello")
        self.assertIn("READ: 5 chars", out)
        self.assertEqual(self.srv.prompts[-1]["system"], "SYSTEM")
        self.assertFalse(self.srv.prompts[-1]["stream"])
        self.assertEqual(self.srv.prompts[-1]["options"]["num_ctx"], 8192)

    def test_error_from_ollama_raises(self):
        self.srv.fail = True
        with self.assertRaises(RuntimeError):
            Ollama(self.srv.url, "x", timeout=5).generate("s", "p")

    def test_not_running(self):
        c = Ollama("http://127.0.0.1:9", "m", timeout=1)
        with self.assertRaises(Exception):
            c.models()


class LanguageTests(unittest.TestCase):
    def test_lock(self):
        self.assertEqual(language("Resistance at 100, support at 90, a dark pool print, the trigger fired, an iceberg"),
                         "supply at 100, demand at 90, a large orders print, the pivot fired, a large size")
        self.assertEqual(language("RESISTANCE"), "SUPPLY")
        self.assertIn("support the", language("flow must support the thesis"))   # the verb stays


def desk(ai_cfg=None, rec=None):
    c = cfg(ai=dict({"enabled": True, "model": "llama3.1:8b"}, **(ai_cfg or {})))
    eng = Engine(plays(), c)
    t = time.time()
    day0 = studies.day_key(t)
    # a little history: two daily bars and a few minutes today, a story, an alert, a note, a judged call
    st = eng.syms["AAA"]
    for i, (o, h, l, cl) in enumerate([(9.5, 10.2, 9.4, 10.0), (10.0, 10.6, 9.9, 10.4)]):
        st.daily[t - 86400 * (2 - i)] = [o, h, l, cl]
    for k in range(3):
        eng.on_l1("AAA", "last", 10.0 + k * 0.01, 1.0)
        eng.on_print("AAA", 10.0 + k * 0.01, 100, "NSDQ", t + k)
    eng.alerts.appendleft({"t": t, "symbol": "AAA", "label": "RELOAD BUYER", "price": 10.0, "text": "reload buyer 10.00 RELOADING, refilled 3 times", "key": "k1"})
    eng.notes_list.append({"t": t, "symbol": "AAA", "text": "watchin ten even for the reload byer", "kind": "note"})
    eng.score.by["RELOAD BUYER"] = {"n": 2, "hit": 1, "miss": 1, "flat": 0, "sum5": 0.1, "sum15": 0.2}
    eng.score.done.append({"t": t, "symbol": "AAA", "kind": "RELOAD BUYER", "dir": 1, "p0": 10.0, "outcome": "HIT", "moves": {"300": 0.1, "900": 0.2}, "text": "reload buyer 10.00", "atr": 0.5})
    return eng, c, day0


class PacketTests(unittest.TestCase):
    def test_day_packet_carries_the_desk(self):
        eng, c, _ = desk()
        a = DeskAI(eng, c, None)
        p = a.packet_day(time.time())
        for word in ("=== AAA ===", "ATR (daily)", "DAILY:", "daily ", "LEVELS:", "CALLS", "RELOAD BUYER", "THE DESK SCORE", "1 hit / 1 miss", "TWINEY'S NOTES", "watchin ten"):
            self.assertIn(word, p, word)
        self.assertIn("pivot 10.00", p)            # Twiney's drawn lines, in PS60 words
        self.assertNotIn("trigger 10.00", p)

    def test_explain_notes_study_packets(self):
        eng, c, _ = desk()
        with tempfile.TemporaryDirectory() as d:
            eng.storyline_path = os.path.join(d, "storylines.jsonl")
            eng.score.path = os.path.join(d, "score.jsonl")
            t = time.time()
            with open(eng.storyline_path, "w") as f:
                f.write(json.dumps({"t": t, "day": studies.day_key(t), "symbol": "AAA", "topic": "lean", "text": "sellers have the tape", "price": 10.0, "live": True}) + "\n")
            with open(eng.score.path, "w") as f:
                f.write(json.dumps({"t": t, "symbol": "AAA", "kind": "RELOAD BUYER", "dir": 1, "p0": 10.0, "outcome": "MISS"}) + "\n")
            a = DeskAI(eng, c, d)
            e = a.packet_explain(t, "AAA", "", key="k1")
            self.assertIn("THE CALL TO EXPLAIN", e)
            self.assertIn("RELOAD BUYER @ 10.00", e)
            n = a.packet_notes(t)
            self.assertIn("watchin ten even", n)
            s = a.packet_study(t, 5)
            self.assertIn("sellers have the tape", s)
            self.assertIn("SCORE that day: 0 hit / 1 miss", s)
            self.assertIn("AAA DAILY BARS", s)


class JobTests(unittest.TestCase):
    def setUp(self):
        self.srv = FakeOllama()
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.srv.stop()
        self.tmp.cleanup()

    def test_recap_runs_saves_and_speaks_ps60(self):
        eng, c, _ = desk({"url": self.srv.url})
        a = DeskAI(eng, c, self.tmp.name)
        eng.ai = a
        r = a.run("recap", t=time.time())
        self.assertTrue(r["ok"], r)
        self.assertTrue(wait_for(lambda: a.busy is None and a.result("recap") is not None))
        res = a.result("recap")
        self.assertIsNone(res["error"])
        self.assertIn("supply", res["text"])              # the language lock on the model's words
        self.assertNotIn("Resistance", res["text"])
        self.assertTrue(res["file"] and os.path.exists(os.path.join(self.tmp.name, "ai", res["file"])))
        saved = open(os.path.join(self.tmp.name, "ai", res["file"]), encoding="utf-8").read()
        self.assertIn("## What the AI was given", saved)
        self.assertIn("=== AAA ===", saved)
        sent = self.srv.prompts[-1]
        self.assertIn("PS60 = Pivot System 60", sent["system"])          # taught before it reads a number
        self.assertIn("TOMORROW'S PLAN", sent["prompt"])
        self.assertIn("Never: resistance, support", sent["system"])
        self.assertTrue(any("DESK AI" in m["text"] and "ready" in m["text"] for m in eng.messages))
        self.assertEqual(a.files()[0]["job"], "recap")
        self.assertIn("## What the AI was given", a.read(a.files()[0]["name"]))

    def test_off_unreachable_missing_model_and_busy(self):
        eng, c, _ = desk({"url": self.srv.url, "enabled": False})
        a = DeskAI(eng, c, self.tmp.name)
        self.assertIn("SETTINGS > AI", a.run("recap")["reason"])
        c["ai"]["enabled"] = True
        c["ai"]["url"] = "http://127.0.0.1:9"
        self.assertIn("not answering", a.run("recap")["reason"])
        c["ai"]["url"] = self.srv.url
        c["ai"]["model"] = "nope:1b"
        self.assertIn("ollama pull nope:1b", a.run("recap")["reason"])
        c["ai"]["model"] = "llama3.1:8b"
        self.srv.reply = lambda body: (time.sleep(0.4), "slow answer")[1]
        self.assertTrue(a.run("ask", text="what now?")["ok"])
        self.assertIn("one job at a time", a.run("recap")["reason"])
        self.assertTrue(wait_for(lambda: a.busy is None))
        self.assertEqual(a.result("ask")["text"], "slow answer")
        self.assertIn("TWINEY ASKS: what now?", self.srv.prompts[-1]["prompt"])

    def test_model_error_is_reported_not_raised(self):
        eng, c, _ = desk({"url": self.srv.url})
        a = DeskAI(eng, c, self.tmp.name)
        self.srv.fail = True
        self.assertTrue(a.run("notes")["ok"])
        self.assertTrue(wait_for(lambda: a.busy is None))
        self.assertIn("not found", a.result("notes")["error"])
        self.assertTrue(any(m["level"] == "error" and "DESK AI" in m["text"] for m in eng.messages))

    def test_close_recap_on_its_own(self):
        eng, c, _ = desk({"url": self.srv.url})
        a = DeskAI(eng, c, self.tmp.name)
        # a live day, 16:06 ET: the recap starts once; practice (not CONNECTED) never starts it
        d = studies.ny(time.time()).replace(hour=16, minute=6, second=0, microsecond=0)
        t = d.timestamp()
        eng.connection["state"] = "DEMO"
        self.assertFalse(a.tick(t))
        eng.connection["state"] = "CONNECTED"
        self.assertFalse(a.tick(t - 3600))           # 15:06: too early
        self.assertTrue(a.tick(t))
        self.assertTrue(wait_for(lambda: a.busy is None))
        self.assertFalse(a.tick(t + 60))             # once a day
        c["ai"]["recap_at_close"] = False
        a.recap_day = None
        self.assertFalse(a.tick(t))

    def test_status_is_cheap_and_honest(self):
        eng, c, _ = desk({"url": self.srv.url})
        a = DeskAI(eng, c, self.tmp.name)
        s = a.status()
        self.assertTrue(s["enabled"]); self.assertIsNone(s["reachable"]); self.assertIsNone(s["busy"])
        a.check(force=True)
        s = a.status()
        self.assertTrue(s["reachable"]); self.assertTrue(s["model_ok"]); self.assertEqual(s["models"], ["llama3.1:8b"])


class DashboardRouteTests(unittest.TestCase):
    def setUp(self):
        self.srv = FakeOllama()
        self.tmp = tempfile.TemporaryDirectory()
        self.engine, c, _ = desk({"url": self.srv.url})
        self.engine.ai = DeskAI(self.engine, c, self.tmp.name)
        self.dash = Dashboard(self.engine, "127.0.0.1", 0, clock=time.time).start()

    def tearDown(self):
        self.dash.stop(); self.srv.stop(); self.tmp.cleanup()

    def get(self, path):
        return json.loads(urllib.request.urlopen(self.dash.url + path, timeout=5).read())

    def post(self, path, body):
        req = urllib.request.Request(self.dash.url + path, data=json.dumps(body).encode(), method="POST", headers={"Content-Type": "application/json"})
        return json.loads(urllib.request.urlopen(req, timeout=5).read())

    def test_routes(self):
        st = self.get("/api/ai/status?force=1")
        self.assertTrue(st["ok"] and st["reachable"] and st["enabled"])
        self.assertIn("ai", self.get("/api/state"))
        self.assertTrue(self.post("/api/ai/run", {"job": "explain", "symbol": "AAA", "key": "k1"})["ok"])
        self.assertTrue(wait_for(lambda: self.engine.ai.busy is None))
        r = self.get("/api/ai/result?job=explain")
        self.assertTrue(r["ok"]); self.assertIn("READ:", r["result"]["text"]); self.assertIn("THE CALL TO EXPLAIN", r["result"]["given"])
        files = self.get("/api/ai/list")["files"]
        self.assertEqual(files[0]["job"], "explain")
        md = urllib.request.urlopen(self.dash.url + "/api/ai/file?name=" + files[0]["name"], timeout=5).read().decode()
        self.assertIn("What the AI was given", md)
        self.assertFalse(self.post("/api/ai/run", {"job": "bogus"})["ok"])


class KnowledgeTests(unittest.TestCase):
    def test_knowledge_file_teaches_the_method(self):
        k = ai_mod.knowledge()
        for w in ("supply", "demand", "second entry", "measured potential", "sneaky pivot", "reload buyer", "RELOADING", "STILL THERE",
                  "CLEANED UP", "PULLED", "option flow", "736.70", "50-day", "6 candles" if "6 candles" in k else "six 60-minute candles"):
            self.assertIn(w, k, w)
        self.assertNotIn("iceberg trader", k)


if __name__ == "__main__":
    unittest.main()
