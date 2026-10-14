# TED on the Hostinger VPS (srv1720022.hstgr.cloud, KVM 4)

The desk runs on the VPS as a system service next to a headless IB Gateway, and you open it from any computer
over an SSH tunnel. Nothing on the VPS is exposed to the internet but SSH.

```
   your laptop / phone ──SSH tunnel──▶ VPS: TED (127.0.0.1:8765) ──TWS API──▶ IB Gateway (127.0.0.1:4002, paper)
                                            │                                   │
                                            └── Quant Data (option flow)        └── IBKR
```

## What you do once

1. **Get in.** hPanel › VPS › the server's page shows the IP and the root password (or set an SSH key there).
   From a terminal: `ssh root@srv1720022.hstgr.cloud`.
2. **Put the deploy kit on the server.** From your laptop, from the unzipped TED folder:
   ```
   scp -r twiney/deploy/vps root@srv1720022.hstgr.cloud:/root/vps
   scp TWINEY.zip root@srv1720022.hstgr.cloud:/opt/ted/TWINEY.zip     # (make /opt/ted first: ssh root@... mkdir -p /opt/ted)
   ```
3. **Your IBKR login for the Gateway**, on the server:
   ```
   mkdir -p /etc/ted && cp /root/vps/ibc.env.example /etc/ted/ibc.env && nano /etc/ted/ibc.env && chmod 600 /etc/ted/ibc.env
   ```
   Paper first: `TRADING_MODE=paper`.
4. **Install everything:**
   ```
   sudo bash /root/vps/install.sh
   ```
   It installs Python and the IBKR API, IB Gateway, IBC (keeps the Gateway logged in and restarts it after IBKR's
   Sunday reset), the two services, and locks the firewall to SSH. It moves the config.json out of the zip into the
   data folder `/var/lib/ted`. Open `/var/lib/ted/config.json` and make sure `ibkr.port` is `4002` (the Gateway's
   paper port) and `dashboard.open_browser` is `false`; or set both in SETTINGS once the desk is up.
5. **The second factor.** The first Gateway login after every restart needs your tap in the IBKR Mobile app. IBC
   waits three minutes for it and retries. Watch `/home/ted/ibc/logs` the first time.
6. **Open the desk** from your laptop:
   ```
   ssh -L 8765:127.0.0.1:8765 ted@srv1720022.hstgr.cloud
   ```
   and go to `http://127.0.0.1:8765` in the browser while that terminal stays open. On the phone, an SSH app that
   does port forwarding (Termius) does the same.

## The practice desk on the VPS

The PRACTICE button on the live desk starts a second TED on the next port (8766) on the practice market and opens it
in a new tab. Through the tunnel that port has to be forwarded too:
```
ssh -L 8765:127.0.0.1:8765 -L 8766:127.0.0.1:8766 ted@srv1720022.hstgr.cloud
```
It stops with the live desk, or from the practice tab's own RESTART / close.

## Every new build

Drop the new `TWINEY.zip` at `/opt/ted/TWINEY.zip`, then `sudo bash /root/vps/update.sh`. The data folder is
never touched. The BUILD stamp prints at the end.

## Useful

```
systemctl status ibgateway      journalctl -u ibgateway -f     ls /home/ted/ibc/logs
systemctl status ted            journalctl -u ted -f
sudo systemctl restart ted
```

## What changes on a server, honestly

- **The voice and the mic.** The browser's own voice still works through the tunnel; the ElevenLabs voice is
  fetched by the server and played by your browser, fine. Mic notes record in your browser and upload: fine.
- **DESK AI (Ollama)** on a KVM 4 (4 vCPU, no GPU) writes slowly: the 3B model is the one to pull there
  (`ollama pull llama3.2:3b`, `curl -fsSL https://ollama.com/install.sh | sh`). The 8B model will take minutes.
- **Latency.** The Gateway sits next to the desk, so the tape is read on the server with no laptop in the path.
  The screen update rides the tunnel; a US-east VPS to a US laptop adds tens of milliseconds, nothing you feel.
- **Market data lines.** The Gateway login uses the same IBKR account: TWS on your laptop and the Gateway on the
  VPS cannot both be logged in with the same user at once (IBKR allows one session). Log in from one place.
- **Depth.** Same three Level II lines as before; SMART depth with your TotalView and ArcaBook.
- **Live trading** stays locked unless `trading.allow_live` is switched on. Keep it off on the server until the
  paper weeks are done.
- **Backups.** `/var/lib/ted` holds everything of yours (config, plays, recordings, journal, AI answers). Copy it
  down now and then: `scp -r ted@srv1720022.hstgr.cloud:/var/lib/ted ~/TED-backup`.

## Not done yet

The kit has not been run on the server: the build container that wrote it cannot reach the VPS (its network
policy denies the host). Expect the first run to need a version bump in `install.sh` if IBKR has moved the TWS API
zip or IB Gateway installer, and tell the agent the error text.
