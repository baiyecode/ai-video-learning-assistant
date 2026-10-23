// @vitest-environment jsdom
import { describe, expect, it, vi } from "vitest";

import {
  type RasterizeDeps,
  buildMindmap,
  downloadBlob,
  exportScale,
  mindmapExportSize,
  mindmapFilename,
  rasterizeSvg,
  sanitizeMindmapMarkdown,
  sanitizeNodeContent,
  serializeMindmapSvg,
} from "@/lib/mindmap";

/** Render markmap's HTML label and read the visible text. */
function label(html: string): string {
  const element = document.createElement("div");
  element.innerHTML = html;
  return element.textContent?.trim() ?? "";
}

interface Shape {
  label: string;
  children: Shape[];
}

function shape(node: { content: string; children?: { content: string; children?: unknown[] }[] }): Shape {
  return {
    label: label(node.content),
    children: (node.children ?? []).map((child) =>
      shape(child as { content: string; children?: { content: string; children?: unknown[] }[] }),
    ),
  };
}

describe("sanitizeMindmapMarkdown", () => {
  it("removes raw HTML but keeps the list hierarchy", () => {
    const source = [
      "## 视频结构",
      "- 主题",
      '  - <script>alert("x")</script>第一章',
      '  - <img src=x onerror="alert(1)">细节',
      "  - **重点** <!-- 隐藏注释 -->",
    ].join("\n");

    expect(sanitizeMindmapMarkdown(source)).toBe(
      ["## 视频结构", "- 主题", "  - 第一章", "  - 细节", "  - **重点**"].join("\n"),
    );
  });
  it("keeps Markdown autolinks that only look like HTML", () => {
    expect(sanitizeMindmapMarkdown("- <https://example.com/a>")).toBe("- <https://example.com/a>");
  });
});

describe("buildMindmap", () => {
  it("turns a nested Markdown list into branches", () => {
    const { root } = buildMindmap(
      ["- 主题", "  - 第一章", "    - 细节 A", "    - 细节 B", "  - 第二章"].join("\n"),
    );

    expect(shape(root)).toEqual({
      label: "主题",
      children: [
        {
          label: "第一章",
          children: [
            { label: "细节 A", children: [] },
            { label: "细节 B", children: [] },
          ],
        },
        { label: "第二章", children: [] },
      ],
    });
  });

  it("never keeps executable markup in node labels", () => {
    const { root } = buildMindmap(
      ["- 主题", "  - <script>alert(1)</script>章节", "  - <img src=x onerror=alert(2)>图片"].join(
        "\n",
      ),
    );
    const serialized = JSON.stringify(root);

    expect(serialized).not.toMatch(/<script/i);
    expect(serialized).not.toMatch(/onerror/i);
    expect(serialized).not.toMatch(/<img/i);
    expect(shape(root).children.map((child) => child.label)).toEqual(["章节", "图片"]);
  });

  it("drops javascript: links while keeping the label text", () => {
    const { root } = buildMindmap("- 主题\n  - [点我](javascript:alert(1))");
    const serialized = JSON.stringify(root);

    expect(serialized).not.toMatch(/javascript:/i);
    expect(shape(root).children.map((child) => child.label)).toEqual(["点我"]);
  });

  it("sanitizes node HTML even when it does not come from Markdown", () => {
    expect(sanitizeNodeContent('<img src=x onerror="alert(1)">安全')).toBe("安全");
    expect(sanitizeNodeContent("<script>alert(1)</script>安全")).toBe("安全");
    expect(sanitizeNodeContent('<a href="javascript:alert(1)">链接</a>')).not.toContain("javascript:");
  });
});

describe("mindmapFilename", () => {
  it("builds a filesystem-safe name from the video title", () => {
    expect(mindmapFilename('第1集: 介绍/概览 <A>?', "svg")).toBe("第1集 介绍概览 A-思维导图.svg");
  });

  it("falls back when the title has no usable characters", () => {
    expect(mindmapFilename("  ...  ", "png")).toBe("思维导图.png");
    expect(mindmapFilename(null, "png")).toBe("思维导图.png");
  });

  it("bounds very long titles", () => {
    const name = mindmapFilename("长".repeat(200), "svg");

    expect(name.length).toBeLessThanOrEqual(80);
    expect(name.endsWith("-思维导图.svg")).toBe(true);
  });
});

describe("exportScale", () => {
  it("upscales small graphs and caps large ones", () => {
    expect(exportScale(800, 600)).toBe(2);
    expect(exportScale(4096, 1000)).toBe(1);
    expect(exportScale(8192, 1000)).toBe(0.5);
  });
});

const SVG_NS = "http://www.w3.org/2000/svg";
const XHTML_NS = "http://www.w3.org/1999/xhtml";

function makeSvg(): SVGSVGElement {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("width", "300");
  svg.setAttribute("height", "200");

  const style = document.createElementNS(SVG_NS, "style");
  style.textContent = ".markmap-node circle { fill: #fff; }";
  svg.appendChild(style);

  const graph = document.createElementNS(SVG_NS, "g");
  graph.setAttribute("transform", "translate(100, 50) scale(2)");

  const node = document.createElementNS(SVG_NS, "g");
  node.setAttribute("class", "markmap-node");
  const foreignObject = document.createElementNS(SVG_NS, "foreignObject");
  const label = document.createElementNS(XHTML_NS, "div");
  label.innerHTML =
    '<p>主题 <strong>重点</strong></p><img src=x onerror="alert(1)"><script>alert(2)</script>';
  foreignObject.appendChild(label);
  node.appendChild(foreignObject);
  graph.appendChild(node);

  // jsdom has no layout engine, so supply the box markmap would measure.
  graph.getBBox = () => ({ x: -10, y: -20, width: 120, height: 60 }) as DOMRect;
  svg.appendChild(graph);
  return svg;
}

describe("serializeMindmapSvg", () => {
  it("crops the exported SVG to the graph bounds and keeps the stylesheet", () => {
    const markup = serializeMindmapSvg(makeSvg(), { padding: 10 });
    const root = new DOMParser().parseFromString(markup, "image/svg+xml").documentElement;

    expect(root.nodeName).toBe("svg");
    expect(root.getAttribute("xmlns")).toBe(SVG_NS);
    expect(root.getAttribute("viewBox")).toBe("-20 -30 140 80");
    expect(root.getAttribute("width")).toBe("140");
    expect(root.getAttribute("height")).toBe("80");
    expect(markup).toContain(".markmap-node");
    // Zoom/pan of the live view must not shift the exported graph.
    expect(root.querySelector("g")?.hasAttribute("transform")).toBe(false);
    expect(mindmapExportSize(makeSvg(), 10)).toEqual({ width: 140, height: 80 });
  });

  it("keeps labels but strips executable markup", () => {
    const markup = serializeMindmapSvg(makeSvg());
    const root = new DOMParser().parseFromString(markup, "image/svg+xml").documentElement;

    expect(root.textContent).toContain("主题");
    expect(root.textContent).toContain("重点");
    expect(markup).not.toMatch(/<script/i);
    expect(markup).not.toMatch(/onerror/i);
    expect(markup).not.toMatch(/javascript:/i);
  });
});

function fakeCanvas(): {
  canvas: HTMLCanvasElement;
  context: { fillStyle: string; fillRect: ReturnType<typeof vi.fn>; drawImage: ReturnType<typeof vi.fn> };
} {
  const context = { fillStyle: "", fillRect: vi.fn(), drawImage: vi.fn() };
  const canvas = {
    width: 0,
    height: 0,
    getContext: vi.fn(() => context),
  } as unknown as HTMLCanvasElement;
  return { canvas, context };
}

describe("rasterizeSvg", () => {
  it("draws the SVG at twice the size and returns the PNG blob", async () => {
    const { canvas, context } = fakeCanvas();
    const blob = new Blob(["png"], { type: "image/png" });
    const image = { width: 140, height: 80 } as unknown as CanvasImageSource;
    let source = "";
    const deps: RasterizeDeps = {
      loadImage: vi.fn(async (src: string) => {
        source = src;
        return image as CanvasImageSource & { width: number; height: number };
      }),
      createCanvas: () => canvas,
      toBlob: vi.fn(async () => blob),
    };

    const result = await rasterizeSvg('<svg xmlns="http://www.w3.org/2000/svg" />', {
      width: 140,
      height: 80,
      deps,
    });

    expect(result).toBe(blob);
    expect(source.startsWith("data:image/svg+xml")).toBe(true);
    expect(canvas.width).toBe(280);
    expect(canvas.height).toBe(160);
    expect(context.fillRect).toHaveBeenCalledWith(0, 0, 280, 160);
    expect(context.drawImage).toHaveBeenCalledWith(image, 0, 0, 280, 160);
  });

  it("rejects when the browser cannot produce a PNG", async () => {
    const { canvas } = fakeCanvas();
    const deps: RasterizeDeps = {
      loadImage: vi.fn(async () => ({}) as CanvasImageSource & { width: number; height: number }),
      createCanvas: () => canvas,
      toBlob: vi.fn(async () => null),
    };

    await expect(rasterizeSvg("<svg />", { width: 100, height: 50, deps })).rejects.toThrow(
      "导出图片失败",
    );
  });
});

describe("downloadBlob", () => {
  it("downloads under the requested filename", () => {
    const createObjectURL = vi.fn(() => "blob:mock");
    const revokeObjectURL = vi.fn();
    Object.defineProperty(URL, "createObjectURL", { value: createObjectURL, configurable: true });
    Object.defineProperty(URL, "revokeObjectURL", { value: revokeObjectURL, configurable: true });

    const clicked: HTMLAnchorElement[] = [];
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(function (this: HTMLAnchorElement) {
        clicked.push(this);
      });

    downloadBlob(new Blob(["x"], { type: "image/png" }), "示例-思维导图.png");

    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(click).toHaveBeenCalledTimes(1);
    expect(clicked[0]?.download).toBe("示例-思维导图.png");
    expect(clicked[0]?.href).toBe("blob:mock");
    expect(clicked[0]?.isConnected).toBe(false);
    click.mockRestore();
  });
});
