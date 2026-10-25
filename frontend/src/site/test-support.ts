/**
 * Shared fixtures for the artifact-seam tests: one client-build shell literal
 * (hashed asset tags, an empty ``#app`` mount and stale head values to replace)
 * plus the temp-directory helper every spec previously copied.
 */
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

import { afterEach } from "vitest";

export const SHELL = [
  "<!doctype html>",
  '<html lang="zh-CN">',
  "  <head>",
  '    <meta charset="UTF-8" />',
  '    <meta name="description" content="stale shell description" />',
  "    <title>AI 视频学习助手</title>",
  '    <link rel="stylesheet" href="/assets/index-abc123.css" />',
  "  </head>",
  '  <body class="bg-slate-50">',
  '    <div id="app"></div>',
  '    <script type="module" src="/assets/index-abc123.js"></script>',
  "  </body>",
  "</html>",
].join("\n");

export async function createTempDir(prefix: string): Promise<string> {
  return mkdtemp(path.join(tmpdir(), prefix));
}

export async function removeTempDirs(dirs: readonly string[]): Promise<void> {
  await Promise.all(dirs.map((dir) => rm(dir, { recursive: true, force: true })));
}

/** Temp-dir factory whose directories are removed after each test. */
export function useTempDirs(prefix: string): () => Promise<string> {
  const created: string[] = [];

  afterEach(async () => {
    await removeTempDirs(created.splice(0));
  });

  return async () => {
    const dir = await createTempDir(prefix);
    created.push(dir);
    return dir;
  };
}
