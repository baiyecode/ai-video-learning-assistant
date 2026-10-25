/**
 * The one reader for Vite build-time arguments (``VITE_*``).
 *
 * Before this module the same job had two shapes: ``lib/billing.ts`` read
 * ``import.meta.env.VITE_*`` numbers without guarding the access (so plain Node, which
 * has no ``import.meta.env``, threw instead of falling back) while ``site/seo.ts``
 * wrapped its origin read in a ``try``. And the free Quota absorbed a fractional
 * argument through ``Math.round`` while the price path rejected junk input.
 *
 * Both shapes now live here: one guarded accessor plus one number parser whose
 * ``integer`` option refuses a fractional value outright.
 */

/** Every ``VITE_*`` argument the app reads, so a typo cannot invent a silent new knob. */
export type BuildEnvKey =
  | "VITE_SITE_ORIGIN"
  | "VITE_SUBSCRIPTION_MONTHLY_USD"
  | "VITE_ANALYSIS_DAILY_QUOTA";

/**
 * Vite replaces each of these exact ``import.meta.env.VITE_*`` property accesses with
 * the build argument at compile time, so they must stay literal here — aliasing
 * ``import.meta`` or indexing it with a variable defeats the static replacement and
 * leaves every consumer on its fallback. Plain Node (the prerender bundle and unit
 * tests outside Vite) has no ``import.meta.env`` at all, so the access throws: the
 * ``try`` turns that into "no build args", which is exactly what the callers expect.
 */
function buildEnvArgs(): Partial<Record<BuildEnvKey, string | undefined>> {
  try {
    return {
      VITE_SITE_ORIGIN: import.meta.env.VITE_SITE_ORIGIN,
      VITE_SUBSCRIPTION_MONTHLY_USD: import.meta.env.VITE_SUBSCRIPTION_MONTHLY_USD,
      VITE_ANALYSIS_DAILY_QUOTA: import.meta.env.VITE_ANALYSIS_DAILY_QUOTA,
    };
  } catch {
    return {};
  }
}

/** The raw build argument, or ``undefined`` when it was never injected. */
export function readBuildEnv(key: BuildEnvKey): string | undefined {
  const raw = buildEnvArgs()[key];
  return raw === undefined || raw === "" ? undefined : raw;
}

/**
 * A numeric build argument with a committed fallback. Absent, unparseable, non-finite
 * or non-positive input falls back — a typo in a deploy arg must never render a
 * ``$NaN/月`` headline or a zero allowance. ``integer`` is for values the backend
 * models as ``int`` (the free Quota): a fractional argument is refused rather than
 * quietly rounded, because the marketing copy would then promise a number nobody
 * enforces.
 */
export function readBuildEnvNumber(
  key: BuildEnvKey,
  fallback: number,
  options: { integer?: boolean } = {},
): number {
  const raw = readBuildEnv(key);
  if (raw === undefined) return fallback;
  const parsed = Number(raw);
  if (!Number.isFinite(parsed) || parsed <= 0) return fallback;
  if (options.integer && !Number.isInteger(parsed)) return fallback;
  return parsed;
}
