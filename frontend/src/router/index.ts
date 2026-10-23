import { createRouter, createWebHistory } from "vue-router";

import { useAuthStore } from "@/stores/auth";
import HomeView from "@/views/HomeView.vue";

declare module "vue-router" {
  interface RouteMeta {
    title?: string;
    requiresAuth?: boolean;
  }
}

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/",
      name: "home",
      component: HomeView,
      meta: { title: "视频下载与 AI 分析" },
    },
    {
      path: "/login",
      name: "login",
      component: () => import("@/views/LoginView.vue"),
      meta: { title: "登录" },
    },
    {
      path: "/analyses",
      name: "analyses",
      component: () => import("@/views/AnalysesView.vue"),
      meta: { title: "我的 Analysis", requiresAuth: true },
    },
    {
      path: "/analyses/:id",
      name: "analysis",
      component: () => import("@/views/AnalysisView.vue"),
      meta: { title: "AI 分析", requiresAuth: true },
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

router.beforeEach(async (to) => {
  if (to.meta.requiresAuth !== true) return true;

  const auth = useAuthStore();
  if (!auth.restored) await auth.bootstrap();
  if (auth.isAuthenticated) return true;

  return { name: "login", query: { next: to.fullPath } };
});

router.afterEach((to) => {
  const title = typeof to.meta.title === "string" ? to.meta.title : null;
  document.title = title ? `${title} · AI 视频学习助手` : "AI 视频学习助手";
});
