/** Download task state: create, poll until terminal, retry. */

import { ApiError, api } from "@/lib/api";
import type { DownloadDto } from "@/lib/download";
import { isTerminalStatus } from "@/lib/download";
import { defineStore } from "pinia";

const POLL_INTERVAL_MS = 1000;

export interface DownloadUiError {
  code: string;
  message: string;
}

interface DownloadState {
  download: DownloadDto | null;
  starting: boolean;
  error: DownloadUiError | null;
  lastVideoId: string | null;
  lastFormatId: string | null;
}

let pollTimer: ReturnType<typeof setTimeout> | null = null;

function stopPolling(): void {
  if (pollTimer !== null) {
    clearTimeout(pollTimer);
    pollTimer = null;
  }
}

function toUiError(caught: unknown): DownloadUiError {
  return caught instanceof ApiError
    ? { code: caught.code, message: caught.message }
    : { code: "network_error", message: "网络异常，请检查连接后重试" };
}

export const useDownloadStore = defineStore("download", {
  state: (): DownloadState => ({
    download: null,
    starting: false,
    error: null,
    lastVideoId: null,
    lastFormatId: null,
  }),
  getters: {
    active: (state): boolean =>
      state.download !== null && !isTerminalStatus(state.download.status),
  },
  actions: {
    async start(videoId: string, formatId: string): Promise<void> {
      if (this.starting) return;
      stopPolling();
      this.starting = true;
      this.error = null;
      this.download = null;
      this.lastVideoId = videoId;
      this.lastFormatId = formatId;
      try {
        this.download = await api.post<DownloadDto>("/downloads", {
          video_id: videoId,
          format_id: formatId,
        });
        this.schedulePoll();
      } catch (caught) {
        this.error = toUiError(caught);
      } finally {
        this.starting = false;
      }
    },
    schedulePoll(): void {
      stopPolling();
      const id = this.download?.id;
      if (!id || !this.download || isTerminalStatus(this.download.status)) return;
      pollTimer = setTimeout(() => {
        void this.poll(id);
      }, POLL_INTERVAL_MS);
    },
    async poll(id: string): Promise<void> {
      if (this.download?.id !== id) return;
      try {
        const next = await api.get<DownloadDto>(`/downloads/${id}`);
        if (this.download?.id !== id) return;
        this.download = next;
        this.error = null;
        this.schedulePoll();
      } catch (caught) {
        if (this.download?.id !== id) return;
        this.error = toUiError(caught);
        // Transient failures keep the countdown alive; a 410 file_expired is terminal.
        if (caught instanceof ApiError && caught.code === "file_expired") return;
        this.schedulePoll();
      }
    },
    async retry(): Promise<void> {
      const current = this.download;
      if (!current || this.starting) return;
      stopPolling();
      this.starting = true;
      this.error = null;
      try {
        this.download = await api.post<DownloadDto>(`/downloads/${current.id}/retry`);
        this.schedulePoll();
      } catch (caught) {
        this.error = toUiError(caught);
      } finally {
        this.starting = false;
      }
    },
    reset(): void {
      stopPolling();
      this.download = null;
      this.error = null;
      this.starting = false;
    },
  },
});
