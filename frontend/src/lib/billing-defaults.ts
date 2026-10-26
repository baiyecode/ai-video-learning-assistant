/**
 * Committed fallbacks for the display price and free Quota, used only when neither the
 * runtime ``GET /me/membership`` payload nor the deploy-time ``VITE_`` injection is
 * available (prerendered marketing pages, plain ``npm run build``, unit tests).
 * The knob itself is ``Settings.subscription_monthly_usd`` / ``analysis_daily_quota``
 * in ``backend/app/config.py``: the running server reports those values on the
 * membership read (see ``MONTHLY_PRICE_USD`` in ``billing.ts``), and docker-compose
 * mirrors the same env pair into the frontend build args so the prerendered Marketing
 * Pages, sitemap and llms.txt move with them. These fallbacks must equal the backend
 * ``Settings`` defaults; ``billing.test.ts`` reads ``backend/app/config.py`` and fails
 * loudly if they drift, so the discovery layer can never silently lie.
 *
 * Kept in a dependency-free module so the Playwright config, which runs outside Vite
 * and cannot resolve the ``@/`` alias graph, can derive the same defaults.
 */
export const DEFAULT_MONTHLY_PRICE_USD = 4.99;
export const DEFAULT_DAILY_FREE_ANALYSIS_LIMIT = 3;
