/**
 * Removes the run-scoped directory that ``playwright.config.ts`` created for this
 * e2e run (see ``E2E_RUN_ROOT`` there).
 *
 * The guard is deliberately strict: only a directory that
 *   - is a direct child of the OS temp directory, and
 *   - carries the run-scope prefix produced by ``fs.mkdtempSync``,
 * is deleted. That check means the hook can only ever target a Playwright run
 * directory under the OS temp directory - never a repository, development or
 * production path. A hand-provided ``E2E_RUN_ROOT`` with a different shape is
 * left untouched.
 */

import fs from "node:fs";
import os from "node:os";
import path from "node:path";

/** Must match the ``fs.mkdtempSync`` prefix in ``playwright.config.ts``. */
const RUN_ROOT_PREFIX = "ai-video-e2e-";

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
  const isOwnRunDir =
    resolvedRunRoot !== resolvedTempDir &&
    path.dirname(resolvedRunRoot) === resolvedTempDir &&
    path.basename(resolvedRunRoot).startsWith(RUN_ROOT_PREFIX);
  if (!isOwnRunDir) {
    return;
  }

  removeRunRoot(resolvedRunRoot);
}
