/**
 * Runtime counterpart of the build-time head contract: replace every managed
 * node with the tags for the current descriptor. Never append a second title,
 * canonical, OG tag or JSON-LD block.
 */
import { headTags, type PageDescriptor } from "@/site/seo";

export function applyHead(descriptor: PageDescriptor, origin: string, doc: Document): void {
  const head = doc.head;

  // Managed nodes from the previous route (including the ones baked into a
  // prerendered page), the static SPA shell title and its description all go.
  for (const node of head.querySelectorAll(
    '[data-seo-managed], title, meta[name="description"]',
  )) {
    node.remove();
  }

  for (const spec of headTags(descriptor, origin)) {
    let element: Element;
    if (spec.tag === "title") {
      element = doc.createElement("title");
    } else if (spec.tag === "script") {
      element = doc.createElement("script");
    } else {
      element = doc.createElement(spec.tag);
    }

    for (const [name, value] of Object.entries(spec.attrs)) {
      element.setAttribute(name, value);
    }
    if (spec.text !== undefined) element.textContent = spec.text;

    head.append(element);
  }
}
