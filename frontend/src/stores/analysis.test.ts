import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  connectSse: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, api: { get: mocks.get, post: mocks.post } };
});

vi.mock("@/lib/sse", () => ({ connectSse: mocks.connectSse }));

import type { AnalysisDto } from "@/lib/analysis";
import type { SseMessage } from "@/lib/sse";
import { useAnalysisStore } from "@/stores/analysis";

function event(name: string, data: unknown): SseMessage {
  return { event: name, data: JSON.stringify(data), id: null };
}

const QUOTA = { daily_limit: 3, used: 1, remaining: 2, resets_at: "2026-01-16T00:00:00+08:00" };

function dto(overrides: Partial<AnalysisDto> = {}): AnalysisDto {
  return {
    id: "a1",
    video_id: "v1",
    status: "streaming",
    summary_markdown: "",
    mindmap_markdown: "",
    subtitle_source: "manual",
    truncated: false,
    error: null,
    created_at: "2026-01-15T08:00:00+00:00",
    updated_at: "2026-01-15T08:00:00+00:00",
    completed_at: null,
    video: {
      id: "v1",
      title: "示例视频",
      platform: "youtube",
      duration_seconds: 300,
      thumbnail_url: null,
    },
    ...overrides,
  };
}

async function* scripted(messages: SseMessage[]) {
  for (const message of messages) yield message;
}

beforeEach(() => {
  setActivePinia(createPinia());
  vi.clearAllMocks();
  mocks.get.mockResolvedValue({ quota: QUOTA });
});

describe("analysis store", () => {
  it("loads the persisted result and then follows the SSE stream", async () => {
    mocks.get.mockImplementation((path: string) =>
      path === "/me" ? Promise.resolve({ quota: QUOTA }) : Promise.resolve(dto()),
    );
    mocks.connectSse.mockReturnValue(
      scripted([
        event("meta", {
          analysis_id: "a1",
          video_id: "v1",
          status: "streaming",
          subtitle_source: "auto",
          truncated: true,
        }),
        event("delta", { text: "## 要点\n" }),
        event("delta", { text: "- 结论" }),
        event("mindmap", { markdown: "- 主题" }),
        event("done", { status: "completed" }),
      ]),
    );

    const store = useAnalysisStore();
    await store.open("a1");

    expect(mocks.connectSse).toHaveBeenCalledWith(
      "/api/analyses/a1/stream",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(store.status).toBe("completed");
    expect(store.summary).toBe("## 要点\n- 结论");
    expect(store.mindmap).toBe("- 主题");
    expect(store.subtitleSource).toBe("auto");
    expect(store.truncated).toBe(true);
    expect(store.streaming).toBe(false);
    await Promise.resolve();
    expect(store.quota?.remaining).toBe(2);
  });

  it("does not stream a failed analysis but keeps the error and video for retry", async () => {
    mocks.get.mockResolvedValue(
      dto({ status: "failed", error: { code: "analysis_failed", message: "生成失败" } }),
    );

    const store = useAnalysisStore();
    await store.open("a1");

    expect(mocks.connectSse).not.toHaveBeenCalled();
    expect(store.status).toBe("failed");
    expect(store.error).toEqual({ code: "analysis_failed", message: "生成失败" });
    expect(store.videoId).toBe("v1");

    mocks.post.mockResolvedValue(dto({ id: "a2", status: "pending" }));
    await expect(store.retry()).resolves.toBe("a2");
    expect(mocks.post).toHaveBeenCalledWith("/analyses", { video_id: "v1" });
  });

  it("surfaces a stream error as a stable code", async () => {
    mocks.get.mockResolvedValue(dto());
    mocks.connectSse.mockReturnValue(
      (async function* () {
        throw new Error("connection lost");
      })(),
    );

    const store = useAnalysisStore();
    await store.open("a1");

    expect(store.error?.code).toBe("network_error");
    expect(store.streaming).toBe(false);
  });
});
