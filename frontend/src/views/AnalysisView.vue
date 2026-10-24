<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import MindmapPanel from "@/components/MindmapPanel.vue";
import {
  analysisStatusLabel,
  formatQuota,
  formatQuotaReset,
  reanalysisAvailability,
  visibleSummary,
} from "@/lib/analysis";
import { ApiError } from "@/lib/api";
import { renderMarkdown } from "@/lib/markdown";
import { platformLabel, subtitleSourceLabel } from "@/lib/video";
import { useAnalysisStore } from "@/stores/analysis";

const route = useRoute();
const router = useRouter();
const store = useAnalysisStore();
const retrying = ref(false);
const retryError = ref<string | null>(null);
const confirmOpen = ref(false);
const reanalyzing = ref(false);
const reanalyzeError = ref<string | null>(null);

const analysisId = computed(() => String(route.params.id ?? ""));
const statusLabel = computed(() => analysisStatusLabel(store.status));
const sourceLabel = computed(() =>
  store.subtitleSource ? subtitleSourceLabel(store.subtitleSource === "auto") : "",
);
const summaryMarkdown = computed(() => visibleSummary(store.summary));
const summaryHtml = computed(() => renderMarkdown(summaryMarkdown.value));
const quotaLabel = computed(() => (store.quota ? formatQuota(store.quota) : ""));
const quotaReset = computed(() => formatQuotaReset(store.quota?.resets_at));
const canRetry = computed(() => store.status === "failed" && store.videoId !== null);
const canReanalyze = computed(() => store.status === "completed" && store.videoId !== null);
const reanalysis = computed(() => reanalysisAvailability(store.quota));
const reanalysisBlockedReason = computed(() => {
  if (reanalysis.value.allowed) return "";
  return quotaReset.value ? `${reanalysis.value.message}，${quotaReset.value}` : reanalysis.value.message;
});
const videoMeta = computed(() => {
  if (!store.video) return "";
  return `${platformLabel(store.video.platform)} · ${analysisStatusLabel(store.status)}`;
});

watch(
  analysisId,
  (id) => {
    if (id) void store.open(id);
  },
  { immediate: true },
);

onBeforeUnmount(() => store.close());

async function retry(): Promise<void> {
  if (!canRetry.value || retrying.value) return;
  retrying.value = true;
  retryError.value = null;
  try {
    const newId = await store.retry();
    if (newId) await router.replace({ name: "analysis", params: { id: newId } });
  } catch (caught) {
    retryError.value =
      caught instanceof ApiError ? caught.message : "重新分析失败，请稍后重试";
  } finally {
    retrying.value = false;
  }
}

function openReanalyzeConfirm(): void {
  if (!canReanalyze.value || !reanalysis.value.allowed) return;
  reanalyzeError.value = null;
  confirmOpen.value = true;
}

function closeReanalyzeConfirm(): void {
  if (reanalyzing.value) return;
  confirmOpen.value = false;
}

async function confirmReanalyze(): Promise<void> {
  if (!reanalysis.value.allowed || reanalyzing.value) return;
  reanalyzing.value = true;
  reanalyzeError.value = null;
  try {
    const newId = await store.reanalyze();
    confirmOpen.value = false;
    if (newId) await router.push({ name: "analysis", params: { id: newId } });
  } catch (caught) {
    reanalyzeError.value =
      caught instanceof ApiError ? caught.message : "重新分析失败，请稍后重试";
    // A rejected re-analysis often means the Quota snapshot was stale.
    if (caught instanceof ApiError && caught.code === "quota_exhausted") {
      void store.loadQuota();
    }
  } finally {
    reanalyzing.value = false;
  }
}
</script>

<template>
  <section class="mx-auto w-full max-w-3xl space-y-6">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <RouterLink to="/" class="text-sm text-slate-600 transition-colors hover:text-slate-900">
        ← 返回首页
      </RouterLink>
      <div class="flex flex-wrap items-center gap-2 text-xs text-slate-500">
        <span v-if="quotaLabel">{{ quotaLabel }}</span>
        <span v-if="quotaReset">{{ quotaReset }}</span>
      </div>
    </div>

    <header class="space-y-2">
      <h1 class="break-words text-2xl font-bold tracking-tight text-slate-900">
        {{ store.video?.title ?? "AI 分析" }}
      </h1>
      <div class="flex flex-wrap items-center gap-2 text-xs">
        <span
          v-if="store.video"
          class="rounded-full bg-slate-100 px-2 py-0.5 font-medium text-slate-600"
        >
          {{ videoMeta }}
        </span>
        <span
          v-if="sourceLabel"
          class="rounded-full px-2 py-0.5 font-medium"
          :class="
            store.subtitleSource === 'auto'
              ? 'bg-amber-50 text-amber-700'
              : 'bg-emerald-50 text-emerald-700'
          "
        >
          {{ sourceLabel }}
        </span>
        <span
          v-if="!store.loading"
          class="rounded-full px-2 py-0.5 font-medium"
          :class="
            store.status === 'failed'
              ? 'bg-red-50 text-red-700'
              : store.status === 'completed'
                ? 'bg-slate-100 text-slate-600'
                : 'bg-sky-50 text-sky-700'
          "
        >
          {{ statusLabel }}
        </span>
      </div>
    </header>

    <div v-if="canReanalyze" class="flex flex-wrap items-center gap-3">
      <button
        type="button"
        class="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 transition-colors hover:border-slate-400 hover:bg-white disabled:cursor-not-allowed disabled:border-slate-200 disabled:text-slate-400"
        :disabled="!reanalysis.allowed"
        :title="reanalysis.allowed ? reanalysis.message : reanalysisBlockedReason"
        @click="openReanalyzeConfirm"
      >
        重新分析
      </button>
      <span v-if="!reanalysis.allowed" class="text-xs text-slate-500">
        {{ reanalysisBlockedReason }}
      </span>
    </div>

    <p
      v-if="store.truncated"
      class="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800"
    >
      字幕内容较长，本次结果基于截断内容生成，可能未覆盖完整视频。
    </p>

    <div
      v-if="store.loading"
      role="status"
      class="rounded-xl border border-slate-200 bg-white p-6 text-center text-sm text-slate-600"
    >
      正在加载分析结果…
    </div>

    <div
      v-else-if="store.error && store.status === 'failed'"
      role="alert"
      class="space-y-2 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800"
    >
      <p class="font-medium">{{ store.error.message }}</p>
      <div class="flex flex-wrap items-center gap-3 text-xs text-red-600">
        <span>错误代码：{{ store.error.code }}</span>
        <span v-if="quotaReset" class="text-red-500">{{ quotaReset }}，届时 Quota 恢复</span>
        <button
          v-if="canRetry"
          type="button"
          class="rounded-md border border-red-300 px-3 py-1 font-medium text-red-700 transition-colors hover:bg-red-100 disabled:cursor-not-allowed disabled:text-red-400"
          :disabled="retrying"
          @click="retry"
        >
          {{ retrying ? "正在重试…" : "重新生成" }}
        </button>
      </div>
      <p v-if="retryError" class="text-xs text-red-600">{{ retryError }}</p>
    </div>

    <div
      v-else-if="store.error"
      role="alert"
      class="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800"
    >
      <p class="font-medium">{{ store.error.message }}</p>
      <p class="mt-1 text-xs text-red-600">错误代码：{{ store.error.code }}</p>
    </div>

    <article
      v-if="summaryMarkdown"
      class="analysis-markdown rounded-xl border border-slate-200 bg-white p-5 text-sm leading-relaxed text-slate-700 shadow-sm"
      aria-live="polite"
    >
      <div v-html="summaryHtml" />
      <span
        v-if="store.streaming"
        class="mt-2 inline-block h-3 w-2 animate-pulse rounded-sm bg-slate-400 align-middle"
        aria-hidden="true"
      />
    </article>

    <div
      v-else-if="store.streaming"
      role="status"
      class="rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-600"
    >
      <span class="mr-2 inline-block h-2 w-2 animate-pulse rounded-full bg-sky-500" aria-hidden="true" />
      正在生成摘要…
    </div>

    <MindmapPanel
      v-if="store.mindmap || store.status === 'completed'"
      :markdown="store.mindmap"
      :title="store.video?.title ?? ''"
    />

    <p v-if="store.streaming" class="text-xs text-slate-400">
      关闭页面不会中断生成；重新打开会从已生成的内容继续。
    </p>

    <div
      v-if="confirmOpen"
      class="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4"
      @click.self="closeReanalyzeConfirm"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="reanalyze-title"
        aria-describedby="reanalyze-cost"
        class="w-full max-w-md space-y-4 rounded-xl bg-white p-5 shadow-xl"
      >
        <h2 id="reanalyze-title" class="text-lg font-semibold text-slate-900">重新分析</h2>
        <p class="text-sm text-slate-600">
          将重新生成摘要与思维导图。原结果会保留在历史记录中，可随时回访。
        </p>
        <p id="reanalyze-cost" class="rounded-lg bg-amber-50 p-3 text-sm text-amber-800">
          {{ reanalysis.message }}
          <span v-if="reanalysis.resetsAt && quotaReset">，{{ quotaReset }}</span>
        </p>
        <p v-if="reanalyzeError" class="text-xs text-red-600">{{ reanalyzeError }}</p>
        <div class="flex justify-end gap-2">
          <button
            type="button"
            class="rounded-lg border border-slate-300 px-3 py-1.5 text-sm text-slate-700 transition-colors hover:border-slate-400 disabled:cursor-not-allowed disabled:text-slate-400"
            :disabled="reanalyzing"
            @click="closeReanalyzeConfirm"
          >
            取消
          </button>
          <button
            type="button"
            class="rounded-lg bg-slate-900 px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-slate-700 disabled:cursor-not-allowed disabled:bg-slate-300"
            :disabled="reanalyzing || !reanalysis.allowed"
            @click="confirmReanalyze"
          >
            {{ reanalyzing ? "正在创建…" : "确认重新分析" }}
          </button>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.analysis-markdown :deep(h1) {
  margin-top: 1rem;
  font-size: 1.25rem;
  font-weight: 700;
  color: #0f172a;
}
.analysis-markdown :deep(h2) {
  margin-top: 1rem;
  font-size: 1.05rem;
  font-weight: 600;
  color: #0f172a;
}
.analysis-markdown :deep(h3) {
  margin-top: 0.75rem;
  font-weight: 600;
  color: #0f172a;
}
.analysis-markdown :deep(p) {
  margin-top: 0.5rem;
}
.analysis-markdown :deep(ul) {
  margin-top: 0.5rem;
  list-style: disc;
  padding-left: 1.25rem;
}
.analysis-markdown :deep(ol) {
  margin-top: 0.5rem;
  list-style: decimal;
  padding-left: 1.25rem;
}
.analysis-markdown :deep(li) {
  margin-top: 0.25rem;
}
.analysis-markdown :deep(code) {
  border-radius: 0.25rem;
  background: #f1f5f9;
  padding: 0.1rem 0.25rem;
  font-size: 0.85em;
}
.analysis-markdown :deep(pre) {
  margin-top: 0.5rem;
  overflow-x: auto;
  border-radius: 0.5rem;
  background: #f1f5f9;
  padding: 0.75rem;
}
.analysis-markdown :deep(blockquote) {
  margin-top: 0.5rem;
  border-left: 3px solid #cbd5e1;
  padding-left: 0.75rem;
  color: #64748b;
}
</style>
