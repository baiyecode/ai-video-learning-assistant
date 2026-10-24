/** DTOs and presentation mapping for the Analysis history list (`GET /api/analyses`). */

import {
  type AnalysisStatus,
  type SubtitleSource,
  analysisStatusLabel,
  formatShanghaiDateTime,
} from "@/lib/analysis";
import { platformLabel, subtitleSourceLabel } from "@/lib/video";

export interface HistoryVideoDto {
  id: string;
  title: string;
  platform: string;
  thumbnail_url: string | null;
}

export interface AnalysisHistoryItemDto {
  id: string;
  video_id: string;
  status: AnalysisStatus;
  subtitle_source: SubtitleSource;
  truncated: boolean;
  summary_snippet: string;
  error_code: string | null;
  created_at: string;
  completed_at: string | null;
  video: HistoryVideoDto | null;
}

export interface HistoryRow {
  id: string;
  videoId: string;
  title: string;
  platform: string;
  platformLabel: string;
  thumbnailUrl: string | null;
  status: AnalysisStatus;
  statusLabel: string;
  subtitleSourceLabel: string;
  snippet: string;
  createdLabel: string;
  errorCode: string | null;
  truncated: boolean;
}

function createdAtMs(item: AnalysisHistoryItemDto): number {
  const value = Date.parse(item.created_at);
  return Number.isNaN(value) ? 0 : value;
}

/** Newest first; equal/invalid timestamps keep the server order (stable sort). */
export function sortHistoryNewestFirst(
  items: readonly AnalysisHistoryItemDto[],
): AnalysisHistoryItemDto[] {
  return [...items].sort((a, b) => createdAtMs(b) - createdAtMs(a));
}

export function toHistoryRow(item: AnalysisHistoryItemDto): HistoryRow {
  return {
    id: item.id,
    videoId: item.video_id,
    title: item.video?.title ?? "未知视频",
    platform: item.video?.platform ?? "",
    platformLabel: item.video ? platformLabel(item.video.platform) : "",
    thumbnailUrl: item.video?.thumbnail_url ?? null,
    status: item.status,
    statusLabel: analysisStatusLabel(item.status),
    subtitleSourceLabel: subtitleSourceLabel(item.subtitle_source === "auto"),
    snippet: item.summary_snippet.trim(),
    createdLabel: formatShanghaiDateTime(item.created_at),
    errorCode: item.error_code,
    truncated: item.truncated,
  };
}

export function historyRows(items: readonly AnalysisHistoryItemDto[]): HistoryRow[] {
  return sortHistoryNewestFirst(items).map(toHistoryRow);
}
