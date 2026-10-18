#!/usr/bin/env bash
# TED on a Linux VPS (Ubuntu 22.04 / 24.04, Hostinger KVM): IB Gateway (headless, kept logged in by IBC) + TED as
# system services. Run once as root on the fresh server:
#
#     sudo bash install.sh
#
# What it does, in order (each step is safe to run again):
#   1. packages: python3, venv, unzip, Xvfb (IB Gateway needs a display even headless), a firewall
#   2. a `ted` user; TED unpacked into /opt/ted; a venv with the IBKR TWS API (ibapi) in it
#   3. IB Gateway (stable standalone) under /home/ted/Jts; IBC (keeps the Gateway logged in, restarts it on the
#      weekly IBKR reset) under /opt/ibc
#   4. systemd units: ibgateway.service (Xvfb + IBC + Gateway on paper port 4002) and ted.service (the desk)
#   5. the firewall: SSH only. The desk stays on 127.0.0.1 by design; you reach it over an SSH tunnel:
#        ssh -L 8765:127.0.0.1:8765 ted@srv1720022.hstgr.cloud      then open http://127.0.0.1:8765
#
# Before you run it, put your files in place (never in git):
#   /etc/ted/ibc.env         IBKR login for the Gateway (see ibc.env.example)
#   /var/lib/ted/config.json your TED config.json (Quant Data key, ElevenLabs key); ibkr.port must be 4002
#   /var/lib/ted/plays.json  your plays
#   /opt/ted/TWINEY.zip      the TED zip this script unpacks (or let it clone the branch: set TED_GIT below)
#
# Versions (change if IBKR moves them): the TWS API zip and the IBC release.
set -euo pipefail

TWSAPI_URL="${TWSAPI_URL:-https://interactivebrokers.github.io/downloads/twsapi_macunix.1030.01.zip}"
IBGW_URL="${IBGW_URL:-https://download2.interactivebrokers.com/installers/ibgateway/stable-standalone/ibgateway-stable-standalone-linux-x64.sh}"
IBC_VER="${IBC_VER:-3.20.0}"
IBC_URL="${IBC_URL:-https://github.com/IbcAlpha/IBC/releases/download/${IBC_VER}/IBCLinux-${IBC_VER}.zip}"
TED_GIT="${TED_GIT:-}"                       # e.g. https://github.com/antoineriley1-debug/pmwatch (branch below); empty = use /opt/ted/TWINEY.zip
TED_BRANCH="${TED_BRANCH:-claude/twiney-v1-complete-gdn0ws}"
TED_HOME=/var/lib/ted
TED_DIR=/opt/ted

say(){ printf '\n\033[1;33m== %s\033[0m\n' "$*"; }

[ "$(id -u)" = 0 ] || { echo "run as root: sudo bash install.sh"; exit 1; }
[ -f /etc/ted/ibc.env ] || { echo "missing /etc/ted/ibc.env (copy ibc.env.example there and fill it in)"; exit 1; }

say "1. packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip unzip curl xvfb xauth libxtst6 libxrender1 libxi6 libgtk-3-0 ufw git >/dev/null

say "2. the ted user and TED under $TED_DIR"
id ted >/dev/null 2>&1 || useradd -m -s /bin/bash ted
mkdir -p "$TED_DIR" "$TED_HOME" /etc/ted
if [ -n "$TED_GIT" ]; then
  if [ -d "$TED_DIR/src/.git" ]; then git -C "$TED_DIR/src" fetch -q origin "$TED_BRANCH" && git -C "$TED_DIR/src" checkout -q "$TED_BRANCH" && git -C "$TED_DIR/src" reset -q --hard "origin/$TED_BRANCH"
  else git clone -q --depth 1 --branch "$TED_BRANCH" "$TED_GIT" "$TED_DIR/src"; fi
  APP="$TED_DIR/src/twiney"
elif [ -f "$TED_DIR/TWINEY.zip" ]; then
  rm -rf "$TED_DIR/unpack" && mkdir -p "$TED_DIR/unpack" && unzip -q -o "$TED_DIR/TWINEY.zip" -d "$TED_DIR/unpack"
  APP="$TED_DIR/unpack/TWINEY/twiney"
  # the zip carries your private config.json: it belongs in the data folder, never next to the program
  if [ -f "$APP/config.json" ] && [ ! -f "$TED_HOME/config.json" ]; then mv "$APP/config.json" "$TED_HOME/config.json"; fi
  rm -f "$APP/config.json"
else
  echo "no TED source: set TED_GIT or put TWINEY.zip in $TED_DIR"; exit 1
fi
ln -sfn "$APP" "$TED_DIR/app"
[ -f "$TED_HOME/plays.json" ] || cp "$APP/plays.example.json" "$TED_HOME/plays.json"
[ -f "$TED_HOME/config.json" ] || { cp "$APP/config.example.json" "$TED_HOME/config.json"; echo "NOTE: $TED_HOME/config.json is the example; put yours there (ibkr.port 4002)"; }
chown -R ted:ted "$TED_DIR" "$TED_HOME"
chmod 700 "$TED_HOME"

say "2b. python venv + the IBKR TWS API (ibapi)"
[ -d "$TED_DIR/venv" ] || sudo -u ted python3 -m venv "$TED_DIR/venv"
if ! sudo -u ted "$TED_DIR/venv/bin/python" -c "import ibapi" 2>/dev/null; then
  rm -rf "$TED_DIR/twsapi" && mkdir -p "$TED_DIR/twsapi"
  curl -fsSL "$TWSAPI_URL" -o "$TED_DIR/twsapi/twsapi.zip"
  unzip -q -o "$TED_DIR/twsapi/twsapi.zip" -d "$TED_DIR/twsapi"
  PYCLIENT="$(find "$TED_DIR/twsapi" -type d -path '*source/pythonclient' | head -1)"
  chown -R ted:ted "$TED_DIR/twsapi"
  (cd "$PYCLIENT" && sudo -u ted "$TED_DIR/venv/bin/pip" install -q .)
fi
sudo -u ted "$TED_DIR/venv/bin/python" -c "import ibapi; print('ibapi', ibapi.__version__ if hasattr(ibapi, '__version__') else 'ok')"

say "3. IB Gateway + IBC"
if [ ! -d /home/ted/Jts/ibgateway ]; then
  curl -fsSL "$IBGW_URL" -o /tmp/ibgateway.sh
  chmod +x /tmp/ibgateway.sh
  sudo -u ted /tmp/ibgateway.sh -q -dir /home/ted/Jts/ibgateway/stable     # unattended install
fi
GW_VER="$(ls /home/ted/Jts/ibgateway 2>/dev/null | grep -E '^[0-9]+$' | sort -n | tail -1 || true)"
[ -n "$GW_VER" ] || GW_VER="$(ls /home/ted/Jts/ibgateway | head -1)"
if [ ! -f /opt/ibc/gatewaystart.sh ]; then
  mkdir -p /opt/ibc && curl -fsSL "$IBC_URL" -o /tmp/ibc.zip && unzip -q -o /tmp/ibc.zip -d /opt/ibc && chmod +x /opt/ibc/*.sh /opt/ibc/scripts/*.sh
fi
# IBC's config: the template with your login filled in from /etc/ted/ibc.env (TRADING_MODE paper, API on 4002)
# shellcheck disable=SC1091
. /etc/ted/ibc.env
mkdir -p /home/ted/ibc
sed -e "s|__IB_USER__|${IB_USER}|" -e "s|__IB_PASSWORD__|${IB_PASSWORD}|" -e "s|__TRADING_MODE__|${TRADING_MODE:-paper}|" \
    "$(dirname "$0")/ibc-config.ini.template" > /home/ted/ibc/config.ini
chown -R ted:ted /home/ted/ibc /opt/ibc
chmod 600 /home/ted/ibc/config.ini
# the Gateway's own API settings: API on, socket port 4002 for paper, trusted 127.0.0.1 only, read-only API off
mkdir -p /home/ted/Jts
cat > /home/ted/Jts/jts.ini <<EOF
[IBGateway]
ApiOnly=true
LocalServerPort=4002
TrustedIPs=127.0.0.1
[Logon]
Locale=en
UseSSL=true
EOF
chown ted:ted /home/ted/Jts/jts.ini

say "4. services"
install -m 644 "$(dirname "$0")/ibgateway.service" /etc/systemd/system/ibgateway.service
install -m 644 "$(dirname "$0")/ted.service" /etc/systemd/system/ted.service
sed -i "s|__GW_VER__|${GW_VER}|" /etc/systemd/system/ibgateway.service
systemctl daemon-reload
systemctl enable ibgateway.service ted.service >/dev/null
systemctl restart ibgateway.service
sleep 5
systemctl restart ted.service

say "5. firewall: SSH only (the desk is reached over an SSH tunnel)"
ufw --force reset >/dev/null
ufw default deny incoming >/dev/null
ufw default allow outgoing >/dev/null
ufw allow OpenSSH >/dev/null
ufw --force enable >/dev/null

say "done"
echo "IB Gateway:  systemctl status ibgateway   (log: /home/ted/ibc/logs)"
echo "TED:         systemctl status ted         (log: journalctl -u ted -f)"
echo "From your laptop:  ssh -L 8765:127.0.0.1:8765 ted@$(hostname -f 2>/dev/null || hostname)   then open http://127.0.0.1:8765"
echo "IBKR second factor: the first Gateway login after every restart needs your tap in the IBKR Mobile app."
