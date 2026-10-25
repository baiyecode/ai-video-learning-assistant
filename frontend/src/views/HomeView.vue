<script setup lang="ts">
import { computed, ref } from "vue";
import { useRouter } from "vue-router";

import ComplianceNotice from "@/components/ComplianceNotice.vue";
import DownloadPanel from "@/components/DownloadPanel.vue";
import SubtitlePanel from "@/components/SubtitlePanel.vue";
import { acknowledgeCompliance, complianceMessageForCode } from "@/lib/compliance";
import { DAILY_FREE_ANALYSIS_LIMIT, PRICE_HEADLINE } from "@/lib/billing";
import { asUiError, isQuotaExhausted, uiErrorMessage, type UiError } from "@/lib/uiError";
import {
  formatDuration,
  formatFileSize,
  platformLabel,
  subtitleSourceLabel,
} from "@/lib/video";
import { useArticleCollection } from "@/site/article-sources";
import { capabilities } from "@/site/capabilities-content";
import { homeFaqItems } from "@/site/faq-content";
import { guideSteps } from "@/site/guide-content";
import { useAnalysisStore } from "@/stores/analysis";
import { useAuthStore } from "@/stores/auth";
import { useVideoStore } from "@/stores/video";

const store = useVideoStore();
const auth = useAuthStore();
const analysisStore = useAnalysisStore();
const router = useRouter();
const url = ref("");
const creatingAnalysis = ref(false);
const analysisError = ref<UiError | null>(null);

/** Marketing content lives below the tool and disappears once a Video resolves. */
const latestArticles = useArticleCollection().published.slice(0, 3);
const marketingFaqs = homeFaqItems;

const steps = guideSteps;

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
    analysisError.value = asUiError(caught);
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
        粘贴视频地址，下载视频、导出字幕并生成 AI 摘要
      </h1>
      <p class="text-slate-600">
        解析公开视频，导出字幕，并基于字幕生成简体中文摘要与思维导图。
      </p>
    </div>

    <form
      id="resolve"
      class="flex flex-col gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm sm:flex-row"
      @submit.prevent="submit"
    >
      <input
        v-model="url"
        class="min-w-0 flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none placeholder:text-slate-400 focus:border-slate-500 disabled:cursor-not-allowed disabled:bg-slate-100"
        type="text"
        inputmode="url"
        aria-label="视频地址"
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

    <noscript>
      <p
        class="rounded-lg border border-amber-200 bg-amber-50 p-3 text-center text-xs text-amber-800"
      >
        本工具需要 JavaScript 才能解析页面地址；下方的产品介绍、使用指南、常见问题与文章仍可直接阅读。
      </p>
    </noscript>

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
      <p class="font-medium">{{ complianceHint ?? uiErrorMessage(error) }}</p>
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
              该视频没有可用字幕，暂不支持 AI 分析。
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
          {{ creatingAnalysis ? "正在创建…" : "AI 分析" }}
        </button>
        <span v-if="!result.can_analyze" class="text-xs text-amber-700">
          该视频没有可用字幕，暂不支持 AI 分析。
        </span>
        <span v-if="analysisError" role="alert" class="text-xs text-red-600">
          {{ uiErrorMessage(analysisError) }}
          <RouterLink
            v-if="isQuotaExhausted(analysisError)"
            to="/pricing"
            class="ml-2 font-medium text-slate-900 underline transition-colors hover:text-slate-600"
          >
            升级 VIP，Analysis 不限次
          </RouterLink>
          <RouterLink
            v-else-if="analysisError.code === 'email_not_verified'"
            to="/account"
            class="ml-2 font-medium text-slate-900 underline transition-colors hover:text-slate-600"
          >
            查看验证指引
          </RouterLink>
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

  <!-- Marketing surface: only while there is no resolved Video, so the result
       card stays the focus once a page address has been parsed. -->
  <div v-if="!result" class="mx-auto mt-12 max-w-4xl space-y-10">
    <section id="home-value" aria-labelledby="home-value-heading" class="max-w-3xl space-y-3">
      <h2 id="home-value-heading" class="text-2xl font-bold tracking-tight text-slate-900">
        把公开视频变成可用的学习材料
      </h2>
      <p class="leading-relaxed text-slate-600">
        先确认页面地址能否解析、视频是否带有 Subtitle，再按需保存文件或生成摘要。解析、Download、Subtitle 导出与 Analysis 在同一条流程里完成，
        不需要在多个工具之间搬运文本。
      </p>
      <a
        href="#resolve"
        class="inline-block text-sm font-medium text-slate-900 underline transition-colors hover:text-slate-600"
      >
        回到解析表单开始解析
      </a>
    </section>

    <section id="home-steps" aria-labelledby="home-steps-heading" class="space-y-4">
      <h2 id="home-steps-heading" class="text-2xl font-bold tracking-tight text-slate-900">
        三步完成一次解析
      </h2>
      <ol class="grid gap-4 sm:grid-cols-3">
        <li
          v-for="(step, index) in steps"
          :key="step.title"
          class="space-y-2 rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
        >
          <span class="text-xs font-medium text-slate-400">步骤 {{ index + 1 }}</span>
          <h3 class="text-lg font-semibold text-slate-900">{{ step.title }}</h3>
          <p class="text-sm leading-relaxed text-slate-600">{{ step.text }}</p>
        </li>
      </ol>
    </section>

    <section id="home-capabilities" aria-labelledby="home-capabilities-heading" class="space-y-4">
      <h2 id="home-capabilities-heading" class="text-2xl font-bold tracking-tight text-slate-900">
        六项能力
      </h2>
      <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <div
          v-for="capability in capabilities"
          :key="capability.title"
          class="flex flex-col gap-2 rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
        >
          <h3 class="text-base font-semibold text-slate-900">{{ capability.title }}</h3>
          <p class="flex-1 text-sm leading-relaxed text-slate-600">{{ capability.summary }}</p>
          <RouterLink
            to="/features"
            class="text-sm font-medium text-slate-900 underline transition-colors hover:text-slate-600"
          >
            查看功能说明
          </RouterLink>
        </div>
      </div>
    </section>

    <section id="home-platforms" aria-labelledby="home-platforms-heading" class="space-y-4">
      <h2 id="home-platforms-heading" class="text-2xl font-bold tracking-tight text-slate-900">
        支持的 Platform 与限制
      </h2>
      <div class="grid gap-4 sm:grid-cols-2">
        <div class="space-y-2 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h3 class="text-base font-semibold text-slate-900">支持的 Platform</h3>
          <ul class="list-disc space-y-1 pl-5 text-sm leading-relaxed text-slate-600">
            <li>B 站：解析、Download 与 Subtitle 导出。</li>
            <li>YouTube：解析、Download 与 Subtitle 导出。</li>
            <li>抖音：仅在部署开启灰度（APP_DOUYIN_ENABLED）时可用，产物为单一清晰度且带水印。</li>
          </ul>
        </div>
        <div class="space-y-2 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h3 class="text-base font-semibold text-slate-900">关键限制</h3>
          <ul class="list-disc space-y-1 pl-5 text-sm leading-relaxed text-slate-600">
            <li>单个视频最长 2 小时、最大 2 GB。</li>
            <li>服务端文件最多保留 1 小时，下载链接 15 分钟内有效。</li>
            <li>不支持播放列表、直播、DRM 与会员专属内容。</li>
            <li>不做 ASR：没有 Subtitle 就不能导出字幕或生成 Analysis。</li>
          </ul>
        </div>
      </div>
    </section>

    <section
      id="home-pricing"
      aria-labelledby="home-pricing-heading"
      class="space-y-3 rounded-xl border border-slate-200 bg-white p-6 shadow-sm"
    >
      <h2 id="home-pricing-heading" class="text-2xl font-bold tracking-tight text-slate-900">
        价格与升级
      </h2>
      <p class="text-sm leading-relaxed text-slate-600">
        免费账号每日 {{ DAILY_FREE_ANALYSIS_LIMIT }} 次 Analysis；VIP 会员
        <strong class="font-semibold text-slate-900">{{ PRICE_HEADLINE }}</strong>
        解锁 Analysis 不限次，按月自动续费，可随时在订阅管理中取消。
      </p>
      <RouterLink
        to="/pricing"
        class="inline-block rounded-lg bg-slate-900 px-5 py-2 text-sm font-medium text-white transition-colors hover:bg-slate-700"
      >
        查看价格与升级
      </RouterLink>
    </section>

    <section id="home-faq" aria-labelledby="home-faq-heading" class="space-y-4">
      <h2 id="home-faq-heading" class="text-2xl font-bold tracking-tight text-slate-900">
        常见问题
      </h2>
      <div class="grid gap-4 sm:grid-cols-2">
        <div
          v-for="item in marketingFaqs"
          :key="item.question"
          class="space-y-2 rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
        >
          <h3 class="text-base font-semibold text-slate-900">{{ item.question }}</h3>
          <p class="text-sm leading-relaxed text-slate-600">{{ item.answer }}</p>
        </div>
      </div>
      <RouterLink
        to="/faq"
        class="inline-block text-sm font-medium text-slate-900 underline transition-colors hover:text-slate-600"
      >
        查看全部常见问题
      </RouterLink>
    </section>

    <section id="home-articles" aria-labelledby="home-articles-heading" class="space-y-4">
      <h2 id="home-articles-heading" class="text-2xl font-bold tracking-tight text-slate-900">
        最新文章
      </h2>
      <ul class="grid gap-4 sm:grid-cols-3">
        <li v-for="article in latestArticles" :key="article.slug">
          <article class="flex h-full flex-col gap-2 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
            <h3 class="text-base font-semibold text-slate-900">
              <RouterLink
                :to="`/articles/${article.slug}`"
                class="transition-colors hover:text-slate-600"
              >
                {{ article.title }}
              </RouterLink>
            </h3>
            <p class="flex-1 text-sm leading-relaxed text-slate-600">{{ article.description }}</p>
            <p class="text-xs text-slate-500">
              <time :datetime="article.published">{{ article.published }}</time>
              · 约 {{ article.readingMinutes }} 分钟阅读
            </p>
          </article>
        </li>
      </ul>
      <RouterLink
        to="/articles"
        class="inline-block text-sm font-medium text-slate-900 underline transition-colors hover:text-slate-600"
      >
        全部文章
      </RouterLink>
    </section>

    <section id="home-compliance" aria-labelledby="home-compliance-heading" class="space-y-3">
      <h2 id="home-compliance-heading" class="text-2xl font-bold tracking-tight text-slate-900">
        合规使用
      </h2>
      <p class="text-sm leading-relaxed text-slate-600">
        本工具仅用于个人备份或已获授权的内容；不支持播放列表、直播、DRM 与会员专属内容。侵权或滥用可通过
        <RouterLink to="/terms#report" class="font-medium text-slate-900 underline hover:text-slate-600">
          举报表单
        </RouterLink>
        反馈。
      </p>
    </section>
  </div>
</template>
