import { SecureStorage } from "@aparajita/capacitor-secure-storage";
import { isNative } from "./config";

/**
 * Small key/value store for secrets (login tokens).
 * Android: encrypted with a key held in the Android Keystore.
 * Web: localStorage (the browser has no equivalent; tokens are short-lived).
 */
export const secureStore = {
  async get<T>(key: string): Promise<T | null> {
    try {
      if (isNative) return ((await SecureStorage.get(key)) as T | null) ?? null;
      const raw = localStorage.getItem(key);
      return raw ? (JSON.parse(raw) as T) : null;
    } catch {
      return null;
    }
  },

  async set(key: string, value: unknown): Promise<void> {
    try {
      if (isNative) await SecureStorage.set(key, value as Record<string, unknown>);
      else localStorage.setItem(key, JSON.stringify(value));
    } catch {
      /* private browsing etc.: the session lasts for this run only */
    }
  },

  async remove(key: string): Promise<void> {
    try {
      if (isNative) await SecureStorage.remove(key);
      else localStorage.removeItem(key);
    } catch {
      /* already gone */
    }
  },
};
