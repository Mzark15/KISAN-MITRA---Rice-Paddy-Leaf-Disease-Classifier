/**
 * Login session: phone + SMS code once, then silent token refresh.
 *
 * The access token lasts 1 hour; each refresh also returns a new refresh token
 * (rotation), so a farmer who keeps using the app never sees the login screen
 * again. Being offline never logs anyone out.
 */
import { useSyncExternalStore } from "react";
import { API_BASE } from "./config";
import { secureStore } from "./secureStore";

export interface UserProfile {
  user_id: string;
  phone: string;
  language?: "hi" | "mr" | "en";
  village?: string;
  name?: string;
}

export interface Session {
  access_token: string;
  refresh_token: string;
  username: string;
  expires_at: number;
  user: UserProfile;
}

interface TokenResponse {
  access_token: string;
  refresh_token?: string;
  expires_in: number;
  username: string;
  user?: UserProfile;
}

/** The backend rejected the request with a known error code (e.g. "invalid_code"). */
export class ApiError extends Error {
  constructor(public code: string, public status: number) {
    super(code);
  }
}

/** The session can't be renewed: the user must log in again. */
export class SessionExpiredError extends Error {}

const STORAGE_KEY = "km_session_v1";

// Temporary guest mode (build with VITE_AUTH_DISABLED=1, server with AUTH_DISABLED=1): no login
// screen and no tokens. Remove both flags to bring the phone + SMS login back unchanged.
export const GUEST = import.meta.env.VITE_AUTH_DISABLED === "1";
const guestSession = (): Session => ({
  access_token: "",
  refresh_token: "",
  username: "guest",
  expires_at: Number.MAX_SAFE_INTEGER,
  user: { user_id: "guest", phone: "" },
});

type State = { status: "loading" | "logged_out" | "logged_in"; session: Session | null; message?: string };
let state: State = { status: "loading", session: null };
const listeners = new Set<() => void>();

function setState(next: State) {
  state = next;
  listeners.forEach(l => l());
}

export function useAuth(): State {
  return useSyncExternalStore(
    cb => { listeners.add(cb); return () => listeners.delete(cb); },
    () => state,
  );
}

export function currentSession(): Session | null {
  return state.session;
}

export async function restoreSession(): Promise<void> {
  if (GUEST) {
    setState({ status: "logged_in", session: guestSession() });
    return;
  }
  const saved = await secureStore.get<Session>(STORAGE_KEY);
  setState(saved?.refresh_token ? { status: "logged_in", session: saved } : { status: "logged_out", session: null });
}

async function saveSession(session: Session | null, message?: string) {
  if (session) await secureStore.set(STORAGE_KEY, session);
  else await secureStore.remove(STORAGE_KEY);
  setState(session ? { status: "logged_in", session } : { status: "logged_out", session: null, message });
}

function applyTokens(data: TokenResponse, base: Session | null): Session {
  return {
    access_token: data.access_token,
    refresh_token: data.refresh_token ?? base?.refresh_token ?? "",
    username: data.username ?? base?.username ?? "",
    expires_at: Date.now() + data.expires_in * 1000,
    user: data.user ?? base!.user,
  };
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new ApiError("network", 0);
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(typeof data.detail === "string" ? data.detail : "generic", res.status);
  return data as T;
}

// ── Login with phone + code ─────────────────────────────────────────────────

export interface OtpStart {
  phone: string;
  flow: "signup" | "signin";
  session: string | null;
  resend_after: number;
}

export function startOtp(phone: string): Promise<OtpStart> {
  return postJson<OtpStart>("/auth/otp/start", { phone });
}

export async function verifyOtp(start: OtpStart, code: string): Promise<void> {
  const data = await postJson<TokenResponse>("/auth/otp/verify", {
    phone: start.phone, flow: start.flow, session: start.session, code,
  });
  await saveSession(applyTokens(data, null));
}

// ── Token refresh ───────────────────────────────────────────────────────────

let refreshing: Promise<void> | null = null;

function refreshTokens(): Promise<void> {
  if (!refreshing) {
    refreshing = (async () => {
      const s = state.session;
      if (!s) throw new SessionExpiredError();
      let res: Response;
      try {
        res = await fetch(`${API_BASE}/auth/refresh`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: s.refresh_token, username: s.username }),
        });
      } catch {
        throw new ApiError("network", 0);   // offline: keep the session
      }
      if (res.status === 400 || res.status === 401) throw new SessionExpiredError();
      if (!res.ok) throw new ApiError("generic", res.status);
      await saveSession(applyTokens(await res.json(), s));
    })().finally(() => { refreshing = null; });
  }
  return refreshing;
}

/** fetch() for logged-in endpoints: adds the token, refreshes it when needed, retries once on 401. */
export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  if (GUEST) {
    try {
      return await fetch(`${API_BASE}${path}`, init);
    } catch (err) {
      if ((err as Error).name === "AbortError") throw err;
      throw new ApiError("network", 0);
    }
  }
  if (!state.session) throw new SessionExpiredError();
  const send = () => fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { ...(init.headers ?? {}), Authorization: `Bearer ${state.session!.access_token}` },
  });

  try {
    if (Date.now() > state.session.expires_at - 60_000) await refreshTokens();
    let res: Response;
    try {
      res = await send();
    } catch (err) {
      if ((err as Error).name === "AbortError") throw err;
      throw new ApiError("network", 0);
    }
    if (res.status === 401) {
      await refreshTokens();
      res = await send();
    }
    if (res.status === 401) throw new SessionExpiredError();
    return res;
  } catch (err) {
    if (err instanceof SessionExpiredError) await saveSession(null, "sessionExpired");
    throw err;
  }
}

/** apiFetch + JSON body + error codes. */
export async function apiJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await apiFetch(path, init);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(typeof data.detail === "string" ? data.detail : "generic", res.status);
  return data as T;
}

// ── Profile, logout, account deletion ───────────────────────────────────────

export async function updateProfile(fields: Partial<Pick<UserProfile, "language" | "village" | "name">>): Promise<void> {
  if (GUEST) {
    if (state.session) setState({ status: "logged_in", session: { ...state.session, user: { ...state.session.user, ...fields } } });
    return;
  }
  const user = await apiJson<UserProfile>("/auth/me", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(fields),
  });
  if (state.session) await saveSession({ ...state.session, user });
}

export async function logout(): Promise<void> {
  if (GUEST) return;
  const s = state.session;
  if (s) postJson("/auth/logout", { refresh_token: s.refresh_token }).catch(() => {});
  await saveSession(null);
}

/** Permanently delete the account on the server, then log out. */
export async function deleteAccount(): Promise<void> {
  if (GUEST) return;
  const res = await apiFetch("/auth/me", { method: "DELETE" });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new ApiError(typeof data.detail === "string" ? data.detail : "generic", res.status);
  }
  await saveSession(null);
}
