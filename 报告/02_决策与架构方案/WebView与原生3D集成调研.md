# Single-window desktop app: web UI + native 3D viewport

**Research report — evidence, versions, licenses.** Compiled 2026-10-16 (versions verified against registries on that date).

**Target:** macOS (Apple Silicon) first, Windows second. MuJoCo robot-arm workbench: Python data/logic layer, React/Tailwind 2D UI in a native webview, and a native C++ **Filament** 3D view that must live in the **same OS window** as the webview ("sibling view" layout, not one rendered into the other).

**Method note.** Version/license facts were read from npm/crates.io/PyPI registry APIs and official docs. Where possible I read **actual source code** (the `wry` 0.57.0 crate tarball, the `pywebview` 6.2.1 sdist) rather than trusting prose. Uncertain items are explicitly marked **[UNVERIFIED]**.

---

## 1. Desktop webview shells

### 1.1 Wails (Go) — v2 stable, v3 beta

| | Wails **v2** | Wails **v3** |
|---|---|---|
| Latest version | **v2.16.0** (published 2026-09-14) | **v3.0.0-beta.30** (2026-10-15) |
| Status | **Stable**, "continues to receive fixes" | **Beta**, "stable desktop API… test thoroughly before deployment" |
| License | **MIT** | **MIT** |
| Repo | github.com/wailsapp/wails — **36,573★**, created 2018-12-15, 348 open issues | same repo (monorepo, `v3/` dir) |
| Language | Go backend + web frontend | Go backend + web frontend |
| Engine | macOS: **WKWebView**; Windows: **WebView2**; Linux: WebKitGTK | macOS: **WKWebView**; Windows: **WebView2**; Linux: default **GTK4 + WebKitGTK 6.0** (Ubuntu 24.04+/Debian 13+/Fedora 40+), legacy `-tags gtk3` → WebKit2GTK 4.1 until v3.1. **WebKit2GTK 4.0 unsupported.** |
| Requirements | — | Go **1.25+**, Node/npm; Xcode CLT (macOS); WebView2 (Windows); gcc + GTK/WebKit dev (Linux) |
| Bundle size | Official claim "**~15 MB**" (vs Electron ~150 MB) | Official FAQ: "single binary that typically weighs in around **10 MB**" |
| Multi-window | No (single main window) | Yes, native (`app.Window.New()`) |
| System tray / updater | Limited | Yes; built-in self-updater with GitHub Releases / keygen.sh / Sparkle AppCast providers + signature verification |
| **Native 3D child view** | See §4.1 — **no public window-handle API** | See §4.1 — **no public window-handle API**; codebase explicitly "hackable", extension = WEP/fork |

**Notable v3 architectural facts (relevant to §2 and §4):**
- Webview transparency on macOS **requires the private-API build tag `private_mac_apis`**. Wails' own docs state: *"Internally, Wails sets WebKit's private `drawsBackground` key. A transparent HTML or CSS background alone cannot make an opaque native WKWebView transparent."* Without the tag, private-only operations are **no-ops**.
- v3 Windows offers `WindowsWindow.WebView2CompositionHosting`, which switches from the default HWND-hosted WebView2 controller to **composition controller hosting with DirectComposition** and "forwards input explicitly." Wails warns this "may have rendering, input, focus, or WebView2 Runtime compatibility issues." **This materially changes the native-child-view story on Windows** — see §4.1.
- v3 has purpose-built **"Notch Windows"** (transparent webview inside a shaped panel) — i.e. shaped windows exist, but as a framework feature, not a generic "carve a hole for my renderer" API.

### 1.2 Tauri v2 (Rust)

- **Stable: v2.12.4** (2026-10-14). **v3.0.0-alpha.5** exists (2026-10-14) — alpha, not for production.
- License: **Apache-2.0 OR MIT** (dual). Repo **111,941★**, created 2019-07-13.
- Engine: **`wry` 0.57.0** + **`tao` 0.37.1** (`wry` and `tao` are both `Apache-2.0 OR MIT`). Per platform: macOS → **WKWebView** (via `objc2-web-kit` 0.3.2); Windows → **WebView2** (`webview2-com` 0.39, `windows` 0.62); Linux → **WebKitGTK 4.1** (`webkit2gtk` 2.0.2) + GTK 3 (`gtk` 0.18).
- Rust MSRV: **1.90** for tauri 2.12.4; **1.95** for 3.x.
- Platform support: macOS (Intel + Apple Silicon), Windows, Linux, **plus iOS and Android** (Tauri v2 is cross-platform including mobile — a differentiator vs Wails).
- Bundle size: Tauri's official position is "by default very small binaries" with a documented `[profile.release]` recipe (`codegen-units=1`, `lto=true`, `opt-level="s"`, `panic="abort"`, `strip=true`) and a `build.removeUnusedCommands` option. Tauri does **not** publish a headline number.
- **The decisive capability for us:** Tauri v2 exposes a documented **multiwebview API** and a documented **native-handle escape hatch** — both covered in §2 and §4.
- WebView2 runtime: Tauri's config exposes `WebviewInstallMode` with a download-bootstrapper default (preinstalled on Windows 11 and most Windows 10).

### 1.3 Electron

- **v44.8.0** (2026-10-16), MIT. Bundles **Chromium + Node.js**.
- Bundle size: the independent Elanis benchmark measures an **empty** Electron app at **≈236 MB (Windows x64)**, **≈376 MB (macOS x64)**, **≈240 MB (Linux x64)**. (A newer revision of that table is summarised by search as Windows x64 ≈385 MB — the number is methodology/version dependent; treat "**~230–390 MB**" as the honest range.)
- **It is the only option here with an officially documented, multi-view, sibling-native-view API**: `BaseWindow` + `WebContentsView` + `contentView.addChildView(view)` + `view.setBounds({x,y,width,height})`. Electron's own docs open with: *"`BaseWindow` provides a flexible way to compose multiple web views in a single window."* It also documents `transparent: true` windows and `view.setBackgroundColor` for transparent view backgrounds.
- **Caveat:** Electron's `addChildView` composes **Electron `View`s** (including web views). Placing an **external** C++/Metal/D3D surface requires the native window handle, which Electron does not expose as a first-class API — **[UNVERIFIED]** whether a supported path exists; most projects use a native Node addon. Electron's own multi-view story solves "web + web", not "web + foreign native renderer".

### 1.4 pywebview (Python)

- **v6.2.1** (2026-04-15). License **BSD 3-Clause** (Copyright 2014–2017 Roman Sirokov). `requires_python >=3.8`.
- Engine per platform (per official docs):

| Platform | Code | Renderer | Provider |
|---|---|---|---|
| macOS | — | WebKit | **WKWebView** (bundled with OS) |
| Windows | `edgechromium` | **Chromium** | **WebView2** via .NET (Net Framework > 4.6.2 + Edge Runtime) |
| Windows | `cef` / `mshtml` | CEF (Chrome 66) / MSHTML (deprecated) | — |
| Linux | `gtk` | WebKit | WebKit2 (min > 2.2) |
| Linux | `qt` | QtWebEngine / QtWebKit | — |

- Dependencies (from PyPI metadata): `pyobjc-core`, `pyobjc-framework-Cocoa`, `-Quartz`, `-WebKit`, `-security`, `-UniformTypeIdentifiers` (all ≥9.0) on macOS; `pythonnet` on Windows; `proxy_tools`, `bottle`, `typing_extensions` everywhere.
- Bundle size: **dominated by the Python interpreter**; pywebview's own overhead is small (it is a pure-Python wrapper over OS webviews). Total shipped size ≈ PyInstaller/Nuitka output. **[UNVERIFIED — depends entirely on your packaging choice and MuJoCo's wheel size.]**
- **Native handle access is excellent** — see §4.4.

### 1.5 Neutralinojs

- CLI **@neutralinojs/neu v11.8.0** (2026-10-06), **MIT**. Engine: **OS webview** (WebKitGTK on Linux, WebView2 on Windows, WKWebView on macOS) driven by a small native binary; JS backend (`neutralino.*` API) instead of Go/Rust.
- Bundle size: the **smallest measured** — Elanis benchmark: **≈2 MB (Windows x64)**, **≈1 MB (macOS x64)**, **≈1 MB (Linux x64)**.
- **Blocking limitation for us:** Neutralino's backend is JavaScript talking to a bundled native helper. There is **no documented mechanism to attach a foreign native GL/Metal child view to the app window**. **[UNVERIFIED-negative: I found no evidence it can be done; treat as not viable.]**

### 1.6 Bare system WebView via C++ (`webview/webview`)

- **github.com/webview/webview** — **MIT**, **14,274★**, latest tag **0.12.0**, C++11 (C++14 on Windows).
- Backends: **Cocoa/WebKit** (macOS), **Win32/WebView2** (Windows), **GTK/WebKitGTK** (Linux, 6.0 / 4.1 / 4.0 selectable via `WEBVIEW_WEBKITGTK_API`).
- Windows: ships a built-in WebView2 loader implementation, so **`WebView2Loader.dll` need not be distributed**; `WEBVIEW_MSWEBVIEW2_BUILTIN_IMPL` is on by default.
- Bundle size: essentially **your own binary** + the OS webview. Smallest possible footprint, but you write window/layout/menus/updater yourself.
- **For us this is the most interesting "no new language" option**: we are already a C++ host. It gives 100% control of the window's view hierarchy, so the Filament surface and the webview are peer child views by construction. Cost: you re-implement everything a framework gives you (asset serving, IPC, packaging, updater, single-instance, file dialogs) — and there is **no official installer/packaging story**.

### 1.7 Comparison table

| | Engine | Empty-app size (measured, Elanis) | Ships Python? | Can host native GPU child view in same window | Platforms | License | Maturity |
|---|---|---|---|---|---|---|---|
| **Wails v2** | WKWebView / WebView2 / WebKitGTK | ≈**8 MB** Win, ≈**7 MB** macOS, ≈**6 MB** Linux | via sidecar (manual) | **No public API** (§4.1) | macOS, Windows, Linux | MIT | **Stable** since 2022; 36.6k★ |
| **Wails v3** | + GTK4/WebKitGTK 6.0 on Linux | ~10–15 MB (claim) | via sidecar (manual) | **No public API**; needs fork/WEP (§4.1) | + iOS/Android (experimental) | MIT | **Beta** (beta.30, near-daily releases) |
| **Tauri v2** | wry → WKWebView / WebView2 / WebKitGTK | ≈**1 MB** Win, ≈**3 MB** macOS, ≈**4 MB** Linux | **official sidecar** | **YES — documented** (`with_webview` → NSWindow/HWND) + `unstable` multiwebview for sibling regions (§4.2) | macOS, Windows, Linux, iOS, Android | Apache-2.0 OR MIT | **Stable 2.12.4**; 111.9k★ |
| **Electron** | bundled Chromium + Node | ≈**236 MB** Win, ≈**376 MB** macOS, ≈**240 MB** Linux | via child process | Composes Electron `View`s officially; foreign native surface **[UNVERIFIED]** | macOS, Windows, Linux | MIT | Very mature; 44.8.0 |
| **pywebview** | WKWebView / WebView2 / WebKitGTK | interpreter-dominated (unverified) | **IS Python** | **YES for macOS & Windows** (`window.native`) (§4.4) | macOS, Windows, Linux (+Android) | BSD-3-Clause | Mature, slower cadence (6.2.1, Apr 2026) |
| **Neutralinojs** | OS webview | ≈**2 MB** Win, ≈**1 MB** macOS, ≈**1 MB** Linux | — | **No** | macOS, Windows, Linux | MIT | Mature-ish; JS backend |
| **bare `webview/webview`** | WKWebView / WebView2 / WebKitGTK | your binary only | via embedding | **YES — you own the view tree** | macOS, Windows, Linux | MIT | Stable lib (0.12.0), no app scaffolding |

*Size caveat: the Elanis numbers are for **empty** apps, from a 2023 archive of that benchmark, on GitHub CI. Electron's figure mostly *is* the pinned Chromium build; Tauri/Wails figures exclude the shared OS WebView2 runtime on Windows. Treat them as orders of magnitude, not shipping numbers.*

---

## 2. Transparent / overlaid webview — **the good news**

**The framing matters.** You asked whether a webview can be transparent so a native view shows through a "hole." But your actual layout is a **sibling view**: the native 3D view gets its own rectangle and the webview fills the rest. **In that layout transparency is not required at all.** You need:

- (a) the ability to **size and position** the webview so it does not cover the native rectangle — **available everywhere**; and
- (b) only if you want rounded corners, HUD overlays, or the 3D view to bleed under a translucent toolbar, **transparency** — which is where things get platform-specific.

This is a significant risk reduction: **the hardest part of your plan (transparency) is optional, not load-bearing.**

### 2.1 (a) Transparency, with source-level evidence

I read the `wry` 0.57.0 source tarball (the engine under Tauri v2) to verify what actually happens per platform.

#### macOS — WKWebView

**Supported, but only via a private API.** `wry-0.57.0/src/wkwebview/mod.rs`:

```rust
if attributes.transparent || attributes.background_color.is_some() {
  let no = NSNumber::numberWithBool(false);
  // TODO: Check if this property exists or is used on iOS
  config.setValue_forKey(Some(&no), ns_string!("drawsBackground"));
}
```

and, for runtime changes:

```rust
// Disable the default white background using the same drawsBackground KVC key
// as the `transparent` feature. On the webview instance (vs config) for runtime changes.
// NOTE: Private API — `drawsBackground` is a private KVC key on WKWebView instance.
```

Sources: [docs.rs/wry WebViewBuilder](https://docs.rs/wry/0.57.0/wry/struct.WebViewBuilder.html) — *"macOS: Disables the default white WKWebView background via the `drawsBackground` KVC key (same as the `transparent` feature) and sets `underPageBackgroundColor` (macOS 12+) for overscroll areas."*

Independent corroboration:
- **Tauri gates this behind a Cargo feature**: `WebviewBuilder::transparent()` is documented as *"Available on **crate feature `macos-private-api`** or non-macOS only."*
- **Wails documents the identical private key** and the identical constraint (see §1.1).
- **Apple does not expose `drawsBackground` on `WKWebView`.** The `drawsBackground` property that *is* documented belongs to the **deprecated `WebKit.WebView`** class — confirmed by reading the `objc2-web-kit` 0.3.1 bindings, where `setDrawsBackground` appears under `WebView` (marked *"👎 Deprecated: No longer supported; please adopt WKWebView"*), not under `WKWebView`. The public knob on modern macOS is `WKWebView.underPageBackgroundColor` (macOS 12+, [Apple docs](https://developer.apple.com/documentation/webkit/wkwebview/underpagebackgroundcolor)) — and **wry's own comment concedes it is insufficient**: *"Those alternatives do not make the webview transparent"* (Wails' wording) / `underPageBackgroundColor` only "handles the color visible when scrolling past page bounds" (wry's wording).

**Verdict (macOS):** Transparent WKWebView = **works, via the private KVC key `drawsBackground`**. It is *not* a documented Apple API. Practical consequence: use it if you are distributing outside the Mac App Store (or accept the review risk), and prefer to avoid needing it.

#### Windows — WebView2

**Supported, documented, public API.** `ICoreWebView2Controller2::put_DefaultBackgroundColor` — from Microsoft's own reference:

> "The `A` represents an Alpha value, meaning `DefaultBackgroundColor` can be transparent. In the case of a transparent `DefaultBackgroundColor` WebView will render hosting app content as the background. … Semi-transparent colors are not currently supported by this API and setting `DefaultBackgroundColor` to a semi-transparent color will fail with `E_INVALIDARG`. The only supported alpha values are **0 and 255**."

Microsoft also documents the caveat: *"There is a known issue with background color where setting the color by API can still leave the app with a white flicker before the `DefaultBackgroundColor` takes effect. Setting the color via environment variable solves this issue"* (`WEBVIEW2_DEFAULT_BACKGROUND_COLOR`). Introduced in WebView2 Win32 **1.0.774.44**.

`wry` uses exactly this (`webview2/mod.rs`): `background_color = if transparent { Some((0,0,0,0)) }`, then `opts3.SetDefaultBackgroundColor(COREWEBVIEW2_COLOR { R,G,B, A: if a != 0 { 255 } else { 0 } })`.

**Verdict (Windows):** **Public, documented, supported** — with two caveats: **no semi-transparency** (0 or 255 only), and a possible white flash on load that the env-var route avoids. Wails v2's `windows.Options.WebviewIsTransparent` is the same thing surfaced as an option.

#### Linux — WebKitGTK

**API exists; `wry` does NOT set up the prerequisites.** `webkit_web_view_set_background_color()` (since WebKitGTK **2.8**, verified against API version 4.1 / lib version 2.42.5) takes a `GdkRGBA`, and its docs state the requirement plainly:

> "Note that the **parent window must have a RGBA visual** and **`GtkWidget:app-paintable` property set to `TRUE`** for backgrounds colors to work."

`wry` calls the setter:

```rust
// wry-0.57.0/src/webkitgtk/mod.rs
if attributes.transparent {
  webview.set_background_color(&gtk::gdk::RGBA::new(0., 0., 0., 0.));
}
```

but a source-wide grep of `wry-0.57.0/src/webkitgtk/mod.rs` for `paintable`, `rgba_visual`, `set_visual`, or `is_composited` returns **zero hits**. So wry (and therefore Tauri v2) sets the colour without establishing the RGBA visual / `app-paintable` precondition.

**Verdict (Linux):** Transparency is **not reliably delivered by wry/Tauri v2** — the documented GTK precondition is not satisfied in the source I read. If a C++ host calls `webkit_web_view_set_background_color` **and** sets the RGBA visual + `app-paintable` on the toplevel itself (as the WebKitGTK docs' own code sample does), it should work. **Linux is out of scope for v1 (macOS → Windows), so this is a footnote, not a blocker.**

#### Transparency summary

| Platform | Transparent webview? | Mechanism | Status |
|---|---|---|---|
| macOS WKWebView | ✅ Yes | KVC `drawsBackground = NO` (+ `underPageBackgroundColor` for overscroll) | **Private/undocumented** |
| Windows WebView2 | ✅ Yes | `ICoreWebView2Controller2::DefaultBackgroundColor` A=0 | **Public & documented**; 0-or-255 only |
| Linux WebKitGTK | ⚠️ API yes, framework no | `webkit_web_view_set_background_color` + parent RGBA visual + `app-paintable` | wry omits the prerequisites |
| Electron | ✅ Yes | `transparent: true` window + `view.setBackgroundColor` | Public & documented |

### 2.2 (b) Resizing / positioning to leave a rectangle free

| Framework | Mechanism | Constraint |
|---|---|---|
| **Tauri v2** | `Window::add_child(WebviewBuilder, position, size)` — *"a single window can host any number of webviews, each of them positioned and sized by you"*; `Webview::set_bounds/set_position/set_size`; `WebviewBuilder::auto_resize()` to grow/shrink with the parent | **Requires the `unstable` Cargo feature.** Docs example literally splits one window into two half-width webviews |
| **Wails v2/v3** | Webview fills the window. No webview sub-rectangle API. Window-level only (`Width/Height/X/Y`, `SetSize`, `SetPosition`) | Must do it in native code with the window handle — which isn't public (§4.1) |
| **Electron** | `new BaseWindow()`, `win.contentView.addChildView(view)`, `view.setBounds({x,y,width,height})` | Officially documented, stable |
| **pywebview** | No webview sub-rectangle API; you manipulate `window.native` (NSWindow / WinForms Form) directly | You own the geometry code |

### 2.3 (c) Z-order / hit-testing problems — **the real risk area**

This is where the honest answer is "there are known failure modes and one of them is architectural."

1. **WebView2 + `add_child` deadlock (Windows).** Tauri's own API docs carry a **Known issues** note on *both* `Window::builder` and `Window::add_child` and `WebviewBuilder::new`:
   > "On Windows, this function **deadlocks** when used in a synchronous command or event handlers, see [the Webview2 issue](https://github.com/tauri-apps/wry/issues/583). You should use `async` commands and separate threads when creating windows."
   This is a real, upstream, still-open constraint (wry#583) that dictates your threading design on Windows.

2. **macOS: layer-backed webview vs. non-layer-backed GL view.** WKWebView is layer-backed; `NSOpenGLView` is not (classically). Mixing them produces the classic overlay/compositing artefacts. The robust modern answer is to give the native renderer its **own layer-backed view** — Filament on Metal is exactly that (`CAMetalLayer`). **[UNVERIFIED: I found no first-party documentation stating "CAMetalLayer sibling of WKWebView in one window is supported and artefact-free." This is the single most important thing to spike.]** Note that `wry`'s own macOS child path does the structurally correct thing:

   ```rust
   if is_child {
     ns_view.addSubview(&webview);          // NSView subview of parent content view
   } else {
     let ns_window = ns_view.window().unwrap();
     ...
     parent_view.addSubview(&webview);
   }
   ```
   i.e. **child webviews are `NSView` subviews of the parent window's content view** — meaning a Metal/GL `NSView` added as a *sibling* subview is the structurally symmetric approach.

3. **macOS: real bug report — transparency lost after DMG build.** Search surfaced [tauri-apps/tauri#13415](https://github.com/tauri-apps/tauri/issues/13415), *"[bug] macOS .transparent(true) Webview Windows Lose Transparency After DMG Build"*. I could **not fetch its body** (GitHub is unreachable from my sandbox — see Limitations), so I report only the title/URL as a signal, not as verified detail. **[UNVERIFIED — needs reading.]**

4. **Windows: layered-window click-through.** [wailsapp/wails#5812](https://github.com/wailsapp/wails/issues/5812) is titled *"[v3/windows] Cannot combine per-pixel transparency and click-through for overlay windows (WebView2)"* — again, **title/URL only, body unverified.** Read together with Wails' own warning that `WebView2CompositionHosting` "may have rendering, input, focus, or WebView2 Runtime compatibility issues," the pattern is clear: **on Windows, per-pixel transparency + custom hit-testing is a WebView2 friction point.** Your sibling layout avoids this entirely (no transparency, no click-through).

5. **Airspace is the general framing.** Two independently-composited surfaces in one window cannot freely overlap without one of them being rendered into the other's compositor. Tauri's Windows `WebView2CompositionHosting` is exactly Wails' answer to this (DirectComposition), and its documented instability is the airspace tax. Electron's `WebContentsView`/`View` hierarchy solves it *for Electron-owned views* via Chromium's compositor.

6. **The pattern is well-trodden — but mostly in Electron.** The most-cited "webview next to a native render surface in one window" evidence is Electron's `BaseWindow` + `WebContentsView` docs. There is also [tauri-apps Discussions #14273](https://github.com/orgs/tauri-apps/discussions/14273) — *"When will Tauri support functionality similar to Electron's addChildView and the `<webview>` element?"* — which is precisely the multiwebview feature that landed as the `unstable` `add_child` API. And the C++ `webview/webview` library gives you the window directly, so sibling layout is trivial there by construction.

7. **Linux/GTK is structurally different.** GTK/WebKitGTK containers are single-toolkit; there is no "foreign HWND child" concept. Embedding an external GL surface means using `GtkGLArea`/`GtkFixed` inside the GTK hierarchy. `wry` documents that on Linux `build_as_child` **"Only X11 is supported. This method won't work on Wayland."** Out of scope for v1.

---

## 3. Python interop

### 3.1 Tauri v2 — **officially supported sidecar**

Tauri has first-class, documented external-binary support. From [v2.tauri.app/develop/sidecar](https://v2.tauri.app/develop/sidecar/):

> "You may need to embed external binaries … We call this binary a `sidecar`. Binaries are executables written in any programming language. **Common use cases are Python CLI applications or API servers bundled using `pyinstaller`.**"

**Bundling.** `bundle.externalBin` in `tauri.conf.json`:
```json
{ "bundle": { "externalBin": ["/abs/path/to/sidecar", "../relative/path", "binaries/my-sidecar"] } }
```
The **critical, easy-to-miss rule**: each target architecture needs its own file with a **`-$TARGET_TRIPLE` suffix** — e.g. `binaries/my-sidecar-aarch64-apple-darwin` on Apple Silicon, `binaries/my-sidecar-x86_64-pc-windows-msvc.exe` on Windows. Get it via `rustc --print host-tuple` (Rust ≥1.84), or parse `rustc -Vv`.

**Mechanism.** `tauri-plugin-shell` + `ShellExt::shell().sidecar("my-sidecar")`, which returns `(rx, child)`. Then event-driven stdin/stdout:
```rust
let sidecar_command = app.shell().sidecar("my-sidecar").unwrap();
let (mut rx, mut child) = sidecar_command.spawn().expect("Failed to spawn sidecar");
tauri::async_runtime::spawn(async move {
  while let Some(event) = rx.recv().await {
    if let CommandEvent::Stdout(line_bytes) = event {
      app.emit("message", Some(format!("'{}'", String::from_utf8_lossy(&line_bytes)))).unwrap();
      child.write("message from Rust\n".as_bytes()).unwrap();
    }
  }
});
```
So: **stdin/stdout line-oriented JSON-RPC**, brokered by Rust, surfaced to JS as Tauri events / commands. Note `sidecar()` takes **just the filename**, not the configured path.

**Pain points (documented or inherent):**
- The sidecar must be a **compiled binary**, not a script → Python must be frozen (PyInstaller/Nuitka/`python-build-standalone`) before it can be a sidecar.
- **Target-triple naming** is manual and a common "sidecar not found" failure.
- **macOS notarization of nested executables** inside the `.app` — PyInstaller output means code signing a bundle-within-a-bundle with the hardened runtime. **[UNVERIFIED: Tauri's macOS signing docs cover signing the app; I did not verify they cover a frozen-Python nested binary specifically.]** This is the pain point to budget for.
- **Lifecycle**: Tauri gives you a `CommandChild`; killing the Python process on app exit is **your** responsibility. No automatic reaping is documented.
- `stdout` line framing: Python needs `flush=True` / unbuffered (`-u`) or you get apparent hangs.

**Status of community Python-native bindings (`pytauri`, `tauri-plugin-python`):** **[UNVERIFIED — I did not verify versions/licences/maturity of these; do not plan around them without a check.]**

### 3.2 Wails v2/v3 — **no first-class sidecar; DIY**

I found **no official Wails sidecar facility** in either the v2 or v3 documentation sets I read (v3's FAQ, architecture, window API, extending-Wails, and runtime-internals pages). The supported path is therefore the generic Go one:

1. `os/exec` the Python process from `OnStartup` (or a `ServiceStartup` in v3).
2. Speak **line-delimited JSON over stdin/stdout**, or **WebSocket / named pipe / localhost HTTP** (Wails' asset server does **not** speak WebSockets — its feature matrix lists WebSockets ❌ on Win/Mac/Linux, so you'd need your own listener).
3. Bundle Python yourself (PyInstaller `onedir` is generally kinder than `onefile` for startup and for notarization) into `Contents/Resources` (macOS) or beside the `.exe` (Windows).
4. Kill it in `OnShutdown`.

**Known pain points for the Go route (general, not Wails-specific):** child not reaped if the app is force-quit; Go `cmd.Wait()` needed to avoid zombies; Windows console-window flash unless the child is built with `-ldflags -H=windowsgui` or launched with `CREATE_NO_WINDOW`; macOS **hardened-runtime + notarization of nested executables**; Python stdout buffering; large `.app` size.

**Net:** Wails can do this, but it is **strictly more assembly** than Tauri's documented sidecar, with no framework help on packaging or lifecycle.

### 3.3 pywebview + a Python local server — **Python owns the process**

**This is the smallest-delta architecture**, because your logic layer already *is* Python.

- **pywebview v6.2.1**, BSD-3-Clause. Python creates the window and launches the OS webview.
- **JS↔Python bridge is built in**: `js_api=` exposes a Python object as `window.pywebview.api.<method>(...)` returning a **Promise**; `window.evaluate_js(...)`. Caveat from the API docs: *"Only basic Python objects (like int, str, dict, ...) can be returned to Javascript."*
- **Local-server pattern**: pass a **WSGI server object** as pywebview's `url` (`webview.create_window(..., url=my_wsgi_app)`), or use `webview.start(http_server=True, http_port=...)`. pywebview's own notes: *"For each window, a separate HTTP server is spawned… By default port is randomized"*, and the default server is **Bottle** (`server=http.BottleServer`). A random port is exactly the handshake you want.
- **Security**: pywebview ships `webview.token` — *"A CSRF token property unique to the session. The same token is exposed as `window.pywebview.token`."* Use it (or your own random token in the URL) plus a `127.0.0.1` bind to stop other local processes and browsers from driving your API. Also note `webview.start(ssl=False)` by default and `IGNORE_SSL_ERRORS: False`; pywebview can serve TLS if `cryptography` is installed (`ssl=True`). The loopback-bind + token pattern is the standard mitigation for localhost CSRF / DNS-rebinding; **[UNVERIFIED: I did not verify pywebview documents a CORS policy for the built-in server — set it yourself in your FastAPI/Starlette app.]**
- **Packaging reality**: PyInstaller / py2app / Briefcase can produce a double-clickable `.app`, but you are shipping a whole interpreter, and you sign/notarize it yourself. Windows: PyInstaller onefile bundles are a well-known **antivirus false-positive** magnet. **[UNVERIFIED — widely reported, I did not verify a specific AV vendor's behaviour.]**

**What it gives up vs. Tauri/Wails:**
- **~40 MB+ of interpreter** you must ship and update yourself (no OS-managed runtime).
- **Slower cold start** than a compiled Go/Rust host (interpreter boot + MuJoCo import).
- **No framework updater, no framework ACL/permission model, no first-class installer tooling** (Tauri has NSIS/MSI/DMG/AppImage; Wails v3 has `wails3 package` + a built-in signed updater).
- **macOS notarization is entirely on you**, including the nested-binary problem.
- **Windows support is thinner**: pywebview's `transparent` window is *"Not supported on Windows"*, and the Windows backend is WinForms + pythonnet + WebView2 — a stack with more moving parts than WKWebView/pyobjc.

**Is it viable for a real product?** **Yes, with eyes open** — it is a legitimate shipping architecture (the pattern of "Python process owns a webview + local server" is common in scientific tooling), and it is by far the fastest path to a working single-window macOS build. What it *isn't* is a low-maintenance distributable. The interpreter you ship is now a product surface you own forever.

### 3.4 Interop comparison

| | Mechanism | Bundling | Cleanup on exit | Signing pain | Size | Maturity |
|---|---|---|---|---|---|---|
| **Tauri v2 sidecar** | stdin/stdout JSON via `tauri-plugin-shell`; JS gets events | `bundle.externalBin` + target-triple-suffixed binaries | Manual (`CommandChild`) | **High** (nested frozen Python in `.app`) | Frozen Python dominates | **Official, documented** |
| **Wails v2/v3** | DIY: `os/exec` + stdio / WS / pipe / HTTP | Yourself into `Contents/Resources` | Manual (`OnShutdown`) | **High** (same) | Frozen Python dominates | Community pattern |
| **pywebview + server** | `js_api` bridge **and/or** loopback WSGI/HTTP on a random port + `webview.token` | PyInstaller / py2app / Briefcase | Python owns everything | **High** (whole interpreter) | Frozen Python dominates | Mature; Windows thinner |

**Honest observation:** in all three routes, **bundle size is dominated by frozen Python + MuJoCo, not by the shell.** The 1 MB vs 8 MB vs 236 MB shell difference is real but second-order next to a several-hundred-MB scientific Python payload. **Optimise the shell for native-window control and packaging ergonomics, not for size.**

---

## 4. Hosting the native 3D view inside the app window

### 4.1 Wails v2 / v3 — **no public native-window-handle API**

**Findings:**

- The v2 options struct (`pkg/options`, v2.16.0) has **no handle field**. Public surface = window geometry (`Width/Height/X/Y/MinWidth/…`), `Frameless`, `BackgroundColour *RGBA`, `Windows *windows.Options`, `Mac *mac.Options`, `Linux *linux.Options`. No `HWND`, no `NSWindow`.
- Wails **v2** *does* expose `Mac.WebviewIsTransparent` and `Windows.WebviewIsTransparent` — i.e. transparency is plumbed, but **window/view handles are not**.
- **Wails v3**: I read the Window API reference, the WebviewWindowOptions struct, the Extending-Wails guide, and the Runtime Internals guide. `WebviewWindowOptions` has window geometry, appearance, `Mac/Windows/Linux` sub-structs — **no handle field**. The extension guide's documented method for new native behaviour is: add a method to `pkg/application/webview_window.go`, implement it per-OS in `pkg/application/webview_window_{darwin,linux,windows}.go`, register a message processor, and **open a WEP (Wails Enhancement Proposal) draft PR** — explicitly "bending Wails to your will" by **forking or upstreaming**.
- A search surfaced **[wailsapp/wails PR #4471](https://github.com/wailsapp/wails/pull/4471)** referencing `nativeWindowHandle() uintptr` → `nativeWindow() NativeWindow`. That is **internal** plumbing for Wails' own use, and **not** part of the documented public API. **[Title/snippet only — body unverified.]**

**Verdict:**
- Hosting an **external** native GL/Metal view inside a Wails window is **possible only by forking Wails** (or landing a WEP) to expose the `NSWindow`/`HWND`. There is no supported, documented path today.
- Practical mitigation if you choose Wails anyway: Wails v3's own **`WebView2CompositionHosting`** and **Notch Windows** show the maintainers are solving compositing internally — but those are framework features, not extension points for a foreign renderer.
- **Rating: (iii) not possible without forking.**

### 4.2 Tauri v2 — **documented path exists**

**Two independent, documented capabilities:**

**(i) Native handle access — `Webview::with_webview()`.** Tauri's own doc example is unambiguous:

```rust
main_webview.with_webview(|webview| {
  #[cfg(target_os = "macos")]
  unsafe {
    let view: &objc2_web_kit::WKWebView = &*webview.inner().cast();
    let controller: &objc2_web_kit::WKUserContentController = &*webview.controller().cast();
    let window: &objc2_app_kit::NSWindow = &*webview.ns_window().cast();
    view.setPageZoom(4.);
    controller.removeAllUserScripts();
    let bg_color = objc2_app_kit::NSColor::colorWithDeviceRed_green_blue_alpha(0.5, 0.2, 0.4, 1.);
    window.setBackgroundColor(Some(&bg_color));
  }
  #[cfg(windows)]
  unsafe { webview.controller().SetZoomFactor(4.).unwrap(); }
  #[cfg(target_os = "linux")]
  { use webkit2gtk::WebViewExt; webview.inner().set_zoom_level(4.); }
});
```
So: **macOS → the real `NSWindow`**, **Windows → the `ICoreWebView2Controller`** (hosting HWND reachable), **Linux → the `webkit2gtk::WebView`**. The docs warn: *"`webview2-com`, `webkit2gtk`, `objc2_web_kit` and similar crates may be updated in minor releases of Tauri. Therefore it's recommended to pin Tauri to at least a minor version when you're using `with_webview`."*

Plus `tauri::Window` implements **`HasWindowHandle`** and **`HasDisplayHandle`** (`raw-window-handle ^0.6`), giving `RawWindowHandle::AppKit` / `Win32` / `Xlib`, and platform getters `Window::gtk_window()` and `Window::default_vbox()` on Linux. `tao`'s `WindowExtMacOS` provides `ns_window() -> *mut c_void` and `ns_view() -> *mut c_void`; `WindowExtWindows` provides `hwnd() -> isize`.

**Architecturally this is the right shape:** on macOS the webview is an `NSView` added to the content view (`ns_view.addSubview(&webview)`); your Filament view is another `NSView` (a `CAMetalLayer`-backed one) added as a **sibling**. On Windows, add_child creates the webview as a **child HWND**, so a Filament child HWND beside it is symmetric.

**(ii) Sibling-region layout — the `unstable` multiwebview API.**
```rust
pub fn add_child<P: Into<Position>, S: Into<Size>>(
    &self, webview_builder: WebviewBuilder<R>, position: P, size: S,
) -> Result<Webview<R>>
```
Docs: *"Adds a new webview as a child of this window. This is the multiwebview API: a single window can host any number of webviews, each of them positioned and sized by you. **It requires the `unstable` Cargo feature** and is only available on desktop."* Also `Webview::reparent()`, `set_bounds/set_position/set_size`, `auto_resize`. `Window::builder()` likewise requires `unstable` and *"creates a window without any webview attached to it"* — **exactly the "leave a rectangle free" primitive.**

**(iii) Third-party precedent (weak but real).** Crates.io lists **`tauri-nssplitview` 0.1.0** (repo `Vanalite/tauri-nssplitview`) — *"A wrapper plugin for Tauri to build MacOS app with NSSplitView."* **Only 316 downloads, license field null, last updated 2025-10-07** — i.e. a proof-of-concept that the native-view-mixing approach works, **not** a dependency to adopt.

**Verdict: (ii) possible via documented raw-handle API + FFI; the *layout* half is officially supported, the *foreign renderer* half is documented-but-unproven.** Rating: **(i)+(ii)** — best-supported of all the webview shells.

### 4.3 Electron

`BaseWindow` + `WebContentsView` + `addChildView` + `setBounds` is documented, stable, and designed for exactly this composition. But composes **Electron `View`s**. Attaching a **foreign** C++/Metal/D3D surface requires the native handle — **[UNVERIFIED]**. Cost: ~236 MB minimum before your Python.

### 4.4 pywebview — **direct native object access, verified in source**

`window.native` is set by each backend (verified in the 6.2.1 sdist):

| Platform | File:line | `window.native` is |
|---|---|---|
| **macOS** | `webview/platforms/cocoa.py:595` | **`self.window`** — a `BrowserView.WindowHost`, which subclasses **`AppKit.NSWindow`** |
| **Windows** | `webview/platforms/winforms.py:195` | **`self`** — the **`WinForms.Form`** subclass (has `.Handle`) |
| Linux | `webview/platforms/gtk.py:80` | the **`gtk.ApplicationWindow`** |
| Qt | `webview/platforms/qt.py:325` | the Qt `BrowserView` |

The declaration is `webview/window.py:182`: `self.native = None  # set in the gui after window creation`.

The macOS webview itself is `webview/platforms/cocoa.py:609`:
```python
self.webview = BrowserView.WebKitHost.alloc().initWithFrame_configuration_(rect, config)
```
i.e. a **`WKWebView` subclass** reachable from Python.

**Therefore, on macOS:**
```python
w = webview.create_window("workbench", url=my_wsgi_app)
...
ns_window = w.native                       # NSWindow (pyobjc)
content   = ns_window.contentView()        # NSView
content.addSubview_(my_filament_view)      # sibling NSView / CAMetalLayer host
my_filament_view.setFrame_(rect)           # leave a rectangle free
w.webview.setFrame_(webview_rect)          # shrink the webview to the rest
```
This is **the same NSView-sibling structure** wry uses internally, expressed in Python. Filament can be driven from Python via `ctypes` against `libfilament`+`libbackend`, passing the `NSView*`/`CAMetalLayer*` — or via a small C++/pybind11 shim.

**Windows:** `w.native.Handle` gives the top-level `HWND`; adding a child HWND for Filament is standard Win32. pywebview itself uses this (WinForms `BrowserForm.Handle`, `windll.user32.*`). **[UNVERIFIED: I did not find a worked pywebview example doing exactly this — a spike is required.]**

**Verdict: (i)/(ii) — officially exposed objects, unusually direct, but the specific Filament-sibling step is unproven.**

### 4.5 Native-view summary

| Framework | Handle access | Can host **external** native GL/Metal view? | Evidence |
|---|---|---|---|
| **Wails v2** | ❌ none public | **No — fork required** | `pkg/options` v2.16.0 has no handle field |
| **Wails v3** | ❌ none public | **No — WEP/fork required** | Window API + WebviewWindowOptions + Extending-Wails |
| **Tauri v2** | ✅ `with_webview()` → NSWindow / WebView2 controller / webkit2gtk; `HasWindowHandle`; `Window::gtk_window()` | **Yes — documented path; layout via `unstable` multiwebview** | docs.rs/tauri Webview::with_webview; docs.rs/tauri Window::add_child |
| **Electron** | Composes Electron `View`s officially; foreign surface **[UNVERIFIED]** | Likely, via native addon — undocumented | Electron BaseWindow docs |
| **pywebview** | ✅ `window.native` = NSWindow / WinForms Form (`.Handle`) | **Likely yes on macOS & Windows; unproven for Filament specifically** | sdist source, lines cited above |
| **bare `webview/webview`** | ✅ you create the window | **Yes — trivial; you own the hierarchy** | MIT, 14.3k★, Cocoa/Win32/GTK backends |

---

## 5. Recommendation — ranked routes

### 🥇 Route 1 — **Tauri v2 host + Python sidecar + `unstable` multiwebview + Filament child NSView/HWND**

**Most robust, and the only route where every needed mechanism is documented.**

- Rust `src-tauri` creates a `Window` **with no webview** (`Window::builder`, `unstable`) so a rectangle is free.
- Webview added via `add_child(builder, position, size)` as an **`NSView` subview / child HWND**; the Filament surface goes in the free rectangle as a sibling, driven through a tiny C++ FFI shim (`extern "C"` entry taking the `NSWindow*`/`HWND` from `with_webview()` / `HasWindowHandle`).
- Python runs as an official **sidecar** (`bundle.externalBin`, target-triple-suffixed frozen binary), talking line-JSON over stdio, surfaced to React as Tauri events. Python stays the sole owner of MuJoCo/logic.
- Webview transparency **not needed** (sibling layout) → **the macOS private API is avoided entirely**. Windows transparency stays available via `DefaultBackgroundColor` if you later want overlays.
- `Apache-2.0 OR MIT`, stable 2.12.4, 111.9k★, plus iOS/Android headroom.

**Needs a spike:** (1) **Filament actually attaching to the passed `NSWindow` next to a WKWebView without compositing artefacts** — the highest-risk unknown in this whole report; (2) the `unstable` feature flag's stability guarantee; (3) macOS notarization of a frozen-Python sidecar; (4) confirming the `add_child` sync-command deadlock (wry#583) is avoided by doing it in `setup`/async.

**Cost:** introduces **Rust** *and* a **C++ shim** — three languages (Rust, C++, Python) plus TS. For a Python/C++ shop that is the main argument against it.

---

### 🥈 Route 2 — **pywebview + loopback server + native `NSView` sibling** *(fewest new languages — Python-only)*

**Lowest new-language count; fastest to a working macOS single window.**

- Python owns everything: `webview.create_window(..., url=my_wsgi_app)` (FastAPI/uvicorn or Bottle) bound to `127.0.0.1` on a **random port**, with `webview.token` CSRF protection and your own CORS policy. React/Tailwind UI is served from the same process that runs MuJoCo — **no IPC serialisation tax for the data layer.**
- Native view: `w.native` is a real **`NSWindow`** (verified: `cocoa.py:595`). Shrink the WKWebView's frame and `addSubview_` a Filament-backed `NSView`/`CAMetalLayer` sibling — the same structure wry uses.
- Windows: `w.native.Handle` → child HWND. Packaging via PyInstaller/py2app.

**Gives up:** you ship a ~40 MB+ interpreter forever; no framework updater/ACL/installer; you own notarization (nested-binary problem) and Windows AV false positives; slower cold start; Windows path is genuinely thinner (`transparent` windows unsupported on Windows; WinForms+pythonnet+WebView2 stack).

**Needs a spike:** (1) same Filament-sibling question as Route 1 — **unverified in both, so spike it once and the answer informs both routes**; (2) `w.native.Handle` → child-HWND for Filament on Windows; (3) PyInstaller + notarization end-to-end; (4) do NOT rely on pywebview webview *transparency* on Windows (unsupported) or macOS (only `setOpaque_(False)` on the window, `cocoa.py:674-675` — the webview itself is a separate matter).

**Verdict: viable for a real product.** Best route if the priority is "ship the macOS version soon, keep the team Python-only," and you accept owning the interpreter as a product surface.

---

### 🥉 Route 3 — **Own the window yourself: C++ host using `webview/webview` + Filament**

**Most robust for Windows *and* fewest new languages — because we are already C++.**

- `webview/webview` (**MIT**, 14.3k★, 0.12.0) gives you the **window you created** — so the webview and the Filament surface are peer child views by construction, on **both** macOS (Cocoa/WebKit) and Windows (Win32/WebView2). No raw-handle escape hatch is needed because there is nothing to escape.
- Ships a built-in WebView2 loader (no `WebView2Loader.dll` to distribute) and lets you pick WebKitGTK 6.0 / 4.1 / 4.0 on Linux.
- Your existing C++ host survives — this is an *incremental* change (swap ImGui for a webview) rather than a rewrite into Go or Rust. **Zero new languages** if the UI stays HTML/CSS/JS + the existing C++.
- Footprint is the smallest of all options (your binary + OS webview).

**Cost — and it is real:** you implement asset serving, JS↔C++ IPC, packaging/installers (`.app`/DMG, NSIS/MSI), code signing, auto-update, single-instance, and file dialogs. Tauri/Wails give you all of that. You also get **no** iOS/Android path and no framework community.

**Needs a spike:** (1) **macOS: `CAMetalLayer`-backed Filament `NSView` as a sibling of the `WKWebView`** (same unknown as Routes 1–2 — but here you control the view tree, so it is the *most* tractable); (2) Windows: Filament child HWND + WebView2 child HWND sharing a parent, including the known WebView2 white-flash and resize-flicker behaviours; (3) since `webview/webview` is a library not a scaffold, confirm you're happy owning updater/installer.

**Why ranked third despite being arguably the best architectural fit:** the engineering *surrounding* the window (packaging, signing, updates, IPC, dialogs) is where a two-person team loses months. Rank it first if and only if your C++ host already has an installer/signing/update pipeline you would keep.

---

### Ruled out (with reasons)

- **Wails v2/v3** — best size/startup story and the most mature *stable* option (v2), but **no public native-window-handle API** (§4.1). Hosting Filament would require forking Wails or landing a WEP. Additionally, v3's Windows `WebView2CompositionHosting` mode is documented as potentially unstable for rendering/input/focus. **Do not choose Wails for this app unless you are willing to fork it.**
- **Electron** — 236–390 MB before your Python, and the foreign-native-surface path is undocumented.
- **Neutralinojs** — smallest binaries, but no native-view mechanism at all.

---

### Cross-cutting recommendation: **spike the Filament sibling view BEFORE choosing a shell**

Every viable route (1, 2, 3) converges on the **same load-bearing unknown**, and it is *not* a framework question:

> **Can a Filament (Metal) `NSView`/`CAMetalLayer` be added as a sibling of a `WKWebView` in one `NSWindow`, without compositing artefacts — and then the same for a child HWND pair on Windows?**

Prove that in a ~200-line native prototype **first** (Cocoa: `NSWindow` + `WKWebView` + a `CAMetalLayer` `NSView` side by side). The result:
- If **yes** → the shell decision becomes a *packaging and team-skills* decision, and Routes 1/2/3 are all live.
- If **no** (artefacts, flicker, occlusion) → you need either a **separate always-adjacent OS window** positioned over the gap (a well-known airspace workaround, tracking the parent's move/resize), or Tauri's Windows-only `WebView2CompositionHosting`, or Electron's compositor. **That answer changes the architecture, so get it before committing.**

**Second, equally important decision:** the **sibling layout removes the transparency requirement**, which removes the macOS **private API** (`drawsBackground`) from the critical path. That is worth protecting — resist features (translucent toolbars over the 3D view, rounded window corners with 3D bleed) that reintroduce it, because that is the one thing that could jeopardise Mac App Store distribution and future macOS compatibility.

---

## Limitations & honesty flags

1. **GitHub is unreachable from my sandbox** (`github.com` resolves to a non-public IP; the Go module proxy timed out). Therefore I could **not read the bodies** of issues I cite by title: [tauri#13415](https://github.com/tauri-apps/tauri/issues/13415) (macOS transparency lost after DMG), [wails#5812](https://github.com/wailsapp/wails/issues/5812) (per-pixel transparency + click-through), [wails PR#4471](https://github.com/wailsapp/wails/pull/4471) (`nativeWindowHandle`), [tauri Discussion #14273](https://github.com/orgs/tauri-apps/discussions/14273). Their **titles** are evidence of the *existence* of these problem classes; their contents are unverified. **Read them before committing.**
2. **Bundle sizes are from the Elanis benchmark** (empty apps, GitHub CI, a 2023 archive of the table; ⚠️ the current revision reports a different Electron Windows figure ≈385 MB vs the archived ≈236 MB). Directional only.
3. **`wry` transparency on Linux** is my *source-level* finding (the setter is called; `app-paintable`/RGBA-visual prerequisites are absent from `webkitgtk/mod.rs`). I did not run it. It is possible GTK4/WebKitGTK 6.0 makes the precondition unnecessary — **[UNVERIFIED]**.
4. **Transparency issues #13415 and #5812** are **title-level only**. Do not quote them as confirmed behaviour.
5. **Filament-in-webview-window is unproven on every route.** I found no first-party or community evidence of Filament specifically being embedded beside a WKWebView/WebView2. The closest precedent is `tauri-nssplitview` (316 downloads, no license, 0.1.0) — a PoC, not a reference.
6. **I ran no builds.** Go and Rust toolchains are not on this machine; `npm` is unusable (root-owned cache). All claims are documentation- and source-derived.
7. **`pytauri` / `tauri-plugin-python` / `tauri-plugin-metal` / wgpu-in-Tauri** are **unverified** — I did not check their versions, licences, or maturity. Do not plan around them.
8. **Wails v3 is beta** (beta.30, releases every 1–4 days). Its FAQ says "stable desktop API" and that apps are in production, but also "test thoroughly before deployment."

---

## Sources

**Registries & metadata (queried 2026-10-16)**
- PyPI: `pywebview` 6.2.1 — https://pypi.org/pypi/pywebview/json
- npm: `@tauri-apps/cli` 2.12.3, `@tauri-apps/api` 2.12.4, `electron` 44.8.0, `@neutralinojs/neu` 11.8.0 — https://registry.npmjs.org/
- crates.io API: `tauri` 2.12.4 / 3.0.0-alpha.5, `wry` 0.57.0, `tao` 0.37.1, `raw-window-handle` 0.6.2, `tauri-nssplitview` 0.1.0 — https://crates.io/api/v1/crates/
- GitHub API: wails 36,573★ / MIT / created 2018-12-15; tauri 111,941★ / Apache-2.0 / created 2019-07-13

**Source code read directly**
- `wry` 0.57.0 crate tarball — `src/wkwebview/mod.rs` (drawsBackground KVC, addSubview child path), `src/webview2/mod.rs` (DefaultBackgroundColor, container HWND), `src/webkitgtk/mod.rs` (set_background_color, absent app-paintable), `src/lib.rs` (build_as_child platform notes)
- `pywebview` 6.2.1 sdist — `webview/platforms/cocoa.py:595,609,674`, `winforms.py:195`, `gtk.py:80`, `qt.py:325`, `window.py:182`
- `tao` 0.37.1 crate — `src/platform/macos.rs` (`ns_window`/`ns_view`), `src/platform/windows.rs` (`hwnd`)

**Official documentation**
- Wails v3 FAQ — https://v3.wails.io/faq/
- Wails v3 Private macOS APIs — https://v3.wails.io/guides/build/private-macos-apis/
- Wails v3 Frameless Windows (`WebView2CompositionHosting`) — https://v3.wails.io/features/windows/frameless/
- Wails v3 Window API — https://v3.wails.io/reference/window/
- Wails v3 Extending Wails (WEP / fork) — https://v3.wails.io/contributing/extending-wails/
- Wails v3 Runtime Internals — https://v3.wails.io/contributing/runtime-internals/
- Wails v2 Options (`WebviewIsTransparent`) — https://wails.io/docs/reference/options/
- `pkg/options` v2.16.0 (no handle field) — https://pkg.go.dev/github.com/wailsapp/wails/v2/pkg/options
- Tauri v2 Embedding External Binaries (sidecar) — https://v2.tauri.app/develop/sidecar/
- Tauri v2 App Size — https://v2.tauri.app/concept/size/
- Tauri v2 Configuration — https://v2.tauri.app/reference/config/
- `tauri::window::Window::add_child` — https://docs.rs/tauri/2.12.0/tauri/window/struct.Window.html
- `tauri::webview::WebviewBuilder` — https://docs.rs/tauri/2.12.0/tauri/webview/struct.WebviewBuilder.html
- `tauri::webview::Webview::with_webview` — https://docs.rs/tauri/2.12.0/tauri/webview/struct.Webview.html
- `wry::WebViewBuilder` (transparency, `build_as_child`) — https://docs.rs/wry/0.57.0/wry/struct.WebViewBuilder.html
- `objc2-web-kit::WebView` (deprecated, has `setDrawsBackground`) — https://docs.rs/objc2-web-kit/0.3.1/objc2_web_kit/struct.WebView.html
- Electron `BaseWindow` / `WebContentsView` — https://www.electronjs.org/docs/latest/api/base-window
- pywebview API (`native`, `token`, `server`, `transparent`) — https://pywebview.flowrl.com/api/
- pywebview Web engine — https://pywebview.flowrl.com/guide/web_engine.html
- WebView2 `ICoreWebView2Controller2::put_DefaultBackgroundColor` — https://learn.microsoft.com/en-us/microsoft-edge/webview2/reference/win32/icorewebview2controller2
- WebKitGTK `webkit_web_view_set_background_color` — https://webkitgtk.org/reference/webkit2gtk/stable/method.WebView.set_background_color.html
- Apple: `WKWebView.underPageBackgroundColor` — https://developer.apple.com/documentation/webkit/wkwebview/underpagebackgroundcolor
- `webview/webview` (C/C++, MIT) — https://github.com/webview/webview

**Independent benchmarks & issues cited by title**
- Elanis web-to-desktop-framework-comparison (sizes, memory, startup) — https://github.com/Elanis/web-to-desktop-framework-comparison (archived table: http://ng-tech.icu/books/web-notes/04.%E8%B7%A8%E7%AB%AF%E5%BC%80%E5%8F%91/99.%E5%8F%82%E8%80%83%E8%B5%84%E6%96%99/2023-web-to-desktop-framework-comparison/)
- wry#583 (WebView2 deadlock) — https://github.com/tauri-apps/wry/issues/583
- tauri#13415 — https://github.com/tauri-apps/tauri/issues/13415
- wails#5812 — https://github.com/wailsapp/wails/issues/5812
- wails PR#4471 — https://github.com/wailsapp/wails/pull/4471
- tauri Discussion #14273 — https://github.com/orgs/tauri-apps/discussions/14273
