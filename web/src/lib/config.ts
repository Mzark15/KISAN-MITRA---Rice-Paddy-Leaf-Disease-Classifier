import { Capacitor } from "@capacitor/core";

declare const __APP_VERSION__: string;

export const isNative = Capacitor.isNativePlatform();
export const APP_VERSION = __APP_VERSION__;

// Backend origin for the Android app, baked in at build time from VITE_API_BASE_URL
// (web/.env.production for release, web/.env.local for local testing, e.g. http://10.0.2.2:8000
// from the emulator). Use the `api_url` Terraform output / your DNS name for the ALB.
// The website is served by the backend itself, so it stays same-origin.
const fromEnv = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.trim().replace(/\/$/, "");

if (isNative && !fromEnv) {
  console.error("VITE_API_BASE_URL was not set when this app was built: API calls will fail.");
}

export const API_BASE = fromEnv || (isNative ? "" : window.location.origin);

export const PRIVACY_URL = `${API_BASE}/privacy`;
