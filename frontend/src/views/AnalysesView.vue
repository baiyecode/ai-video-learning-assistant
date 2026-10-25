<script setup lang="ts">
import { computed, onMounted } from "vue";

import { formatQuota, formatQuotaReset, isQuotaDepleted } from "@/lib/analysis";
import { membershipStatusLabel } from "@/lib/billing";
import { historyRows } from "@/lib/history";
import { useAuthStore } from "@/stores/auth";
import { useBillingStore } from "@/stores/billing";
import { useHistoryStore } from "@/stores/history";

const store = useHistoryStore();
const auth = useAuthStore();
const billing = useBillingStore();

const rows = computed(() => historyRows(store.items));
const quotaLabel = computed(() => (store.quota ? formatQuota(store.quota) : ""));
const quotaReset = computed(() => formatQuotaReset(store.quota?.resets_at));
// The free-plan cap exhausted today is the strongest moment to offer the upgrade.
const quotaDepleted = computed(
  () => !!store.quota && isQuotaDepleted(store.quota, billing.isVip),
);

onMounted(() => {
  void store.load();
  if (auth.isAuthenticated) void billing.loadMembership();
});

function statusClass(status: string): string {
  if (status === "failed") return "bg-red-50 text-red-700";
  if (status === "completed") return "bg-slate-100 text-slate-600";
  return "bg-sky-50 text-sky-700";
}
</script>

<template>
  <section class="mx-auto w-full max-w-3xl space-y-6">
    <div class="flex flex-wrap items-end justify-between gap-3">
      <div class="space-y-1">
        <h1 class="text-2xl font-bold tracking-tight text-slate-900">我的 Analysis</h1>
        <p class="text-sm text-slate-600">查看历史结果不会消耗 Quota；重新分析才会。</p>
      </div>
      <div class="flex flex-wrap items-center gap-2 text-xs text-slate-500">
        <span v-if="quotaLabel">{{ quotaLabel }}</span>
        <span v-if="quotaReset">{{ quotaReset }}</span>
        <span
          v-if="auth.isAuthenticated && billing.membership"
          class="rounded-full px-2 py-0.5 font-medium"
          :class="billing.isVip ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-600'"
        >
          {{ membershipStatusLabel(billing.membership) }}
        </span>
        <RouterLink
          v-if="quotaDepleted"
          to="/pricing"
          class="rounded-full bg-slate-900 px-2.5 py-0.5 font-medium text-white transition-colors hover:bg-slate-700"
        >
          升级不限次
        </RouterLink>
      </div>
    </div>

    <div
      v-if="store.loading"
      role="status"
      class="rounded-xl border border-slate-200 bg-white p-6 text-center text-sm text-slate-600"
    >
      正在加载历史记录…
    </div>

    <div
      v-else-if="store.error"
      role="alert"
      class="space-y-2 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800"
    >
      <p class="font-medium">{{ store.error }}</p>
      <button
        type="button"
        class="rounded-md border border-red-300 px-3 py-1 text-xs font-medium text-red-700 transition-colors hover:bg-red-100"
        @click="store.load()"
      >
        重试
      </button>
    </div>

    <div
      v-else-if="rows.length === 0"
      class="space-y-3 rounded-xl border border-dashed border-slate-300 bg-white p-10 text-center"
    >
      <p class="text-sm text-slate-600">还没有 Analysis 记录。</p>
      <RouterLink
        to="/"
        class="inline-block rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-slate-700"
      >
        去首页解析一个视频
      </RouterLink>
    </div>

    <ul v-else class="space-y-3">
      <li v-for="row in rows" :key="row.id">
        <RouterLink
          :to="`/analyses/${row.id}`"
          class="flex gap-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm transition-colors hover:border-slate-300 hover:bg-slate-50"
        >
          <div class="h-20 w-32 shrink-0 overflow-hidden rounded-lg bg-slate-100">
            <img
              v-if="row.thumbnailUrl"
              :src="row.thumbnailUrl"
              alt=""
              class="h-full w-full object-cover"
              loading="lazy"
            />
            <div
              v-else
              class="flex h-full w-full items-center justify-center text-xs text-slate-400"
            >
              {{ row.platformLabel || "视频" }}
            </div>
          </div>

          <div class="min-w-0 flex-1 space-y-1">
            <div class="flex flex-wrap items-center gap-2">
              <h2 class="min-w-0 truncate text-sm font-semibold text-slate-900">
                {{ row.title }}
              </h2>
              <span
                class="rounded-full px-2 py-0.5 text-xs font-medium"
                :class="statusClass(row.status)"
              >
                {{ row.statusLabel }}
              </span>
            </div>
            <div class="flex flex-wrap items-center gap-2 text-xs text-slate-500">
              <span v-if="row.platformLabel">{{ row.platformLabel }}</span>
              <span>{{ row.subtitleSourceLabel }}</span>
              <span v-if="row.createdLabel">{{ row.createdLabel }}</span>
              <span v-if="row.truncated" class="text-amber-700">基于截断字幕</span>
            </div>
            <p v-if="row.snippet" class="line-clamp-2 break-words text-xs text-slate-600">
              {{ row.snippet }}
            </p>
            <p v-else-if="row.status === 'failed'" class="text-xs text-red-600">
              生成失败{{ row.errorCode ? `（${row.errorCode}）` : "" }}
            </p>
            <p v-else class="text-xs text-slate-400">摘要生成中…</p>
          </div>
        </RouterLink>
      </li>
    </ul>
  </section>
</template>
