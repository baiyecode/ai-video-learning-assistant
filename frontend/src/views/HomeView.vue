<script setup lang="ts">
import { computed, ref } from "vue";
import { useRouter } from "vue-router";

import ComplianceNotice from "@/components/ComplianceNotice.vue";
import DownloadPanel from "@/components/DownloadPanel.vue";
import SubtitlePanel from "@/components/SubtitlePanel.vue";
import { ApiError } from "@/lib/api";
import { acknowledgeCompliance, complianceMessageForCode } from "@/lib/compliance";
import {
  formatDuration,
  formatFileSize,
  platformLabel,
  subtitleSourceLabel,
} from "@/lib/video";
import { useAnalysisStore } from "@/stores/analysis";
import { useAuthStore } from "@/stores/auth";
import { useVideoStore } from "@/stores/video";

const store = useVideoStore();
const auth = useAuthStore();
const analysisStore = useAnalysisStore();
const router = useRouter();
const url = ref("");
const creatingAnalysis = ref(false);
const analysisError = ref<{ code: string; message: string } | null>(null);

const result = computed(() => store.result);
const error = computed(() => store.error);
const canSubmit = computed(() => url.value.trim().length > 0 && !store.loading);
const complianceHint = computed(() =>
  error.value ? complianceMessageForCode(error.value.code) : null,
);

const complianceOpen = ref(false);
let pendingDownload: (() => void) | null = null;

function submit(): void {
  if (!canSubmit.value) return;
  void store.resolve(url.value);
}

function retry(): void {
  void store.retry();
}

async function startAnalysis(): Promise<void> {
  const resolved = result.value;
  if (!resolved || !resolved.can_analyze || creatingAnalysis.value) return;

  if (!auth.isAuthenticated) {
    await router.push({ name: "login", query: { next: "/" } });
    return;
  }

  creatingAnalysis.value = true;
  analysisError.value = null;
  try {
    const analysis = await analysisStore.create(resolved.video.id);
    await router.push({ name: "analysis", params: { id: analysis.id } });
  } catch (caught) {
    analysisError.value =
      caught instanceof ApiError
        ? { code: caught.code, message: caught.message }
        : { code: "network_error", message: "网络异常，请检查连接后重试" };
  } finally {
    creatingAnalysis.value = false;
  }
}

/** DownloadPanel asks HomeView to gate the very first Download behind the notice. */
function requireCompliance(startDownload: () => void): void {
  pendingDownload = startDownload;
  complianceOpen.value = true;
}

function confirmCompliance(): void {
  acknowledgeCompliance();
  complianceOpen.value = false;
  const startDownload = pendingDownload;
  pendingDownload = null;
  startDownload?.();
}

function cancelCompliance(): void {
  complianceOpen.value = false;
  pendingDownload = null;
}
</script>

<template>
  <section class="mx-auto max-w-3xl space-y-6">
    <div class="space-y-3 text-center">
      <h1 class="text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl">
        粘贴视频链接，下载并读懂它
      </h1>
      <p class="text-slate-600">
        解析公开视频，导出字幕，并基于字幕生成简体中文摘要与思维导图。
      </p>
    </div>

    <form
      class="flex flex-col gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm sm:flex-row"
      @submit.prevent="submit"
    >
      <input
        v-model="url"
        class="min-w-0 flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none placeholder:text-slate-400 focus:border-slate-500 disabled:cursor-not-allowed disabled:bg-slate-100"
        type="text"
        inputmode="url"
        aria-label="视频链接"
        placeholder="https://www.bilibili.com/video/... 或 https://youtu.be/..."
        :disabled="store.loading"
      />
      <button
        type="submit"
        class="rounded-lg bg-slate-900 px-5 py-2 text-sm font-medium text-white transition-colors hover:bg-slate-700 disabled:cursor-not-allowed disabled:bg-slate-400"
        :disabled="!canSubmit"
      >
        {{ store.loading ? "解析中…" : "解析视频" }}
      </button>
    </form>

    <p class="text-center text-xs text-slate-500">
      仅限个人备份或已获授权内容，不支持播放列表、直播与 DRM 内容。
    </p>

    <div
      v-if="store.loading"
      role="status"
      class="rounded-xl border border-slate-200 bg-white p-6 text-center text-sm text-slate-600"
    >
      正在解析视频，请稍候…
    </div>

    <div
      v-else-if="error"
      role="alert"
      class="space-y-2 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800"
    >
      <p class="font-medium">{{ complianceHint ?? error.message }}</p>
      <div class="flex flex-wrap items-center gap-3 text-xs text-red-600">
        <span>错误代码：{{ error.code }}</span>
        <button
          type="button"
          class="rounded-md border border-red-300 px-3 py-1 font-medium text-red-700 transition-colors hover:bg-red-100"
          @click="retry"
        >
          重试
        </button>
      </div>
    </div>

    <article
      v-if="result && !store.loading"
      class="space-y-5 rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
    >
      <div class="flex flex-col gap-4 sm:flex-row">
        <div
          class="flex aspect-video w-full shrink-0 items-center justify-center overflow-hidden rounded-lg bg-slate-100 sm:w-56"
        >
          <img
            v-if="result.video.thumbnail_url"
            :src="result.video.thumbnail_url"
            alt="视频封面"
            class="h-full w-full object-cover"
            referrerpolicy="no-referrer"
          />
          <span v-else class="text-xs text-slate-400">暂无封面</span>
        </div>

        <div class="min-w-0 flex-1 space-y-2">
          <div class="flex flex-wrap items-center gap-2">
            <span
              class="rounded-full px-2 py-0.5 text-xs font-medium"
              :class="
                result.video.platform === 'bilibili'
                  ? 'bg-pink-50 text-pink-700'
                  : 'bg-red-50 text-red-700'
              "
            >
              {{ platformLabel(result.video.platform) }}
            </span>
            <span class="text-xs text-slate-500">
              时长 {{ formatDuration(result.video.duration_seconds) }}
            </span>
          </div>
          <h2 class="break-words text-lg font-semibold text-slate-900">
            {{ result.video.title }}
          </h2>
          <p v-if="result.video.uploader" class="text-sm text-slate-500">
            作者：{{ result.video.uploader }}
          </p>

          <div class="flex flex-wrap gap-2">
            <span
              v-for="subtitle in result.subtitles"
              :key="subtitle.language + subtitle.name"
              class="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600"
            >
              {{ subtitle.name }} · {{ subtitleSourceLabel(subtitle.is_automatic) }}
            </span>
            <span v-if="result.subtitles.length === 0" class="text-xs text-amber-700">
              该视频没有可用字幕，暂不支持 AI 总结。
            </span>
          </div>
        </div>
      </div>

      <div class="space-y-2">
        <h3 class="text-sm font-semibold text-slate-900">可选格式</h3>
        <div v-if="result.formats.length" class="overflow-x-auto">
          <table class="w-full min-w-[28rem] border-collapse text-sm">
            <thead>
              <tr class="border-b border-slate-200 text-left text-xs text-slate-500">
                <th scope="col" class="py-2 pr-4 font-medium">清晰度</th>
                <th scope="col" class="py-2 pr-4 font-medium">格式</th>
                <th scope="col" class="py-2 pr-4 font-medium">大小</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="format in result.formats"
                :key="format.format_id"
                class="border-b border-slate-100 last:border-0"
              >
                <td class="py-2 pr-4">
                  <span class="font-medium text-slate-800">{{ format.resolution }}</span>
                  <span v-if="format.label && format.label !== format.resolution" class="ml-2 text-xs text-slate-400">
                    {{ format.label }}
                  </span>
                </td>
                <td class="py-2 pr-4 uppercase text-slate-600">{{ format.ext }}</td>
                <td class="py-2 pr-4 text-slate-600">{{ formatFileSize(format.filesize) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-else class="text-sm text-slate-500">暂无可下载格式。</p>
      </div>

      <DownloadPanel
        :video="result.video"
        :formats="result.formats"
        compliance-required
        @compliance-required="requireCompliance"
      />

      <SubtitlePanel :video-id="result.video.id" />

      <div class="flex flex-wrap items-center gap-2 border-t border-slate-100 pt-4">
        <button
          type="button"
          class="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-slate-700 disabled:cursor-not-allowed disabled:bg-slate-400"
          :disabled="creatingAnalysis || !result.can_analyze"
          :title="result.can_analyze ? '登录后可生成摘要' : '该视频没有可用字幕'"
          @click="startAnalysis"
        >
          {{ creatingAnalysis ? "正在创建…" : "AI 总结" }}
        </button>
        <span v-if="!result.can_analyze" class="text-xs text-amber-700">
          该视频没有可用字幕，暂不支持 AI 总结。
        </span>
        <span v-if="analysisError" role="alert" class="text-xs text-red-600">
          {{ analysisError.message }}
        </span>
        <span class="text-xs text-slate-400">{{ result.resolve_notice }}</span>
      </div>
    </article>

    <ComplianceNotice
      :open="complianceOpen"
      @confirm="confirmCompliance"
      @cancel="cancelCompliance"
    />
  </section>
</template>
