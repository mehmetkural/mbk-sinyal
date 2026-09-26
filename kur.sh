#!/bin/bash
# MBK Sinyal tarayıcısını macOS'ta her 15 dakikada bir (mum kapanışından 1 dk sonra) çalışacak şekilde kurar.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
PY="$(command -v python3)"
PLIST="$HOME/Library/LaunchAgents/com.mbk.sinyal.plist"
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.mbk.sinyal</string>
  <key>ProgramArguments</key><array><string>$PY</string><string>$DIR/mbk_scanner.py</string></array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>StartCalendarInterval</key><array>
    <dict><key>Minute</key><integer>1</integer></dict>
    <dict><key>Minute</key><integer>16</integer></dict>
    <dict><key>Minute</key><integer>31</integer></dict>
    <dict><key>Minute</key><integer>46</integer></dict>
  </array>
  <key>StandardOutPath</key><string>$DIR/launchd.out.log</string>
  <key>StandardErrorPath</key><string>$DIR/launchd.err.log</string>
</dict></plist>
EOF
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "Kuruldu: $PLIST"
"$PY" "$DIR/mbk_scanner.py" --test
