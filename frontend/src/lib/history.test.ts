import { describe, expect, it } from "vitest";

import { historyRows, sortHistoryNewestFirst, type AnalysisHistoryItemDto } from "@/lib/history";

function item(overrides: Partial<AnalysisHistoryItemDto> = {}): AnalysisHistoryItemDto {
  return {
    id: "a1",
    video_id: "v1",
    status: "completed",
    subtitle_source: "manual",
    truncated: false,
    summary_snippet: "核心要点 背景介绍",
    error_code: null,
    created_at: "2026-01-15T08:00:00+00:00",
    completed_at: "2026-01-15T08:01:00+00:00",
    video: {
      id: "v1",
      title: "示例视频",
      platform: "youtube",
      thumbnail_url: "https://img.example/cover.jpg",
    },
    ...overrides,
  };
}

describe("sortHistoryNewestFirst", () => {
  it("orders rows by creation time, newest first", () => {
    const older = item({ id: "old", created_at: "2026-01-14T08:00:00+00:00" });
    const newer = item({ id: "new", created_at: "2026-01-15T08:00:00+00:00" });

    expect(sortHistoryNewestFirst([older, newer]).map((entry) => entry.id)).toEqual([
      "new",
      "old",
    ]);
  });

  it("keeps server order for equal timestamps and leaves input untouched", () => {
    const first = item({ id: "first" });
    const second = item({ id: "second" });
    const input = [first, second];

    expect(sortHistoryNewestFirst(input).map((entry) => entry.id)).toEqual(["first", "second"]);
    expect(input.map((entry) => entry.id)).toEqual(["first", "second"]);
  });
});

describe("historyRows", () => {
  it("maps a DTO to the fields the list renders", () => {
    const [row] = historyRows([item()]);

    expect(row).toMatchObject({
      id: "a1",
      videoId: "v1",
      title: "示例视频",
      platform: "youtube",
      platformLabel: "YouTube",
      thumbnailUrl: "https://img.example/cover.jpg",
      status: "completed",
      statusLabel: "已完成",
      subtitleSourceLabel: "人工字幕",
      snippet: "核心要点 背景介绍",
      errorCode: null,
    });
    expect(row.createdLabel).toBe("01-15 16:00");
  });

  it("renders failed rows with their error code and an unknown video fallback", () => {
    const [row] = historyRows([
      item({
        status: "failed",
        summary_snippet: "",
        error_code: "analysis_failed",
        video: null,
      }),
    ]);

    expect(row.title).toBe("未知视频");
    expect(row.thumbnailUrl).toBeNull();
    expect(row.statusLabel).toBe("生成失败");
    expect(row.errorCode).toBe("analysis_failed");
    expect(row.snippet).toBe("");
  });

  it("maps automatic subtitles and keeps the newest row first", () => {
    const rows = historyRows([
      item({ id: "old", created_at: "2026-01-14T08:00:00+00:00" }),
      item({ id: "new", subtitle_source: "auto", created_at: "2026-01-15T08:00:00+00:00" }),
    ]);

    expect(rows.map((row) => row.id)).toEqual(["new", "old"]);
    expect(rows[0].subtitleSourceLabel).toBe("自动字幕");
  });
});
