<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRoute } from "vue-router";

import { ApiError } from "@/lib/api";
import {
  PRICE_BENEFIT,
  PRICE_HEADLINE,
  PRICE_PROVIDER_NOTICE,
  membershipStatusLabel,
} from "@/lib/billing";
import { useAuthStore } from "@/stores/auth";
import { useBillingStore } from "@/stores/billing";

const auth = useAuthStore();
const billing = useBillingStore();
const route = useRoute();

const starting = ref(false);
const checkoutError = ref<string | null>(null);

onMounted(() => {
  if (auth.isAuthenticated) void billing.loadMembership();
});

/** The hosted payment page owns the card; this page only starts the jump. */
async function upgrade(): Promise<void> {
  if (!auth.isAuthenticated) {
    checkoutError.value = null;
    return;
  }
  if (starting.value) return;
  starting.value = true;
  checkoutError.value = null;
  try {
    const url = await billing.openCheckout();
    window.location.assign(url);
  } catch (caught) {
    checkoutError.value =
      caught instanceof ApiError ? caught.message : "暂时无法发起支付，请稍后重试";
    starting.value = false;
  }
}
</script>

<template>
  <section class="mx-auto w-full max-w-xl space-y-6">
    <div class="space-y-1">
      <h1 class="text-2xl font-bold tracking-tight text-slate-900">升级 VIP 会员</h1>
      <p class="text-sm text-slate-600">
        一个方案，一个价格：Analysis 不受每日 Quota 限制。
      </p>
    </div>

    <div class="space-y-4 rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
      <div class="flex items-baseline gap-2">
        <span class="text-3xl font-bold tracking-tight text-slate-900">{{ PRICE_HEADLINE }}</span>
        <span class="text-sm text-slate-500">按月订阅，随时取消</span>
      </div>
      <ul class="space-y-1 text-sm text-slate-700">
        <li class="flex items-center gap-2">
          <span class="h-1.5 w-1.5 rounded-full bg-emerald-500" aria-hidden="true" />
          {{ PRICE_BENEFIT }}
        </li>
        <li class="flex items-center gap-2">
          <span class="h-1.5 w-1.5 rounded-full bg-emerald-500" aria-hidden="true" />
          支付由 Stripe 托管，本产品不接触卡号
        </li>
      </ul>
      <p class="rounded-lg bg-slate-50 p-3 text-xs text-slate-500">
        {{ PRICE_PROVIDER_NOTICE }}
      </p>

      <p v-if="checkoutError" role="alert" class="text-xs text-red-600">{{ checkoutError }}</p>

      <button
        v-if="auth.isAuthenticated"
        type="button"
        class="w-full rounded-lg bg-slate-900 px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-slate-700 disabled:cursor-not-allowed disabled:bg-slate-400"
        :disabled="starting"
        @click="upgrade"
      >
        {{ starting ? "正在跳转支付…" : "立即升级" }}
      </button>
      <RouterLink
        v-else
        :to="{ name: 'login', query: { next: route.fullPath } }"
        class="block w-full rounded-lg bg-slate-900 px-4 py-2.5 text-center text-sm font-medium text-white transition-colors hover:bg-slate-700"
      >
        登录后升级
      </RouterLink>
      <p v-if="!auth.isAuthenticated" class="text-xs text-slate-500">
        升级需要先登录账号；注册后请留意邮箱中的验证邮件。
      </p>
    </div>

    <p v-if="auth.isAuthenticated" class="text-xs text-slate-500">
      当前订阅状态：{{ membershipStatusLabel(billing.membership) }}。
      支付完成后回到本站，以个人中心的订阅状态为准。
      <RouterLink to="/account" class="text-slate-700 underline hover:text-slate-900">
        前往个人中心
      </RouterLink>
    </p>
  </section>
</template>
