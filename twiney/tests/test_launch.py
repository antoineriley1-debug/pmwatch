"""The practice desk launches: run_twiney.py --demo comes up, keeps /api/state closed until you sign in, and answers
it after (catches a name that only a real launch resolves, never the unit tests)."""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from twiney.auth import Auth  # noqa: E402


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class LaunchTests(unittest.TestCase):
    def test_demo_desk_comes_up(self):
        port = _free_port()
        d = tempfile.mkdtemp()
        cfg = os.path.join(d, "config.json")
        plays = os.path.join(d, "plays.json")
        with open(cfg, "w") as f:
            json.dump({"recording": {"dir": os.path.join(d, "rec")}, "dashboard": {"port": port}}, f)
        with open(plays, "w") as f:
            json.dump({"plays": [{"symbol": "AAPL", "watch": True}]}, f)
        Auth(os.path.join(d, "auth.json"), iterations=1000).set_password("launch test pw 1")
        env = dict(os.environ, TWINEY_HOME=d)
        proc = subprocess.Popen([sys.executable, os.path.join(ROOT, "run_twiney.py"), "--demo", "--config", cfg, "--plays", plays,
                                 "--port", str(port), "--no-browser"], cwd=ROOT, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        try:
            state, closed = None, None
            base = f"http://127.0.0.1:{port}"
            for _ in range(60):
                if proc.poll() is not None:
                    break
                try:
                    with urllib.request.urlopen(base + "/healthz", timeout=2):
                        break
                except Exception:
                    time.sleep(0.5)
            try:
                urllib.request.urlopen(base + "/api/state", timeout=5)
                closed = False
            except urllib.error.HTTPError as e:
                closed = e.code == 401
            except Exception:
                pass
            try:
                req = urllib.request.Request(base + "/api/login", data=json.dumps({"password": "launch test pw 1"}).encode(),
                                             headers={"Content-Type": "application/json"}, method="POST")
                with urllib.request.urlopen(req, timeout=5) as r:
                    cookie = r.headers["Set-Cookie"].split(";")[0]
                with urllib.request.urlopen(urllib.request.Request(base + "/api/state", headers={"Cookie": cookie}), timeout=5) as r:
                    state = json.loads(r.read())
            except Exception:
                pass
            out = ""
            if state is None:
                proc.terminate()
                out = (proc.communicate(timeout=10)[0] or b"").decode(errors="replace")[-2000:]
            self.assertTrue(closed, "the desk answered /api/state without a sign-in:\n" + out)
            self.assertIsNotNone(state, "the practice desk never answered /api/state:\n" + out)
            self.assertIn("score", state)
            self.assertIn("panes", state)
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()


if __name__ == "__main__":
    unittest.main()
