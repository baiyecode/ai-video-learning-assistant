<script setup lang="ts">
import { computed, onMounted } from "vue";

import { ApiError } from "@/lib/api";
import { formatQuota, formatQuotaReset } from "@/lib/analysis";
import {
  expirationNotice,
  membershipAlert,
  membershipStatusLabel,
  renewalNotice,
} from "@/lib/billing";
import { authErrorMessage } from "@/lib/authMessages";
import { useAnalysisStore } from "@/stores/analysis";
import { useAuthStore } from "@/stores/auth";
import { useBillingStore } from "@/stores/billing";

const auth = useAuthStore();
const billing = useBillingStore();
const analysis = useAnalysisStore();

const alert = computed(() => membershipAlert(billing.membership));
const expiration = computed(() => expirationNotice(billing.membership));
const renewal = computed(() => renewalNotice(billing.membership));
const quotaLabel = computed(() => formatQuota(analysis.quota));
const quotaReset = computed(() => formatQuotaReset(analysis.quota?.resets_at));

const portalBusy = computed(() => billing.loading);

onMounted(() => {
  void billing.loadMembership();
  // Remaining Quota stays visible right next to the subscription state (story 35).
  void analysis.loadQuota();
});

/** POST /billing/portal, then the browser owns the Stripe page. */
async function openPortal(): Promise<void> {
  try {
    const url = await billing.openPortal();
    window.location.assign(url);
  } catch (caught) {
    if (caught instanceof ApiError && caught.code === "subscription_not_found") {
      billing.error = authErrorMessage(caught.code);
    } else {
      billing.error =
        caught instanceof ApiError ? caught.message : "打开订阅管理失败，请稍后重试";
    }
  }
}
</script>

<template>
  <section class="mx-auto w-full max-w-3xl space-y-6">
    <div class="space-y-1">
      <h1 class="text-2xl font-bold tracking-tight text-slate-900">个人中心</h1>
      <p class="text-sm text-slate-600">{{ auth.account?.email }}</p>
    </div>

    <div class="space-y-4 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <h2 class="text-sm font-semibold text-slate-900">订阅状态</h2>
        <span
          class="rounded-full px-2 py-0.5 text-xs font-medium"
          :class="billing.vipActive ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-600'"
        >
          {{ membershipStatusLabel(billing.membership) }}
        </span>
      </div>

      <div v-if="billing.loading" role="status" class="text-sm text-slate-500">
        正在加载订阅状态…
      </div>
      <div v-else-if="billing.error" role="alert" class="space-y-2 text-sm text-red-700">
        <p>{{ billing.error }}</p>
        <button
          type="button"
          class="rounded-md border border-red-300 px-3 py-1 text-xs font-medium text-red-700 transition-colors hover:bg-red-100"
          @click="billing.loadMembership()"
        >
          重试
        </button>
      </div>
      <div v-else class="space-y-2 text-sm text-slate-700">
        <p v-if="renewal">{{ renewal }}</p>
        <p v-if="alert" role="alert" class="rounded-lg bg-red-50 p-3 text-red-800">
          {{ alert }}
        </p>
        <p v-if="expiration" class="rounded-lg bg-amber-50 p-3 text-amber-800">
          {{ expiration }}
        </p>
        <p v-if="billing.membership?.status === 'free'" class="text-slate-500">
          当前为免费版，每日 Quota 用尽后需等待重置。升级 VIP 后 Analysis 不限次。
        </p>
      </div>

      <div class="flex flex-wrap items-center gap-3 pt-1">
        <button
          type="button"
          class="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 transition-colors hover:border-slate-400 hover:bg-slate-50 disabled:cursor-not-allowed disabled:text-slate-400"
          :disabled="portalBusy"
          @click="openPortal"
        >
          {{ portalBusy ? "正在打开…" : "订阅管理" }}
        </button>
        <RouterLink
          to="/pricing"
          class="rounded-lg bg-slate-900 px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-slate-700"
        >
          升级 VIP
        </RouterLink>
      </div>
      <p v-if="!billing.loading && billing.error" class="text-xs text-slate-500">
        订阅状态以服务端记录为准；从支付页返回后这里会自动刷新。
      </p>
    </div>

    <div class="space-y-3 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 class="text-sm font-semibold text-slate-900">今日 Quota</h2>
      <p class="text-sm text-slate-700">
        {{ quotaLabel }}
        <span v-if="quotaReset" class="ml-2 text-xs text-slate-500">{{ quotaReset }}</span>
      </p>
    </div>

    <div
      class="space-y-2 rounded-xl border p-5 shadow-sm"
      :class="auth.emailVerified
        ? 'border-slate-200 bg-white'
        : 'border-amber-300 bg-amber-50'"
    >
      <h2 class="text-sm font-semibold text-slate-900">邮箱验证</h2>
      <p v-if="auth.emailVerified" class="text-sm text-emerald-700">
        邮箱已验证，可以正常发起 Analysis。
      </p>
      <p v-else class="text-sm text-amber-800">
        邮箱尚未验证：你可以解析与下载视频，但无法发起 Analysis。
        请查收注册时发送的验证邮件；没有收到可使用页面顶部横幅的「重新发送验证邮件」。
      </p>
    </div>
  </section>
</template>
