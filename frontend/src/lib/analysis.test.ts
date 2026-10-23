import { describe, expect, it } from "vitest";

import {
  type AnalysisStreamState,
  analysisStatusLabel,
  applyAnalysisEvent,
  formatQuota,
  formatQuotaReset,
  formatShanghaiDateTime,
  initialStreamState,
  visibleSummary,
} from "@/lib/analysis";
import type { SseMessage } from "@/lib/sse";

function event(name: string, data: unknown): SseMessage {
  return { event: name, data: JSON.stringify(data), id: null };
}

function applyAll(messages: SseMessage[]): AnalysisStreamState {
  return messages.reduce(applyAnalysisEvent, initialStreamState());
}

const META = event("meta", {
  analysis_id: "a1",
  video_id: "v1",
  status: "streaming",
  subtitle_source: "manual",
  truncated: false,
});

describe("applyAnalysisEvent", () => {
  it("follows the meta → delta* → mindmap → done order", () => {
    const state = applyAll([
      META,
      event("delta", { text: "## 要点\n" }),
      event("delta", { text: "- 第一点" }),
      event("mindmap", { markdown: "- 主题\n  - 子主题" }),
      event("done", { status: "completed" }),
    ]);

    expect(state.summary).toBe("## 要点\n- 第一点");
    expect(state.mindmap).toBe("- 主题\n  - 子主题");
    expect(state.status).toBe("completed");
    expect(state.done).toBe(true);
    expect(state.error).toBeNull();
    expect(state.subtitleSource).toBe("manual");
  });

  it("replays from meta after a reconnect without duplicating text", () => {
    const beforeDrop = applyAll([META, event("delta", { text: "第一段" })]);
    expect(beforeDrop.summary).toBe("第一段");

    // connectSse reconnects after a broken stream; the server replays from `meta`.
    const resumed = [
      META,
      event("delta", { text: "第一段" }),
      event("delta", { text: "续写" }),
      event("done", { status: "completed" }),
    ].reduce(applyAnalysisEvent, beforeDrop);

    expect(resumed.summary).toBe("第一段续写");
    expect(resumed.done).toBe(true);
  });

  it("marks the stream failed with a stable code and message", () => {
    const state = applyAll([
      META,
      event("delta", { text: "半截" }),
      event("error", { code: "analysis_failed", message: "AI 生成失败，请稍后重试" }),
    ]);

    expect(state.status).toBe("failed");
    expect(state.done).toBe(true);
    expect(state.error).toEqual({ code: "analysis_failed", message: "AI 生成失败，请稍后重试" });
    expect(state.summary).toBe("半截");
  });

  it("ignores unknown events and malformed data", () => {
    const state = applyAll([
      META,
      { event: "heartbeat", data: "{}", id: null },
      { event: "delta", data: "not json", id: null },
      event("delta", { text: "ok" }),
    ]);

    expect(state.summary).toBe("ok");
  });
});

describe("summary and quota presentation", () => {
  it("hides a mindmap section that leaked into the summary text", () => {
    expect(visibleSummary("## 要点\n正文\n## 思维导图\n- 主题")).toBe("## 要点\n正文");
    expect(visibleSummary("## 要点\n正文")).toBe("## 要点\n正文");
  });

  it("formats remaining quota", () => {
    expect(formatQuota({ daily_limit: 3, used: 1, remaining: 2, resets_at: "" })).toBe(
      "剩余 2 / 3 次",
    );
    expect(formatQuota(null)).toBe("Quota 加载中");
  });

  it("formats the Quota reset time in Asia/Shanghai", () => {
    expect(formatShanghaiDateTime("2026-01-16T00:00:00+08:00")).toBe("01-16 00:00");
    expect(formatQuotaReset("2026-01-16T00:00:00+08:00")).toBe("将于 01-16 00:00 重置");
    expect(formatQuotaReset("not-a-date")).toBe("");
    expect(formatQuotaReset(null)).toBe("");
  });

  it("labels statuses in Simplified Chinese", () => {
    expect(analysisStatusLabel("pending")).toBe("排队中");
    expect(analysisStatusLabel("streaming")).toBe("生成中");
    expect(analysisStatusLabel("completed")).toBe("已完成");
    expect(analysisStatusLabel("failed")).toBe("生成失败");
  });
});
