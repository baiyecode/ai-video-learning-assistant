<script setup lang="ts">
import { computed, watch } from "vue";

import {
  SUBTITLE_EXPORT_FORMATS,
  type SubtitleExportFormat,
} from "@/lib/subtitle";
import { subtitleSourceLabel } from "@/lib/video";
import { useSubtitleStore } from "@/stores/subtitle";

const props = defineProps<{ videoId: string }>();

const store = useSubtitleStore();

watch(
  () => props.videoId,
  (videoId) => {
    if (videoId) void store.load(videoId);
  },
  { immediate: true },
);

const EMPTY_MESSAGE = "该视频没有可用字幕，暂不支持 AI 分析";

const sourceLabel = computed(() =>
  store.subtitle
    ? subtitleSourceLabel(store.subtitle.source_type === "auto")
    : "",
);

const emptyMessage = computed(() => {
  const error = store.error;
  if (!error || error.code === "subtitles_unavailable") return EMPTY_MESSAGE;
  return error.message || EMPTY_MESSAGE;
});

const canRetry = computed(
  () => store.error !== null && store.error.code !== "subtitles_unavailable",
);

const exportLabels: Record<SubtitleExportFormat, string> = {
  srt: "SRT",
  vtt: "VTT",
  txt: "TXT",
};

function download(format: SubtitleExportFormat): void {
  void store.download(format);
}
</script>

<template>
  <section class="space-y-3 border-t border-slate-100 pt-4" aria-labelledby="subtitle-heading">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <h3 id="subtitle-heading" class="text-sm font-semibold text-slate-900">字幕全文</h3>
      <div v-if="store.subtitle" class="flex flex-wrap items-center gap-2 text-xs">
        <span class="rounded-full bg-slate-100 px-2 py-0.5 font-medium text-slate-600">
          {{ sourceLabel }}
        </span>
        <span class="text-slate-500">{{ store.subtitle.language }}</span>
      </div>
    </div>

    <p v-if="store.loading" role="status" class="text-sm text-slate-500">正在加载字幕…</p>

    <div v-else-if="store.subtitle" class="space-y-3">
      <div class="max-h-96 overflow-y-auto rounded-lg bg-slate-50 p-3">
        <p class="whitespace-pre-wrap break-words text-sm leading-relaxed text-slate-700">
          {{ store.subtitle.text }}
        </p>
      </div>

      <div class="flex flex-wrap items-center gap-2">
        <span class="text-xs text-slate-500">导出字幕：</span>
        <button
          v-for="format in SUBTITLE_EXPORT_FORMATS"
          :key="format"
          type="button"
          class="rounded-md border border-slate-300 px-3 py-1 text-xs font-medium text-slate-700 transition-colors hover:bg-slate-100 disabled:cursor-not-allowed disabled:text-slate-400"
          :disabled="store.exporting !== null"
          @click="download(format)"
        >
          {{ store.exporting === format ? "导出中…" : exportLabels[format] }}
        </button>
      </div>

      <p v-if="store.exportError" role="alert" class="text-xs text-red-600">
        {{ store.exportError.message }}
      </p>
    </div>

    <div v-else class="space-y-2 text-sm text-amber-700">
      <p>{{ emptyMessage }}</p>
      <button
        v-if="canRetry"
        type="button"
        class="rounded-md border border-amber-300 px-3 py-1 text-xs font-medium text-amber-800 transition-colors hover:bg-amber-100"
        @click="store.retry()"
      >
        重试
      </button>
    </div>
  </section>
</template>
