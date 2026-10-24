import { createRouter, createWebHistory } from "vue-router";

import { useAuthStore } from "@/stores/auth";
import HomeView from "@/views/HomeView.vue";

declare module "vue-router" {
  interface RouteMeta {
    title?: string;
    requiresAuth?: boolean;
    /** ADR-0005: private pages stay out of search engines; only marketing pages are indexable. */
    noindex?: boolean;
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
      path: "/pricing",
      name: "pricing",
      component: () => import("@/views/PricingView.vue"),
      meta: { title: "升级 VIP 会员" },
    },
    {
      path: "/account",
      name: "account",
      component: () => import("@/views/AccountView.vue"),
      meta: { title: "个人中心", requiresAuth: true, noindex: true },
    },
    {
      // Landing target of the emailed verification link (backend
      // ``identity/verification.FRONTEND_VERIFY_PATH``): consumes the token via
      // ``POST /auth/verification/confirm``, which authenticates by the token alone.
      path: "/verify-email",
      name: "verify-email",
      component: () => import("@/views/VerifyEmailView.vue"),
      meta: { title: "邮箱验证", noindex: true },
    },
    {
      path: "/analyses",
      name: "analyses",
      component: () => import("@/views/AnalysesView.vue"),
      meta: { title: "我的 Analysis", requiresAuth: true, noindex: true },
    },
    {
      path: "/analyses/:id",
      name: "analysis",
      component: () => import("@/views/AnalysisView.vue"),
      meta: { title: "AI 分析", requiresAuth: true, noindex: true },
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
  applyRobots(to.meta.noindex === true);
});

/** The SPA shell is one HTML document, so robots directives are swapped per route. */
function applyRobots(noindex: boolean): void {
  let tag = document.head.querySelector<HTMLMetaElement>('meta[name="robots"]');
  if (!tag) {
    tag = document.createElement("meta");
    tag.name = "robots";
    document.head.append(tag);
  }
  tag.content = noindex ? "noindex,nofollow" : "index,follow";
}
