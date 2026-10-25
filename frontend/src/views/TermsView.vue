<script setup lang="ts">
import { nextTick, onMounted, reactive, ref } from "vue";
import { useRoute } from "vue-router";

import { ApiError, api } from "@/lib/api";
import {
  REPORT_REASONS,
  toReportPayload,
  validateReport,
  type ReportFormInput,
} from "@/lib/report";

interface ReportReceipt {
  id: string;
  created_at: string;
  status: string;
}

const route = useRoute();

const form = reactive<ReportFormInput>({
  url: "",
  reason: REPORT_REASONS[0].value,
  contact: "",
  details: "",
});
const submitting = ref(false);
const formError = ref<string | null>(null);
const receipt = ref<ReportReceipt | null>(null);

async function submitReport(): Promise<void> {
  if (submitting.value) return;
  formError.value = null;

  const message = validateReport(form);
  if (message !== null) {
    formError.value = message;
    receipt.value = null;
    return;
  }

  submitting.value = true;
  try {
    receipt.value = await api.post<ReportReceipt>("/reports", toReportPayload(form));
    form.url = "";
    form.contact = "";
    form.details = "";
  } catch (caught) {
    receipt.value = null;
    formError.value =
      caught instanceof ApiError ? caught.message : "网络异常，举报未能提交，请稍后重试。";
  } finally {
    submitting.value = false;
  }
}

onMounted(async () => {
  if (route.hash !== "#report") return;
  // The footer links to /terms#report; lazy route rendering can beat the router's scroll.
  await nextTick();
  document.getElementById("report")?.scrollIntoView({ behavior: "smooth" });
});
</script>

<template>
  <article class="mx-auto max-w-2xl space-y-8">
    <header class="space-y-2">
      <h1 class="text-3xl font-bold tracking-tight text-slate-900">使用条款</h1>
      <p class="text-sm text-slate-500">请在解析、下载或使用 AI 分析前阅读以下条款。</p>
    </header>

    <section class="space-y-2 text-slate-700">
      <h2 class="text-xl font-semibold text-slate-900">一、合规使用</h2>
      <p>
        本产品仅限用于<strong>个人备份或已获授权内容</strong>。发起 Download
        之前，请确认你对目标视频拥有保存权，或已获得权利人的明确授权。
      </p>
      <p>
        本产品不提供绕过 DRM 或会员权限的能力。受 DRM 保护的视频
        与会员专属内容会被明确拒绝解析与下载，请通过 Platform 的官方渠道观看。
      </p>
    </section>

    <section class="space-y-2 text-slate-700">
      <h2 class="text-xl font-semibold text-slate-900">二、禁止用途</h2>
      <ul class="list-disc space-y-1 pl-5">
        <li>未经授权复制、传播、销售或公开提供受版权保护的内容。</li>
        <li>破解、绕过或协助绕过 DRM、付费墙与会员权限。</li>
        <li>批量抓取、自动化爬取或对 Platform 造成异常负载。</li>
        <li>将本产品用于违法活动，或侵害他人的合法权益。</li>
        <li>干扰、攻击或试图破坏本服务的正常运行。</li>
      </ul>
    </section>

    <section class="space-y-2 text-slate-700">
      <h2 class="text-xl font-semibold text-slate-900">三、临时文件与保留策略</h2>
      <p>
        Download 完成后，服务端临时文件将在 <strong>1 小时后自动删除</strong>；下载链接在
        15 分钟内有效，且只对当次 Download 生效。请在有效期内保存文件，过期后需要重新发起 Download。
      </p>
      <p>访客的 Download 不产生长期历史记录，本产品不会长期保存下载的文件。</p>
    </section>

    <section class="space-y-2 text-slate-700">
      <h2 class="text-xl font-semibold text-slate-900">四、版权与投诉</h2>
      <p>
        我们尊重版权。如你是权利人，或认为某个链接涉及侵权、滥用或绕过权限，请通过下方举报入口提交
        视频页面地址、原因与必要的说明。我们会在核实后处理，并保留在收到有效通知后停止处理相关内容的权利。
      </p>
    </section>

    <section id="report" class="scroll-mt-24 space-y-4 border-t border-slate-200 pt-6">
      <div class="space-y-1">
        <h2 class="text-xl font-semibold text-slate-900">五、举报方式</h2>
        <p class="text-sm text-slate-600">
          提交后会生成可追踪的举报编号。请尽量提供具体视频地址与说明；联系方式仅用于核实，不会公开展示。
        </p>
      </div>

      <form class="space-y-4 rounded-xl border border-slate-200 bg-white p-5 shadow-sm" @submit.prevent="submitReport">
        <label class="flex flex-col gap-1 text-sm font-medium text-slate-700">
          视频地址（可选）
          <input
            v-model="form.url"
            type="text"
            inputmode="url"
            placeholder="https://..."
            class="rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal outline-none placeholder:text-slate-400 focus:border-slate-500"
          />
        </label>

        <label class="flex flex-col gap-1 text-sm font-medium text-slate-700">
          举报原因
          <select
            v-model="form.reason"
            class="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-normal outline-none focus:border-slate-500"
          >
            <option v-for="reason in REPORT_REASONS" :key="reason.value" :value="reason.value">
              {{ reason.label }}
            </option>
          </select>
        </label>

        <label class="flex flex-col gap-1 text-sm font-medium text-slate-700">
          联系方式（可选）
          <input
            v-model="form.contact"
            type="text"
            placeholder="邮箱或其他可联系到你的方式"
            class="rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal outline-none placeholder:text-slate-400 focus:border-slate-500"
          />
        </label>

        <label class="flex flex-col gap-1 text-sm font-medium text-slate-700">
          详情（可选）
          <textarea
            v-model="form.details"
            rows="4"
            placeholder="请描述侵权或滥用情况，例如权利归属、具体时间点等。"
            class="resize-y rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal outline-none placeholder:text-slate-400 focus:border-slate-500"
          />
        </label>

        <div
          v-if="formError"
          role="alert"
          class="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800"
        >
          {{ formError }}
        </div>

        <div
          v-if="receipt"
          role="status"
          class="space-y-1 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800"
        >
          <p>举报已提交，我们会尽快核实处理。</p>
          <p class="text-xs">举报编号：{{ receipt.id }}</p>
        </div>

        <button
          type="submit"
          class="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-slate-700 disabled:cursor-not-allowed disabled:bg-slate-400"
          :disabled="submitting"
        >
          {{ submitting ? "正在提交…" : "提交举报" }}
        </button>
      </form>
    </section>

    <section
      id="terms-cta"
      class="rounded-xl border border-slate-200 bg-white p-6 text-center shadow-sm"
    >
      <h2 class="text-lg font-semibold text-slate-900">条款读完，回到工具</h2>
      <p class="mt-2 text-sm text-slate-600">
        回到首页粘贴页面地址，先解析；需要字幕与摘要时再登录账号。
      </p>
      <RouterLink
        to="/"
        class="mt-4 inline-block rounded-lg bg-slate-900 px-5 py-2 text-sm font-medium text-white transition-colors hover:bg-slate-700"
      >
        回到首页开始解析
      </RouterLink>
    </section>
  </article>
</template>
