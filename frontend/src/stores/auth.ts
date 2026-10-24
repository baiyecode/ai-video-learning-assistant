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
  /** Email verification (P2-05): null until the one-time link is confirmed. */
  email_verified_at: string | null;
}

export interface AuthResponse {
  account: Account;
  access_token: string;
  token_type: string;
  expires_in: number;
}

/**
 * POST /auth/register response (P2-06): a neutral acknowledgement only.
 *
 * Registration no longer authenticates and never reveals whether the email is taken,
 * so the body carries a single ``message`` sentence and no Session — see ticket #22.
 */
export interface RegisterResponse {
  message: string;
}

/**
 * POST /auth/verification/request (P2-08): 202 ack.
 *
 * ``email_verified`` reflects the Account after the call: a re-send to an
 * already-verified address sends nothing and says so. Frequency rejection is a
 * 429 ``too_many_requests`` whose ``details`` carry ``retry_after``/``reset_at``.
 */
export interface VerificationResponse {
  message: string;
  email_verified: boolean;
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
    /** False while signed out: the verification banner only guards a live session. */
    emailVerified: (state): boolean => state.account?.email_verified_at != null,
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
    /**
     * POST /auth/register: creates an Account and returns a neutral acknowledgement.
     *
     * It never starts a Session and never reveals whether the email is already registered
     * (a taken email yields the same sentence), so the caller cannot auto-login afterwards —
     * the Account must confirm the emailed link and then log in explicitly.
     */
    async register(email: string, password: string): Promise<string> {
      const body = await api.post<RegisterResponse>(
        "/auth/register",
        { email, password },
        { retryOn401: false },
      );
      return body.message;
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
    /**
     * POST /auth/verification/request: re-send the verification email for the
     * signed-in Account. A frequency refusal surfaces as a 429 ``too_many_requests``
     * whose ``details`` carry ``retry_after``/``reset_at`` for the caller to show.
     */
    async requestVerification(): Promise<VerificationResponse> {
      const body = await api.post<VerificationResponse>("/auth/verification/request", {});
      if (body.email_verified && this.account && this.account.email_verified_at == null) {
        // Keep the banner honest when the backend reports the email is already verified.
        this.account = { ...this.account, email_verified_at: new Date().toISOString() };
      }
      return body;
    },
    /**
     * POST /auth/verification/confirm: the token itself authenticates (no session).
     * A signed-in Account adopts the fresh ``email_verified_at``; invalid or expired
     * tokens surface as ``ApiError`` for the caller to explain.
     */
    async confirmVerification(token: string): Promise<Account> {
      const account = await api.post<Account>(
        "/auth/verification/confirm",
        { token },
        { retryOn401: false },
      );
      if (this.account && this.account.id === account.id) {
        this.account = account;
      }
      return account;
    },
  },
});

setUnauthorizedHandler(() => {
  useAuthStore().clearSession();
  redirectToLogin();
});
