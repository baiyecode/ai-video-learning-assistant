<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";

import {
  downloadStatusLabel,
  formatCountdown,
  formatProgress,
  isTerminalStatus,
  remainingSeconds,
} from "@/lib/download";
import { isComplianceAcknowledged } from "@/lib/compliance";
import { formatFileSize } from "@/lib/video";
import type { VideoDto, VideoFormatDto } from "@/lib/video";
import { useDownloadStore } from "@/stores/download";

const props = withDefaults(
  defineProps<{ video: VideoDto; formats: VideoFormatDto[]; complianceRequired?: boolean }>(),
  { complianceRequired: false },
);
// The compliance gate is owned by HomeView: it shows the notice and calls ``retry``
// once the acknowledgement is persisted. Ticket #14 keeps this hook tiny on purpose.
const emit = defineEmits<{ "compliance-required": [retry: () => void] }>();

const store = useDownloadStore();
const selectedFormatId = ref(props.formats[0]?.format_id ?? "");
const now = ref(Date.now());
let ticker: ReturnType<typeof setInterval> | null = null;

const download = computed(() => store.download);
const status = computed(() => download.value?.status ?? null);
const statusLabel = computed(() => (status.value ? downloadStatusLabel(status.value) : ""));
const busy = computed(
  () => store.starting || (status.value !== null && !isTerminalStatus(status.value)),
);
const showProgress = computed(
  () => status.value === "queued" || status.value === "downloading" || status.value === "merging",
);
const progressLabel = computed(() => formatProgress(download.value?.progress ?? 0));
const progressPercent = computed(() =>
  Math.round(Math.min(1, Math.max(0, download.value?.progress ?? 0)) * 100),
);
const canStart = computed(() => selectedFormatId.value.length > 0 && !busy.value);
const remaining = computed(() =>
  remainingSeconds(download.value?.url_expires_at ?? null, now.value),
);
const remainingLabel = computed(() => formatCountdown(remaining.value));
const failureMessage = computed(
  () => store.error?.message ?? download.value?.error?.message ?? "下载失败，请稍后重试",
);
const hint = computed(() => {
  if (status.value === "queued") return "正在排队，请保持页面打开。";
  if (status.value === "downloading") return "正在从平台下载文件…";
  if (status.value === "merging") return "正在合并音视频…";
  return "";
});

function formatOptionLabel(format: VideoFormatDto): string {
  const size = format.filesize ? ` · ${formatFileSize(format.filesize)}` : "";
  return `${format.resolution} · ${format.ext.toUpperCase()}${size}`;
}

function startDownload(): void {
  if (!canStart.value) return;
  if (props.complianceRequired && !isComplianceAcknowledged()) {
    emit("compliance-required", startDownload);
    return;
  }
  void store.start(props.video.id, selectedFormatId.value);
}

function retryDownload(): void {
  void store.retry();
}

watch(
  () => props.video.id,
  () => {
    selectedFormatId.value = props.formats[0]?.format_id ?? "";
    store.reset();
    now.value = Date.now();
  },
);

onMounted(() => {
  ticker = setInterval(() => {
    now.value = Date.now();
  }, 1000);
});

onBeforeUnmount(() => {
  if (ticker !== null) clearInterval(ticker);
  ticker = null;
  store.reset();
});
</script>

<template>
  <section class="space-y-3 border-t border-slate-100 pt-4">
    <h3 class="text-sm font-semibold text-slate-900">下载文件</h3>
    <div class="flex flex-wrap items-end gap-3">
      <label class="flex min-w-48 flex-col gap-1 text-xs font-medium text-slate-600">
        下载格式
        <select
          v-model="selectedFormatId"
          class="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 outline-none focus:border-slate-500 disabled:cursor-not-allowed disabled:bg-slate-100"
          :disabled="busy || formats.length === 0"
        >
          <option v-for="format in formats" :key="format.format_id" :value="format.format_id">
            {{ formatOptionLabel(format) }}
          </option>
        </select>
      </label>
      <button
        type="button"
        class="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-slate-700 disabled:cursor-not-allowed disabled:bg-slate-400"
        :disabled="!canStart"
        @click="startDownload"
      >
        {{ store.starting ? "正在创建…" : busy ? "下载进行中…" : "开始下载" }}
      </button>
      <span class="text-xs text-slate-400">文件保留 1 小时，下载链接 15 分钟内有效。</span>
    </div>

    <p v-if="formats.length === 0" class="text-sm text-slate-500">暂无可下载格式。</p>

    <div
      v-if="store.error"
      role="alert"
      class="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800"
    >
      <p class="font-medium">{{ store.error.message }}</p>
      <p class="mt-1 text-xs text-red-600">错误代码：{{ store.error.code }}</p>
    </div>

    <div v-if="download" class="space-y-2 rounded-lg border border-slate-200 bg-slate-50 p-4">
      <div class="flex items-center justify-between gap-3 text-sm">
        <span class="font-medium text-slate-800">{{ statusLabel }}</span>
        <span v-if="showProgress" class="text-xs text-slate-500">{{ progressLabel }}</span>
      </div>

      <div
        v-if="showProgress"
        role="progressbar"
        aria-label="下载进度"
        aria-valuemin="0"
        aria-valuemax="100"
        :aria-valuenow="progressPercent"
        class="h-2 w-full overflow-hidden rounded-full bg-slate-200"
      >
        <div class="h-full rounded-full bg-slate-900 transition-all" :style="{ width: progressLabel }" />
      </div>
      <p v-if="showProgress" class="text-xs text-slate-500">{{ hint }}</p>

      <div v-if="status === 'ready'" class="space-y-2 text-sm">
        <p class="break-words text-slate-700">
          {{ download.file_name }}
          <span v-if="download.file_size !== null" class="text-xs text-slate-500">
            （{{ formatFileSize(download.file_size) }}）
          </span>
        </p>
        <div class="flex flex-wrap items-center gap-3">
          <a
            v-if="download.download_url && remaining > 0"
            :href="download.download_url"
            class="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-slate-700"
            download
          >
            保存文件
          </a>
          <span v-if="remaining > 0" class="text-xs text-slate-500">
            链接剩余有效期 {{ remainingLabel }}
          </span>
          <span v-else class="text-xs text-amber-700">链接已过期，请重新发起下载。</span>
        </div>
      </div>

      <div v-if="status === 'failed' || status === 'expired'" class="space-y-2 text-sm">
        <p class="text-red-700">{{ failureMessage }}</p>
        <div class="flex flex-wrap items-center gap-3">
          <button
            v-if="download.can_retry"
            type="button"
            class="rounded-md border border-slate-300 px-3 py-1 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-100 disabled:cursor-not-allowed disabled:text-slate-400"
            :disabled="store.starting"
            @click="retryDownload"
          >
            {{ store.starting ? "正在重试…" : "重试" }}
          </button>
          <span v-else class="text-xs text-slate-500">重试次数已达上限，请重新发起下载。</span>
          <span v-if="download.error" class="text-xs text-slate-400">
            错误代码：{{ download.error.code }}
          </span>
        </div>
      </div>
    </div>
  </section>
</template>
