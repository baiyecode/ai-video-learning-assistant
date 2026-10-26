/**
 * Ticket #47 seam: the repricing story asserted through the built artifacts.
 * One test injects a non-default ``VITE_`` price/quota pair (the same stub pattern
 * ``billing.test.ts`` uses for the mirror) and asserts the prerendered seed Article
 * pages, their meta descriptions and the pricing page all carry the injected value
 * verbatim — the single-source mirror extended from the marketing pages to Articles.
 * The other pins the user story that the prerendered (SSR) Article HTML and a client
 * mount of the same route show the interpolated text character-for-character, so
 * hydration cannot drift from the published artifact.
 *
 * Everything is imported fresh inside each test (``vi.resetModules``) because the
 * placeholder values are resolved once per module graph at init; only observable
 * artifact text is asserted, never the interpolation internals.
 */
// @vitest-environment jsdom
import { readFile } from "node:fs/promises";
import path from "node:path";

import { JSDOM } from "jsdom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SHELL, useTempDirs } from "@/site/test-support";

const ORIGIN = "https://example.com";
const tempDir = useTempDirs("article-repricing-");

const SEED_SLUGS = [
  "ai-video-summary-mindmap",
  "bilibili-subtitle-download",
  "youtube-study-notes",
  "douyin-video-parsing",
] as const;

function parse(html: string): Document {
  return new JSDOM(html).window.document;
}

function findNodeOfType(value: unknown, type: string): Record<string, unknown> | undefined {
  if (Array.isArray(value)) {
    for (const item of value) {
      const found = findNodeOfType(item, type);
      if (found) return found;
    }
  } else if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    if (record["@type"] === type) return record;
    for (const item of Object.values(record)) {
      const found = findNodeOfType(item, type);
      if (found) return found;
    }
  }
  return undefined;
}

/** The first visible ``$X.XX/月`` headline on a page, or null. */
function visiblePrice(text: string): string | undefined {
  return text.match(/\$\d+\.\d{2}\/月/)?.[0];
}

afterEach(() => {
  vi.unstubAllEnvs();
  vi.resetModules();
});

describe("repriced Article artifacts", () => {
  it(
    "renders the injected price and Quota into every Article page, its meta description and the pricing page",
    async () => {
      const outDir = await tempDir();

      // A repricing/re-quota deploy: same VITE_ knobs the pricing page already reads.
      vi.resetModules();
      vi.stubEnv("VITE_SUBSCRIPTION_MONTHLY_USD", "8.50");
      vi.stubEnv("VITE_ANALYSIS_DAILY_QUOTA", "5");
      const [{ buildSite }, { renderRoute }, { pageDescriptors }] = await Promise.all([
        import("@/site/build-site"),
        import("@/site/entry-server"),
        import("@/site/seo"),
      ]);

      await buildSite({
        origin: ORIGIN,
        descriptors: pageDescriptors,
        shellHtml: SHELL,
        outputDir: outDir,
        renderRoute,
      });

      for (const slug of SEED_SLUGS) {
        const document = parse(
          await readFile(path.join(outDir, "articles", `${slug}.html`), "utf8"),
        );
        const text = document.body.textContent ?? "";
        expect(text, `${slug} states the injected price`).toContain("$8.50/月");
        expect(text, `${slug} states the injected Quota`).toContain("5 次");
        expect(text, `${slug} hides the default price`).not.toContain("$4.99/月");
        expect(text, `${slug} hides the default Quota claim`).not.toContain("3 次");
        expect(text, `${slug} leaks no placeholder`).not.toContain("{{");
      }

      // The Article whose frontmatter description promises price and Quota: the SEO
      // meta must move with the body (same interpolated description feeds both).
      const mindmap = parse(
        await readFile(path.join(outDir, "articles", "ai-video-summary-mindmap.html"), "utf8"),
      );
      const description =
        mindmap.querySelector('meta[name="description"]')?.getAttribute("content") ?? "";
      expect(description).toContain("每日 5 次");
      expect(description).toContain("$8.50/月");
      expect(description).not.toContain("$4.99/月");

      // Same-source mirror: the pricing page shows the very same injected headline.
      const pricing = parse(await readFile(path.join(outDir, "pricing.html"), "utf8"));
      const pricingText = pricing.body.textContent ?? "";
      expect(visiblePrice(pricingText)).toBe("$8.50/月");
      expect(pricingText).toContain("自然日 5 次");
      const offer = findNodeOfType(
        JSON.parse(
          pricing.querySelector('script[type="application/ld+json"]')?.textContent ?? "{}",
        ),
        "Offer",
      );
      expect(offer?.price).toBe(8.5);

      // GEO artifact: llms.txt quotes the same interpolated facts, so an answer
      // engine cannot read a stale price or Quota out of it.
      const llms = await readFile(path.join(outDir, "llms.txt"), "utf8");
      expect(llms).toContain("$8.50/月");
      expect(llms).toContain("每日 5 次");
      expect(llms).not.toContain("$4.99/月");

      // The identical injected string appears verbatim on an Article page and the
      // pricing page — one knob, one price everywhere.
      const articleText = mindmap.body.textContent ?? "";
      expect(visiblePrice(articleText)).toBe(visiblePrice(pricingText));
    },
    60_000,
  );
});

describe("Article SSR/client rendering parity", () => {
  it("renders the interpolated Article text verbatim the same in SSR and a client mount", async () => {
    vi.resetModules();
    const [{ renderRoute }, { defaultArticleCollection }, vue, { createPinia }, { createMemoryHistory }] =
      await Promise.all([
        import("@/site/entry-server"),
        import("@/site/article-sources"),
        import("vue"),
        import("pinia"),
        import("vue-router"),
      ]);
    const [{ default: App }, { createAppRouter }, { ARTICLES_KEY }] = await Promise.all([
      import("@/App.vue"),
      import("@/router"),
      import("@/site/article-sources"),
    ]);

    const routePath = "/articles/ai-video-summary-mindmap";
    const collection = defaultArticleCollection();
    const { html } = await renderRoute(routePath, collection);
    const ssrArticle = parse(`<div id="app">${html}</div>`).querySelector("article");
    expect(ssrArticle).not.toBeNull();

    const container = document.createElement("div");
    document.body.appendChild(container);
    // ``entry-server`` shims window/document/HTMLElement but not every constructor the
    // client mount consults; supply the ones Vue's runtime-dom looks up on the global.
    const scope = globalThis as unknown as Record<string, unknown>;
    const shimWindow = scope.window as Record<string, unknown>;
    for (const key of ["SVGElement", "MathMLElement"]) {
      if (scope[key] === undefined && shimWindow[key] !== undefined) scope[key] = shimWindow[key];
    }
    const app = vue.createApp(App);
    app.use(createPinia());
    app.provide(ARTICLES_KEY, collection);
    const router = createAppRouter(createMemoryHistory(), { updateHead: false });
    app.use(router);
    await router.push(routePath);
    await router.isReady();
    app.mount(container);
    await vue.nextTick();

    const clientArticle = container.querySelector("article");
    expect(clientArticle).not.toBeNull();

    // The compared text must actually be interpolated content, not untouched copy:
    // the built-in defaults render the placeholder into the same sentences.
    expect(ssrArticle!.textContent).toContain("$4.99/月");
    expect(ssrArticle!.textContent).toContain("每日 3 次");
    expect(ssrArticle!.textContent).not.toContain("{{");

    // Verbatim parity between the prerendered artifact text and the client render.
    expect(clientArticle!.textContent).toBe(ssrArticle!.textContent);

    app.unmount();
    container.remove();
  }, 60_000);
});
