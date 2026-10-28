#!/bin/bash
# Install the reviewed bounded restore service; installation does not disable NTP.
set -euo pipefail
BASE=/Library/Application\ Support/openstack-k8s-clock-guard
STATE=/var/db/openstack-k8s-clock-guard
REQUEST=/var/run/openstack-k8s-clock-guard
PLIST=/Library/LaunchDaemons/dev.openstack-k8s.clock-guard.plist
[[ $(id -u) = 0 ]] || { echo 'Administrator required'; exit 1; }
if [[ ${1:-} = uninstall ]]; then
  /usr/bin/python3 -I -S "$BASE/service.py" --restore
  /bin/launchctl bootout system "$PLIST"
  /bin/rm "$PLIST" "$BASE/service.py"
  echo 'Restored original setting and removed service; audit state retained.'
  exit 0
fi
[[ ${1:-} = install && ${2:-} =~ ^[0-9]+$ && $2 -gt 0 ]] || exit 2
OWNER_UID=$2
SOURCE="$(cd "$(dirname "$0")/.." && pwd)/evaluation/fresh_clock_guard.py"
for path in "$BASE" "$STATE" "$REQUEST" "$PLIST"; do
  [[ ! -L "$path" ]] || { echo "Refusing symlink: $path"; exit 1; }
done
[[ ! -e "$PLIST" ]] || { echo 'Existing service requires explicit reconciliation'; exit 1; }
/usr/bin/install -d -o root -g wheel -m 755 "$BASE" "$STATE"
/usr/bin/install -d -o "$OWNER_UID" -g wheel -m 700 "$REQUEST"
/usr/bin/install -o root -g wheel -m 644 "$SOURCE" "$BASE/service.py"
/bin/cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>dev.openstack-k8s.clock-guard</string>
<key>ProgramArguments</key><array><string>/usr/bin/python3</string><string>-I</string><string>-S</string><string>$BASE/service.py</string><string>--serve</string><string>$OWNER_UID</string></array>
<key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
<key>ThrottleInterval</key><integer>5</integer>
<key>StandardOutPath</key><string>$STATE/service.log</string>
<key>StandardErrorPath</key><string>$STATE/service-error.log</string>
</dict></plist>
EOF
/usr/sbin/chown root:wheel "$PLIST"
/bin/chmod 644 "$PLIST"
/usr/bin/plutil -lint "$PLIST"
/usr/sbin/systemsetup -getusingnetworktime > "$STATE/preinstall-network-time.txt"
/usr/sbin/systemsetup -getnetworktimeserver >> "$STATE/preinstall-network-time.txt"
/bin/launchctl bootstrap system "$PLIST"
/bin/launchctl print system/dev.openstack-k8s.clock-guard
