import { createRouter, createWebHistory } from "vue-router";

import HomeView from "@/views/HomeView.vue";

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/",
      name: "home",
      component: HomeView,
      meta: { title: "视频下载与 AI 总结" },
    },
    {
      path: "/terms",
      name: "terms",
      component: () => import("@/views/TermsView.vue"),
      meta: { title: "使用条款" },
    },
    {
      path: "/:pathMatch(.*)*",
      name: "not-found",
      component: () => import("@/views/NotFoundView.vue"),
      meta: { title: "页面不存在" },
    },
  ],
  scrollBehavior(to) {
    if (to.hash) return { el: to.hash, behavior: "smooth" };
    return { top: 0 };
  },
});

router.afterEach((to) => {
  const title = typeof to.meta.title === "string" ? to.meta.title : null;
  document.title = title ? `${title} · AI 视频学习助手` : "AI 视频学习助手";
});
