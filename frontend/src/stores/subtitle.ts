/**
 * Subtitle state for the Home resolve flow.
 *
 * The JSON endpoint and the file exports are both plain GETs; exports are fetched as a
 * blob so the SPA can surface errors instead of navigating away.
 */

import { defineStore } from "pinia";

import { api, apiErrorFromResponse, apiUrl, getAccessToken } from "@/lib/api";
import {
  filenameFromContentDisposition,
  subtitleExportFilename,
  subtitlePath,
  type SubtitleDetailDto,
  type SubtitleExportFormat,
} from "@/lib/subtitle";
import { asUiError, type UiError } from "@/lib/uiError";

interface SubtitleState {
  videoId: string | null;
  subtitle: SubtitleDetailDto | null;
  loading: boolean;
  error: UiError | null;
  exporting: SubtitleExportFormat | null;
  exportError: UiError | null;
}

let loadSequence = 0;

function saveBlob(blob: Blob, filename: string): void {
  if (typeof document === "undefined" || typeof URL.createObjectURL !== "function") return;
  const href = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = href;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  // Revoke later so the browser has time to start the download.
  setTimeout(() => URL.revokeObjectURL(href), 1000);
}

export const useSubtitleStore = defineStore("subtitle", {
  state: (): SubtitleState => ({
    videoId: null,
    subtitle: null,
    loading: false,
    error: null,
    exporting: null,
    exportError: null,
  }),
  getters: {
    available: (state): boolean => state.subtitle !== null,
  },
  actions: {
    async load(videoId: string): Promise<void> {
      const sequence = ++loadSequence;
      this.videoId = videoId;
      this.subtitle = null;
      this.error = null;
      this.exportError = null;
      this.loading = true;
      try {
        const subtitle = await api.get<SubtitleDetailDto>(subtitlePath(videoId));
        if (sequence !== loadSequence) return;
        this.subtitle = subtitle;
      } catch (caught) {
        if (sequence !== loadSequence) return;
        this.subtitle = null;
        this.error = asUiError(caught);
      } finally {
        if (sequence === loadSequence) this.loading = false;
      }
    },
    async download(format: SubtitleExportFormat): Promise<void> {
      const videoId = this.videoId;
      if (!videoId || this.exporting !== null) return;

      this.exporting = format;
      this.exportError = null;
      try {
        const headers = new Headers();
        const token = getAccessToken();
        if (token) headers.set("Authorization", `Bearer ${token}`);
        const response = await fetch(apiUrl(subtitlePath(videoId, format)), {
          headers,
          credentials: "same-origin",
        });
        if (!response.ok) throw await apiErrorFromResponse(response);

        const filename = filenameFromContentDisposition(
          response.headers.get("content-disposition"),
          subtitleExportFilename(videoId, format),
        );
        saveBlob(await response.blob(), filename);
      } catch (caught) {
        this.exportError = asUiError(caught);
      } finally {
        this.exporting = null;
      }
    },
    retry(): void {
      if (this.videoId) void this.load(this.videoId);
    },
  },
});
