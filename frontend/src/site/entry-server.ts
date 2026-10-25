/**
 * SSR/prerender entry. Bundled by ``vite build --ssr`` and imported by
 * ``scripts/prerender.mjs``; also re-exports the site builder so the script and
 * the artifact tests share exactly one implementation.
 *
 * No network access: private routes are never rendered and the auth guard only
 * runs for ``requiresAuth`` routes.
 */
import { JSDOM } from "jsdom";

export { buildSite } from "@/site/build-site";
export { publicDescriptors, resolveSiteOrigin } from "@/site/seo";

/**
 * DOMPurify (used by ``lib/markdown.ts``) and vue-router guards expect a window.
 * The shim must exist before any app module is imported, hence the dynamic
 * imports inside ``renderRoute``.
 */
function installDomShim(): void {
  if (typeof globalThis.window !== "undefined" && typeof globalThis.document !== "undefined") {
    return;
  }
  const dom = new JSDOM("<!doctype html><html><head></head><body></body></html>", {
    url: "http://localhost/",
  });
  const scope = globalThis as unknown as Record<string, unknown>;
  scope.window = dom.window;
  scope.document = dom.window.document;
  scope.history = dom.window.history;
  scope.location = dom.window.location;
  scope.HTMLElement = dom.window.HTMLElement;
  scope.Node = dom.window.Node;
  // vue-router's scrollBehavior runs during memory navigation; jsdom has no layout.
  (dom.window as unknown as { scrollTo: () => void }).scrollTo = () => {};
}

installDomShim();

export interface RenderedRoute {
  html: string;
}

/** Render one public route to the inner HTML of ``#app``. */
export async function renderRoute(routePath: string): Promise<RenderedRoute> {
  const [{ createSSRApp }, { renderToString }, { createPinia, setActivePinia }, { createMemoryHistory }] =
    await Promise.all([import("vue"), import("vue/server-renderer"), import("pinia"), import("vue-router")]);
  const [{ default: App }, { createAppRouter }] = await Promise.all([
    import("@/App.vue"),
    import("@/router"),
  ]);

  const app = createSSRApp(App);
  const pinia = createPinia();
  app.use(pinia);
  setActivePinia(pinia);

  const router = createAppRouter(createMemoryHistory(), { updateHead: false });
  app.use(router);

  await router.push(routePath);
  await router.isReady();

  return { html: await renderToString(app) };
}
