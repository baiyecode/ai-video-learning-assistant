/**
 * Shared by ``playwright.config.ts`` (which creates the per-run directory) and
 * ``e2e/global-teardown.ts`` (which removes it), so the naming contract lives once.
 *
 * ``RUN_ROOT_MARKER`` makes deletion provable rather than guessed from a name: the
 * config writes it only into the directory ``fs.mkdtempSync`` created for this run, so
 * a hand-exported ``E2E_RUN_ROOT`` that merely looks like a run directory is never
 * removed. A marker left behind by a crashed run is what lets a worker process (which
 * re-evaluates the config and reuses the path) still recognise the directory as owned.
 */
import fs from "node:fs";
import path from "node:path";

export const RUN_ROOT_PREFIX = "ai-video-e2e-";

export const RUN_ROOT_MARKER = ".this-run-created-me";

/** Whether this directory carries the ownership marker written by ``createRunScope``. */
export function hasRunRootMarker(runRoot: string): boolean {
  return fs.existsSync(path.join(runRoot, RUN_ROOT_MARKER));
}
