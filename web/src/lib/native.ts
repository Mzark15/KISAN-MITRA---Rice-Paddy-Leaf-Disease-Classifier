/** Native integration: splash screen, status bar, Android back button, haptics, share, clipboard, network. */
import { useEffect, useSyncExternalStore } from "react";
import { SystemBars, SystemBarsStyle, SystemBarType } from "@capacitor/core";
import { App } from "@capacitor/app";
import { Clipboard } from "@capacitor/clipboard";
import { Haptics, ImpactStyle } from "@capacitor/haptics";
import { Network } from "@capacitor/network";
import { Share } from "@capacitor/share";
import { SplashScreen } from "@capacitor/splash-screen";
import { isNative } from "./config";

export async function initNative(): Promise<void> {
  if (!isNative) return;
  App.addListener("backButton", () => {
    for (let i = backHandlers.length - 1; i >= 0; i--) {
      if (backHandlers[i]()) return;
    }
    App.minimizeApp();
  });
}

// ── Status / navigation bar icon colours ────────────────────────────────────
//
// Two layouts exist on Android:
// - Edge-to-edge (WebView 140+, most phones): the page draws behind the bars and Capacitor
//   sets --safe-area-inset-* to the real sizes. Icons must contrast with the page.
// - Padded (older WebViews): Capacitor sets the insets to 0 and pads the page, so the bars
//   sit on the green window background (android/.../colors_app.xml). Icons are always light.

let greenHeader = false;

function applyBarIcons(): void {
  const root = document.documentElement;
  const edgeToEdge = parseFloat(getComputedStyle(root).getPropertyValue("--safe-area-inset-top")) > 0;
  const darkMode = window.matchMedia("(prefers-color-scheme: dark)").matches;
  const style = (onDark: boolean) => (onDark ? SystemBarsStyle.Dark : SystemBarsStyle.Light);
  const statusOnDark = !edgeToEdge || greenHeader || darkMode;
  const navOnDark = !edgeToEdge || darkMode;
  SystemBars.setStyle({ style: style(statusOnDark), bar: SystemBarType.StatusBar }).catch(() => {});
  SystemBars.setStyle({ style: style(navOnDark), bar: SystemBarType.NavigationBar }).catch(() => {});
}

/** The current screen has the dark green top bar (main app) or not (login). */
export function setBarIcons(hasGreenHeader: boolean): void {
  if (!isNative) return;
  greenHeader = hasGreenHeader;
  applyBarIcons();
}

if (isNative) {
  // Capacitor injects the inset values via a style attribute, possibly after the first render.
  new MutationObserver(applyBarIcons).observe(document.documentElement, { attributes: true, attributeFilter: ["style"] });
}

export function hideSplash(): void {
  if (isNative) SplashScreen.hide({ fadeOutDuration: 200 }).catch(() => {});
}

// ── Android back button: the most recently opened screen/sheet handles it first ──

const backHandlers: (() => boolean)[] = [];

/** While `active`, Android back calls `onBack` (e.g. close the drawer) instead of leaving the app. */
export function useBackHandler(active: boolean, onBack: () => void): void {
  useEffect(() => {
    if (!active) return;
    const handler = () => { onBack(); return true; };
    backHandlers.push(handler);
    return () => {
      const i = backHandlers.lastIndexOf(handler);
      if (i >= 0) backHandlers.splice(i, 1);
    };
  }, [active, onBack]);
}

// ── Small native helpers with web fallbacks ─────────────────────────────────

export function tap(): void {
  if (isNative) Haptics.impact({ style: ImpactStyle.Light }).catch(() => {});
}

export async function copyText(text: string): Promise<void> {
  if (isNative) await Clipboard.write({ string: text });
  else await navigator.clipboard?.writeText(text);
}

export async function shareText(text: string, title: string): Promise<void> {
  try {
    if (isNative) await Share.share({ title, text, dialogTitle: title });
    else if (navigator.share) await navigator.share({ title, text });
    else await copyText(text);
  } catch {
    /* user closed the share sheet */
  }
}

// ── Online / offline ────────────────────────────────────────────────────────

let online = navigator.onLine;
const netListeners = new Set<() => void>();
function setOnline(value: boolean) {
  if (value === online) return;
  online = value;
  netListeners.forEach(l => l());
}
if (isNative) {
  Network.getStatus().then(s => setOnline(s.connected)).catch(() => {});
  Network.addListener("networkStatusChange", s => setOnline(s.connected));
} else {
  window.addEventListener("online", () => setOnline(true));
  window.addEventListener("offline", () => setOnline(false));
}

export function useOnline(): boolean {
  return useSyncExternalStore(
    cb => { netListeners.add(cb); return () => netListeners.delete(cb); },
    () => online,
  );
}
