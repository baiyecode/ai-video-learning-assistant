<script setup lang="ts">
/**
 * Public marketing page (indexable): the same six capabilities as the home
 * page, expanded into problem, usage and limits. Copy lives in the shared
 * ``capabilities-content`` module so the two pages cannot drift; it stays inside
 * verified product facts — no ASR, no platform-wide promises, no DRM bypass.
 */
import { capabilities as features } from "@/site/capabilities-content";

</script>

<template>
  <div class="mx-auto max-w-4xl space-y-10">
    <header class="space-y-3">
      <h1 class="text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl">
        功能：从解析到 AI 分析
      </h1>
      <p class="text-slate-600">
        AI 视频学习助手把公开视频的解析、下载、字幕导出与 AI
        分析放在同一条流程里。下面按能力说明它解决什么问题、怎么用，以及明确的限制。
      </p>
    </header>

    <div class="grid gap-5 sm:grid-cols-2">
      <section
        v-for="feature in features"
        :key="feature.title"
        class="space-y-3 rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
      >
        <h2 class="text-lg font-semibold text-slate-900">{{ feature.title }}</h2>
        <div class="space-y-2 text-sm leading-relaxed text-slate-600">
          <p>
            <span class="font-medium text-slate-800">解决什么问题：</span>
            {{ feature.problem }}
          </p>
          <p>
            <span class="font-medium text-slate-800">如何使用：</span>
            {{ feature.usage }}
          </p>
          <p class="rounded-lg bg-slate-50 p-3 text-slate-600">
            <span class="font-medium text-slate-800">限制：</span>
            {{ feature.limit }}
          </p>
        </div>
      </section>
    </div>

    <section class="rounded-xl border border-slate-200 bg-white p-6 text-center shadow-sm">
      <h2 class="text-lg font-semibold text-slate-900">从一次解析开始</h2>
      <p class="mt-2 text-sm text-slate-600">
        回到首页粘贴页面地址，先解析；需要字幕与摘要时再登录账号。
      </p>
      <RouterLink
        to="/"
        class="mt-4 inline-block rounded-lg bg-slate-900 px-5 py-2 text-sm font-medium text-white transition-colors hover:bg-slate-700"
      >
        回到首页开始解析
      </RouterLink>
    </section>
  </div>
</template>
