/**
 * Auth state placeholder.
 *
 * The access token lives in memory only; the refresh token is an HttpOnly cookie.
 * Ticket #7 owns the real auth flow (register/login/refresh/logout, /api/me).
 */

import { defineStore } from "pinia";

import { api, setAccessToken, setUnauthorizedHandler } from "@/lib/api";

export interface Account {
  id: string;
  email: string;
  is_vip?: boolean;
}

interface AuthState {
  account: Account | null;
  accessToken: string | null;
  restored: boolean;
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
    /**
     * Restore the Session on boot by rotating the refresh cookie.
     * Ticket #7 implements the response contract; until then this stays dormant.
     */
    async restore(): Promise<void> {
      try {
        const body = await api.post<{ access_token: string; account: Account }>("/auth/refresh");
        this.setSession(body.access_token, body.account);
      } catch {
        this.clearSession();
      } finally {
        this.restored = true;
      }
    },
  },
});

setUnauthorizedHandler(() => {
  const store = useAuthStore();
  store.clearSession();
});
