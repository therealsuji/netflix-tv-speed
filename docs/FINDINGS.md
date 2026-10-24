# Findings

Everything below was observed on the device or read out of the APK/libgibbon. Inferences
are marked.

## Target

- TV: Xiaomi `MiTV-AFKR0`, Android 11, Amlogic "awesome2", 1920x1080 panel.
- App: Netflix Android TV 13.2.1 build 27207 (`com.netflix.ninja`), installed as an
  updated system app from `/product/app/Netflix` (base 9.1.0, signature recorded).
- Stock app stays installed; our clone is `com.suji.n1fspeed` signed with `tv.keystore`
  (alias `tv`, pass `netf1ix`).

## Repack method

1. `apktool d` the base APK, patch smali, reassemble dex with `smali` (2.5.2).
2. Rewrite the binary `AndroidManifest.xml` in place with a hand-written AXML rewriter:
   rename package, permissions, provider authorities, `DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION`,
   turn relative component names (`.MainActivity`) into absolute ones, keep class names
   pointing at `com.netflix.ninja.*`.
3. Rebuild the zip byte-faithfully: original entries, original compression, only the
   dex + manifest replaced, `META-INF` cert files stripped.
4. Rebuild the native split the same way (its `libnetflix.so` may need a string patch,
   but see below — the working build does not patch it).
5. Sign base + split with `uber.jar` (apksigner), install with
   `adb install-multiple --no-incremental`.

Tooling: `~/Library/Android/sdk/build-tools/36.0.0/{d8,aapt2,zipalign,apksigner,dexdump}`,
`smali252.jar` + `cp/*.jar` (dexlib2/guava/util), `uber.jar`, JDK 17.

## The two boot blockers (this is the important part)

The clone installed and started Java but `nativeGibbonStartup` returned in ~40 ms with no
engine threads (`GIBBON_SURFACE_*`, `NRD_AM_*`, `DRMSYSTEM0` all absent) and the splash
never went away. Instrumented probes showed the timeline: `service.onCreate` →
`nativeGibbonPrepare` → DRM-ready handler → `gibbonStartup` → `nativeGibbonStartup` → return.

1. **Package visibility.** `libnetflix.so` calls
   `PackageManager.getPackageInfo("com.netflix.ninja", GET_SIGNATURES)` during boot.
   A non-system app on Android 11 can only see packages it declares in `<queries>`.
   The manifest only queried `com.google.android.katniss`, `com.netflix.partner.ncm`,
   `com.google.android.apps.mediashell`, `com.netflix.partner.contentprovider`.
   The lookup threw `NameNotFoundException`, the exception was cleared, and the native
   code aborted with `JNI DETECTED ERROR: java_object == null / GetObjectClass`.
   **Fix:** repoint an unused `<queries>` entry (`com.google.android.katniss`) at
   `com.netflix.ninja` (`QUERY_GRANT=1`).
2. **Do not retarget that package string.** An earlier workaround rewrote
   `com.netflix.ninja` → `com.suji.n1fspeed` inside `libnetflix.so`. That makes the call
   succeed but the engine then sees our signature and bails silently in ~40 ms.
   **Fix:** leave the string alone (`KEEP_PKGSTR=1`) and rely on blocker 1.

Confirmed engine threads once both were done. `screencap` then returns 0 bytes because
the engine's surface is `isSecure=true`.

## Playback speed

Measured with a probe on `MediaDecoderBase$Clock.updateUs(long)`, comparing media time to
`SystemClock.elapsedRealtime()` once per second.

Gates found, in the order they bit:

1. **App clamp.** `JPlayer2.ConfigVideo` stores `mMaxSpeed = min(requested, 2.0)` and the
   device config reports 1.0, so speed changes were rejected with
   `Unsupported PlaySpeed. speedToSet: 2.0, dpiMaxSpeed: 1.0, deviceMaxSpeed: 1.0`.
   Patch: force the stored `mMaxSpeed` to 2.0.
2. **Audio routing.** `MediaDecoder2Audio.createAttrAudioTrack` opens the track with
   `FLAG_HW_AV_SYNC` (0x10) and the tunnel `sidebandSessionId`, which routes it to
   offload/direct output. `setPlaybackParams(2.0)` is silently ignored there; with PCM it
   throws `IllegalArgumentException: arguments out of range`.
   Patch: drop the flag and pass session id 0.
3. **PCM decode.** With surround passthrough enabled, audio goes through
   `MediaDecoder2AudioPassthru` (compressed DD+), which cannot be time-stretched at all.
   TV must output PCM (`external_surround_sound_enabled=0`, `digital_audio_format=0`).
4. **Tunneled video.** Tunnel mode couples video to the tunneled audio session we just
   removed, so the picture froze while audio ran at 2x. Patch: force
   `mUseTunneledMode = false` (`NOTUNNEL=1`).
5. **The speed value itself.** `PlaySpeed.<init>(float)` and `reset()` are patched to read
   `com.suji.Speed.CURRENT`, and `JPlayer2.Play(float)` also writes `Speed.player` so the
   LAN page can push a change into the live player.

Result: clock 1.998–2.020 at 2x, 1.243–1.253 at 1.25x, 1.000 at 1x.

## Control surface

`src/com/suji/Web.java` runs a tiny HTTP server on port 8099 inside the app process:

- `GET /` → page with 1x / 1.25x / 1.5x / 2x
- `GET /speed?v=1.5` → sets `Speed.CURRENT`, persists it, calls `JPlayer2.Play(speed)`
- `GET /state` → `{"speed":2.0,"player":true}`

Nothing is drawn on the TV and no remote key is intercepted (all key hooks removed).

## Why there is no control inside Netflix's own UI

The UI is not Android views: uiautomator shows only `FrameLayout` containers
(`gibbonMain`, `playerContainer`); everything is drawn by the native NRDP/gibbon engine
into SurfaceViews. The APK ships no JS/HTML UI bundle (`assets/` holds only
`PublicSuffixDatabase`, dexopt profiles, `assets/nrd/...`).

Inside `libgibbon.so` (63 MB, V8 + UI framework) these exist as symbol strings:
`nrdp.gibbon.eval`, `makeWidget`, `scene.overlay/addOverlay`, `loadScript(url)`
(fetch → `eval`), `runConsole`, `_replaceUrls`, `_prepareNetworkRequest`.

Attempts to reach them from Java:

- `NetflixService.nativeCommandEvent(String)` (wrapped by `M1cMYXGO(String)` behind an
  `AtomicBoolean`). Called the private native method directly by reflection with
  `/key down` and `/reload`; guard read as `true`, logs confirm the call. Screenshots
  before/after were pixel-identical while a real key event did change the screen.
  **Conclusion: that bridge does not reach the UI script.**
- The UI script URL comes from the vendor's appboot response over TLS with trust stores
  in config (pinning assumed). Turning verification off (`/command ssl-peer-verification
  false`) is only reachable from inside the engine.

Full plan for the in-UI version, including the TLS-interception route and the focus-graph
risk, is in `docs/PLAN_A_in_ui_control.md`.

## The TV deletes the clone (important operational note)

`system_server` logs `PackageManager: Potential threat com.suji.n1fspeed` during install
and once removed the package ~20 s later (`ACTION_PACKAGE_FULLY_REMOVED`). This is the
TV's own package-integrity hook, not Netflix. It has not recurred since (many launches,
hours of use), so the trigger looks install-time rather than periodic.

Mitigations applied:

- `settings put global package_verifier_enable 0` and `verifier_verify_adb_installs 0`.
- APKs copied to `/sdcard/Download/netflix2x-{base,split}.apk`.
- `scripts/watchdog.sh` reinstalls over ADB if the package is missing (load as a launchd
  agent if a host is always on; the user does not want a laptop dependency).
- `MERGE=1` produces `netflix2x.apk`, one standalone signed APK with the native libs
  folded in and `requiredSplitTypes` blanked, installable from the TV with the
  Downloader app.

Known wrinkles:

- The launcher shows two identical "Netflix" tiles (stock first, ours at the end). Custom
  icons were built (`ICON=1`) but reverted; they can be re-applied.
- A `-14` "device is not optimized for Netflix" dialog appears on a cold app start and
  blocks boot until dismissed.

## Open questions

- Does the merged single APK install and run standalone? Built and signature-verified,
  but not install-tested because replacing the split install loses the clone's data.
- Can the integrity hook be neutralised without root? Not found; `mitv.service` and
  friends are system packages.
- Does the clone survive a TV reboot? Not yet verified.
