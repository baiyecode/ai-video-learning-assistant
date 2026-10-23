/**
 * Analysis DTOs, the SSE event reducer and Quota presentation helpers.
 *
 * The server replays persisted state on every (re)connect: a `meta` event always
 * restarts the summary, so applying a second `meta` after a dropped connection
 * rebuilds the text from the replay instead of duplicating it.
 */

import type { SseMessage } from "@/lib/sse";

export type AnalysisStatus = "pending" | "streaming" | "completed" | "failed";
export type SubtitleSource = "manual" | "auto";

export interface AnalysisError {
  code: string;
  message: string;
}

export interface AnalysisVideoDto {
  id: string;
  title: string;
  platform: string;
  duration_seconds: number;
  thumbnail_url: string | null;
}

export interface AnalysisDto {
  id: string;
  video_id: string;
  status: AnalysisStatus;
  summary_markdown: string;
  mindmap_markdown: string;
  subtitle_source: SubtitleSource;
  truncated: boolean;
  error: AnalysisError | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  video: AnalysisVideoDto | null;
}

/** `GET /api/me` quota block. `resets_at` is ISO8601 with a `+08:00` offset. */
export interface QuotaDto {
  daily_limit: number;
  used: number;
  remaining: number;
  resets_at: string;
}

export const MINDMAP_MARKER = "## 思维导图";
export const ANALYSIS_FAILED_MESSAGE = "AI 生成失败，请稍后重试";

export interface AnalysisStreamState {
  status: AnalysisStatus;
  summary: string;
  mindmap: string;
  subtitleSource: SubtitleSource | null;
  truncated: boolean;
  error: AnalysisError | null;
  done: boolean;
}

export function initialStreamState(): AnalysisStreamState {
  return {
    status: "pending",
    summary: "",
    mindmap: "",
    subtitleSource: null,
    truncated: false,
    error: null,
    done: false,
  };
}

type Payload = Record<string, unknown>;

function parsePayload(data: string): Payload | null {
  try {
    const value: unknown = JSON.parse(data);
    return value !== null && typeof value === "object" ? (value as Payload) : null;
  } catch {
    return null;
  }
}

function asText(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function asStatus(value: unknown): AnalysisStatus {
  return value === "pending" || value === "completed" || value === "failed"
    ? value
    : "streaming";
}

function asSource(value: unknown): SubtitleSource | null {
  return value === "manual" || value === "auto" ? value : null;
}

/** Fold one SSE message into the stream state. Unknown events are ignored. */
export function applyAnalysisEvent(
  state: AnalysisStreamState,
  message: SseMessage,
): AnalysisStreamState {
  const payload = parsePayload(message.data);
  if (payload === null) return state;

  switch (message.event) {
    case "meta":
      // A new generation or a replay after reconnect: summary restarts.
      return {
        ...state,
        status: asStatus(payload.status),
        summary: "",
        mindmap: "",
        subtitleSource: asSource(payload.subtitle_source) ?? state.subtitleSource,
        truncated: payload.truncated === true,
        error: null,
        done: false,
      };
    case "delta": {
      const text = asText(payload.text);
      return text === null ? state : { ...state, summary: state.summary + text };
    }
    case "mindmap": {
      const markdown = asText(payload.markdown);
      return markdown === null ? state : { ...state, mindmap: markdown };
    }
    case "done":
      return { ...state, status: "completed", done: true };
    case "error":
      return {
        ...state,
        status: "failed",
        done: true,
        error: {
          code: asText(payload.code) ?? "analysis_failed",
          message: asText(payload.message) ?? ANALYSIS_FAILED_MESSAGE,
        },
      };
    default:
      return state;
  }
}

/** Summary text without the trailing mindmap section (defensive while streaming). */
export function visibleSummary(markdown: string): string {
  const index = markdown.indexOf(MINDMAP_MARKER);
  return index === -1 ? markdown : markdown.slice(0, index).trimEnd();
}

export function analysisStatusLabel(status: AnalysisStatus): string {
  switch (status) {
    case "pending":
      return "排队中";
    case "streaming":
      return "生成中";
    case "completed":
      return "已完成";
    case "failed":
      return "生成失败";
  }
}

export function formatQuota(quota: QuotaDto | null | undefined): string {
  if (!quota) return "Quota 加载中";
  const limit = Math.max(0, quota.daily_limit);
  const remaining = Math.max(0, Math.min(quota.remaining, limit));
  return `剩余 ${remaining} / ${limit} 次`;
}

/** `2026-01-16T00:00:00+08:00` → `01-16 00:00` (always rendered in Asia/Shanghai). */
export function formatShanghaiDateTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";

  const parts = new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(date);
  const part = (type: Intl.DateTimeFormatPartTypes): string =>
    parts.find((item) => item.type === type)?.value ?? "";

  return `${part("month")}-${part("day")} ${part("hour")}:${part("minute")}`;
}

export function formatQuotaReset(resetsAt: string | null | undefined): string {
  const label = formatShanghaiDateTime(resetsAt);
  return label ? `将于 ${label} 重置` : "";
}
