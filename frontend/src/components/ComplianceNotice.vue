<script setup lang="ts">
import { nextTick, ref, watch } from "vue";

import { COMPLIANCE_STATEMENT } from "@/lib/compliance";

const props = defineProps<{ open: boolean }>();
const emit = defineEmits<{ confirm: []; cancel: [] }>();

const dialog = ref<HTMLElement | null>(null);

watch(
  () => props.open,
  async (open) => {
    if (!open) return;
    await nextTick();
    dialog.value?.focus();
  },
);
</script>

<template>
  <div
    v-if="open"
    class="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4"
    @click.self="emit('cancel')"
  >
    <div
      ref="dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="compliance-title"
      tabindex="-1"
      class="w-full max-w-lg space-y-4 rounded-xl bg-white p-6 shadow-xl outline-none"
      @keydown.esc="emit('cancel')"
    >
      <div class="space-y-1">
        <h2 id="compliance-title" class="text-lg font-semibold text-slate-900">下载前请确认</h2>
        <p class="text-sm font-medium text-slate-900">「{{ COMPLIANCE_STATEMENT }}」</p>
      </div>

      <ul class="list-disc space-y-1 pl-5 text-sm text-slate-600">
        <li>请仅下载你有权保存的内容：个人备份，或已获得权利人授权。</li>
        <li>本产品不提供绕过 DRM 或会员权限的能力，相关视频会被拒绝解析与下载。</li>
        <li>服务端临时文件将在 1 小时后自动删除，下载链接 15 分钟内有效。</li>
        <li>
          完整规则与举报入口见
          <RouterLink to="/terms" class="underline hover:text-slate-900" @click="emit('cancel')">
            使用条款
          </RouterLink>
          。
        </li>
      </ul>

      <div class="flex flex-wrap justify-end gap-3">
        <button
          type="button"
          class="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-100"
          @click="emit('cancel')"
        >
          取消
        </button>
        <button
          type="button"
          class="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-slate-700"
          @click="emit('confirm')"
        >
          我已了解，继续下载
        </button>
      </div>
    </div>
  </div>
</template>
