/**
 * Analysis detail state: fetch the persisted result, then follow the SSE stream.
 *
 * Generation lives on the server, so leaving the page (or a broken connection) only
 * stops the reader. Reconnecting replays the persisted text followed by live deltas.
 */

import { defineStore } from "pinia";

import {
  type AnalysisDto,
  type AnalysisError,
  type AnalysisStreamState,
  type AnalysisVideoDto,
  type QuotaDto,
  applyAnalysisEvent,
  initialStreamState,
} from "@/lib/analysis";
import { ApiError, api } from "@/lib/api";
import { connectSse } from "@/lib/sse";

interface AnalysisState extends AnalysisStreamState {
  id: string | null;
  videoId: string | null;
  video: AnalysisVideoDto | null;
  loading: boolean;
  streaming: boolean;
  quota: QuotaDto | null;
}

let activeStream: AbortController | null = null;

function toError(caught: unknown): AnalysisError {
  if (caught instanceof ApiError) return { code: caught.code, message: caught.message };
  return { code: "network_error", message: "网络异常，请检查连接后重试" };
}

export const useAnalysisStore = defineStore("analysis", {
  state: (): AnalysisState => ({
    id: null,
    videoId: null,
    video: null,
    loading: false,
    streaming: false,
    quota: null,
    ...initialStreamState(),
  }),
  getters: {
    hasResult: (state): boolean =>
      state.status === "completed" && (state.summary.length > 0 || state.mindmap.length > 0),
    isActive: (state): boolean => state.status === "pending" || state.status === "streaming",
  },
  actions: {
    /** POST /api/analyses: reuse an in-progress/completed result or reserve one Quota. */
    async create(videoId: string, options: { force?: boolean } = {}): Promise<AnalysisDto> {
      const body = options.force ? { video_id: videoId, force: true } : { video_id: videoId };
      return await api.post<AnalysisDto>("/analyses", body);
    },

    /** Load the persisted result, then stream it (replays everything when finished). */
    async open(id: string): Promise<void> {
      this.close();
      this.$patch({
        id,
        videoId: null,
        video: null,
        loading: true,
        streaming: false,
        quota: null,
        ...initialStreamState(),
      });

      let analysis: AnalysisDto;
      try {
        analysis = await api.get<AnalysisDto>(`/analyses/${id}`);
      } catch (caught) {
        this.error = toError(caught);
        this.loading = false;
        return;
      }

      this.$patch({
        videoId: analysis.video_id,
        video: analysis.video,
        status: analysis.status,
        summary: analysis.summary_markdown,
        mindmap: analysis.mindmap_markdown,
        subtitleSource: analysis.subtitle_source,
        truncated: analysis.truncated,
        error: analysis.error,
        done: analysis.status === "completed" || analysis.status === "failed",
      });
      this.loading = false;
      void this.loadQuota();

      if (this.status !== "failed") await this.stream(id);
    },

    async stream(id: string): Promise<void> {
      const controller = new AbortController();
      activeStream?.abort();
      activeStream = controller;
      this.streaming = true;

      try {
        for await (const message of connectSse(`/api/analyses/${id}/stream`, {
          signal: controller.signal,
        })) {
          this.$patch(applyAnalysisEvent(this, message));
          if (this.done) break;
        }
      } catch (caught) {
        if (!controller.signal.aborted) this.error = toError(caught);
      } finally {
        if (activeStream === controller) activeStream = null;
        this.streaming = false;
      }
    },

    /** Retry a failed Analysis: failure released its Quota, so a new one may be created. */
    async retry(): Promise<string | null> {
      if (!this.videoId) return null;
      const analysis = await this.create(this.videoId);
      return analysis.id;
    },

    /** Explicit re-analysis: always a new Analysis row and one Quota unit. */
    async reanalyze(): Promise<string | null> {
      if (!this.videoId) return null;
      const analysis = await this.create(this.videoId, { force: true });
      return analysis.id;
    },

    async loadQuota(): Promise<void> {
      try {
        const me = await api.get<{ quota: QuotaDto }>("/me");
        this.quota = me.quota;
      } catch {
        // Quota is supplementary; the analysis itself stays usable.
      }
    },

    /** Stop reading the stream. Server-side generation continues. */
    close(): void {
      activeStream?.abort();
      activeStream = null;
      this.streaming = false;
    },

    reset(): void {
      this.close();
      this.$patch({
        id: null,
        videoId: null,
        video: null,
        loading: false,
        quota: null,
        ...initialStreamState(),
      });
    },
  },
});
