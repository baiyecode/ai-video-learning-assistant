/**
 * Auth state.
 *
 * The access token lives in memory only; the refresh token is an HttpOnly cookie managed by
 * the backend. ``bootstrap()`` rotates that cookie on app start to restore the Session.
 */

import { defineStore } from "pinia";

import { api, setAccessToken, setUnauthorizedHandler } from "@/lib/api";

export interface Account {
  id: string;
  email: string;
  created_at: string;
}

export interface AuthResponse {
  account: Account;
  access_token: string;
  token_type: string;
  expires_in: number;
}

interface AuthState {
  account: Account | null;
  accessToken: string | null;
  restored: boolean;
}

let bootstrapPromise: Promise<void> | null = null;

function redirectToLogin(): void {
  if (typeof window === "undefined") return;
  if (window.location.pathname.startsWith("/login")) return;
  const next = `${window.location.pathname}${window.location.search}`;
  window.location.assign(`/login?next=${encodeURIComponent(next)}`);
}

export const useAuthStore = defineStore("auth", {
  state: (): AuthState => ({
    account: null,
    accessToken: null,
    restored: false,
  }),
  getters: {
    isAuthenticated: (state): boolean => state.account !== null,
  },
  actions: {
    setSession(token: string, account: Account): void {
      this.accessToken = token;
      this.account = account;
      setAccessToken(token);
    },
    clearSession(): void {
      this.accessToken = null;
      this.account = null;
      setAccessToken(null);
    },
    /** Restore the Session once per page load by rotating the refresh cookie. */
    async bootstrap(): Promise<void> {
      if (this.restored) return;
      if (bootstrapPromise) return bootstrapPromise;

      bootstrapPromise = (async () => {
        try {
          const body = await api.post<AuthResponse>("/auth/refresh", undefined, {
            retryOn401: false,
          });
          this.setSession(body.access_token, body.account);
        } catch {
          this.clearSession();
        } finally {
          this.restored = true;
          bootstrapPromise = null;
        }
      })();

      return bootstrapPromise;
    },
    async login(email: string, password: string): Promise<Account> {
      const body = await api.post<AuthResponse>(
        "/auth/login",
        { email, password },
        { retryOn401: false },
      );
      this.setSession(body.access_token, body.account);
      this.restored = true;
      return body.account;
    },
    async register(email: string, password: string): Promise<Account> {
      const body = await api.post<AuthResponse>(
        "/auth/register",
        { email, password },
        { retryOn401: false },
      );
      this.setSession(body.access_token, body.account);
      this.restored = true;
      return body.account;
    },
    async logout(): Promise<void> {
      try {
        await api.post<void>("/auth/logout", undefined, { retryOn401: false });
      } catch {
        // Logging out locally must succeed even if the Session is already gone.
      } finally {
        this.clearSession();
        this.restored = true;
      }
    },
  },
});

setUnauthorizedHandler(() => {
  useAuthStore().clearSession();
  redirectToLogin();
});
