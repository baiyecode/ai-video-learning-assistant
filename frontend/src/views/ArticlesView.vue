<script setup lang="ts">
/**
 * Article index (indexable): newest first, with the description, dates, tags and
 * reading time that also feed the page head and the Blog JSON-LD.
 */
import { useArticleCollection } from "@/site/article-sources";

const articles = useArticleCollection().published;
</script>

<template>
  <div class="mx-auto max-w-4xl space-y-8">
    <header class="space-y-3">
      <h1 class="text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl">文章</h1>
      <p class="text-slate-600">
        围绕 B 站与 YouTube 的 Subtitle 导出、学习笔记与 AI 摘要，按发布时间收录的实操文章。
        每篇都给出可执行的步骤、真实的产品限制与明确的边界。
      </p>
    </header>

    <p v-if="articles.length === 0" class="rounded-xl border border-slate-200 bg-white p-6 text-slate-600">
      暂无已发布的文章。
    </p>

    <ul v-else class="space-y-5">
      <li v-for="article in articles" :key="article.slug">
        <article class="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          <h2 class="text-xl font-semibold text-slate-900">
            <RouterLink :to="`/articles/${article.slug}`" class="hover:text-slate-700">
              {{ article.title }}
            </RouterLink>
          </h2>
          <p class="mt-2 text-sm leading-relaxed text-slate-600">{{ article.description }}</p>
          <p class="mt-3 text-xs text-slate-500">
            <time :datetime="article.published">{{ article.published }}</time>
            <template v-if="article.updated && article.updated !== article.published">
              （更新于 <time :datetime="article.updated">{{ article.updated }}</time>）
            </template>
            · 约 {{ article.readingMinutes }} 分钟阅读
          </p>
          <ul v-if="article.tags.length" class="mt-3 flex flex-wrap gap-2">
            <li
              v-for="tag in article.tags"
              :key="tag"
              class="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs text-slate-600"
            >
              {{ tag }}
            </li>
          </ul>
        </article>
      </li>
    </ul>

    <section
      id="articles-cta"
      class="rounded-xl border border-slate-200 bg-white p-6 text-center shadow-sm"
    >
      <h2 class="text-lg font-semibold text-slate-900">读完就试一次</h2>
      <p class="mt-2 text-sm text-slate-600">
        回到工具粘贴页面地址，解析视频后即可导出字幕；需要 AI 摘要时再登录账号。
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
