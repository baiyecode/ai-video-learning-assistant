/**
 * Subscription state: the Account's membership as reported by the backend.
 *
 * Membership is supplementary context: a failed read clears the state and keeps the
 * rest of the app usable, mirroring how the history store treats Quota.
 */

import { defineStore } from "pinia";

import { isVipMembership, type MembershipDto } from "@/lib/billing";
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
    isVip: (state): boolean => isVipMembership(state.membership),
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
    reset(): void {
      this.membership = null;
      this.loading = false;
      this.error = null;
    },
  },
});
