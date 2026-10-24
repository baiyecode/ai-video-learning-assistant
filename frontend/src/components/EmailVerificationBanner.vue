<script setup lang="ts">
/**
 * Banner for a signed-in Account whose email is not verified yet.
 *
 * It explains the exact boundary (解析/下载照常，Analysis 被 403 拦下) and offers the
 * only self-service fix: re-send the verification email. A frequency refusal (429)
 * shows when the ceiling lifts instead of a bare "稍后再试".
 */
import { ref } from "vue";

import { ApiError } from "@/lib/api";
import { verificationResendNotice } from "@/lib/authMessages";
import { useAuthStore } from "@/stores/auth";

const auth = useAuthStore();

const busy = ref(false);
const notice = ref<string | null>(null);
const error = ref<string | null>(null);

async function resend(): Promise<void> {
  if (busy.value) return;
  busy.value = true;
  notice.value = null;
  error.value = null;
  try {
    const body = await auth.requestVerification();
    notice.value = body.message;
  } catch (caught) {
    if (caught instanceof ApiError && caught.code === "too_many_requests") {
      error.value = verificationResendNotice(caught.details);
    } else {
      error.value =
        caught instanceof ApiError ? caught.message : "发送失败，请检查网络后重试";
    }
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <div
    v-if="auth.isAuthenticated && !auth.emailVerified"
    role="status"
    class="border-b border-amber-200 bg-amber-50"
  >
    <div class="mx-auto flex w-full max-w-5xl flex-wrap items-center justify-between gap-3 px-4 py-3">
      <p class="text-sm text-amber-900">
        邮箱尚未验证：视频解析与下载不受影响，但无法发起 Analysis。
        请打开验证邮件中的链接；没有收到？
      </p>
      <span class="flex flex-wrap items-center gap-3">
        <span v-if="notice" class="text-xs text-emerald-700">{{ notice }}</span>
        <span v-if="error" role="alert" class="text-xs text-red-700">{{ error }}</span>
        <button
          type="button"
          class="rounded-lg border border-amber-400 bg-white px-3 py-1.5 text-xs font-medium text-amber-900 transition-colors hover:bg-amber-100 disabled:cursor-not-allowed disabled:opacity-60"
          :disabled="busy"
          @click="resend"
        >
          {{ busy ? "正在发送…" : "重新发送验证邮件" }}
        </button>
      </span>
    </div>
  </div>
</template>
