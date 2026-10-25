/**
 * Subscription state: the Account's membership as reported by the backend.
 *
 * Membership is supplementary context: a failed read clears the state and keeps the
 * rest of the app usable, mirroring how the history store treats Quota. VIP is the
 * backend-derived flag from `/me/membership`; the frontend never guesses it.
 */

import { defineStore } from "pinia";

import type { MembershipDto } from "@/lib/billing";
import { ApiError, api } from "@/lib/api";

interface BillingState {
  membership: MembershipDto | null;
  loading: boolean;
  error: string | null;
}

export const useBillingStore = defineStore("billing", {
  state: (): BillingState => ({
    membership: null,
    loading: false,
    error: null,
  }),
  getters: {
    vipActive: (state): boolean => state.membership?.vip_active === true,
  },
  actions: {
    async loadMembership(): Promise<void> {
      this.loading = true;
      this.error = null;
      try {
        this.membership = await api.get<MembershipDto>("/me/membership");
      } catch (caught) {
        this.membership = null;
        this.error =
          caught instanceof ApiError ? caught.message : "加载失败，请稍后重试";
      } finally {
        this.loading = false;
      }
    },
    /**
     * POST /billing/checkout: mint the hosted payment page and hand it to the browser.
     *
     * Returns the URL for the caller to navigate to (full-page jump: the card never
     * lives in this app). The redirect back is never treated as proof of payment —
     * only a fresh ``loadMembership()`` read of /me/membership decides the outcome.
     */
    async openCheckout(): Promise<string> {
      const body = await api.post<{ url: string }>("/billing/checkout", {});
      return body.url;
    },
    /** POST /billing/portal: the self-service management page (cards, invoices). */
    async openPortal(): Promise<string> {
      const body = await api.post<{ url: string }>("/billing/portal", {});
      return body.url;
    },
    reset(): void {
      this.membership = null;
      this.loading = false;
      this.error = null;
    },
  },
});
