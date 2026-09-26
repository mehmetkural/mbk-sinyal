#!/bin/bash
# Zamanlayıcıyı durdurur ve kaldırır (dosyalar yerinde kalır).
PLIST="$HOME/Library/LaunchAgents/com.mbk.sinyal.plist"
launchctl unload "$PLIST" 2>/dev/null || true
rm -f "$PLIST"
echo "MBK Sinyal zamanlayıcısı kaldırıldı."
