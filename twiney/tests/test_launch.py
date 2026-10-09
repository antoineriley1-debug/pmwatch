"""The practice desk launches: run_twiney.py --demo comes up and answers /api/state (catches a name that only a
real launch resolves, never the unit tests)."""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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
        env = dict(os.environ, TWINEY_HOME=d)
        proc = subprocess.Popen([sys.executable, os.path.join(ROOT, "run_twiney.py"), "--demo", "--config", cfg, "--plays", plays,
                                 "--port", str(port), "--no-browser"], cwd=ROOT, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        try:
            state = None
            for _ in range(60):
                if proc.poll() is not None:
                    break
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=2) as r:
                        state = json.loads(r.read())
                        break
                except Exception:
                    time.sleep(0.5)
            out = ""
            if state is None:
                proc.terminate()
                out = (proc.communicate(timeout=10)[0] or b"").decode(errors="replace")[-2000:]
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
