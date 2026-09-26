import os
import re
import unittest

from twiney.safety import FORBIDDEN_CALLS, ReadOnlyGuard, ReadOnlyViolation

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def sources():
    yield os.path.join(ROOT, "run_twiney.py")
    for dirpath, _dirs, files in os.walk(os.path.join(ROOT, "twiney")):
        for f in files:
            if f.endswith((".py", ".html")):
                yield os.path.join(dirpath, f)


class SafetyTests(unittest.TestCase):
    def test_guard_blocks_every_order_call(self):
        g = ReadOnlyGuard()
        for name in FORBIDDEN_CALLS:
            with self.assertRaises(ReadOnlyViolation, msg=name):
                getattr(g, name)(1, 2, 3)

    def test_no_source_file_references_order_calls(self):
        pattern = re.compile(r"\b(" + "|".join(FORBIDDEN_CALLS) + r"|transmit|ibapi\.order)\b")
        for path in sources():
            if path.endswith(os.path.join("twiney", "safety.py")):
                continue
            with open(path, encoding="utf-8") as fh:
                for n, line in enumerate(fh, 1):
                    self.assertIsNone(pattern.search(line), f"{path}:{n}: {line.strip()}")

    def test_dashboard_write_routes_are_screen_controls_only(self):
        with open(os.path.join(ROOT, "twiney", "dashboard.py"), encoding="utf-8") as fh:
            src = fh.read()
        for verb in ("do_PUT", "do_DELETE", "do_PATCH"):
            self.assertNotIn(verb, src)
        routes = set(re.findall(r'path == "(/api/[a-z]+)"', src))
        self.assertEqual(routes, {"/api/state", "/api/pin", "/api/autorotate"})

    def test_real_ibapi_client_is_guarded_when_installed(self):
        try:
            from twiney.ibkr import ibapi_app_factory
            factory = ibapi_app_factory()
        except ImportError:
            self.skipTest("ibapi not installed")
        mro = factory.__mro__
        from ibapi.client import EClient
        self.assertLess(mro.index(ReadOnlyGuard), mro.index(EClient))
        for name in FORBIDDEN_CALLS:
            if hasattr(EClient, name):
                self.assertIs(getattr(factory, name), getattr(ReadOnlyGuard, name))


if __name__ == "__main__":
    unittest.main()
