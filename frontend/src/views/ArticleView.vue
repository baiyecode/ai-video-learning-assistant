<script setup lang="ts">
/**
 * Article detail (indexable): one H1 from frontmatter, sanitized Markdown body,
 * stable TOC anchors, attribution/dates/reading time, related Articles and a
 * CTA back to the tool.
 */
import { computed } from "vue";
import { useRoute } from "vue-router";

import { AUTHOR_NAME, relatedArticles } from "@/site/articles";
import { renderArticleMarkdown } from "@/site/article-render";
import { useArticleCollection } from "@/site/article-sources";

const collection = useArticleCollection();
const route = useRoute();

const article = computed(() => collection.bySlug.get(String(route.params.slug ?? "")) ?? null);
const rendered = computed(() =>
  article.value ? renderArticleMarkdown(article.value.body) : null,
);
const related = computed(() =>
  article.value ? relatedArticles(article.value, collection) : [],
);
</script>

<template>
  <article v-if="article && rendered" class="mx-auto max-w-4xl space-y-8">
    <nav aria-label="面包屑" class="text-sm text-slate-500">
      <RouterLink to="/" class="hover:text-slate-900">首页</RouterLink>
      <span aria-hidden="true"> / </span>
      <RouterLink to="/articles" class="hover:text-slate-900">文章</RouterLink>
      <span aria-hidden="true"> / </span>
      <span class="text-slate-700">{{ article.title }}</span>
    </nav>

    <header class="space-y-3">
      <h1 class="text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl">
        {{ article.title }}
      </h1>
      <p class="text-lg leading-relaxed text-slate-600">{{ article.description }}</p>
      <p class="text-sm text-slate-500">
        作者 {{ AUTHOR_NAME }} · 发布于
        <time :datetime="article.published">{{ article.published }}</time>
        · 更新于
        <time :datetime="article.updated ?? article.published">{{
          article.updated ?? article.published
        }}</time>
        · 约 {{ article.readingMinutes }} 分钟阅读
      </p>
      <ul v-if="article.tags.length" class="flex flex-wrap gap-2">
        <li
          v-for="tag in article.tags"
          :key="tag"
          class="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs text-slate-600"
        >
          {{ tag }}
        </li>
      </ul>
    </header>

    <div class="grid gap-8 lg:grid-cols-[minmax(0,1fr)_15rem]">
      <!-- Sanitized by renderArticleMarkdown (DOMPurify) before it reaches v-html. -->
      <div class="article-body" v-html="rendered.html"></div>

      <nav
        v-if="rendered.toc.length"
        aria-label="文章目录"
        class="h-fit rounded-xl border border-slate-200 bg-white p-4 text-sm shadow-sm lg:sticky lg:top-6"
      >
        <p class="font-semibold text-slate-900">目录</p>
        <ol class="mt-2 space-y-1.5">
          <li
            v-for="entry in rendered.toc"
            :key="entry.id"
            :class="entry.depth === 3 ? 'pl-4' : ''"
          >
            <a :href="`#${entry.id}`" class="text-slate-600 hover:text-slate-900">
              {{ entry.text }}
            </a>
          </li>
        </ol>
      </nav>
    </div>

    <section v-if="related.length" class="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
      <h2 class="text-lg font-semibold text-slate-900">相关文章</h2>
      <ul class="mt-3 space-y-2 text-sm">
        <li v-for="item in related" :key="item.slug">
          <RouterLink :to="`/articles/${item.slug}`" class="text-slate-700 hover:text-slate-900">
            {{ item.title }}
          </RouterLink>
          <span class="text-slate-400"> · {{ item.published }}</span>
        </li>
      </ul>
    </section>

    <section class="rounded-xl border border-slate-200 bg-white p-6 text-center shadow-sm">
      <h2 class="text-lg font-semibold text-slate-900">继续阅读与试用</h2>
      <p class="mt-2 text-sm text-slate-600">
        回到工具粘贴页面地址，解析视频后即可导出 Subtitle；需要 AI 摘要时再登录账号。
      </p>
      <div class="mt-4 flex flex-wrap justify-center gap-3">
        <RouterLink
          to="/"
          class="inline-block rounded-lg bg-slate-900 px-5 py-2 text-sm font-medium text-white transition-colors hover:bg-slate-700"
        >
          回到首页开始解析
        </RouterLink>
        <RouterLink
          to="/features"
          class="inline-block rounded-lg border border-slate-300 px-5 py-2 text-sm font-medium text-slate-700 transition-colors hover:border-slate-400"
        >
          查看功能说明
        </RouterLink>
        <RouterLink
          to="/articles"
          class="inline-block rounded-lg border border-slate-300 px-5 py-2 text-sm font-medium text-slate-700 transition-colors hover:border-slate-400"
        >
          全部文章
        </RouterLink>
      </div>
    </section>
  </article>

  <section v-else class="mx-auto max-w-xl space-y-4 text-center">
    <h1 class="text-3xl font-bold tracking-tight text-slate-900">页面不存在</h1>
    <p class="text-slate-600">这篇文章可能已被移动、删除，或仍是草稿。</p>
    <RouterLink
      to="/articles"
      class="inline-block rounded-lg bg-slate-900 px-5 py-2 text-sm font-medium text-white transition-colors hover:bg-slate-700"
    >
      返回文章列表
    </RouterLink>
  </section>
</template>

<style scoped>
.article-body {
  color: var(--color-slate-700, #334155);
  font-size: 1rem;
  line-height: 1.75;
}
.article-body :deep(h2) {
  margin-top: 2rem;
  margin-bottom: 0.75rem;
  font-size: 1.35rem;
  font-weight: 600;
  color: var(--color-slate-900, #0f172a);
  scroll-margin-top: 1.5rem;
}
.article-body :deep(h3) {
  margin-top: 1.5rem;
  margin-bottom: 0.5rem;
  font-size: 1.1rem;
  font-weight: 600;
  color: var(--color-slate-900, #0f172a);
  scroll-margin-top: 1.5rem;
}
.article-body :deep(p) {
  margin-bottom: 1rem;
}
.article-body :deep(ul),
.article-body :deep(ol) {
  margin-bottom: 1rem;
  padding-left: 1.5rem;
  list-style-position: outside;
}
.article-body :deep(ul) {
  list-style-type: disc;
}
.article-body :deep(ol) {
  list-style-type: decimal;
}
.article-body :deep(li) {
  margin-bottom: 0.35rem;
}
.article-body :deep(a) {
  color: var(--color-slate-900, #0f172a);
  text-decoration: underline;
  text-underline-offset: 2px;
}
.article-body :deep(table) {
  width: 100%;
  margin-bottom: 1rem;
  border-collapse: collapse;
  font-size: 0.9rem;
}
.article-body :deep(th),
.article-body :deep(td) {
  border: 1px solid var(--color-slate-200, #e2e8f0);
  padding: 0.5rem 0.75rem;
  text-align: left;
}
.article-body :deep(th) {
  background: var(--color-slate-50, #f8fafc);
  font-weight: 600;
}
.article-body :deep(blockquote) {
  margin-bottom: 1rem;
  border-left: 3px solid var(--color-slate-300, #cbd5e1);
  padding-left: 1rem;
  color: var(--color-slate-500, #64748b);
}
.article-body :deep(code) {
  border-radius: 0.25rem;
  background: var(--color-slate-100, #f1f5f9);
  padding: 0.1rem 0.3rem;
  font-size: 0.9em;
}
</style>
