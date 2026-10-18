# DESK AI on the VPS (Ollama), step by step

Goal: the DESK AI (recap + tomorrow's plan, EXPLAIN, notes, the study, CALL PHRASES' WRITE VERSIONS) runs on the
Hostinger VPS, next to TED, so it does not depend on anyone's computer being on.

Everything below is pasted into the **Hostinger Web console** (hPanel › VPS › Terminal), one block at a time.

## Rules while doing this (do not skip)

- Do **not** touch: `trading-dashboard.service` (port 5000), `/root/trading_data`, `/root/sophia-bot`, the
  hermes / traefik containers, `/root/ib-gateway`. Do not stop or restart `ibgateway.service`.
- Never print or open `/etc/ted/ibc.env`, `/var/lib/ted/config.json` or `/var/lib/ted/auth.json`.
- Ollama stays on `127.0.0.1` only. Do **not** set `OLLAMA_HOST=0.0.0.0` on the VPS and do not open port 11434 in any
  firewall: only TED (on the same machine) talks to it.
- Never use `tailscale funnel`.
- Paper only: nothing here touches trading settings.

## 1. Check the machine

```
free -h; nproc; df -h /
```

Look at **Mem › available** and the free disk space on `/`. Pick the model:

| memory available | model to use | download |
|---|---|---|
| 10 GB or more | `llama3.1:8b` | about 4.9 GB |
| 5 to 10 GB | `llama3.2:3b` | about 2.0 GB |
| under 5 GB | `llama3.2:1b` (plain, but works) | about 1.3 GB |

You need the download size plus 2 GB free on `/`. If not, stop and report back.

## 2. Install Ollama

```
curl -fsSL https://ollama.com/install.sh | sh
```

This installs Ollama and an `ollama.service` that starts on boot, listening on `127.0.0.1:11434` only.

## 3. Keep it from slowing the desk

The desk comes first. This caps Ollama to one job at a time, a share of the CPU, a lower priority and a memory
ceiling, and lets the model leave memory 5 minutes after it is used. Change `MemoryMax` to fit the table above
(8b: `7G`, 3b: `4G`, 1b: `3G`).

```
mkdir -p /etc/systemd/system/ollama.service.d
cat > /etc/systemd/system/ollama.service.d/ted.conf <<'EOF'
[Service]
Environment="OLLAMA_HOST=127.0.0.1:11434"
Environment="OLLAMA_NUM_PARALLEL=1"
Environment="OLLAMA_MAX_LOADED_MODELS=1"
Environment="OLLAMA_KEEP_ALIVE=5m"
Nice=10
CPUQuota=75%
MemoryMax=7G
EOF
systemctl daemon-reload && systemctl restart ollama && systemctl --no-pager status ollama | head -5
```

Expect `active (running)`.

## 4. Pull the model (use the one you picked in step 1)

```
ollama pull llama3.1:8b
```

## 5. Test it on the VPS

```
curl -s http://127.0.0.1:11434/api/tags | head -c 300; echo
time curl -s http://127.0.0.1:11434/api/generate -d '{"model":"llama3.1:8b","prompt":"Say ready in one word.","stream":false}' | head -c 200; echo
```

The first line lists the model. The second answers with a word; note how many seconds `real` says (the first call
loads the model, so it is slower).

## 6. Turn it on in TED

In the desk (browser): **SETTINGS › AI**

- **enabled**: on
- **Ollama address**: `http://127.0.0.1:11434` (already the default)
- **Model**: exactly the name you pulled (`llama3.1:8b`, `llama3.2:3b` or `llama3.2:1b`)
- **Wait for an answer up to (s)**: `600` (a VPS processor writes the recap in one to five minutes)
- **Reading window (tokens)**: `8192` for 8b; `4096` for 3b / 1b
- **SAVE**

Do this in the SETTINGS page, not by editing `/var/lib/ted/config.json`.

## 7. Check it from the desk

1. **PANELS › DESK AI**: the status line says **READY** with the model name. If it says Ollama is not answering,
   run step 5 again and report what it prints.
2. Click **RECAP + TOMORROW**. It says WRITING; the answer lands in one to five minutes.
3. **PANELS › CALL PHRASES** › open a call › **WRITE VERSIONS**: yellow PENDING versions appear.

## 8. If something goes wrong

```
systemctl --no-pager status ollama | head -15
journalctl -u ollama --no-pager -n 40
free -h
```

- `out of memory` / killed: use the next smaller model (step 4), set it in SETTINGS › AI, and lower `MemoryMax`.
- Very slow: use the smaller model; the recap at the close runs on its own 5 minutes after 16:00 ET, so speed
  matters less there.
- To remove it all: `systemctl disable --now ollama` (TED keeps working; the AI buttons say Ollama is not
  answering).

## What to send back

The output of step 1, the `real` time from step 5, and a screenshot of the DESK AI status line.
