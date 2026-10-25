/**
 * Deploy wiring, asserted on the real config files: nginx routing/headers,
 * the Docker build arg and the compose/env plumbing for the site origin. This
 * is a static contract test (no Docker, no network); the runtime curl checks
 * live in the README deployment checklist.
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { PRIVATE_APP_ROUTES } from "@/site/routes";

const FRONTEND_ROOT = path.resolve(fileURLToPath(new URL("../..", import.meta.url)));
const REPO_ROOT = path.resolve(FRONTEND_ROOT, "..");

function read(...segments: string[]): string {
  return readFileSync(path.join(...segments), "utf8");
}

const nginx = read(FRONTEND_ROOT, "nginx.conf");
const dockerfile = read(FRONTEND_ROOT, "Dockerfile");
const compose = read(REPO_ROOT, "docker-compose.yml");
const envExample = read(REPO_ROOT, ".env.example");

/** The body of one nginx block, located by its opening line. */
function block(config: string, opening: string): string {
  const start = config.indexOf(opening);
  expect(start, `missing nginx block: ${opening}`).toBeGreaterThan(-1);
  const end = config.indexOf("\n    }", start);
  expect(end, `unterminated nginx block: ${opening}`).toBeGreaterThan(start);
  return config.slice(start, end);
}

describe("nginx.conf", () => {
  it("keeps the /api/ and /health proxies exactly as before", () => {
    const api = block(nginx, "location /api/ {");
    expect(api).toContain("proxy_pass http://api:8000;");
    expect(api).toContain("proxy_set_header X-Request-ID $request_id;");
    expect(api).toContain("proxy_buffering off;");
    expect(api).toContain("proxy_read_timeout 3600s;");
    expect(api).toContain("client_max_body_size 2m;");

    const health = block(nginx, "location = /health {");
    expect(health).toContain("proxy_pass http://api:8000/health;");
    expect(health).toContain("access_log off;");
  });

  it("resolves public pages as file -> .html -> directory -> 404, never to index.html", () => {
    const root = block(nginx, "location / {");
    expect(root).toContain("try_files $uri $uri.html $uri/ =404;");
    expect(root).toContain('Cache-Control "no-cache"');
  });

  it("serves private routes from the noindex app.html shell", () => {
    const alternation = PRIVATE_APP_ROUTES.map((route) => route.slice(1)).join("|");
    const privateRoutes = block(nginx, `location ~ ^/(${alternation})`);
    expect(privateRoutes).toContain("try_files /app.html =404;");
    expect(privateRoutes).toContain('X-Robots-Tag "noindex, nofollow"');
    expect(privateRoutes).toContain('Cache-Control "no-cache"');
  });

  it("returns real 404s through 404.html with a noindex header", () => {
    expect(nginx).toContain("error_page 404 /404.html;");
    expect(nginx).not.toMatch(/try_files[^;]*\/index\.html/);

    const notFound = block(nginx, "location = /404.html {");
    expect(notFound).toContain('X-Robots-Tag "noindex, nofollow"');
    expect(notFound).toContain('Cache-Control "no-cache"');
  });

  it("keeps HTML uncached, hashed assets immutable and discovery files short-lived", () => {
    const assets = block(nginx, "location /assets/ {");
    expect(assets).toContain("expires 1y;");
    expect(assets).toContain("immutable");

    const discovery = block(nginx, "location ~ ^/(sitemap");
    expect(discovery).toContain("max-age=3600");
  });

  it("gzip covers HTML, CSS, JS, JSON, XML and plain text", () => {
    const gzip = block(nginx, "gzip_types");
    for (const type of [
      "text/html",
      "text/css",
      "application/javascript",
      "application/json",
      "application/xml",
      "text/plain",
    ]) {
      expect(gzip).toContain(type);
    }
  });
});

describe("site origin deploy wiring", () => {
  it("bakes VITE_SITE_ORIGIN into the Docker build next to the Sentry arg", () => {
    expect(dockerfile).toContain('ARG VITE_SITE_ORIGIN="http://localhost:8080"');
    expect(dockerfile).toContain("ENV VITE_SITE_ORIGIN=$VITE_SITE_ORIGIN");
    expect(dockerfile).toContain('ARG VITE_SENTRY_DSN=""');
  });

  it("passes SITE_ORIGIN from compose into the web build", () => {
    expect(compose).toMatch(/VITE_SITE_ORIGIN: \$\{SITE_ORIGIN:-http:\/\/localhost:8080\}/);
  });

  it("documents SITE_ORIGIN as a bare origin that must match APP_FRONTEND_BASE_URL", () => {
    expect(envExample).toMatch(/^SITE_ORIGIN=http:\/\/localhost:8080$/m);
    expect(envExample).toMatch(/APP_FRONTEND_BASE_URL/);
    expect(envExample).toMatch(/https origin/i);
  });
});

describe("billing single-source deploy wiring", () => {
  it("bakes the price and free-quota mirrors into the Docker build", () => {
    expect(dockerfile).toContain('ARG VITE_ANALYSIS_DAILY_QUOTA="3"');
    expect(dockerfile).toContain("ENV VITE_ANALYSIS_DAILY_QUOTA=$VITE_ANALYSIS_DAILY_QUOTA");
    expect(dockerfile).toContain('ARG VITE_SUBSCRIPTION_MONTHLY_USD="4.99"');
    expect(dockerfile).toContain(
      "ENV VITE_SUBSCRIPTION_MONTHLY_USD=$VITE_SUBSCRIPTION_MONTHLY_USD",
    );
  });

  it("feeds the web build from the SAME env vars the api enforces", () => {
    // One repricing/re-quota edit (the APP_ env) drives backend enforcement AND the
    // static marketing, so the two can never drift into a silent lie.
    expect(compose).toMatch(
      /VITE_ANALYSIS_DAILY_QUOTA: \$\{APP_ANALYSIS_DAILY_QUOTA:-3\}/,
    );
    expect(compose).toMatch(
      /VITE_SUBSCRIPTION_MONTHLY_USD: \$\{APP_SUBSCRIPTION_MONTHLY_USD:-4\.99\}/,
    );
    expect(compose).toMatch(/APP_ANALYSIS_DAILY_QUOTA: \$\{APP_ANALYSIS_DAILY_QUOTA:-3\}/);
  });

  it("documents the mirrored VITE_ quota/price in the env example", () => {
    expect(envExample).toMatch(/VITE_ANALYSIS_DAILY_QUOTA/);
    expect(envExample).toMatch(/VITE_SUBSCRIPTION_MONTHLY_USD/);
  });
});
