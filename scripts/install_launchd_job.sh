#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
JOB_NAME="com.romanomasiello.yieldcurves.sync"
PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$PLIST_DIR/$JOB_NAME.plist"
LOG_DIR="$ROOT/logs"
RUN_SCRIPT="$ROOT/scripts/run_sync.sh"
LAUNCHD_COMMAND="cd \"$ROOT\" && \"$RUN_SCRIPT\" >> \"$LOG_DIR/launchd.stdout.log\" 2>> \"$LOG_DIR/launchd.stderr.log\""
LAUNCHD_COMMAND_XML="${LAUNCHD_COMMAND//&/&amp;}"
LAUNCHD_COMMAND_XML="${LAUNCHD_COMMAND_XML//>/&gt;}"
LAUNCHD_COMMAND_XML="${LAUNCHD_COMMAND_XML//</&lt;}"

mkdir -p "$PLIST_DIR" "$LOG_DIR"

cat >"$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$JOB_NAME</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>-lc</string>
    <string>$LAUNCHD_COMMAND_XML</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>19</integer>
    <key>Minute</key>
    <integer>30</integer>
  </dict>
</dict>
</plist>
PLIST

chmod +x "$RUN_SCRIPT"
launchctl bootout "gui/$(id -u)" "$PLIST_PATH" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"
launchctl kickstart -k "gui/$(id -u)/$JOB_NAME"

echo "Installed $JOB_NAME"
echo "Plist: $PLIST_PATH"
echo "Logs:  $LOG_DIR"
