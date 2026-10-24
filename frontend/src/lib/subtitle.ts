/** Pure helpers and DTOs for Subtitle display and export. */

export type SubtitleSourceType = "manual" | "auto";
export type SubtitleExportFormat = "srt" | "vtt" | "txt";

export interface SubtitleCueDto {
  start: number;
  end: number;
  text: string;
}

export interface SubtitleDetailDto {
  language: string;
  source_type: SubtitleSourceType;
  text: string;
  cues: SubtitleCueDto[];
  can_analyze: boolean;
}

export const SUBTITLE_EXPORT_FORMATS: readonly SubtitleExportFormat[] = ["srt", "vtt", "txt"];

/** API path for one Video's Subtitle (JSON, or a downloadable file when ``format`` is set). */
export function subtitlePath(videoId: string, format?: SubtitleExportFormat): string {
  const base = `/videos/${encodeURIComponent(videoId)}/subtitles`;
  return format === undefined ? base : `${base}?format=${format}`;
}

/** Last-resort filename when the server did not send ``Content-Disposition``. */
export function subtitleExportFilename(videoId: string, format: SubtitleExportFormat): string {
  const safeId = videoId.replace(/[^A-Za-z0-9._-]+/g, "_") || "subtitle";
  return `${safeId}.${format}`;
}

/** Prefer the RFC 5987 ``filename*`` form, then the plain ``filename``, then ``fallback``. */
export function filenameFromContentDisposition(
  header: string | null | undefined,
  fallback: string,
): string {
  if (!header) return fallback;

  const encoded = /filename\*\s*=\s*UTF-8''([^;]+)/i.exec(header);
  if (encoded?.[1]) {
    try {
      return decodeURIComponent(encoded[1].trim().replace(/^"|"$/g, ""));
    } catch {
      // Malformed percent-encoding: fall through to the plain filename.
    }
  }

  const plain = /filename\s*=\s*"?([^";]+)"?/i.exec(header);
  return plain?.[1]?.trim() || fallback;
}
