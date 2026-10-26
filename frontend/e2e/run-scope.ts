/**
 * Shared by ``playwright.config.ts`` (which creates the per-run directory) and
 * ``e2e/global-teardown.ts`` (which removes it), so the naming contract lives once.
 */
export const RUN_ROOT_PREFIX = "ai-video-e2e-";
