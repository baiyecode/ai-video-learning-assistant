<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRoute } from "vue-router";

import { ApiError } from "@/lib/api";
import {
  DAILY_FREE_ANALYSIS_LIMIT,
  MONTHLY_PRICE_USD,
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

/** Same constant as ``PRICE_HEADLINE``; used where the headline would repeat. */
const priceUsd = MONTHLY_PRICE_USD.toFixed(2);

const comparison = [
  {
    benefit: "每日 Analysis",
    free: `${DAILY_FREE_ANALYSIS_LIMIT} 次（Asia/Shanghai 自然日）`,
    vip: PRICE_BENEFIT,
  },
  { benefit: "视频解析", free: "可用", vip: "可用" },
  { benefit: "Download 与 Subtitle 导出", free: "可用", vip: "可用" },
  { benefit: "订阅价格", free: "免费", vip: `每月 ${priceUsd} 美元（USD）` },
  { benefit: "计费与取消", free: "无需付费", vip: "按月自动续费，可随时取消" },
];

const faqs = [
  {
    question: "VIP 会员多少钱？",
    answer: `每月 ${priceUsd} 美元（USD），按月自动续费；实际扣款金额与条款以支付方结账页展示为准。`,
  },
  {
    question: "VIP 解锁哪些能力？",
    answer: `${PRICE_BENEFIT}。视频解析、Download 与 Subtitle 导出对免费账号同样开放，VIP 不改变这些能力的上限。`,
  },
  {
    question: "如何取消订阅？",
    answer:
      "在个人中心的「订阅管理」中进入 Stripe 门户取消自动续费；取消后不再扣费，VIP 权益保留至当期结束，之后恢复免费 Quota。",
  },
  {
    question: "免费 Quota 每天重置吗？",
    answer:
      `会。免费账号每个 Asia/Shanghai 自然日 ${DAILY_FREE_ANALYSIS_LIMIT} 次 Analysis；成功创建才消耗，失败会退回，查看已有结果不消耗。`,
  },
  {
    question: "开通 VIP 会改变 Download 限制吗？",
    answer:
      "不会。Download 仍受单个视频最长 2 小时、最大 2 GB 的限制，服务端文件保留 1 小时，下载链接 15 分钟内有效。",
  },
];

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
  <div class="mx-auto w-full max-w-4xl space-y-10">
    <header class="space-y-2">
      <h1 class="text-3xl font-bold tracking-tight text-slate-900">升级 VIP 会员</h1>
      <p class="text-sm text-slate-600">
        一个方案，一个价格：Analysis 不受每日 Quota 限制。下方对比免费账号与 VIP 的权益，并说明计费与取消方式。
      </p>
    </header>

    <section class="max-w-2xl space-y-4 rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
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
    </section>

    <p v-if="auth.isAuthenticated" class="text-xs text-slate-500">
      当前订阅状态：{{ membershipStatusLabel(billing.membership) }}。
      支付完成后回到本站，以个人中心的订阅状态为准。
      <RouterLink to="/account" class="text-slate-700 underline hover:text-slate-900">
        前往个人中心
      </RouterLink>
    </p>

    <section class="space-y-3">
      <h2 class="text-xl font-semibold text-slate-900">免费账号与 VIP 会员对比</h2>
      <div class="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm">
        <table class="w-full border-collapse text-left text-sm">
          <caption class="border-b border-slate-200 px-4 py-3 text-left text-sm text-slate-600">
            免费账号与 VIP 会员的权益对比；VIP 按月订阅，价格以支付方结账页为准。
          </caption>
          <thead class="bg-slate-50 text-slate-700">
            <tr>
              <th scope="col" class="px-4 py-2 font-semibold">权益</th>
              <th scope="col" class="px-4 py-2 font-semibold">免费账号</th>
              <th scope="col" class="px-4 py-2 font-semibold">VIP 会员</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100 text-slate-700">
            <tr v-for="row in comparison" :key="row.benefit">
              <th scope="row" class="px-4 py-2 font-medium text-slate-800">{{ row.benefit }}</th>
              <td class="px-4 py-2">{{ row.free }}</td>
              <td class="px-4 py-2">{{ row.vip }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section class="space-y-3">
      <h2 class="text-xl font-semibold text-slate-900">计费与取消</h2>
      <ul class="list-disc space-y-1 pl-5 text-sm leading-relaxed text-slate-700">
        <li>订阅通过 Stripe 托管的结账页按月扣费，本产品不接触或保存卡号。</li>
        <li>可随时在个人中心的「订阅管理」中进入 Stripe 门户取消自动续费。</li>
        <li>取消后不再续费，VIP 权益保留至当期结束，之后恢复免费 Quota。</li>
        <li>实际扣款金额与条款以支付方结账页展示为准。</li>
      </ul>
    </section>

    <section id="pricing-faq" class="space-y-4">
      <h2 class="text-xl font-semibold text-slate-900">常见问题</h2>
      <div class="space-y-3">
        <div v-for="faq in faqs" :key="faq.question" class="space-y-1">
          <h3 class="text-base font-semibold text-slate-900">{{ faq.question }}</h3>
          <p class="text-sm leading-relaxed text-slate-600">{{ faq.answer }}</p>
        </div>
      </div>
    </section>
  </div>
</template>
