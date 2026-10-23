<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";

import {
  buildMindmap,
  downloadBlob,
  mindmapExportSize,
  mindmapFilename,
  rasterizeSvg,
  serializeMindmapSvg,
} from "@/lib/mindmap";

const props = defineProps<{
  markdown: string;
  title?: string | null;
}>();

const svgElement = ref<SVGSVGElement | null>(null);
const fullscreen = ref(false);
const rendering = ref(false);
const error = ref<string | null>(null);
const exporting = ref<"svg" | "png" | null>(null);

// markmap-view touches the DOM on import, so it is loaded only after mount.
type MarkmapInstance = import("markmap-view").Markmap;
let markmap: MarkmapInstance | null = null;
let renderToken = 0;
let previousOverflow = "";

const hasMindmap = computed(() => props.markdown.trim().length > 0);
const busy = computed(() => rendering.value || exporting.value !== null);

function destroyMarkmap(): void {
  markmap?.destroy();
  markmap = null;
}

async function renderMindmap(): Promise<void> {
  const token = ++renderToken;
  const svg = svgElement.value;
  if (!svg) return;

  destroyMarkmap();
  svg.innerHTML = "";
  error.value = null;

  if (!hasMindmap.value) {
    rendering.value = false;
    return;
  }

  rendering.value = true;
  try {
    const { root } = buildMindmap(props.markdown);
    const { Markmap } = await import("markmap-view");
    if (token !== renderToken || !svgElement.value) return;

    markmap = Markmap.create(
      svgElement.value,
      {
        autoFit: false,
        duration: 300,
        maxWidth: 320,
        pan: true,
        zoom: true,
        scrollForPan: false,
      },
      root,
    );
    await nextTick();
    await markmap.fit();
  } catch {
    if (token === renderToken) error.value = "思维导图渲染失败，请稍后重试";
  } finally {
    if (token === renderToken) rendering.value = false;
  }
}

function currentScale(): number {
  const transform = markmap?.g.attr("transform") ?? "";
  const match = /scale\(([\d.]+)\)/.exec(transform);
  return match ? Number(match[1]) : 1;
}

function zoomBy(factor: number): void {
  if (!markmap) return;
  const scale = Math.min(4, Math.max(0.2, currentScale() * factor));
  void markmap.rescale(scale);
}

function resetView(): void {
  void markmap?.fit();
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === "Escape" && fullscreen.value) void toggleFullscreen();
}

async function toggleFullscreen(): Promise<void> {
  fullscreen.value = !fullscreen.value;
  if (fullscreen.value) {
    previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", onKeydown);
  } else {
    document.body.style.overflow = previousOverflow;
    window.removeEventListener("keydown", onKeydown);
  }
  // The graph container changes size; wait for layout before refitting.
  await nextTick();
  await markmap?.fit();
}

function exportSvg(): void {
  const svg = svgElement.value;
  if (!svg || exporting.value) return;
  exporting.value = "svg";
  try {
    const markup = serializeMindmapSvg(svg);
    downloadBlob(new Blob([markup], { type: "image/svg+xml;charset=utf-8" }), mindmapFilename(props.title, "svg"));
  } catch {
    error.value = "导出 SVG 失败，请稍后重试";
  } finally {
    exporting.value = null;
  }
}

async function exportPng(): Promise<void> {
  const svg = svgElement.value;
  if (!svg || exporting.value) return;
  exporting.value = "png";
  try {
    const markup = serializeMindmapSvg(svg);
    const { width, height } = mindmapExportSize(svg);
    const blob = await rasterizeSvg(markup, { width, height });
    downloadBlob(blob, mindmapFilename(props.title, "png"));
  } catch {
    error.value = "导出 PNG 失败，请稍后重试";
  } finally {
    exporting.value = null;
  }
}

onMounted(() => {
  void renderMindmap();
});

watch(
  () => props.markdown,
  () => {
    void renderMindmap();
  },
);

onBeforeUnmount(() => {
  renderToken += 1;
  destroyMarkmap();
  if (fullscreen.value) {
    document.body.style.overflow = previousOverflow;
    window.removeEventListener("keydown", onKeydown);
  }
});
</script>

<template>
  <section
    :class="
      fullscreen
        ? 'fixed inset-0 z-50 flex flex-col gap-3 overflow-hidden bg-white p-4'
        : 'space-y-3 rounded-xl border border-slate-200 bg-white p-5 shadow-sm'
    "
    aria-labelledby="mindmap-heading"
  >
    <div class="flex flex-wrap items-center justify-between gap-2">
      <h2 id="mindmap-heading" class="text-sm font-semibold text-slate-900">思维导图</h2>
      <div v-if="hasMindmap" class="flex flex-wrap items-center gap-1.5" role="toolbar" aria-label="思维导图操作">
        <button
          type="button"
          class="mindmap-button"
          title="放大"
          :disabled="busy"
          @click="zoomBy(1.25)"
        >
          放大
        </button>
        <button
          type="button"
          class="mindmap-button"
          title="缩小"
          :disabled="busy"
          @click="zoomBy(0.8)"
        >
          缩小
        </button>
        <button
          type="button"
          class="mindmap-button"
          title="适应画布"
          :disabled="busy"
          @click="resetView"
        >
          重置
        </button>
        <button
          type="button"
          class="mindmap-button"
          :disabled="busy"
          @click="toggleFullscreen"
        >
          {{ fullscreen ? "退出全屏" : "全屏" }}
        </button>
        <button
          type="button"
          class="mindmap-button"
          :disabled="busy"
          @click="exportSvg"
        >
          {{ exporting === "svg" ? "导出中…" : "导出 SVG" }}
        </button>
        <button
          type="button"
          class="mindmap-button"
          :disabled="busy"
          @click="exportPng"
        >
          {{ exporting === "png" ? "导出中…" : "导出 PNG" }}
        </button>
      </div>
    </div>

    <div
      v-if="hasMindmap"
      class="mindmap-canvas relative w-full overflow-hidden rounded-lg border border-slate-100 bg-slate-50"
      :class="fullscreen ? 'min-h-0 flex-1' : 'h-[420px]'"
      :aria-busy="rendering"
    >
      <svg ref="svgElement" class="block h-full w-full" role="img" aria-label="思维导图" />
      <p
        v-if="rendering"
        class="pointer-events-none absolute inset-0 flex items-center justify-center text-xs text-slate-500"
      >
        正在渲染思维导图…
      </p>
    </div>

    <div
      v-else
      class="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-4 text-sm text-slate-500"
    >
      本次生成没有返回思维导图。
    </div>

    <p v-if="error" role="alert" class="text-xs text-red-600">{{ error }}</p>
    <p v-if="hasMindmap && !error" class="text-xs text-slate-400">
      滚轮缩放，拖拽平移，点击节点可折叠分支。
    </p>
  </section>
</template>

<style scoped>
.mindmap-button {
  border-radius: 0.375rem;
  border-width: 1px;
  border-color: #e2e8f0;
  padding: 0.15rem 0.5rem;
  font-size: 0.75rem;
  font-weight: 500;
  color: #475569;
  transition: background-color 0.15s ease;
}
.mindmap-button:hover:not(:disabled) {
  background-color: #f8fafc;
}
.mindmap-button:disabled {
  cursor: not-allowed;
  color: #94a3b8;
}
.mindmap-canvas :deep(svg) {
  touch-action: none;
}
</style>
