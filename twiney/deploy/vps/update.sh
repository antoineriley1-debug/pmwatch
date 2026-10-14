#!/usr/bin/env bash
# A new TED build on the VPS: drop the new TWINEY.zip at /opt/ted/TWINEY.zip (or let it pull the branch), then
#     sudo bash update.sh
# Your data folder (/var/lib/ted: config.json, plays, layouts, recordings) is never touched.
set -euo pipefail
TED_DIR=/opt/ted
TED_HOME=/var/lib/ted
TED_GIT="${TED_GIT:-}"
TED_BRANCH="${TED_BRANCH:-claude/twiney-v1-complete-gdn0ws}"
if [ -n "$TED_GIT" ] && [ -d "$TED_DIR/src/.git" ]; then
  git -C "$TED_DIR/src" fetch -q origin "$TED_BRANCH" && git -C "$TED_DIR/src" reset -q --hard "origin/$TED_BRANCH"
elif [ -f "$TED_DIR/TWINEY.zip" ]; then
  rm -rf "$TED_DIR/unpack.new" && mkdir -p "$TED_DIR/unpack.new" && unzip -q -o "$TED_DIR/TWINEY.zip" -d "$TED_DIR/unpack.new"
  rm -f "$TED_DIR/unpack.new/TWINEY/twiney/config.json"      # the private config lives in the data folder only
  rm -rf "$TED_DIR/unpack" && mv "$TED_DIR/unpack.new" "$TED_DIR/unpack"
  ln -sfn "$TED_DIR/unpack/TWINEY/twiney" "$TED_DIR/app"
else
  echo "nothing to update from: no TWINEY.zip and no git checkout"; exit 1
fi
chown -R ted:ted "$TED_DIR"
systemctl restart ted
sleep 3
systemctl --no-pager status ted | head -5
grep -o 'name="build" content="[^"]*"' "$TED_DIR/app/twiney/static/dashboard.html" || true
chown -R ted:ted "$TED_HOME" 2>/dev/null || true   # the data folder (config.json with your keys) stays the service user's
