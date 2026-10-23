import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, api: { get: mocks.get, post: mocks.post } };
});

import { ApiError } from "@/lib/api";
import type { DownloadDto } from "@/lib/download";
import { useDownloadStore } from "@/stores/download";

function dto(overrides: Partial<DownloadDto> = {}): DownloadDto {
  return {
    id: "d1",
    video_id: "v1",
    format_id: "best",
    status: "queued",
    progress: 0,
    error: null,
    attempts: 0,
    file_name: null,
    file_size: null,
    created_at: "2026-01-15T08:00:00+00:00",
    updated_at: "2026-01-15T08:00:00+00:00",
    ready_at: null,
    download_url: null,
    url_expires_at: null,
    file_expires_at: null,
    can_retry: false,
    ...overrides,
  };
}

function error(status: number, code: string): ApiError {
  return new ApiError(code, "失败", status);
}

beforeEach(() => {
  setActivePinia(createPinia());
  vi.clearAllMocks();
  vi.useFakeTimers();
  mocks.post.mockResolvedValue(dto());
});

afterEach(() => {
  vi.useRealTimers();
});

describe("download store polling", () => {
  it("stops polling after a terminal 4xx", async () => {
    const store = useDownloadStore();
    await store.start("v1", "best");

    mocks.get.mockRejectedValue(error(404, "download_not_found"));
    await vi.advanceTimersByTimeAsync(1000);
    expect(mocks.get).toHaveBeenCalledTimes(1);
    expect(store.error?.code).toBe("download_not_found");

    await vi.advanceTimersByTimeAsync(5000);
    expect(mocks.get).toHaveBeenCalledTimes(1);
  });

  it("keeps polling through a transient 5xx until the task becomes terminal", async () => {
    const store = useDownloadStore();
    await store.start("v1", "best");

    mocks.get.mockRejectedValueOnce(error(503, "service_unavailable"));
    await vi.advanceTimersByTimeAsync(1000);
    expect(mocks.get).toHaveBeenCalledTimes(1);
    expect(store.error?.code).toBe("service_unavailable");

    mocks.get.mockResolvedValueOnce(dto({ status: "ready", progress: 1 }));
    await vi.advanceTimersByTimeAsync(1000);
    expect(mocks.get).toHaveBeenCalledTimes(2);
    expect(store.download?.status).toBe("ready");
    expect(store.error).toBeNull();

    await vi.advanceTimersByTimeAsync(5000);
    expect(mocks.get).toHaveBeenCalledTimes(2);
  });
});
