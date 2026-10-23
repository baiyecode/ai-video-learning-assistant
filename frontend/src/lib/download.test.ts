import { describe, expect, it } from "vitest";

import {
  downloadStatusLabel,
  formatCountdown,
  formatProgress,
  formatQueuePosition,
  isTerminalStatus,
  remainingSeconds,
} from "@/lib/download";

describe("downloadStatusLabel", () => {
  it("maps every Download state to its Chinese label", () => {
    expect(downloadStatusLabel("queued")).toBe("排队中");
    expect(downloadStatusLabel("downloading")).toBe("下载中");
    expect(downloadStatusLabel("merging")).toBe("合并中");
    expect(downloadStatusLabel("ready")).toBe("已完成");
    expect(downloadStatusLabel("failed")).toBe("失败");
    expect(downloadStatusLabel("expired")).toBe("已过期");
  });

  it("falls back to the raw status", () => {
    expect(downloadStatusLabel("unknown_state")).toBe("unknown_state");
  });
});

describe("isTerminalStatus", () => {
  it("stops polling for ready, failed and expired", () => {
    expect(isTerminalStatus("ready")).toBe(true);
    expect(isTerminalStatus("failed")).toBe(true);
    expect(isTerminalStatus("expired")).toBe(true);
  });

  it("keeps polling while the task is in flight", () => {
    expect(isTerminalStatus("queued")).toBe(false);
    expect(isTerminalStatus("downloading")).toBe(false);
    expect(isTerminalStatus("merging")).toBe(false);
  });
});

describe("formatProgress", () => {
  it("renders a rounded percentage", () => {
    expect(formatProgress(0)).toBe("0%");
    expect(formatProgress(0.456)).toBe("46%");
    expect(formatProgress(1)).toBe("100%");
  });

  it("clamps out-of-range and invalid values", () => {
    expect(formatProgress(-0.2)).toBe("0%");
    expect(formatProgress(1.7)).toBe("100%");
    expect(formatProgress(Number.NaN)).toBe("0%");
  });
});

describe("formatQueuePosition", () => {
  it("renders the 1-based FIFO position", () => {
    expect(formatQueuePosition(1)).toBe("（第 1 位）");
    expect(formatQueuePosition(4)).toBe("（第 4 位）");
  });

  it("renders nothing when the task is not waiting", () => {
    expect(formatQueuePosition(null)).toBe("");
    expect(formatQueuePosition(undefined)).toBe("");
    expect(formatQueuePosition(0)).toBe("");
    expect(formatQueuePosition(Number.NaN)).toBe("");
  });
});

describe("remainingSeconds", () => {
  const now = Date.parse("2026-01-15T08:00:00Z");

  it("counts down to the signed URL expiry", () => {
    expect(remainingSeconds("2026-01-15T08:15:00Z", now)).toBe(900);
    expect(remainingSeconds("2026-01-15T08:00:30Z", now)).toBe(30);
  });

  it("returns zero once expired or when the expiry is unknown", () => {
    expect(remainingSeconds("2026-01-15T07:59:00Z", now)).toBe(0);
    expect(remainingSeconds(null, now)).toBe(0);
    expect(remainingSeconds("not-a-date", now)).toBe(0);
  });
});

describe("formatCountdown", () => {
  it("renders mm:ss under an hour", () => {
    expect(formatCountdown(900)).toBe("15:00");
    expect(formatCountdown(65)).toBe("1:05");
    expect(formatCountdown(59)).toBe("0:59");
  });

  it("renders h:mm:ss from one hour up", () => {
    expect(formatCountdown(3600)).toBe("1:00:00");
    expect(formatCountdown(3725)).toBe("1:02:05");
  });

  it("clamps invalid or negative input", () => {
    expect(formatCountdown(0)).toBe("0:00");
    expect(formatCountdown(-5)).toBe("0:00");
    expect(formatCountdown(Number.NaN)).toBe("0:00");
  });
});
