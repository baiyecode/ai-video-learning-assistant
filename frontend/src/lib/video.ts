/** Pure presentation helpers and DTOs for the Video resolve flow. */

export interface VideoDto {
  id: string;
  platform: string;
  platform_video_id: string;
  title: string;
  duration_seconds: number;
  webpage_url: string;
  uploader: string | null;
  thumbnail_url: string | null;
  is_drm: boolean;
  is_members_only: boolean;
}

export interface VideoFormatDto {
  format_id: string;
  label: string;
  ext: string;
  resolution: string;
  width: number | null;
  height: number | null;
  filesize: number | null;
  has_video: boolean;
  has_audio: boolean;
}

export interface SubtitleDto {
  language: string;
  name: string;
  is_automatic: boolean;
}

export interface ResolveResult {
  video: VideoDto;
  formats: VideoFormatDto[];
  subtitles: SubtitleDto[];
  can_analyze: boolean;
  resolve_notice: string;
}

const PLATFORM_LABELS: Record<string, string> = {
  youtube: "YouTube",
  bilibili: "B 站",
  douyin: "抖音",
};

/**
 * Resolve-flow codes the product owns its own copy for (ticket #23).
 * Everything else keeps the server-issued message.
 */
const VIDEO_FLOW_MESSAGES: Record<string, string> = {
  platform_not_enabled: "抖音暂未开放",
};

const SIZE_UNITS = ["B", "KB", "MB", "GB", "TB"] as const;

export function platformLabel(platform: string): string {
  return PLATFORM_LABELS[platform] ?? platform;
}

export function videoFlowMessageForCode(code: string): string | null {
  return VIDEO_FLOW_MESSAGES[code] ?? null;
}

export function subtitleSourceLabel(isAutomatic: boolean): string {
  return isAutomatic ? "自动字幕" : "人工字幕";
}

/** `3725` → `1:02:05`, `65` → `1:05`. Invalid input clamps to `0:00`. */
export function formatDuration(seconds: number): string {
  const finite = Number.isFinite(seconds) ? seconds : 0;
  const total = Math.max(0, Math.floor(finite));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const remainder = total % 60;
  const pad = (value: number): string => String(value).padStart(2, "0");
  return hours > 0 ? `${hours}:${pad(minutes)}:${pad(remainder)}` : `${minutes}:${pad(remainder)}`;
}

/** `1536` → `1.5 KB`; unknown or invalid sizes render as `未知`. */
export function formatFileSize(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || !Number.isFinite(bytes) || bytes < 0) {
    return "未知";
  }
  if (bytes < 1024) return `${Math.round(bytes)} B`;

  let value = bytes;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < SIZE_UNITS.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  const rounded = Math.round(value * 10) / 10;
  return `${rounded} ${SIZE_UNITS[unitIndex]}`;
}
