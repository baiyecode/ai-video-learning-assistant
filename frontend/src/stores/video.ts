/** Resolved Video state for the Home resolve flow. */

import { api } from "@/lib/api";
import type { ResolveResult } from "@/lib/video";
import { asUiError, type UiError } from "@/lib/uiError";
import { defineStore } from "pinia";

interface VideoState {
  result: ResolveResult | null;
  loading: boolean;
  error: UiError | null;
  lastUrl: string;
}

export const useVideoStore = defineStore("video", {
  state: (): VideoState => ({
    result: null,
    loading: false,
    error: null,
    lastUrl: "",
  }),
  getters: {
    hasResult: (state): boolean => state.result !== null,
  },
  actions: {
    async resolve(url: string): Promise<void> {
      const trimmed = url.trim();
      if (!trimmed || this.loading) return;

      this.lastUrl = trimmed;
      this.loading = true;
      this.error = null;
      this.result = null;
      try {
        this.result = await api.post<ResolveResult>("/videos/resolve", { url: trimmed });
      } catch (caught) {
        this.result = null;
        this.error = asUiError(caught);
      } finally {
        this.loading = false;
      }
    },
    async retry(): Promise<void> {
      if (this.lastUrl) await this.resolve(this.lastUrl);
    },
    reset(): void {
      this.result = null;
      this.error = null;
      this.loading = false;
    },
  },
});
