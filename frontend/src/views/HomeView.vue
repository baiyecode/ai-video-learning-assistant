<script setup lang="ts">
const supportedPlatforms = ["B 站", "YouTube", "抖音"];
</script>

<template>
  <section class="mx-auto max-w-2xl space-y-6">
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
      @submit.prevent
    >
      <input
        class="min-w-0 flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none placeholder:text-slate-400 disabled:cursor-not-allowed disabled:bg-slate-100"
        type="url"
        inputmode="url"
        aria-label="视频链接"
        placeholder="https://www.bilibili.com/video/..."
        disabled
      />
      <button
        type="submit"
        class="rounded-lg bg-slate-900 px-5 py-2 text-sm font-medium text-white transition-colors hover:bg-slate-700 disabled:cursor-not-allowed disabled:bg-slate-400"
        disabled
      >
        解析视频
      </button>
    </form>

    <div class="space-y-2 text-center text-sm text-slate-500">
      <p>解析与下载功能即将上线。</p>
      <p>当前支持：{{ supportedPlatforms.join("、") }} 等公开视频平台。</p>
      <p class="text-xs text-slate-400">仅限个人备份或已获授权内容，不支持播放列表、直播与 DRM 内容。</p>
    </div>
  </section>
</template>
