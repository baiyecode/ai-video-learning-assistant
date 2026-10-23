import { afterEach, describe, expect, it } from "vitest";

import { ApiError, setAccessToken } from "@/lib/api";
import { connectSse, parseSseStream, type SseMessage } from "@/lib/sse";

function streamOf(chunks: readonly string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
}

async function collect(generator: AsyncGenerator<SseMessage>): Promise<SseMessage[]> {
  const messages: SseMessage[] = [];
  for await (const message of generator) messages.push(message);
  return messages;
}

afterEach(() => setAccessToken(null));

describe("parseSseStream", () => {
  it("parses events split across arbitrary chunk boundaries", async () => {
    const messages = await collect(
      parseSseStream(streamOf(["data: 你", "好\n\n", "event: delta\ndata: second\n\n"])),
    );

    expect(messages).toEqual([
      { event: "message", data: "你好", id: null },
      { event: "delta", data: "second", id: null },
    ]);
  });

  it("handles CRLF split across chunks, multi-line data and id persistence", async () => {
    const messages = await collect(
      parseSseStream(
        streamOf([
          "id: 7\r",
          "\n",
          "event: meta\r\n",
          "data: a\r\n",
          "data: b\r\n\r\n",
          ": keep-alive\n\n",
          "data: c\n\n",
        ]),
      ),
    );

    expect(messages).toEqual([
      { event: "meta", data: "a\nb", id: "7" },
      { event: "message", data: "c", id: "7" },
    ]);
  });

  it("ignores comments and blocks without data", async () => {
    const messages = await collect(
      parseSseStream(streamOf([": ping\n\n", "event: ping\n\n", "data: x\n\n"])),
    );

    expect(messages).toEqual([{ event: "message", data: "x", id: null }]);
  });

  it("flushes a trailing event that has no blank line before EOF", async () => {
    const messages = await collect(parseSseStream(streamOf(["event: done\ndata: {}"])));

    expect(messages).toEqual([{ event: "done", data: "{}", id: null }]);
  });
});

describe("connectSse", () => {
  it("reconnects after a broken stream and sends Last-Event-ID", async () => {
    const encoder = new TextEncoder();
    const requests: Headers[] = [];
    let calls = 0;

    const fetchImpl = (async (_input: string | URL | Request, init?: RequestInit) => {
      calls += 1;
      requests.push(new Headers(init?.headers));
      if (calls === 1) {
        let sent = false;
        return new Response(
          new ReadableStream<Uint8Array>({
            pull(controller) {
              if (!sent) {
                controller.enqueue(encoder.encode("id: 42\nevent: delta\ndata: hi\n\n"));
                sent = true;
                return;
              }
              controller.error(new Error("connection reset"));
            },
          }),
        );
      }
      return new Response(streamOf(["event: done\ndata: end\n\n"]));
    }) as typeof fetch;

    const messages = await collect(
      connectSse("/api/analyses/x/stream", {
        fetchImpl,
        maxRetries: 2,
        baseRetryDelayMs: 1,
        sleep: async () => undefined,
      }),
    );

    expect(messages).toEqual([
      { event: "delta", data: "hi", id: "42" },
      { event: "done", data: "end", id: null },
    ]);
    expect(calls).toBe(2);
    expect(requests[1]?.get("Last-Event-ID")).toBe("42");
  });

  it("sends the in-memory access token and accepts event-stream", async () => {
    setAccessToken("token-123");
    const seen: Headers[] = [];

    const fetchImpl = (async (_input: string | URL | Request, init?: RequestInit) => {
      seen.push(new Headers(init?.headers));
      return new Response(streamOf(["data: ok\n\n"]));
    }) as typeof fetch;

    await collect(connectSse("/api/analyses/x/stream", { fetchImpl }));

    expect(seen[0]?.get("Authorization")).toBe("Bearer token-123");
    expect(seen[0]?.get("Accept")).toBe("text/event-stream");
  });

  it("throws the unified ApiError for a client error response", async () => {
    const fetchImpl = (async () =>
      new Response(
        JSON.stringify({
          error: { code: "analysis_not_found", message: "分析不存在", details: {} },
        }),
        { status: 404, headers: { "content-type": "application/json" } },
      )) as typeof fetch;

    const attempt = collect(connectSse("/api/analyses/x/stream", { fetchImpl }));

    await expect(attempt).rejects.toBeInstanceOf(ApiError);
    await expect(attempt).rejects.toMatchObject({
      code: "analysis_not_found",
      message: "分析不存在",
    });
  });
});
