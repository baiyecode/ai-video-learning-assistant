<template>
  <footer class="border-t border-slate-200 bg-white">
    <div
      class="mx-auto flex w-full max-w-5xl flex-col gap-3 px-4 py-6 text-sm text-slate-500 sm:flex-row sm:items-center sm:justify-between"
    >
      <p>仅限个人备份或已获授权内容。</p>
      <nav aria-label="页脚导航" class="flex flex-wrap items-center gap-x-4 gap-y-2">
        <RouterLink to="/features" class="transition-colors hover:text-slate-900">功能</RouterLink>
        <RouterLink to="/guide" class="transition-colors hover:text-slate-900">指南</RouterLink>
        <RouterLink to="/faq" class="transition-colors hover:text-slate-900">FAQ</RouterLink>
        <RouterLink to="/articles" class="transition-colors hover:text-slate-900">文章</RouterLink>
        <RouterLink to="/pricing" class="transition-colors hover:text-slate-900">价格</RouterLink>
        <RouterLink to="/terms" class="transition-colors hover:text-slate-900">条款</RouterLink>
        <RouterLink to="/terms#report" class="transition-colors hover:text-slate-900">
          举报
        </RouterLink>
      </nav>
    </div>
  </footer>
</template>
