/** DTOs and pure presentation helpers for the Download flow. */

import { formatDuration } from "@/lib/video";

export type DownloadStatus = "queued" | "downloading" | "merging" | "ready" | "failed" | "expired";

export interface DownloadErrorDto {
  code: string;
  message: string;
}

export interface DownloadDto {
  id: string;
  video_id: string;
  format_id: string;
  status: DownloadStatus;
  progress: number;
  error: DownloadErrorDto | null;
  attempts: number;
  file_name: string | null;
  file_size: number | null;
  created_at: string;
  updated_at: string;
  ready_at: string | null;
  download_url: string | null;
  url_expires_at: string | null;
  file_expires_at: string | null;
  can_retry: boolean;
  /** 1-based FIFO position while queued; null once running or terminal. */
  queue_position?: number | null;
}

const STATUS_LABELS: Record<DownloadStatus, string> = {
  queued: "排队中",
  downloading: "下载中",
  merging: "合并中",
  ready: "已完成",
  failed: "失败",
  expired: "已过期",
};

const TERMINAL_STATUSES: readonly DownloadStatus[] = ["ready", "failed", "expired"];

export function downloadStatusLabel(status: string): string {
  return STATUS_LABELS[status as DownloadStatus] ?? status;
}

export function isTerminalStatus(status: DownloadStatus): boolean {
  return TERMINAL_STATUSES.includes(status);
}

/** `0.456` → `46%`; invalid input clamps to `0%`. */
export function formatProgress(progress: number): string {
  const value = Number.isFinite(progress) ? Math.min(1, Math.max(0, progress)) : 0;
  return `${Math.round(value * 100)}%`;
}

/** `2` → `（第 2 位）`; unknown or invalid positions render as an empty string. */
export function formatQueuePosition(position: number | null | undefined): string {
  if (typeof position !== "number" || !Number.isFinite(position) || position < 1) return "";
  return `（第 ${Math.floor(position)} 位）`;
}

/** Whole seconds left until `expiresAt`; expired or unparsable input is `0`. */
export function remainingSeconds(expiresAt: string | null | undefined, nowMs: number): number {
  if (!expiresAt) return 0;
  const expires = Date.parse(expiresAt);
  if (!Number.isFinite(expires)) return 0;
  return Math.max(0, Math.floor((expires - nowMs) / 1000));
}

/** `900` → `15:00`, `3725` → `1:02:05`. Invalid input clamps to `0:00`. */
export function formatCountdown(seconds: number): string {
  return formatDuration(seconds);
}
