<script setup lang="ts">
/**
 * Public FAQ (indexable): questions are H2s and answers are visible text, both
 * read from ``faq-content`` — the same list the FAQPage JSON-LD serialises.
 */
import { faqItems } from "@/site/faq-content";
</script>

<template>
  <div class="mx-auto max-w-3xl space-y-8">
    <header class="space-y-3">
      <h1 class="text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl">常见问题</h1>
      <p class="text-slate-600">
        关于支持的 Platform、免费 Quota、VIP 价格、Subtitle 与文件保留的答案都在这里。答案按当前产品真实行为编写，不承诺未支持的能力。
      </p>
    </header>

    <div class="space-y-4">
      <section
        v-for="item in faqItems"
        :key="item.question"
        class="space-y-2 rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
      >
        <h2 class="text-base font-semibold text-slate-900">{{ item.question }}</h2>
        <p class="text-sm leading-relaxed text-slate-600">{{ item.answer }}</p>
      </section>
    </div>

    <section class="space-y-3 rounded-xl border border-slate-200 bg-white p-6 text-center shadow-sm">
      <h2 class="text-lg font-semibold text-slate-900">还有别的疑问？</h2>
      <p class="text-sm text-slate-600">
        操作步骤见
        <RouterLink to="/guide" class="font-medium text-slate-900 underline hover:text-slate-600">使用指南</RouterLink>，
        能力与限制见
        <RouterLink to="/features" class="font-medium text-slate-900 underline hover:text-slate-600">功能页</RouterLink>，
        侵权或滥用可通过
        <RouterLink to="/terms#report" class="font-medium text-slate-900 underline hover:text-slate-600">举报表单</RouterLink>
        反馈。
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
