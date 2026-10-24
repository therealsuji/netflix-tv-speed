#!/bin/bash
# Keeps the patched Netflix clone installed on the MiTV.
# Reinstalls from the saved APKs if the package has disappeared.
set -u

ADB=/opt/homebrew/bin/adb
TV_IP=192.168.1.18
TV=$TV_IP:5555
PKG=${PKG_OVERRIDE:-com.suji.n1fspeed}
APKDIR=/Users/sujithawijewantha/.t3/scratch/2026-10-23-will-you-hack-into-my-7e6f305e/works/2026-10-24-headless-1x
LOG=/Users/sujithawijewantha/.t3/scratch/2026-10-23-will-you-hack-into-my-7e6f305e/watchdog.log

say() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >>"$LOG"; }

# TV asleep or off: nothing to do, do not spam
if ! ping -c 1 -W 2 "$TV_IP" >/dev/null 2>&1; then
    exit 0
fi

"$ADB" connect "$TV" >/dev/null 2>&1
sleep 1

if ! "$ADB" -s "$TV" shell true >/dev/null 2>&1; then
    say "adb not reachable"
    exit 0
fi

if "$ADB" -s "$TV" shell pm list packages 2>/dev/null | grep -q "$PKG"; then
    exit 0
fi

say "package missing, reinstalling"
"$ADB" -s "$TV" install-multiple --no-incremental "$APKDIR/final-base.apk" "$APKDIR/final-split.apk" >>"$LOG" 2>&1
say "reinstall exit=$?"
