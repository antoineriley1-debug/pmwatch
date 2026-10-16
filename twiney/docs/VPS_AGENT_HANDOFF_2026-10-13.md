# TED on the VPS — handoff for the agent that finishes the deploy

Written 2026-10-13 for the bot that has a shell on the Hostinger box (or Antoine's laptop with SSH to it). The
build agent that wrote the kit could not reach the VPS (its network policy denies the host), so nothing below has
been run on the server yet. Everything it needs is in the zip and in the repo.

## Facts

| thing | value |
|---|---|
| VPS | Hostinger KVM 4, `srv1720022.hstgr.cloud` (4 vCPU, no GPU). Root password / SSH key in hPanel › VPS |
| repo | `antoineriley1-debug/pmwatch`, branch `claude/twiney-v1-complete-gdn0ws`, folder `twiney/` |
| build | **20261013-1811**, commit `c2217f2` (the `<meta name="build">` in `twiney/static/dashboard.html`) |
| zip | `TWINEY.zip` (contains `TWINEY/twiney/...` plus the private `config.json` with the Quant Data and ElevenLabs keys: never commit it) |
| deploy kit | `twiney/deploy/vps/`: `install.sh`, `update.sh`, `ted.service`, `ibgateway.service`, `ibc-config.ini.template`, `ibc.env.example` |
| the doc | `twiney/docs/VPS_DEPLOY.md` (the human steps, read it first) |
| data folder on the box | `/var/lib/ted` (config.json, plays.json, recordings, journal, AI answers), env `TWINEY_HOME=/var/lib/ted` |
| code on the box | `/opt/ted/TWINEY` (the unzipped zip), the IBKR Python API at `/opt/ted/twsapi` |
| services | `ted.service` (TED, user `ted`, dashboard `127.0.0.1:8765`), `ibgateway.service` (IB Gateway under IBC, paper port `4002`) |
| access | SSH only; the desk is reached through `ssh -L 8765:127.0.0.1:8765 ted@srv1720022.hstgr.cloud` → `http://127.0.0.1:8765` |

## Rules that never change (from the repo's CLAUDE.md)

- Paper first. `trading.allow_live` stays `false` on the server until Antoine says otherwise.
- The Quant Data key and the ElevenLabs key live only in `/var/lib/ted/config.json` (from the zip) and the IBKR
  login only in `/etc/ted/ibc.env`. Never in git, never in a log you paste back.
- Every word about the market in anything you write or say is a PS60 word (`.claude/skills/ps60-language/SKILL.md`).
- No model identifiers in commits, code or docs.

## Steps (in order)

1. **Get on the box as root.** `ssh root@srv1720022.hstgr.cloud`. Ubuntu 22.04 or 24.04 expected; `install.sh`
   uses apt, systemd, ufw.
2. **Put the kit and the zip on it.**
   ```
   ssh root@srv1720022.hstgr.cloud 'mkdir -p /opt/ted /root/vps'
   scp -r twiney/deploy/vps/* root@srv1720022.hstgr.cloud:/root/vps/
   scp TWINEY.zip root@srv1720022.hstgr.cloud:/opt/ted/TWINEY.zip
   ```
3. **IBKR login for the Gateway** (Antoine types the password; you never see it, never echo it):
   ```
   mkdir -p /etc/ted && cp /root/vps/ibc.env.example /etc/ted/ibc.env && nano /etc/ted/ibc.env && chmod 600 /etc/ted/ibc.env
   ```
   `TRADING_MODE=paper`. The paper username is the one that starts with the live username plus a suffix, as IBKR
   issued it.
4. **Install.** `sudo bash /root/vps/install.sh`. It: installs python3 + unzip + ufw; downloads the TWS API zip
   and points TED at its `pythonclient`; downloads IB Gateway (stable) and IBC; writes the two services; moves the
   zip's `config.json` into `/var/lib/ted`; locks ufw to SSH; starts both services.
   **Expected first-run breakages, fix in place and note what you changed:**
   - `TWSAPI_URL` (`install.sh` line 25) points at `twsapi_macunix.1030.01.zip` on `interactivebrokers.github.io`;
     if 404, open https://interactivebrokers.github.io/ and take the current "Mac/Unix" stable zip, export
     `TWSAPI_URL=...` and rerun. Any 10.x works with TED.
   - `IBC_VER` 3.20.0: if the release is gone, take the latest from https://github.com/IbcAlpha/IBC/releases.
   - The IB Gateway installer URL (`ibgateway-stable-standalone-linux-x64.sh`): if it moved, take the current
     stable from https://www.interactivebrokers.com/en/trading/ibgateway-stable.php.
   - IBC's `config.ini` is written from `ibc-config.ini.template` with the values from `/etc/ted/ibc.env`; check
     `/home/ted/ibc/config.ini` has `TradingMode=paper` and `OverrideTwsApiPort=4002`.
5. **Check `/var/lib/ted/config.json`:** `ibkr.port` = `4002`, `ibkr.host` = `127.0.0.1`, `dashboard.host` =
   `127.0.0.1`, `dashboard.port` = `8765`, `dashboard.open_browser` = `false`. `ibkr.client_id` any number not in
   use (61 is fine). Leave the keys as they are.
6. **The second factor.** The first Gateway login after every restart needs Antoine's tap in IBKR Mobile. IBC waits
   three minutes and retries. Tell him when to tap. Watch `journalctl -u ibgateway -f` and `/home/ted/ibc/logs`.
   One IBKR user can be logged in from one place: TWS on his laptop must be closed while the Gateway logs in.
7. **Verify, in this order, and paste the results back to Antoine:**
   - `systemctl status ibgateway ted` both `active (running)`.
   - `journalctl -u ted -n 50`: the line `TWINEY 3.4.0 ... CONNECTED` (or the paper account id `DU...`), no traceback.
   - `curl -s http://127.0.0.1:8765/api/state | head -c 400` on the box: JSON with `"connection"`.
   - From the laptop, the tunnel: `ssh -L 8765:127.0.0.1:8765 ted@srv1720022.hstgr.cloud`, then the desk at
     `http://127.0.0.1:8765` shows the build stamp `20261013-1811` (SETTINGS, or view-source) and the top-left
     status reads CONNECTED / PAPER, not DISCONNECTED or DEMO.
   - On the Level II: the data header reads `LIVE` (or `DELAYED` outside market hours) and `SMART DEPTH`, not
     `NO BOOK`. If `REFUSED`, the reason is in the header's tooltip and SETTINGS says what to fix (market data
     subscriptions on the paper account must be shared from the live one in Client Portal › Settings › Paper
     Trading Account).
   - Place one paper order of 1 share from the ladder and cancel it. It must show in ORDERS and in the Gateway.
8. **Optional, DESK AI on the box:** `curl -fsSL https://ollama.com/install.sh | sh && ollama pull llama3.2:3b`,
   then SETTINGS › AI › model `llama3.2:3b`. On 4 vCPU the 8B model takes minutes an answer; use the 3B.
9. **Backups:** add a daily `tar` of `/var/lib/ted` to `/root/backups` (cron, keep 14), and tell Antoine the
   `scp` line to pull one down.

## Every new build after this

Antoine drops the new `TWINEY.zip` at `/opt/ted/TWINEY.zip`, then `sudo bash /root/vps/update.sh`. The data folder
is never touched; the BUILD stamp prints at the end.

## What TED is, in one paragraph, so you know what you are checking

TED (Twiney Execution Desk) is a Python server (`run_twiney.py`) that talks to IB Gateway over the TWS API (quotes,
SMART depth, tick-by-tick tape, option chains with open interest, orders) and to Quant Data for option flow, and
serves one page, the desk, over HTTP. The desk is built on the PS60 theory (Dan Shapiro): daily room → 60-minute
pivot → confirmation → second entry → build → pay yourself → runner to MP. It has the Precision Level II (the DOM,
Jigsaw-style, with BUY / SELL order columns, stops, a contract mode when an option is picked on the chain), the
tape, charts with the play's lines, the option chain and flow, the PS60 story, AUTO 2nd entry with scale plan and
breakeven, recordings and replay, the journal, and DESK AI (Ollama) for the recap. Tests: `cd twiney && python3 -m
unittest discover -s tests` (all green at this build). Page build: `python3 page_src/build_page.py`.

## Report back

One message to Antoine with: what you ran, what broke and the exact fix (URL or version), the build stamp the desk
shows through the tunnel, CONNECTED / PAPER confirmed, the paper order and its cancel confirmed, and the backup
line. Nothing else changes on the box without his word.
