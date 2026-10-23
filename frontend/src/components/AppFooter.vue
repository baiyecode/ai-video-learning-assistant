<template>
  <footer class="border-t border-slate-200 bg-white">
    <div
      class="mx-auto flex w-full max-w-5xl flex-col gap-3 px-4 py-6 text-sm text-slate-500 sm:flex-row sm:items-center sm:justify-between"
    >
      <p>仅限个人备份或已获授权内容。</p>
      <nav class="flex items-center gap-4">
        <RouterLink to="/terms" class="transition-colors hover:text-slate-900">使用条款</RouterLink>
        <RouterLink to="/terms#report" class="transition-colors hover:text-slate-900">
          举报/投诉
        </RouterLink>
      </nav>
    </div>
  </footer>
</template>
