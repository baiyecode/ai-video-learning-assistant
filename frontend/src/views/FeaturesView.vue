<script setup lang="ts">
/**
 * Public marketing page (indexable): six capabilities with problem, usage and
 * limits. Copy stays inside verified product facts — no ASR, no platform-wide
 * promises, no DRM bypass.
 */
const features = [
  {
    title: "解析",
    problem: "先确认一个页面地址能否下载或分析，而不是反复试错。",
    usage:
      "粘贴 B 站或 YouTube 的页面地址，点击「解析视频」。抖音仅在部署开启灰度时可用；播放列表、直播、DRM 与会员专属内容不在支持范围内。",
    limit: "单个视频最长 2 小时、最大 2 GB。",
  },
  {
    title: "Download：保存文件",
    problem: "把公开视频保存到本地，用于个人备份或已获授权的内容。",
    usage:
      "解析后选择清晰度与格式，再点击保存。下载链接 15 分钟内有效，服务端文件最多保留 1 小时，过期后重新解析即可。",
    limit: "访客每小时最多发起 5 次 Download，请按需使用。",
  },
  {
    title: "Subtitle 导出",
    problem: "把已有字幕整理成可编辑的文本，用于笔记、校对或归档。",
    usage:
      "选择 SRT、VTT 或 TXT 格式导出；页面会标出字幕是人工上传还是平台自动生成，方便判断准确性。",
    limit: "不做 ASR：视频本身没有可用字幕时，无法导出字幕，也无法发起 Analysis。",
  },
  {
    title: "Analysis：AI 摘要",
    problem: "长视频没时间完整看完，希望先读到结构化的简体中文要点。",
    usage:
      "登录并验证邮箱后，对带字幕的视频发起 Analysis，基于字幕生成摘要。免费账号每个自然日 3 次，Analysis 默认仅自己可见。",
    limit: "没有字幕的视频不能分析；Quota 在成功创建时消耗，失败会退回。",
  },
  {
    title: "思维导图",
    problem: "把摘要变成可展开的结构，便于复盘和讲解。",
    usage:
      "Analysis 完成后打开思维导图，按主题层级浏览内容，也可以配合摘要一起阅读。",
    limit: "思维导图来自 Analysis 结果；没有 Analysis 就没有导图。",
  },
  {
    title: "历史与 VIP",
    problem: "找回过去生成的内容，并在需要时解除每日 Analysis 的 Quota 限制。",
    usage:
      "「我的分析」保留你的 Analysis 历史。VIP 会员 $4.99/月，Analysis 不限次；支付由 Stripe 托管，可随时取消，取消后在当期结束前仍可使用。",
    limit: "免费账号每天 3 次 Analysis；价格与扣款以支付方结账页展示为准。",
  },
];
</script>

<template>
  <div class="mx-auto max-w-4xl space-y-10">
    <header class="space-y-3">
      <h1 class="text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl">
        功能：从解析到 AI 分析
      </h1>
      <p class="text-slate-600">
        AI 视频学习助手把公开视频的解析、下载、字幕导出与 AI
        分析放在同一条流程里。下面按能力说明它解决什么问题、怎么用，以及明确的限制。
      </p>
    </header>

    <div class="grid gap-5 sm:grid-cols-2">
      <section
        v-for="feature in features"
        :key="feature.title"
        class="space-y-3 rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
      >
        <h2 class="text-lg font-semibold text-slate-900">{{ feature.title }}</h2>
        <div class="space-y-2 text-sm leading-relaxed text-slate-600">
          <p>
            <span class="font-medium text-slate-800">解决什么问题：</span>
            {{ feature.problem }}
          </p>
          <p>
            <span class="font-medium text-slate-800">如何使用：</span>
            {{ feature.usage }}
          </p>
          <p class="rounded-lg bg-slate-50 p-3 text-slate-600">
            <span class="font-medium text-slate-800">限制：</span>
            {{ feature.limit }}
          </p>
        </div>
      </section>
    </div>

    <section class="rounded-xl border border-slate-200 bg-white p-6 text-center shadow-sm">
      <h2 class="text-lg font-semibold text-slate-900">从一次解析开始</h2>
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
  </div>
</template>
