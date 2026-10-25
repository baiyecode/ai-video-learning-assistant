/**
 * Route paths that are not prerendered Marketing Pages: the private app
 * surface. robots.txt excludes them, the internal-link audit treats them as
 * legitimate navigation targets, and the router consistency test asserts the
 * real route table still contains every entry.
 */
export const PRIVATE_APP_ROUTES = ["/login", "/account", "/analyses", "/verify-email"] as const;

/** Parameterized Analysis detail route; matched by pattern in the link audit. */
export const ANALYSIS_DETAIL_ROUTE = "/analyses/:id";

/** The non-indexable SPA shell served for private routes. */
export const APP_SHELL_PATH = "/app.html";
