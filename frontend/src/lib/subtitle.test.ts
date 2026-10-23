import { describe, expect, it } from "vitest";

import {
  filenameFromContentDisposition,
  subtitleExportFilename,
  subtitlePath,
} from "@/lib/subtitle";

describe("subtitlePath", () => {
  it("returns the JSON endpoint without a format", () => {
    expect(subtitlePath("abc123")).toBe("/videos/abc123/subtitles");
  });

  it("appends the export format and encodes the video id", () => {
    expect(subtitlePath("a b/c", "srt")).toBe("/videos/a%20b%2Fc/subtitles?format=srt");
    expect(subtitlePath("abc123", "vtt")).toBe("/videos/abc123/subtitles?format=vtt");
  });
});

describe("subtitleExportFilename", () => {
  it("builds a fallback filename from the video id and format", () => {
    expect(subtitleExportFilename("abc123", "txt")).toBe("abc123.txt");
  });

  it("replaces characters that are unsafe in a filename", () => {
    expect(subtitleExportFilename("a/b:c", "srt")).toBe("a_b_c.srt");
  });
});

describe("filenameFromContentDisposition", () => {
  it("reads the quoted filename", () => {
    expect(
      filenameFromContentDisposition(
        'attachment; filename="youtube-dQw4w9WgXcQ.srt"',
        "fallback.srt",
      ),
    ).toBe("youtube-dQw4w9WgXcQ.srt");
  });

  it("prefers the RFC 5987 encoded filename", () => {
    const header =
      "attachment; filename=\"youtube-id.vtt\"; filename*=UTF-8''%E5%AD%97%E5%B9%95.vtt";
    expect(filenameFromContentDisposition(header, "fallback.vtt")).toBe("字幕.vtt");
  });

  it("falls back when the header is missing or has no filename", () => {
    expect(filenameFromContentDisposition(null, "fallback.txt")).toBe("fallback.txt");
    expect(filenameFromContentDisposition("attachment", "fallback.txt")).toBe("fallback.txt");
    expect(filenameFromContentDisposition("attachment; filename*=UTF-8''%E0%A4%A", "x.txt")).toBe(
      "x.txt",
    );
  });
});
