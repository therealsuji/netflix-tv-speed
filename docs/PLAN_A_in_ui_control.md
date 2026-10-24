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
