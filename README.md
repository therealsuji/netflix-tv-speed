# Netflix playback speed on an Android TV

Adds playback speed (1x / 1.25x / 1.5x / 2x) to the Netflix Android TV app on a
Xiaomi MiTV (Android 11, Amlogic), controlled from a phone on the same Wi-Fi.

The modified app is a **separate package** (`com.suji.n1fspeed`), signed with our own
key, installed alongside the stock Netflix app. The stock app and the Netflix account
are untouched. Default speed is 1x; the app behaves stock until you change it.

Control page: `http://<tv-ip>:8099`

## What was done

- Repackaged the Netflix TV APK under a new package name with a byte-faithful zip
  rebuild, a rewritten binary manifest, and our own signature.
- Fixed two boot blockers (see FINDINGS.md):
  - package-visibility grant for `com.netflix.ninja`;
  - do *not* retarget the native `getPackageInfo` string in `libnetflix.so`.
- Forced the player's speed ceiling to 2.0 and made `PlaySpeed` read a controller value.
- Switched the audio track to plain PCM (no `FLAG_HW_AV_SYNC`, no tunnel session) and
  the video to non-tunneled, so Android can actually time-stretch audio.
- Added a headless LAN control page inside the app.
- Built a merged single-APK variant for laptop-free reinstall.

Verified by measuring the media clock against wall time: 1.25x → 1.252, 2.0x → 1.998/2.003.

## Build

```
python3 final.py
```

Environment flags used for the working build:

```
PROBE=1 PROBE2=1 NO_GUARD=1 KEEP_PKGSTR=1 QUERY_GRANT=1 PCM_TRACK=1 NOTUNNEL=1
```

Optional: `MERGE=1` (standalone APK), `ICON=1` (custom icon), `LABEL="Netflix 2x"`.

`final.py` expects to run from a directory containing the original `base.apk` and the
native split, plus `uber.jar`, `tv.keystore`, `smali252.jar` and the smali dependency
jars in `cp/`. See docs/FINDINGS.md for the full toolchain list.

## Requirements on the TV

PCM audio output is required for time-stretch (offload/DD+ silently ignores speed):

```
adb shell settings put global external_surround_sound_enabled 0
adb shell settings put global digital_audio_format 0
```

## Status / limits

- No control inside Netflix's own player UI. That requires script execution in their
  native engine; both routes were investigated and closed. See
  docs/PLAN_A_in_ui_control.md.
- The TV's package scanner flags the clone as a "potential threat" at install time and
  once removed it. Backups of the APKs are kept on the TV in `/sdcard/Download/`, and
  `netflix2x.apk` (single file) can be installed with the Downloader app.
