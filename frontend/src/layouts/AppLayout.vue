<script setup lang="ts">
import AppFooter from "@/components/AppFooter.vue";
</script>

<template>
  <div class="flex min-h-screen flex-col bg-slate-50 text-slate-900 antialiased">
    <header class="border-b border-slate-200 bg-white">
      <div class="mx-auto flex w-full max-w-5xl items-center justify-between px-4 py-3">
        <RouterLink to="/" class="text-lg font-semibold tracking-tight text-slate-900">
          AI 视频学习助手
        </RouterLink>
        <nav class="flex items-center gap-4 text-sm text-slate-600">
          <RouterLink to="/" class="transition-colors hover:text-slate-900">首页</RouterLink>
        </nav>
      </div>
    </header>

    <main class="mx-auto w-full max-w-5xl flex-1 px-4 py-10">
      <slot />
    </main>

    <AppFooter />
  </div>
</template>
