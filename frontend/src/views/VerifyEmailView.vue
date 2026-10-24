<script setup lang="ts">
/**
 * Landing page for the emailed verification link: ``/verify-email?token=…``.
 *
 * The token itself authenticates (no session required, ADR-0004 unchanged). This
 * page only calls ``POST /auth/verification/confirm`` once and shows the outcome;
 * success routes the user back into the main flow, failure explains why.
 */
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";

import { ApiError } from "@/lib/api";
import { useAuthStore } from "@/stores/auth";

const route = useRoute();
const auth = useAuthStore();

type Phase = "confirming" | "verified" | "invalid" | "expired" | "missing";
const phase = ref<Phase>("confirming");
const detail = ref<string | null>(null);

const token = computed(() => {
  const raw = route.query.token;
  return typeof raw === "string" && raw.trim() !== "" ? raw.trim() : null;
});

const headline = computed(() => {
  switch (phase.value) {
    case "verified":
      return "邮箱验证成功";
    case "expired":
      return "验证链接已过期";
    case "invalid":
    case "missing":
      return "验证链接无效";
    default:
      return "正在验证邮箱…";
  }
});

async function confirm(): Promise<void> {
  if (!token.value) {
    phase.value = "missing";
    detail.value = "链接中没有携带验证 Token，请从邮箱中的验证邮件重新打开。";
    return;
  }
  phase.value = "confirming";
  try {
    await auth.confirmVerification(token.value);
    phase.value = "verified";
  } catch (caught) {
    if (caught instanceof ApiError) {
      phase.value = caught.code === "verification_token_expired" ? "expired" : "invalid";
      detail.value = caught.message;
    } else {
      phase.value = "invalid";
      detail.value = "网络异常，请检查连接后从验证邮件重新打开链接。";
    }
  }
}

onMounted(() => void confirm());
</script>

<template>
  <section class="mx-auto w-full max-w-xl space-y-5 text-center">
    <div
      role="status"
      class="rounded-xl border p-8 shadow-sm space-y-3"
      :class="phase === 'verified'
        ? 'border-emerald-200 bg-emerald-50'
        : 'border-slate-200 bg-white'"
    >
      <p v-if="phase === 'confirming'" class="text-sm text-slate-600">正在验证邮箱，请稍候…</p>
      <template v-else>
        <h1
          class="text-xl font-bold tracking-tight"
          :class="phase === 'verified' ? 'text-emerald-800' : 'text-slate-900'"
        >
          {{ headline }}
        </h1>
        <p v-if="phase === 'verified'" class="text-sm text-emerald-700">
          邮箱已验证，现在可以发起 Analysis 了。
        </p>
        <p v-else class="text-sm text-slate-600">
          {{ detail ?? "链接只能使用一次，如已使用请忽略本邮件。" }}
        </p>
        <p v-if="phase === 'expired' || phase === 'invalid'" class="text-xs text-slate-500">
          需要新的链接：登录后可在页面顶部横幅中重新发送验证邮件。
        </p>
      </template>
    </div>

    <div class="flex flex-wrap justify-center gap-3">
      <RouterLink
        to="/"
        class="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-slate-700"
      >
        回到首页
      </RouterLink>
      <RouterLink
        v-if="!auth.isAuthenticated"
        to="/login"
        class="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 transition-colors hover:border-slate-400 hover:bg-white"
      >
        去登录
      </RouterLink>
      <button
        v-else-if="phase !== 'confirming' && phase !== 'verified'"
        type="button"
        class="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 transition-colors hover:border-slate-400 hover:bg-white"
        @click="confirm"
      >
        重试验证
      </button>
    </div>
  </section>
</template>
