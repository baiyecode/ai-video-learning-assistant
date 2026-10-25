<script setup lang="ts">
/**
 * Public guide (indexable): one ordered workflow, platform differences and the
 * troubleshooting paths. Step titles/text come from ``guide-content`` so the
 * visible list and the HowTo JSON-LD are the same strings.
 */
import { DAILY_FREE_ANALYSIS_LIMIT } from "@/lib/billing";
import { guideSteps } from "@/site/guide-content";

const platforms = [
  {
    name: "B 站",
    availability: "始终可用",
    note: "解析、Download 与 Subtitle 导出均可使用；没有字幕的视频不能 Analysis。",
  },
  {
    name: "YouTube",
    availability: "始终可用",
    note: "人工字幕与平台自动生成字幕都可以导出；不做 ASR。",
  },
  {
    name: "抖音",
    availability: "灰度开关控制",
    note: "仅当部署开启 APP_DOUYIN_ENABLED 时可用；产物为单一清晰度且带水印。",
  },
];

const troubleshooting = [
  {
    question: "视频没有 Subtitle，不能生成 Analysis",
    answer:
      "Analysis 只读取 Platform 提供的 Subtitle。没有可用字幕时仍可下载文件，但不能导出字幕，也不能发起 Analysis；本工具不做 ASR。",
  },
  {
    question: "DRM 或会员专属内容会被拒绝",
    answer:
      "DRM 与会员专属内容不在支持范围内，解析阶段就会返回不可用；本工具不会绕过 DRM 或会员限制。",
  },
  {
    question: "下载链接 15 分钟后过期",
    answer:
      "下载链接 15 分钟内有效，服务端文件最多保留 1 小时。过期后重新解析同一个页面地址即可生成新的链接。",
  },
  {
    question: "今日 Quota 已用尽",
    answer:
      `免费 Account 每个 Asia/Shanghai 自然日 ${DAILY_FREE_ANALYSIS_LIMIT} 次 Analysis，次日重置；也可以在价格页升级 VIP 解除每日 Quota 限制。`,
  },
  {
    question: "邮箱尚未验证",
    answer:
      "发起 Analysis 时会提示先验证邮箱；解析、Download 与 Subtitle 导出不受影响。请到个人中心重新发送验证邮件，并打开邮件中的链接。",
  },
  {
    question: "解析或 Download 失败",
    answer:
      "确认单个视频不超过 2 小时、2 GB，且不是播放列表、直播、DRM 或会员专属内容；Visitor 每小时最多发起 5 次 Download。",
  },
];
</script>

<template>
  <div class="mx-auto max-w-4xl space-y-10">
    <header class="space-y-3">
      <h1 class="text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl">
        使用指南：从页面地址到 AI 分析
      </h1>
      <p class="max-w-3xl text-slate-600">
        从粘贴页面地址到拿到 Subtitle、Download 与 Analysis，只需要三步。下面同时说明平台差异、会被拒绝的内容，以及常见提示的排查方式。
      </p>
    </header>

    <section id="guide-steps" aria-labelledby="guide-steps-heading" class="space-y-4">
      <h2 id="guide-steps-heading" class="text-xl font-semibold text-slate-900">
        三步完成一次解析
      </h2>
      <ol class="grid gap-4 sm:grid-cols-3">
        <li
          v-for="(step, index) in guideSteps"
          :key="step.title"
          class="space-y-2 rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
        >
          <span class="text-xs font-medium text-slate-400">步骤 {{ index + 1 }}</span>
          <h3 class="text-lg font-semibold text-slate-900">{{ step.title }}</h3>
          <p class="text-sm leading-relaxed text-slate-600">{{ step.text }}</p>
        </li>
      </ol>
    </section>

    <section aria-labelledby="guide-platforms-heading" class="space-y-3">
      <h2 id="guide-platforms-heading" class="text-xl font-semibold text-slate-900">
        平台差异
      </h2>
      <div class="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm">
        <table class="w-full border-collapse text-left text-sm">
          <caption class="border-b border-slate-200 px-4 py-3 text-left text-sm text-slate-600">
            三个 Platform 的可用范围与产物差异；抖音仍受部署灰度开关控制。
          </caption>
          <thead class="bg-slate-50 text-slate-700">
            <tr>
              <th scope="col" class="px-4 py-2 font-semibold">Platform</th>
              <th scope="col" class="px-4 py-2 font-semibold">可用性</th>
              <th scope="col" class="px-4 py-2 font-semibold">注意事项</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100 text-slate-700">
            <tr v-for="platform in platforms" :key="platform.name">
              <th scope="row" class="px-4 py-2 font-medium text-slate-800">{{ platform.name }}</th>
              <td class="px-4 py-2">{{ platform.availability }}</td>
              <td class="px-4 py-2">{{ platform.note }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section aria-labelledby="guide-troubleshooting-heading" class="space-y-4">
      <h2 id="guide-troubleshooting-heading" class="text-xl font-semibold text-slate-900">
        常见故障排查
      </h2>
      <div class="grid gap-4 sm:grid-cols-2">
        <div
          v-for="item in troubleshooting"
          :key="item.question"
          class="space-y-2 rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
        >
          <h3 class="text-base font-semibold text-slate-900">{{ item.question }}</h3>
          <p class="text-sm leading-relaxed text-slate-600">{{ item.answer }}</p>
        </div>
      </div>
    </section>

    <section id="guide-more" class="space-y-3">
      <h2 class="text-xl font-semibold text-slate-900">想了解更细的边界</h2>
      <p class="text-sm leading-relaxed text-slate-600">
        价格、Quota 与取消方式见
        <RouterLink to="/pricing" class="font-medium text-slate-900 underline hover:text-slate-600">价格页</RouterLink>；
        逐条问答见
        <RouterLink to="/faq" class="font-medium text-slate-900 underline hover:text-slate-600">常见问题</RouterLink>；
        六项能力的详细说明见
        <RouterLink to="/features" class="font-medium text-slate-900 underline hover:text-slate-600">功能页</RouterLink>。
      </p>
    </section>

    <section
      id="guide-cta"
      class="space-y-3 rounded-xl border border-slate-200 bg-white p-6 text-center shadow-sm"
    >
      <h2 class="text-lg font-semibold text-slate-900">回到工具开始</h2>
      <p class="text-sm text-slate-600">
        回到首页粘贴页面地址，先解析；需要字幕与摘要时再登录账号。
      </p>
      <RouterLink
        to="/"
        class="inline-block rounded-lg bg-slate-900 px-5 py-2 text-sm font-medium text-white transition-colors hover:bg-slate-700"
      >
        回到首页开始解析
      </RouterLink>
    </section>
  </div>
</template>
