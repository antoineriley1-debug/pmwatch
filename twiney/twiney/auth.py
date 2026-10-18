"""THE SIGN-IN: nothing on the desk opens without your password.

- The password is never stored, only a salted PBKDF2-SHA256 hash, in ``auth.json`` next to config.json (file mode
  0600, outside SETTINGS, never in git). The practice desk reads the same file, so one sign-in covers both.
- A signed-in browser holds a cookie (``ted_session``): HttpOnly, SameSite=Strict, Secure over HTTPS, signed with
  HMAC-SHA256 by a random key in the same file, good for ``dashboard.session_hours``. Changing the password or
  SIGN OUT EVERYWHERE turns every cookie handed out before it into nothing.
- Wrong passwords: 5 from one address locks that address out for 15 minutes; 30 from everywhere locks the sign-in
  for everyone for 15 minutes. Every refusal waits a moment and says the same thing.
- No password yet: the sign-in page asks you to create one, and only with the one-time SETUP CODE TED prints in
  its own window (on the VPS: ``journalctl -u ted``). Or from a shell: ``python run_twiney.py --set-password``.
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time

COOKIE = "ted_session"
ITERATIONS = 600_000
MIN_LEN = 10
PER_CLIENT_FAILS, GLOBAL_FAILS, LOCK_S = 5, 30, 15 * 60


def hash_password(password, iterations=ITERATIONS, salt=None):
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def check_password(password, stored):
    try:
        algo, it, salt, dk = str(stored).split("$")
        if algo != "pbkdf2_sha256":
            return False
        got = hashlib.pbkdf2_hmac("sha256", str(password).encode("utf-8"), base64.b64decode(salt), int(it))
        return hmac.compare_digest(got, base64.b64decode(dk))
    except (ValueError, TypeError):
        return False


def password_problem(password, confirm=None):
    """Why this password will not do, or None."""
    if not isinstance(password, str) or len(password) < MIN_LEN:
        return f"use at least {MIN_LEN} characters"
    if len(password) > 256:
        return "use at most 256 characters"
    if confirm is not None and password != confirm:
        return "the two passwords are not the same"
    if len(set(password)) < 4:
        return "too easy to guess: mix more characters"
    return None


def auth_path(config_path):
    return os.path.join(os.path.dirname(os.path.abspath(config_path)), "auth.json")


class Auth:
    def __init__(self, path, session_hours=12.0, clock=time.time, iterations=ITERATIONS, fail_delay_s=0.6):
        self.path = path
        self.session_s = max(0.25, float(session_hours or 12)) * 3600
        self.clock = clock
        self.iterations = iterations
        self.fail_delay_s = fail_delay_s
        self._lock = threading.Lock()
        self._data, self._mtime = {}, None
        self._fails = {}            # client -> [failure times]
        self._all_fails = []
        self.setup_code = None
        self._load()

    # ---------------------------------------------------------------- the file
    def _load(self):
        try:
            m = os.stat(self.path).st_mtime_ns
        except OSError:
            self._data, self._mtime = {}, None
            return
        if m == self._mtime:
            return
        try:
            with open(self.path, encoding="utf-8") as fh:
                d = json.load(fh)
            self._data, self._mtime = (d if isinstance(d, dict) else {}), m
        except (OSError, ValueError):
            self._data, self._mtime = {}, None

    def _save(self, d):
        tmp = self.path + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(d, fh)
        os.replace(tmp, self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass
        self._data, self._mtime = d, None
        self._load()

    def has_password(self):
        with self._lock:
            self._load()
            return bool(self._data.get("hash"))

    def _key(self):
        return base64.b64decode(self._data["key"]) if self._data.get("key") else b""

    def set_password(self, password, confirm=None):
        """Save a new password; every cookie handed out before it stops working. Returns (ok, reason)."""
        why = password_problem(password, confirm)
        if why:
            return False, why
        with self._lock:
            self._load()
            d = dict(self._data)
            d["hash"] = hash_password(password, self.iterations)
            d["key"] = base64.b64encode(secrets.token_bytes(32)).decode()     # a new key: every old cookie is void
            d["epoch"] = int(d.get("epoch") or 0) + 1
            d["changed"] = int(self.clock())
            self._save(d)
            self.setup_code = None
        return True, ""

    def sign_out_everywhere(self):
        with self._lock:
            self._load()
            if not self._data.get("hash"):
                return
            d = dict(self._data)
            d["key"] = base64.b64encode(secrets.token_bytes(32)).decode()
            d["epoch"] = int(d.get("epoch") or 0) + 1
            self._save(d)

    # ---------------------------------------------------------------- setup code (no password yet)
    def new_setup_code(self):
        a = secrets.token_hex(3).upper()
        b = secrets.token_hex(3).upper()
        self.setup_code = f"{a}-{b}"
        return self.setup_code

    def setup(self, code, password, confirm, client):
        """Create the first password with the SETUP CODE from TED's window. Returns (ok, reason)."""
        if self.has_password():
            return False, "a password is already set: sign in"
        if self.locked(client):
            return False, "too many tries: wait 15 minutes"
        want = self.setup_code or ""
        if not want or not hmac.compare_digest(str(code or "").strip().upper(), want):
            self._fail(client)
            return False, "wrong setup code (it is printed in TED's own window; on the VPS: journalctl -u ted)"
        return self.set_password(password, confirm)

    # ---------------------------------------------------------------- sign-in and the cookie
    def locked(self, client):
        now = self.clock()
        with self._lock:
            self._all_fails = [t for t in self._all_fails if now - t < LOCK_S]
            mine = self._fails.get(client, [])
            mine = [t for t in mine if now - t < LOCK_S]
            if mine:
                self._fails[client] = mine
            else:
                self._fails.pop(client, None)
            return len(mine) >= PER_CLIENT_FAILS or len(self._all_fails) >= GLOBAL_FAILS

    def _fail(self, client):
        now = self.clock()
        with self._lock:
            self._fails.setdefault(client, []).append(now)
            self._all_fails.append(now)
            if len(self._fails) > 5000:                   # never grows without end
                self._fails.clear()
        if self.fail_delay_s:
            time.sleep(self.fail_delay_s)

    def login(self, password, client):
        """Returns (cookie value or None, reason)."""
        if self.locked(client):
            return None, "too many tries: wait 15 minutes"
        with self._lock:
            self._load()
            stored = self._data.get("hash")
        if not stored:
            return None, "no password yet: create one with the setup code"
        if not check_password(password, stored):
            self._fail(client)
            return None, "wrong password"
        with self._lock:
            self._fails.pop(client, None)
        return self.issue(), ""

    def issue(self):
        with self._lock:
            self._load()
            epoch, key = int(self._data.get("epoch") or 0), self._key()
        exp = int(self.clock() + self.session_s)
        body = f"1.{epoch}.{exp}.{secrets.token_hex(8)}"
        sig = hmac.new(key, body.encode(), hashlib.sha256).hexdigest()
        return f"{body}.{sig}"

    def valid(self, cookie):
        if not cookie:
            return False
        try:
            v, epoch, exp, nonce, sig = cookie.split(".")
            with self._lock:
                self._load()
                if not self._data.get("hash"):
                    return False
                key, cur = self._key(), int(self._data.get("epoch") or 0)
            if v != "1" or int(epoch) != cur or int(exp) < self.clock():
                return False
            want = hmac.new(key, f"{v}.{epoch}.{exp}.{nonce}".encode(), hashlib.sha256).hexdigest()
            return hmac.compare_digest(want, sig)
        except (ValueError, TypeError):
            return False

    def change_password(self, current, new, confirm, client):
        if self.locked(client):
            return False, "too many tries: wait 15 minutes"
        with self._lock:
            self._load()
            stored = self._data.get("hash")
        if not stored or not check_password(current, stored):
            self._fail(client)
            return False, "the current password is wrong"
        return self.set_password(new, confirm)


def cookie_from(header):
    for part in str(header or "").split(";"):
        k, _, v = part.strip().partition("=")
        if k == COOKIE:
            return v
    return None


def set_cookie(value, secure, max_age):
    flags = f"{COOKIE}={value}; Path=/; HttpOnly; SameSite=Strict; Max-Age={int(max_age)}"
    return flags + ("; Secure" if secure else "")


LOGIN_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>TED · Sign in</title>
<style>
:root{--bg:#0c0c0d;--card:#131416;--line:#2c2e33;--ink:#e6e6e3;--dim:#8e9096;--gold:#e3a83a;--red:#d9534f;--green:#3fb56f}
*{box-sizing:border-box}html,body{margin:0;height:100%;background:var(--bg);color:var(--ink);font:14px/1.4 "IBM Plex Sans",system-ui,sans-serif}
main{min-height:100%;display:flex;align-items:center;justify-content:center;padding:16px}
form{width:100%;max-width:360px;background:var(--card);border:1px solid var(--line);border-radius:6px;padding:28px 24px}
h1{margin:0 0 4px;font:600 22px "IBM Plex Mono",monospace;letter-spacing:.18em;color:var(--gold)}
p.sub{margin:0 0 20px;color:var(--dim);font-size:12px;letter-spacing:.08em;text-transform:uppercase}
label{display:block;margin:14px 0 6px;color:var(--dim);font-size:11px;letter-spacing:.1em;text-transform:uppercase}
input{width:100%;padding:10px 12px;background:var(--bg);border:1px solid var(--line);border-radius:4px;color:var(--ink);font:15px "IBM Plex Mono",monospace}
input:focus{outline:none;border-color:var(--gold)}
button{width:100%;margin-top:22px;padding:11px;background:var(--gold);color:#111;border:0;border-radius:4px;font:600 13px "IBM Plex Mono",monospace;letter-spacing:.14em;cursor:pointer}
button:disabled{opacity:.5;cursor:default}
#msg{min-height:18px;margin-top:14px;font-size:12px;color:var(--red)}
.note{margin-top:16px;color:var(--dim);font-size:11px;line-height:1.5}
.setup .signin,.signin-mode .setup{display:none}
</style></head>
<body><main>
<form id="f" class="__MODE__" autocomplete="on">
  <h1>TED</h1><p class="sub">Twiney Execution Desk</p>
  <div class="setup">
    <p class="note">No password yet. Create one. TED printed a SETUP CODE in its own window
    (on the VPS: <code>journalctl -u ted | grep "SETUP CODE"</code>).</p>
    <label for="code">Setup code</label><input id="code" autocomplete="one-time-code" autocapitalize="characters">
  </div>
  <input type="text" name="username" value="twiney" autocomplete="username" hidden>
  <label for="pw">Password</label><input id="pw" type="password" autocomplete="__AC__" autofocus required>
  <div class="setup"><label for="pw2">Password again</label><input id="pw2" type="password" autocomplete="new-password"></div>
  <button id="go" type="submit">__BTN__</button>
  <div id="msg" role="alert"></div>
  <p class="note signin">5 wrong tries lock this address out for 15 minutes.</p>
</form></main>
<script>
const f = document.getElementById("f"), msg = document.getElementById("msg"), go = document.getElementById("go");
const setup = f.classList.contains("setup");
function next(){ const n = new URLSearchParams(location.search).get("next") || "/"; return /^\\/(?!\\/)/.test(n) ? n : "/"; }
f.addEventListener("submit", async e => {
  e.preventDefault(); msg.textContent = ""; go.disabled = true;
  const pw = document.getElementById("pw").value;
  const body = setup ? {code: document.getElementById("code").value, password: pw, confirm: document.getElementById("pw2").value} : {password: pw};
  try {
    const r = await fetch(setup ? "/api/auth/setup" : "/api/login", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body), credentials: "same-origin"});
    const j = await r.json().catch(() => ({}));
    if (r.ok && j.ok) { location.replace(next()); return; }
    msg.textContent = j.reason || ("refused (" + r.status + ")");
  } catch (err) { msg.textContent = "TED did not answer"; }
  go.disabled = false; document.getElementById("pw").select();
});
</script></body></html>
"""


def login_page(setup):
    return (LOGIN_PAGE.replace("__MODE__", "setup" if setup else "signin-mode")
            .replace("__AC__", "new-password" if setup else "current-password")
            .replace("__BTN__", "CREATE PASSWORD" if setup else "SIGN IN"))
