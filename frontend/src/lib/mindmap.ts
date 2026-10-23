/**
 * Mindmap Markdown → markmap data / export helpers.
 *
 * Two sanitization layers protect the graph:
 * 1. raw HTML is stripped from the Markdown before markmap parses it;
 * 2. every transformed node's HTML content and the serialized SVG pass DOMPurify
 *    again (markmap renders node labels through `foreignObject`).
 */

import DOMPurify from "dompurify";
import type { IPureNode } from "markmap-common";
import { Transformer, type ITransformResult } from "markmap-lib";

const SCRIPT_BLOCK = /<(script|style)\b[^>]*>[\s\S]*?<\/\1\s*>/gi;
const HTML_COMMENT = /<!--[\s\S]*?-->/g;
const HTML_TAG = /<\/?[a-z][a-z0-9-]*(?:\s[^>]*)?\/?>/gi;
/** Markdown links to executable schemes keep their label but lose the link. */
const UNSAFE_MARKDOWN_LINK =
  /\[([^\]]*)\]\(\s*(?:javascript|vbscript|data)\s*:(?:[^()\n]|\([^()\n]*\))*\)/gi;

/** Inline markup markmap needs for labels; images, scripts and frames are never useful. */
const LABEL_TAGS = [
  "a",
  "b",
  "br",
  "code",
  "del",
  "em",
  "i",
  "ins",
  "li",
  "mark",
  "ol",
  "p",
  "pre",
  "s",
  "span",
  "strong",
  "u",
  "ul",
];
const LABEL_ATTRS = ["href", "rel", "target", "title"];

/**
 * Remove raw HTML (tags, comments, script/style bodies) while keeping the
 * Markdown list structure intact. Markdown syntax such as `**bold**` survives.
 */
export function sanitizeMindmapMarkdown(source: string): string {
  return source
    .replace(/\r\n?/g, "\n")
    .replace(HTML_COMMENT, "")
    .replace(SCRIPT_BLOCK, "")
    .replace(UNSAFE_MARKDOWN_LINK, "$1")
    .replace(HTML_TAG, "")
    .split("\n")
    .map((line) => line.trimEnd())
    .join("\n")
    .trim();
}

/** Sanitize one transformed label (markmap renders labels as HTML). */
export function sanitizeNodeContent(content: string): string {
  return DOMPurify.sanitize(content, {
    ALLOWED_TAGS: LABEL_TAGS,
    ALLOWED_ATTR: LABEL_ATTRS,
  });
}

function sanitizeTree(node: IPureNode): void {
  node.content = sanitizeNodeContent(node.content);
  node.children?.forEach(sanitizeTree);
}

const ILLEGAL_FILENAME = /[\\/:*?"<>|\u0000-\u001f]/g;
const EDGE_DOTS_OR_SPACES = /^[.\s]+|[.\s]+$/g;
const MAX_TITLE_LENGTH = 60;

/** `<video title>-思维导图.<ext>` with characters every filesystem accepts. */
export function mindmapFilename(title: string | null | undefined, extension: "svg" | "png"): string {
  const base = (title ?? "")
    .replace(ILLEGAL_FILENAME, "")
    .replace(/\s+/g, " ")
    .replace(EDGE_DOTS_OR_SPACES, "")
    .slice(0, MAX_TITLE_LENGTH)
    .trim()
    .replace(EDGE_DOTS_OR_SPACES, "");

  return base ? `${base}-思维导图.${extension}` : `思维导图.${extension}`;
}

const MAX_EXPORT_SIZE = 4096;

/**
 * Rasterization scale: small graphs are doubled for crisp text, huge ones are
 * capped at {@link MAX_EXPORT_SIZE} pixels on the longest side.
 */
export function exportScale(width: number, height: number): number {
  const longest = Math.max(width, height);
  if (!Number.isFinite(longest) || longest <= 0) return 1;
  return Math.min(2, MAX_EXPORT_SIZE / longest);
}

const SVG_NS = "http://www.w3.org/2000/svg";
const DEFAULT_PADDING = 24;

interface Bounds {
  x: number;
  y: number;
  width: number;
  height: number;
}

function round(value: number): number {
  return Math.round(value * 100) / 100;
}

function graphBounds(svg: SVGSVGElement): Bounds {
  const graph = svg.querySelector("g");
  if (graph && typeof graph.getBBox === "function") {
    try {
      const box = graph.getBBox();
      if (box.width > 0 && box.height > 0) {
        return { x: box.x, y: box.y, width: box.width, height: box.height };
      }
    } catch {
      // Detached or unsupported environment: fall back to the viewport below.
    }
  }

  const viewBox = svg.viewBox?.baseVal;
  if (viewBox && viewBox.width > 0 && viewBox.height > 0) {
    return { x: viewBox.x, y: viewBox.y, width: viewBox.width, height: viewBox.height };
  }

  const width = Number(svg.getAttribute("width")) || svg.clientWidth || 800;
  const height = Number(svg.getAttribute("height")) || svg.clientHeight || 600;
  return { x: 0, y: 0, width, height };
}

/**
 * Sanitize a serialized SVG (labels live in `foreignObject`, so HTML fragments
 * are allowed inside it while scripts, images and event handlers are dropped).
 */
export function sanitizeMindmapSvg(markup: string): string {
  const clean = DOMPurify.sanitize(markup, {
    USE_PROFILES: { svg: true, svgFilters: true, html: true },
    ADD_TAGS: ["foreignObject"],
    ADD_ATTR: ["xmlns"],
    HTML_INTEGRATION_POINTS: { foreignobject: true },
    FORBID_TAGS: ["script", "img", "iframe", "object", "embed", "form", "input", "video", "audio"],
  });
  return clean.includes("xmlns=")
    ? clean
    : clean.replace(/^<svg\b/, `<svg xmlns="${SVG_NS}"`);
}

export interface MindmapSvgOptions {
  padding?: number;
}

/** Pixel size of the exported graph (content bounds plus padding). */
export function mindmapExportSize(
  svg: SVGSVGElement,
  padding = DEFAULT_PADDING,
): { width: number; height: number } {
  const bounds = graphBounds(svg);
  return {
    width: round(bounds.width + padding * 2),
    height: round(bounds.height + padding * 2),
  };
}

/**
 * Clone the rendered graph, crop it to its content box (independent of the
 * current zoom/pan), embed markmap's `<style>` and sanitize the result.
 */
export function serializeMindmapSvg(svg: SVGSVGElement, options: MindmapSvgOptions = {}): string {
  const padding = options.padding ?? DEFAULT_PADDING;
  const bounds = graphBounds(svg);
  const size = mindmapExportSize(svg, padding);

  const clone = svg.cloneNode(true) as SVGSVGElement;
  clone.removeAttribute("style");
  clone.querySelector("g")?.removeAttribute("transform");
  clone.setAttribute("xmlns", SVG_NS);
  clone.setAttribute("width", String(size.width));
  clone.setAttribute("height", String(size.height));
  clone.setAttribute(
    "viewBox",
    [
      round(bounds.x - padding),
      round(bounds.y - padding),
      size.width,
      size.height,
    ].join(" "),
  );

  return sanitizeMindmapSvg(new XMLSerializer().serializeToString(clone));
}

type RasterImage = CanvasImageSource & { width: number; height: number };

/** Browser primitives behind PNG export, injectable so tests avoid a real canvas. */
export interface RasterizeDeps {
  loadImage: (source: string) => Promise<RasterImage>;
  createCanvas: () => HTMLCanvasElement;
  toBlob: (canvas: HTMLCanvasElement) => Promise<Blob | null>;
}

export interface RasterizeOptions {
  width: number;
  height: number;
  deps?: RasterizeDeps;
}

function browserRasterizeDeps(): RasterizeDeps {
  return {
    loadImage: (source) =>
      new Promise((resolve, reject) => {
        const image = new Image();
        image.onload = () => resolve(image);
        image.onerror = () => reject(new Error("导出图片加载失败"));
        image.src = source;
      }),
    createCanvas: () => document.createElement("canvas"),
    toBlob: (canvas) => new Promise((resolve) => canvas.toBlob(resolve, "image/png")),
  };
}

/** Rasterize an SVG document to a white-backed PNG blob. */
export async function rasterizeSvg(
  markup: string,
  { width, height, deps = browserRasterizeDeps() }: RasterizeOptions,
): Promise<Blob> {
  const scale = exportScale(width, height);
  const canvas = deps.createCanvas();
  canvas.width = Math.max(1, Math.round(width * scale));
  canvas.height = Math.max(1, Math.round(height * scale));

  const context = canvas.getContext("2d");
  if (!context) throw new Error("无法初始化导出画布");

  const image = await deps.loadImage(
    `data:image/svg+xml;charset=utf-8,${encodeURIComponent(markup)}`,
  );
  context.fillStyle = "#ffffff";
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.drawImage(image, 0, 0, canvas.width, canvas.height);

  const blob = await deps.toBlob(canvas);
  if (!blob) throw new Error("导出图片失败");
  return blob;
}

/** Trigger a client-side download for an in-memory blob. */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = "noopener";
  anchor.style.display = "none";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

let transformer: Transformer | null = null;

/**
 * Sanitize the Markdown, then let markmap build the node tree and sanitize every
 * label again. The transformer is stateless per call but not free to construct.
 */
export function buildMindmap(source: string): ITransformResult {
  transformer ??= new Transformer();
  const result = transformer.transform(sanitizeMindmapMarkdown(source));
  sanitizeTree(result.root);
  return result;
}
