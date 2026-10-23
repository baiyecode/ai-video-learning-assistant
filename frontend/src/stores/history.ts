/**
 * Analysis history list state: the Account's own Analyses plus the daily Quota.
 *
 * The list is a read-only view: opening a row never spends Quota, so a refresh is
 * always safe. Quota is supplementary; losing `/me` never blocks the list.
 */

import { defineStore } from "pinia";

import type { AnalysisHistoryItemDto } from "@/lib/history";
import { sortHistoryNewestFirst } from "@/lib/history";
import type { QuotaDto } from "@/lib/analysis";
import { ApiError, api } from "@/lib/api";

interface HistoryState {
  items: AnalysisHistoryItemDto[];
  quota: QuotaDto | null;
  loading: boolean;
  error: string | null;
}

export const useHistoryStore = defineStore("history", {
  state: (): HistoryState => ({
    items: [],
    quota: null,
    loading: false,
    error: null,
  }),
  actions: {
    async load(): Promise<void> {
      this.loading = true;
      this.error = null;
      try {
        const items = await api.get<AnalysisHistoryItemDto[]>("/analyses");
        this.items = sortHistoryNewestFirst(items);
      } catch (caught) {
        this.items = [];
        this.error =
          caught instanceof ApiError ? caught.message : "加载失败，请稍后重试";
      } finally {
        this.loading = false;
      }

      try {
        const me = await api.get<{ quota: QuotaDto }>("/me");
        this.quota = me.quota;
      } catch {
        // Quota is supplementary; the history itself stays usable.
      }
    },
  },
});
