"""THE SIGN-IN: the password hash, the signed cookie, lockouts, and every route closed until you sign in."""

import json
import os
import tempfile
import unittest
import urllib.error
import urllib.request

from helpers import cfg, plays
from twiney import auth as A
from twiney.dashboard import Dashboard
from twiney.engine import Engine


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


OPENER = urllib.request.build_opener(NoRedirect)


class HashAndCookieTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.now = [1000.0]
        self.a = A.Auth(os.path.join(self.tmp.name, "auth.json"), 12, clock=lambda: self.now[0], iterations=1000, fail_delay_s=0)

    def tearDown(self):
        self.tmp.cleanup()

    def test_hash_never_holds_the_password(self):
        h = A.hash_password("correct horse 1", 1000)
        self.assertNotIn("correct", h)
        self.assertTrue(A.check_password("correct horse 1", h))
        self.assertFalse(A.check_password("correct horse 2", h))
        self.assertFalse(A.check_password("x", "garbage"))

    def test_weak_passwords_refused(self):
        self.assertFalse(self.a.set_password("short")[0])
        self.assertFalse(self.a.set_password("aaaaaaaaaaaa")[0])
        self.assertFalse(self.a.set_password("good password 1", "other password")[0])
        self.assertTrue(self.a.set_password("good password 1", "good password 1")[0])

    def test_file_is_private_and_has_no_password(self):
        self.a.set_password("good password 1")
        with open(self.a.path) as fh:
            self.assertNotIn("good password", fh.read())
        if os.name == "posix":
            self.assertEqual(os.stat(self.a.path).st_mode & 0o777, 0o600)

    def test_cookie_sign_expiry_tamper_and_password_change(self):
        self.a.set_password("good password 1")
        tok, _ = self.a.login("good password 1", "c1")
        self.assertTrue(self.a.valid(tok))
        self.assertFalse(self.a.valid(tok[:-1] + ("0" if tok[-1] != "0" else "1")))
        parts = tok.split("."); parts[2] = str(int(parts[2]) + 99999)
        self.assertFalse(self.a.valid(".".join(parts)))                 # a longer life is a forged cookie
        self.now[0] += 13 * 3600
        self.assertFalse(self.a.valid(tok))                             # ran out
        self.now[0] = 1000.0
        self.assertTrue(self.a.valid(tok))
        self.a.set_password("new password 22")
        self.assertFalse(self.a.valid(tok))                             # a new password signs every browser out

    def test_sign_out_everywhere(self):
        self.a.set_password("good password 1")
        tok, _ = self.a.login("good password 1", "c1")
        self.a.sign_out_everywhere()
        self.assertFalse(self.a.valid(tok))

    def test_lockout(self):
        self.a.set_password("good password 1")
        for _ in range(A.PER_CLIENT_FAILS):
            self.assertIsNone(self.a.login("wrong", "c1")[0])
        tok, why = self.a.login("good password 1", "c1")
        self.assertIsNone(tok); self.assertIn("too many", why)
        self.assertIsNotNone(self.a.login("good password 1", "c2")[0])  # another address is not locked
        self.now[0] += A.LOCK_S + 1
        self.assertIsNotNone(self.a.login("good password 1", "c1")[0])

    def test_global_lockout(self):
        self.a.set_password("good password 1")
        for i in range(A.GLOBAL_FAILS):
            self.a.login("wrong", f"x{i}")
        self.assertIn("too many", self.a.login("good password 1", "fresh")[1])

    def test_a_second_desk_reads_the_same_file(self):
        self.a.set_password("good password 1")
        tok, _ = self.a.login("good password 1", "c1")
        other = A.Auth(self.a.path, 12, clock=lambda: self.now[0], iterations=1000, fail_delay_s=0)
        self.assertTrue(other.valid(tok))                                # the practice desk takes the same sign-in
        self.a.set_password("new password 22")
        self.assertFalse(other.valid(tok))

    def test_setup_needs_the_code(self):
        code = self.a.new_setup_code()
        self.assertFalse(self.a.setup("WRONG-CODE", "good password 1", "good password 1", "c1")[0])
        self.assertTrue(self.a.setup(code.lower(), "good password 1", "good password 1", "c1")[0])
        self.assertFalse(self.a.setup(code, "other password 2", "other password 2", "c1")[0])   # only once


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.auth = A.Auth(os.path.join(self.tmp.name, "auth.json"), 12, iterations=1000, fail_delay_s=0)
        self.engine = Engine(plays(), cfg())
        self.dash = Dashboard(self.engine, "127.0.0.1", 0, clock=lambda: 2.0, auth=self.auth).start()

    def tearDown(self):
        self.dash.stop()
        self.tmp.cleanup()

    def call(self, path, body=None, cookie=None, headers=None):
        h = {"Content-Type": "application/json"}
        if cookie:
            h["Cookie"] = f"{A.COOKIE}={cookie}"
        h.update(headers or {})
        r = urllib.request.Request(self.dash.url + path, data=json.dumps(body).encode() if body is not None else None, headers=h,
                                   method="POST" if body is not None else "GET")
        try:
            with OPENER.open(r, timeout=5) as x:
                return x.status, dict(x.headers), x.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    def login(self):
        code, hd, _ = self.call("/api/login", {"password": "good password 1"})
        self.assertEqual(code, 200)
        return hd["Set-Cookie"].split(";")[0].split("=", 1)[1]

    def test_everything_is_closed_without_a_password(self):
        for p in ("/api/state", "/api/settings", "/api/stream?sym=AAA", "/api/layouts", "/recordings/x.jsonl"):
            self.assertEqual(self.call(p)[0], 401, p)
        code, hd, _ = self.call("/")
        self.assertEqual(code, 303); self.assertTrue(hd["Location"].startswith("/login"))
        self.assertEqual(self.call("/api/trade/flatten_all", {})[0], 401)
        self.assertEqual(self.call("/api/pin", {"symbol": "AAA", "pinned": True})[0], 401)
        code, _, page = self.call("/login")
        self.assertEqual(code, 200); self.assertIn(b"Setup code", page)
        self.assertEqual(self.call("/healthz")[0], 200)

    def test_setup_then_sign_in_then_everything_opens(self):
        code = self.auth.new_setup_code()
        st, hd, _ = self.call("/api/auth/setup", {"code": code, "password": "good password 1", "confirm": "good password 1"})
        self.assertEqual(st, 200)
        ck = hd["Set-Cookie"]
        for flag in ("HttpOnly", "SameSite=Strict", "Path=/"):
            self.assertIn(flag, ck)
        self.assertNotIn("Secure", ck)
        tok = self.login()
        self.assertEqual(self.call("/api/state", cookie=tok)[0], 200)
        self.assertEqual(self.call("/", cookie=tok)[0], 200)
        self.assertEqual(self.call("/login", cookie=tok)[0], 303)        # already in: straight to the desk
        self.assertEqual(self.call("/api/state", cookie=tok + "x")[0], 401)

    def test_wrong_password_and_https_cookie(self):
        self.auth.set_password("good password 1")
        self.assertEqual(self.call("/api/login", {"password": "nope"})[0], 401)
        _, hd, _ = self.call("/api/login", {"password": "good password 1"}, headers={"X-Forwarded-Proto": "https"})
        self.assertIn("Secure", hd["Set-Cookie"])

    def test_another_website_is_refused_even_signed_in(self):
        self.auth.set_password("good password 1")
        tok = self.login()
        st = self.call("/api/pin", {"symbol": "AAA", "pinned": True}, cookie=tok, headers={"Origin": "http://evil.example"})[0]
        self.assertEqual(st, 403)
        host = self.dash.url.split("//")[1]
        st = self.call("/api/pin", {"symbol": "AAA", "pinned": True}, cookie=tok, headers={"Origin": "http://" + host})[0]
        self.assertNotEqual(st, 403)

    def test_tailscale_name_works_once_signed_in(self):
        self.auth.set_password("good password 1")
        tok = self.login()
        hd = {"Host": "ted.tail1234.ts.net", "X-Forwarded-For": "100.64.0.5", "X-Forwarded-Proto": "https"}
        self.assertEqual(self.call("/api/state", cookie=tok, headers=hd)[0], 200)
        self.assertEqual(self.call("/api/state", headers=hd)[0], 401)

    def test_change_password_and_logout(self):
        self.auth.set_password("good password 1")
        tok = self.login()
        st, _, body = self.call("/api/auth/password", {"current": "bad", "password": "new password 22", "confirm": "new password 22"}, cookie=tok)
        self.assertEqual(st, 400)                                       # never a 401: that would throw the desk to the sign-in page
        st, hd, _ = self.call("/api/auth/password", {"current": "good password 1", "password": "new password 22", "confirm": "new password 22"}, cookie=tok)
        self.assertEqual(st, 200)
        new = hd["Set-Cookie"].split(";")[0].split("=", 1)[1]
        self.assertEqual(self.call("/api/state", cookie=tok)[0], 401)     # the old cookie is out
        self.assertEqual(self.call("/api/state", cookie=new)[0], 200)
        st, hd, _ = self.call("/api/logout", {}, cookie=new)
        self.assertIn("Max-Age=0", hd["Set-Cookie"])

    def test_without_auth_the_desk_stays_local_only(self):
        d = Dashboard(self.engine, "127.0.0.1", 0, clock=lambda: 2.0).start()
        try:
            r = urllib.request.Request(d.url + "/api/state", headers={"Host": "ted.tail1234.ts.net"})
            with self.assertRaises(urllib.error.HTTPError) as e:
                urllib.request.urlopen(r, timeout=5)
            self.assertEqual(e.exception.code, 403)
        finally:
            d.stop()


if __name__ == "__main__":
    unittest.main()
