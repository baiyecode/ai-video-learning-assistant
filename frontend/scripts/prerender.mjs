/**
 * Thin prerender wrapper: reuse the tested site builder from the SSR bundle.
 * Reads the client-build shell (hashed asset tags), renders every public route
 * and writes the static HTML next to the SPA shell. Any failure exits non-zero
 * and the builder's message names the offending route.
 */
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const distDir = path.join(root, "dist");
const ssrEntry = path.join(root, "dist-ssr", "entry-server.js");

const shellHtml = await readFile(path.join(distDir, "index.html"), "utf8");
const { buildSite, publicDescriptors, renderRoute, resolveSiteOrigin } = await import(
  pathToFileURL(ssrEntry).href
);

const origin = resolveSiteOrigin(process.env.VITE_SITE_ORIGIN);
const { pages } = await buildSite({
  origin,
  descriptors: publicDescriptors(),
  shellHtml,
  outputDir: distDir,
  renderRoute,
});

console.log(`[prerender] origin: ${origin}`);
for (const page of pages) {
  console.log(`[prerender] ${page.path} -> dist/${page.file}`);
}
