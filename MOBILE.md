# Kisan Mitra — Android app

A Capacitor wrapper around the React app in `web/` (`capacitor.config.ts`, package
`com.mrfounders.kisanmitra`). The web UI is bundled into the app, so the WebView origin is
`https://localhost` (a secure context, which the microphone needs) and all API calls go to
the backend URL baked in at build time via `VITE_API_BASE_URL`.

## Debug APK (testing)

```bash
npm install
# web/.env.local  →  VITE_API_BASE_URL=http://10.0.2.2:8000   (emulator → laptop backend)
npm run android:debug          # → android/app/build/outputs/apk/debug/app-debug.apk
npm run android:install        # installs on a running emulator / USB phone
```

- Windows can't run an APK directly: use an Android Studio emulator (Device Manager) or a phone.
- Emulator → laptop backend is `http://10.0.2.2:8000`; a phone on the same Wi-Fi uses the laptop's
  LAN IP. Plain `http` is allowed only when `VITE_API_BASE_URL` starts with `http://`.
- The debug app installs as `com.mrfounders.kisanmitra.debug`, next to any Play Store version.

## Release build (Play Store)

1. `cp web/.env.production.example web/.env.production` and set your HTTPS API URL
   (the `api_url`/DNS name from `DEPLOY.md`).
2. Ensure `android/keystore.properties` and the `.jks` exist (both gitignored; back them up —
   losing the upload key blocks updates).
3. Bump `version` in `package.json` (versionCode/versionName derive from it).
4. `npm run android:release` → `android/app/release/` AAB. The script refuses non-HTTPS URLs.

The staff dashboard (`/dashboard`) is a web page served by the API, not part of the app.
