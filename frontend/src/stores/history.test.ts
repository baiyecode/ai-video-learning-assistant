import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, api: { get: mocks.get } };
});

import { ApiError } from "@/lib/api";
import type { AnalysisHistoryItemDto } from "@/lib/history";
import { useHistoryStore } from "@/stores/history";

const QUOTA = { daily_limit: 3, used: 1, remaining: 2, resets_at: "2026-01-16T00:00:00+08:00" };

function item(overrides: Partial<AnalysisHistoryItemDto> = {}): AnalysisHistoryItemDto {
  return {
    id: "a1",
    video_id: "v1",
    status: "completed",
    subtitle_source: "manual",
    truncated: false,
    summary_snippet: "背景介绍",
    error_code: null,
    created_at: "2026-01-15T08:00:00+00:00",
    completed_at: null,
    video: { id: "v1", title: "示例视频", platform: "youtube", thumbnail_url: null },
    ...overrides,
  };
}

beforeEach(() => {
  setActivePinia(createPinia());
  vi.clearAllMocks();
});

describe("history store", () => {
  it("loads the Account's analyses newest first together with Quota", async () => {
    mocks.get.mockImplementation((path: string) =>
      path === "/me"
        ? Promise.resolve({ quota: QUOTA })
        : Promise.resolve([
            item({ id: "old", created_at: "2026-01-14T08:00:00+00:00" }),
            item({ id: "new", created_at: "2026-01-15T08:00:00+00:00" }),
          ]),
    );

    const store = useHistoryStore();
    await store.load();

    expect(mocks.get).toHaveBeenCalledWith("/analyses");
    expect(store.items.map((entry) => entry.id)).toEqual(["new", "old"]);
    expect(store.quota?.remaining).toBe(2);
    expect(store.loading).toBe(false);
    expect(store.error).toBeNull();
  });

  it("surfaces the API message when the list cannot be loaded", async () => {
    mocks.get.mockImplementation((path: string) =>
      path === "/me"
        ? Promise.resolve({ quota: QUOTA })
        : Promise.reject(new ApiError("auth_required", "请先登录", 401)),
    );

    const store = useHistoryStore();
    await store.load();

    expect(store.items).toEqual([]);
    expect(store.error).toBe("请先登录");
    expect(store.loading).toBe(false);
  });
});
