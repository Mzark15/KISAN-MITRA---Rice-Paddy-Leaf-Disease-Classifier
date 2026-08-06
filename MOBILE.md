# Kisan Mitra — Mobile App (Capacitor)

The mobile app is a thin native wrapper (via [Capacitor](https://capacitorjs.com/)) around
the exact same `frontend/index.html` and `frontend/dashboard.html` used on the web —
no separate mobile codebase to maintain. Every fix you make to `frontend/` applies to
the mobile app too after a `npm run sync`.

## Why the app bundles the frontend locally (not a remote WebView)

Earlier this pointed the WebView straight at the backend URL (`server.url` in
`capacitor.config.json`). **That was wrong and has been reverted** — it broke
voice chat with `Cannot read properties of undefined (reading 'getUserMedia')`.

Here's why: `navigator.mediaDevices.getUserMedia` (needed for the mic) and a few
other powerful Web APIs only exist on ["secure
contexts"](https://developer.mozilla.org/en-US/docs/Web/Security/Secure_Contexts) —
`https://` origins, or the special `localhost` origin. Pointing the WebView at
`http://10.61.212.4:8000` made the *entire app* an insecure origin, so
`navigator.mediaDevices` was simply undefined — not a permissions problem, the
API didn't exist at all. Capacitor's own docs confirm `server.url` is "intended
for use with live-reload servers... not intended for use in production."

The fix: `webDir: "frontend"` bundles the HTML/JS/CSS into the app itself. The
WebView then loads from `https://localhost` (Android) / `capacitor://localhost`
(iOS) — Capacitor's default, and a secure context — so `getUserMedia` works.

Because the app's own origin is no longer the same as the backend, the frontend
can't rely on `window.location.origin` for API calls anymore. Both
`frontend/index.html` and `frontend/dashboard.html` now do this:

```js
const MOBILE_API_BASE_URL = "http://10.61.212.4:8000";
const API = (window.Capacitor && window.Capacitor.isNativePlatform && window.Capacitor.isNativePlatform())
  ? MOBILE_API_BASE_URL   // native app: explicit backend host
  : window.location.origin; // web: same-origin, unchanged
```

**When your backend address changes, edit `MOBILE_API_BASE_URL` in both files**,
then `npm run sync`:
- **Local testing (phone on same WiFi as your Mac):** your Mac's LAN IP, e.g.
  `http://10.61.212.4:8000` — find it with `ipconfig getifaddr en0`.
- **Real deployment:** your deployed HTTPS URL, e.g. `https://api.kisanmitra.app`
  (see `DEPLOY.md`). Once this is HTTPS, remove `"cleartext": true` and
  `"android": { "allowMixedContent": true }` from `capacitor.config.json` — those
  two flags exist only to allow the app to call a plain-HTTP dev backend and are
  explicitly flagged by Capacitor as **not for production use**.

## One-time setup

```bash
npm install
```

The Android platform (`android/`) is already scaffolded and committed. iOS needs to
be added on a Mac with Xcode installed (Capacitor's iOS tooling requires
Xcode + CocoaPods, which aren't available in every environment):

```bash
npm run add:ios
```

## Every time you change `capacitor.config.json` or `frontend/`

```bash
npm run sync
```

This copies `frontend/` into both native projects and applies config changes.

## Build & run

**Android** (needs [Android Studio](https://developer.android.com/studio)):
```bash
npm run open:android
```
Opens the project in Android Studio — press Run to install on an emulator or a
USB-connected device.

**iOS** (needs Xcode, Mac only):
```bash
npm run open:ios
```
Opens the project in Xcode — press Run to install on the iOS Simulator or a
connected iPhone. You'll need an Apple Developer account to install on a physical
device or submit to the App Store.

## Before shipping to real users

1. Make sure your backend is deployed somewhere with a stable HTTPS URL — don't
   ship an app pointing at your laptop's LAN IP.
2. Update `MOBILE_API_BASE_URL` in both `frontend/index.html` and
   `frontend/dashboard.html` to that HTTPS URL, then remove `cleartext` and
   `allowMixedContent` from `capacitor.config.json` as noted above.
3. Test microphone/camera permission prompts on a real device — they behave
   differently than in a desktop browser, and Android/iOS show native permission
   dialogs the first time each API is used.
4. App icons / splash screens aren't set up yet — see
   [`@capacitor/assets`](https://capacitorjs.com/docs/guides/splash-screens-and-icons)
   when you're ready for a polished build.
