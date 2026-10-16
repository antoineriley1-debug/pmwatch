# THE SIGN-IN — nothing on TED opens without your password

Every page (the desk, MARKET), every API route (state, orders, settings, recordings, the live stream) and the
practice desk answer only to a browser that signed in. Without it: the sign-in page, or `401 sign in first`.

## The first time

TED prints a one-time code in its own window when no password is set:

```
TED SIGN-IN: no password yet. SETUP CODE 3F9A1C-77B2E0 - open the desk and create your password with it
```

Open the desk, type the SETUP CODE, your password twice (10 characters or more), CREATE PASSWORD. On the VPS read the
code with `journalctl -u ted | grep "SETUP CODE"`, or set the password from a shell instead (as the `ted` user, so
the file stays TED's):

```
sudo -u ted /opt/ted/venv/bin/python /opt/ted/app/run_twiney.py --config /var/lib/ted/config.json --set-password
sudo systemctl restart ted
```

On Windows: `python run_twiney.py --set-password` in the TED folder. Forgot it? Same command, a new password.

## How it is kept safe

| piece | what it does |
|---|---|
| password | never stored: a salted PBKDF2-SHA256 hash (600,000 rounds) in `auth.json` next to config.json, file mode 0600, never in git, never in SETTINGS |
| cookie | `ted_session`, signed (HMAC-SHA256) with a random key in `auth.json`; HttpOnly (page scripts cannot read it), SameSite=Strict (other websites cannot use it), Secure over HTTPS (Tailscale); good for `dashboard.session_hours` (12) |
| wrong passwords | 5 from one address: that address waits 15 minutes; 30 from everywhere: the sign-in waits 15 minutes; every refusal is logged in TED's window |
| other websites | a request whose browser Origin is not the desk's own address is refused, signed in or not |
| change password | SETTINGS › Desk › SIGN-IN PASSWORD (needs the current one); every other browser is signed out |
| sign out | SIGN OUT in the header (this browser); SIGN OUT EVERYWHERE in SETTINGS › Desk |
| practice desk | reads the same `auth.json`: one sign-in covers both |
| health check | `/healthz` stays open (says only ok and the connection state) for the box's own checks |

The sign-in can only be turned off by editing `config.json` by hand (`"dashboard": {"sign_in": false}`); then the
desk goes back to answering this computer only, never another address.

Reaching the desk from the phone stays Tailscale only (`tailscale serve`, never `funnel`); the sign-in is the second
lock on top of it.
