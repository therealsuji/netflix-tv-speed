# Plan A (deferred): real control inside Netflix's own player UI

Goal: a speed row that lives in Netflix's menu and participates in their focus graph,
not an Android overlay.

## What is proven
- TV UI is native NRDP/gibbon drawing into SurfaceViews; no Android view tree
  (uiautomator sees only FrameLayouts). No JS/HTML bundle in assets.
- libgibbon.so embeds V8 + UI framework: nrdp.gibbon.eval, makeWidget,
  scene.overlay/addOverlay, loadScript(url) (fetch -> eval), runConsole/_runConsole,
  _replaceUrls, _prepareNetworkRequest.
- Java->engine bridge nativeCommandEvent(String) exists but is inert for UI:
  direct reflection call with "/key down"/"/reload" produced zero visual change
  (verified by screenshot diff), while real key events do change the screen.
- The UI script is fetched at runtime from the vendor's bootstrap service over TLS
  with configured trust stores (assume pinning). It is not baked into a V8 snapshot,
  so the script source is a real seam.

## Route (from second-opinion review + our evidence)
1. Get the engine to evaluate our script. Two candidates:
   a. find any host-facing eval path (JNI export / bridge) - none found so far;
   b. serve the UI script ourselves: disable peer verification in the native TLS
      layer (binary patch of the verify callback in libgibbon/libnetflix), run a
      local proxy, capture the bootstrap/UI bundle, append our widget code.
2. Build the control with nrdp.gibbon.makeWidget + scene.overlay, styled like their
   menu row, and call the same speed path that already works (JPlayer2.Play(speed)).
3. Integrate with their focus/navigation model - THIS IS THE REAL RISK. A widget is
   easy; a focusable menu row the remote can traverse needs their scene node model.
4. Re-verify: 2x on the media clock, plus the row visible in their menu.

## Effort / risk
Days, not hours. TLS interception is the gate; focus integration is the unknown.
Breaks on every Netflix UI bundle update. Snapshot the TV before starting.

## Entry point when we resume
- Confirm where the UI bundle lives after fetch (disk cache vs memory).
- Find the TLS verify callback symbol/call site in libgibbon.so (look for
  SSL_CTX_set_verify / verify_callback usage; strings included OpenSSL).
- Test: patch verify to always-accept, point a proxy at it, confirm we can serve a
  byte-identical copy of their script and the UI still boots. That is the go/no-go.


## Update: 2026-10-25 session

Ruled out tonight, with evidence:

1. **Not a downloaded-then-cached script we can edit.** The APK has no JS bundle;
   `libgibbon.so` carries the framework as 82 gzip modules (~3 MB) plus a 1.44 MB
   webpack bundle and a 530 KB gibbon shim, but no app screen code and no UI strings.
   UI text lives in `resources.arsc` only.
2. **No Java-side network bridge for scripts.** Hooked
   `CronetHttpURLConnection.<init>`: exactly one URL at boot
   (`.../preapp/tiles`). gibbon uses native Cronet (`libcronet.so`) and its own OpenSSL,
   so script fetches never touch Java.
3. **Console is not reachable from Java.** `nativeCommandEvent` (and the public
   `M1cMYXGO` wrapper) executed with guard=true and produced zero visual change;
   `/key down`, `/reload` do nothing. Console commands are registered inside the engine
   (`runConsole`, `addConsoleCommand` typings exist), not exposed to the host.
4. **System HTTP proxy is useless.** gibbon ignores it (verified: no hits on a listener
   while the app booted), and the TV could not reach the Mac anyway (different subnet,
   no return route).
5. **Offline behaviour proves nothing.** The app refuses UI without connectivity
   ("device no internet"), so it cannot be used to distinguish local vs fetched screens.

What is left: native analysis of `libgibbon.so` (63 MB, stripped, V8 embedded).
Targets, in order of value:

- Find where `nrdp.gibbon.loadScript` / `load` resolve their URL and whether a local
  `file:///` path is honoured (`file:///` handling exists in the JS: prefixes are
  stripped and passed to a file loader). If a host-provided path can be influenced from
  Java (startup params, `boot_request`), that is the injection point.
- Find the UI screen code: if it is native C++, locate the player-menu construction and
  add a row there.
- Locate the V8 startup snapshot / embedded script cache to confirm whether any app JS
  is compiled in.

Tooling: Ghidra or IDA on `libgibbon.so` (ARM32), plus `capstone` for scripted triage.
This is a day-scale investigation, not a patch.

## API surface (from the embedded TypeScript typings, 1.59 MB blob at 0x3c6f636)

Confirmed signatures:

```ts
// evaluates a fetched JavaScript file in the current runtime
export function loadScript(request?: ResourceRequestOptions | string,
                           callback?: (result: ResourceLoadResult) => void): int32;

// arbitrary load, callback gets the bytes
export function load(request?: ResourceRequestOptions | string, callback?): int32;

// register/invoke engine console commands
addConsoleCommand(name: string, description: string | undefined,
                  callback: (command: ConsoleCommand) => void, completions?): void;
runConsole(command: string, options?: RunConsoleOptions): void;

// widget creation used by the UI itself
export function makeWidget(obj?: Record<string, unknown>): Widget;
```

All of these are JS-side (`@bind` = provided *to* JavaScript). No host/Java-facing eval
entry exists in the typings, which matches the experiment: `nativeCommandEvent` cannot
reach the script runtime.

So the injection point has to be created, not found:

- either get a script URL of our choosing into `loadScript` (the request accepts a string
  or a ResourceRequestOptions object, and `file:///` prefixes are stripped and treated as
  local paths elsewhere in the platform JS), or
- patch the native implementation of `loadScript` to eval a buffer we supply.

Next session should start with Ghidra on `libgibbon.so`:
- The ELF has no useful section headers; reconstruct memory blocks from PT_LOAD.
- Bridge names live in a table around file offset 0x28254c (226 `nfwbr_host_*` strings
  within ±40 KB). The table uses non-absolute references, so xref work is required.
- JS payloads for reference: 82 gzip modules (~3 MB inflated), a 1.44 MB webpack bundle
  at 0x3b088a3, the 530 KB gibbon shim at 0x2869fa8, typings at 0x3c6f636.
