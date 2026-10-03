import { existsSync, readFileSync } from "node:fs";
import type { CapacitorConfig } from "@capacitor/cli";

/** VITE_API_BASE_URL from the environment or web/.env.local (the same value Vite builds with). */
function apiBase(): string {
  if (process.env.VITE_API_BASE_URL) return process.env.VITE_API_BASE_URL;
  const file = "web/.env.local";
  if (!existsSync(file)) return "";
  const line = readFileSync(file, "utf-8").split(/\r?\n/).find(l => l.startsWith("VITE_API_BASE_URL="));
  return line?.split("=", 2)[1]?.trim() ?? "";
}

// Testing against a laptop backend over plain http (e.g. http://192.168.1.20:8000): the app's
// own origin is https://localhost, so the WebView must allow those requests, and remote
// debugging is handy. Production (HTTPS backend) keeps both off; `npm run android:release`
// refuses to build with an http backend (scripts/check-release.mjs).
const devBackend = apiBase().startsWith("http://");

const config: CapacitorConfig = {
  appId: "com.mrfounders.kisanmitra",
  appName: "Kisan Mitra",
  webDir: "web/dist",
  android: {
    allowMixedContent: devBackend,
    webContentsDebuggingEnabled: devBackend,
  },
  plugins: {
    SplashScreen: {
      launchAutoHide: false,
      backgroundColor: "#1b4332",
      showSpinner: false,
      androidScaleType: "CENTER_CROP",
    },
    SystemBars: {
      insetsHandling: "css",
      initialViewportFitValueHint: "cover",
    },
  },
};

export default config;
