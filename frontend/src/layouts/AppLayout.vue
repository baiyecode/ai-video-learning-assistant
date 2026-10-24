<script setup lang="ts">
import { useRouter } from "vue-router";

import AppFooter from "@/components/AppFooter.vue";
import { useAuthStore } from "@/stores/auth";

const auth = useAuthStore();
const router = useRouter();

async function logout(): Promise<void> {
  await auth.logout();
  await router.push({ name: "home" });
}
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
          <template v-if="auth.isAuthenticated">
            <RouterLink
              to="/analyses"
              class="transition-colors hover:text-slate-900"
            >
              我的分析
            </RouterLink>
            <span class="max-w-48 truncate text-slate-500" :title="auth.account?.email">
              {{ auth.account?.email }}
            </span>
            <button
              type="button"
              class="rounded-lg border border-slate-300 px-3 py-1.5 transition-colors hover:border-slate-400 hover:text-slate-900"
              @click="logout"
            >
              退出登录
            </button>
          </template>
          <RouterLink
            v-else
            to="/login"
            class="rounded-lg bg-slate-900 px-3 py-1.5 font-medium text-white transition-colors hover:bg-slate-700"
          >
            登录
          </RouterLink>
        </nav>
      </div>
    </header>

    <main class="mx-auto w-full max-w-5xl flex-1 px-4 py-10">
      <slot />
    </main>

    <AppFooter />
  </div>
</template>
