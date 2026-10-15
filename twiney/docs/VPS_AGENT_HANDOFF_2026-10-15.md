# TED on the VPS — handoff for the agent on the box (2026-10-15)

You are the agent with a root shell on Antoine's Hostinger VPS. TED is already installed and running there (your
report of 2026-10-13). This handoff does three things: put the newest build on the box, fix the file owner so
saved keys stick, and make the desk reachable from Antoine's phone and tablet through Tailscale.

## Facts

| thing | value |
|---|---|
| VPS | Hostinger KVM 4, `srv1720022.hstgr.cloud`, `31.97.137.133`, Ubuntu, clock UTC |
| repo | `antoineriley1-debug/pmwatch`, branch `claude/twiney-v1-complete-gdn0ws`, folder `twiney/` |
| build | **20261014-0345** or newer (`grep -o 'name="build" content="[^"]*"' /opt/ted/app/twiney/static/dashboard.html`) |
| zip | `TWINEY.zip` from Antoine (carries the private `config.json`; never commit it, never print it) |
| code | `/opt/ted/app` (package `twiney/`), venv `/opt/ted/venv`, TWS API `/opt/ted/twsapi` |
| data | `TWINEY_HOME=/var/lib/ted`: `config.json` (Quant Data, ElevenLabs, Gmail app password), plays, layouts, recordings |
| services | `ted.service` (user `ted`, desk on `127.0.0.1:8765`), `ibgateway.service` (IBC, paper, port 4002), `xvfb-ted.service` |
| practice desk | started by the PRACTICE button on the live desk, a second TED on `127.0.0.1:8766` |
| paper account | DUR225433 |

## Rules that never change

- Paper only. Never set `trading.allow_live`, never use ports 4001 / 7496.
- Never print `/etc/ted/ibc.env` or `/var/lib/ted/config.json`. Keys never go into git or a log you paste back.
- Do not touch `trading-dashboard.service` (port 5000), `/root/trading_data`, `/root/sophia-bot`, the hermes /
  traefik containers, `/root/ib-gateway`.
- The desk is never opened to the public internet. SSH and Tailscale only. No ufw rule for 8765 / 8766.
- Every word about the market in what you write is a PS60 word (`.claude/skills/ps60-language/SKILL.md`). No model
  names in commits or docs.

## 1. Put the newest build on the box

```
# Antoine's TWINEY.zip at /opt/ted/TWINEY.zip, then:
sudo bash /root/vps/update.sh
```

`update.sh` unpacks the code, keeps `/var/lib/ted` untouched, restarts `ted`, prints the BUILD stamp. The new
`update.sh` (inside the zip at `twiney/deploy/vps/update.sh`) also ends with `chown -R ted:ted /var/lib/ted`; copy it
over `/root/vps/update.sh` first:

```
cd /tmp && rm -rf tedzip && mkdir tedzip && cd tedzip && unzip -q /opt/ted/TWINEY.zip
cp TWINEY/twiney/deploy/vps/update.sh /root/vps/update.sh && cp TWINEY/twiney/deploy/vps/*.service /root/vps/
```

## 2. Fix the owner so SETTINGS (keys included) are kept

The ElevenLabs key "did not save": TED runs as `ted`, and a root-owned `config.json` cannot be written. The new build
says NOT SAVED in that case instead of looking saved. Fix it once:

```
sudo chown -R ted:ted /var/lib/ted
sudo -u ted test -w /var/lib/ted/config.json && echo WRITABLE
sudo systemctl restart ted
journalctl -u ted -n 30 | grep -i "not writable" || echo "no read-only warning"
```

Then tell Antoine to enter the ElevenLabs key and Voice ID once in SETTINGS › Voice and look for KEY SAVED. The box
stays empty after saving on purpose.

## 3. Tailscale: the desk on his phone and tablet, nothing opened to the internet

```
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --ssh --hostname ted
```

`tailscale up` prints a login link. **Send that link to Antoine** and wait for him to sign in (the same account he
will use on his phone). Then, in the Tailscale admin console (login.tailscale.com › DNS), MagicDNS and HTTPS
Certificates must be on; ask him to switch them on if `tailscale serve` says so.

Serve the two desks inside his tailnet only (HTTPS, a real certificate, TED keeps listening on 127.0.0.1):

```
sudo tailscale serve --bg --https=443  http://127.0.0.1:8765     # the live desk
sudo tailscale serve --bg --https=8766 http://127.0.0.1:8766     # the practice desk (the PRACTICE button opens port 8766)
tailscale serve status
tailscale status | head -3
```

The practice desk must be on HTTPS port **8766**: the PRACTICE button opens the same host on the next port.
Never use `tailscale funnel` (that would put the desk on the public internet).

Check from the box:

```
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8765/api/state     # 200
```

## 4. What to send Antoine

1. The address, from `tailscale serve status`, e.g. `https://ted.<his-tailnet>.ts.net` (live) and
   `https://ted.<his-tailnet>.ts.net:8766` (practice).
2. On the phone / tablet: install **Tailscale** from the app store, sign in with the same account, switch it on,
   open the address in the browser. Add it to the home screen.
3. The laptop: same app, same address, or the SSH tunnel as before.

## 5. Verify and report back

- `systemctl status ibgateway ted tailscaled` all active.
- The BUILD stamp the desk shows through the Tailscale address.
- CONNECTED / PAPER on the desk; the Level II reads LIVE (or DELAYED outside hours) and SMART DEPTH.
- `config.json` writable by `ted` (the WRITABLE line above); no read-only warning in `journalctl -u ted`.
- The PRACTICE button opens the practice desk at `:8766` and its tape moves.
- One message to Antoine: what you ran, the two addresses, anything that failed and the exact fix. Nothing else
  changes on the box without his word.
