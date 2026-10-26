/**
 * Removes the run-scoped directory that ``playwright.config.ts`` created for this
 * e2e run (see ``E2E_RUN_ROOT`` there).
 *
 * Two conditions must both hold before anything is deleted:
 *   - the path is a direct child of the OS temp directory and carries the run-scope
 *     prefix produced by ``fs.mkdtempSync``, and
 *   - the directory contains the ownership marker ``createRunScope`` writes into the
 *     directory *it* created.
 * The second condition is what makes a hand-exported ``E2E_RUN_ROOT`` safe: a path
 * this run merely inherited was not created by it, so it keeps its contents. That
 * means the hook can only ever target a directory this run made under the OS temp
 * directory - never a repository, development or production path.
 */

import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { RUN_ROOT_PREFIX, hasRunRootMarker } from "./run-scope";

function removeRunRoot(runRoot: string): void {
  const options = { recursive: true, force: true, maxRetries: 5, retryDelay: 100 } as const;
  try {
    fs.rmSync(runRoot, options);
  } catch (error) {
    // Playwright runs global teardown before it stops the web servers, and on
    // Windows the running backend keeps the SQLite files locked. Disposing of the
    // servers happens right after this hook, so retry once more at process exit.
    const code = (error as NodeJS.ErrnoException).code;
    if (code !== "EBUSY" && code !== "EPERM" && code !== "EACCES" && code !== "ENOTEMPTY") {
      throw error;
    }
    process.once("exit", () => {
      try {
        fs.rmSync(runRoot, options);
      } catch {
        // Best effort: the OS temp cleaner will eventually reclaim the leftovers.
      }
    });
  }
}

export default function globalTeardown(): void {
  const runRoot = process.env.E2E_RUN_ROOT;
  if (!runRoot) {
    return;
  }

  const resolvedRunRoot = path.resolve(runRoot);
  const resolvedTempDir = path.resolve(os.tmpdir());
  const isRunScaffold =
    resolvedRunRoot !== resolvedTempDir &&
    path.dirname(resolvedRunRoot) === resolvedTempDir &&
    path.basename(resolvedRunRoot).startsWith(RUN_ROOT_PREFIX);
  if (!isRunScaffold || !hasRunRootMarker(resolvedRunRoot)) {
    return;
  }

  removeRunRoot(resolvedRunRoot);
}
