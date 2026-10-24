<script setup lang="ts">
import { computed, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { ApiError } from "@/lib/api";
import { authErrorMessage } from "@/lib/authMessages";
import { validatePassword } from "@/lib/validation";
import { useAuthStore } from "@/stores/auth";

type Mode = "login" | "register";

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();

const mode = ref<Mode>("login");
const email = ref("");
const password = ref("");
const touched = ref(false);
const submitting = ref(false);
const errorMessage = ref<string | null>(null);
const noticeMessage = ref<string | null>(null);

const isRegister = computed(() => mode.value === "register");
const passwordError = computed(() => (touched.value ? validatePassword(password.value) : null));

const nextPath = computed(() => {
  const next = route.query.next;
  if (typeof next === "string" && next.startsWith("/") && !next.startsWith("//")) return next;
  return "/analyses";
});

function switchMode(next: Mode): void {
  if (submitting.value) return;
  mode.value = next;
  touched.value = false;
  errorMessage.value = null;
  noticeMessage.value = null;
}

async function submit(): Promise<void> {
  touched.value = true;
  errorMessage.value = null;
  noticeMessage.value = null;
  if (validatePassword(password.value) !== null) return;

  submitting.value = true;
  try {
    if (isRegister.value) {
      // Registration only acknowledges; it never signs us in (P2-06, ticket #22).
      // Switch to the login tab so the Account can verify the emailed link and sign in.
      noticeMessage.value = await auth.register(email.value, password.value);
      mode.value = "login";
      return;
    }
    await auth.login(email.value, password.value);
    await router.replace(nextPath.value);
  } catch (error) {
    if (error instanceof ApiError) {
      errorMessage.value = authErrorMessage(error.code);
    } else {
      errorMessage.value = authErrorMessage(undefined);
    }
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <section class="mx-auto w-full max-w-md space-y-6">
    <div class="space-y-2 text-center">
      <h1 class="text-2xl font-bold tracking-tight text-slate-900">
        {{ isRegister ? "创建 Account" : "登录" }}
      </h1>
      <p class="text-sm text-slate-600">
        登录后可以发起 Analysis，保存摘要与思维导图。
      </p>
    </div>

    <div class="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
      <div class="mb-6 grid grid-cols-2 rounded-lg bg-slate-100 p-1 text-sm font-medium">
        <button
          type="button"
          class="rounded-md px-3 py-2 transition-colors"
          :class="!isRegister ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-800'"
          @click="switchMode('login')"
        >
          登录
        </button>
        <button
          type="button"
          class="rounded-md px-3 py-2 transition-colors"
          :class="isRegister ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-800'"
          @click="switchMode('register')"
        >
          注册
        </button>
      </div>

      <form class="space-y-4" novalidate @submit.prevent="submit">
        <div class="space-y-1">
          <label for="email" class="block text-sm font-medium text-slate-700">邮箱</label>
          <input
            id="email"
            v-model="email"
            type="email"
            required
            autocomplete="email"
            class="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-500 disabled:bg-slate-100"
            placeholder="you@example.com"
            :disabled="submitting"
          />
        </div>

        <div class="space-y-1">
          <label for="password" class="block text-sm font-medium text-slate-700">密码</label>
          <input
            id="password"
            v-model="password"
            type="password"
            required
            :autocomplete="isRegister ? 'new-password' : 'current-password'"
            class="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-500 disabled:bg-slate-100"
            :aria-invalid="passwordError !== null"
            aria-describedby="password-hint"
            :disabled="submitting"
          />
          <p
            id="password-hint"
            class="text-xs"
            :class="passwordError ? 'text-red-600' : 'text-slate-500'"
          >
            {{ passwordError ?? "至少 8 位，不要求字符组合" }}
          </p>
        </div>

        <p v-if="errorMessage" class="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">
          {{ errorMessage }}
        </p>

        <p v-if="noticeMessage" class="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-700" role="status">
          {{ noticeMessage }}
        </p>

        <button
          type="submit"
          class="w-full rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-slate-700 disabled:cursor-not-allowed disabled:bg-slate-400"
          :disabled="submitting"
        >
          {{ submitting ? "请稍候…" : isRegister ? "注册" : "登录" }}
        </button>
      </form>
    </div>

    <p class="text-center text-xs text-slate-400">
      继续即表示同意《使用条款》。仅限个人备份或已获授权内容。
    </p>
  </section>
</template>
