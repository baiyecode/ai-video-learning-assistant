import { describe, expect, it } from "vitest";

import {
  formatDuration,
  formatFileSize,
  platformLabel,
  subtitleSourceLabel,
} from "@/lib/video";

describe("formatDuration", () => {
  it("renders minutes and seconds under an hour", () => {
    expect(formatDuration(0)).toBe("0:00");
    expect(formatDuration(65)).toBe("1:05");
  });

  it("renders hours, minutes and seconds", () => {
    expect(formatDuration(3600)).toBe("1:00:00");
    expect(formatDuration(3725)).toBe("1:02:05");
    expect(formatDuration(7325)).toBe("2:02:05");
  });

  it("clamps invalid input", () => {
    expect(formatDuration(-5)).toBe("0:00");
    expect(formatDuration(Number.NaN)).toBe("0:00");
  });
});

describe("formatFileSize", () => {
  it("renders bytes without units above B", () => {
    expect(formatFileSize(0)).toBe("0 B");
    expect(formatFileSize(512)).toBe("512 B");
  });

  it("renders KB, MB and GB with one decimal when needed", () => {
    expect(formatFileSize(1024)).toBe("1 KB");
    expect(formatFileSize(1536)).toBe("1.5 KB");
    expect(formatFileSize(1024 * 1024)).toBe("1 MB");
    expect(formatFileSize(100 * 1024 * 1024)).toBe("100 MB");
    expect(formatFileSize(1.5 * 1024 * 1024 * 1024)).toBe("1.5 GB");
    expect(formatFileSize(2 * 1024 * 1024 * 1024)).toBe("2 GB");
  });

  it("renders unknown sizes explicitly", () => {
    expect(formatFileSize(null)).toBe("未知");
    expect(formatFileSize(undefined)).toBe("未知");
  });
});

describe("platformLabel", () => {
  it("maps known platforms to their Chinese-facing labels", () => {
    expect(platformLabel("youtube")).toBe("YouTube");
    expect(platformLabel("bilibili")).toBe("B 站");
  });

  it("falls back to the raw platform string", () => {
    expect(platformLabel("douyin")).toBe("douyin");
  });
});

describe("subtitleSourceLabel", () => {
  it("distinguishes human and automatic subtitles", () => {
    expect(subtitleSourceLabel(false)).toBe("人工字幕");
    expect(subtitleSourceLabel(true)).toBe("自动字幕");
  });
});
