import { createRouter, createWebHistory, type Router, type RouterHistory } from "vue-router";

import { useAuthStore } from "@/stores/auth";
import { articlesListDescriptor, descriptorForArticleSlug } from "@/site/article-descriptors";
import { defaultArticleCollection } from "@/site/article-sources";
import { applyHead } from "@/site/head";
import { descriptorForRoute, resolveSiteOrigin } from "@/site/seo";
import ArticleView from "@/views/ArticleView.vue";
import ArticlesView from "@/views/ArticlesView.vue";
import FaqView from "@/views/FaqView.vue";
import FeaturesView from "@/views/FeaturesView.vue";
import GuideView from "@/views/GuideView.vue";
import HomeView from "@/views/HomeView.vue";

export interface AppRouterOptions {
  /** The prerender entry writes head tags itself; runtime updates are browser-only. */
  updateHead?: boolean;
}

/**
 * Route table shared by the browser entry and the prerender entry. The history
 * is injected so build-time rendering can use ``createMemoryHistory`` without
 * touching ``window`` at module scope.
 */
export function createAppRouter(
  history: RouterHistory = createWebHistory(),
  options: AppRouterOptions = {},
): Router {
  const updateHead = options.updateHead ?? true;
  const router = createRouter({
    history,
    routes: [
      {
        path: "/",
        name: "home",
        component: HomeView,
      },
      {
        path: "/features",
        name: "features",
        component: FeaturesView,
      },
      {
        path: "/guide",
        name: "guide",
        component: GuideView,
      },
      {
        path: "/faq",
        name: "faq",
        component: FaqView,
      },
      {
        path: "/login",
        name: "login",
        component: () => import("@/views/LoginView.vue"),
      },
      {
        path: "/pricing",
        name: "pricing",
        component: () => import("@/views/PricingView.vue"),
      },
      {
        path: "/account",
        name: "account",
        component: () => import("@/views/AccountView.vue"),
        meta: { requiresAuth: true },
      },
      {
        // Landing target of the emailed verification link (backend
        // ``identity/verification.FRONTEND_VERIFY_PATH``): consumes the token via
        // ``POST /auth/verification/confirm``, which authenticates by the token alone.
        path: "/verify-email",
        name: "verify-email",
        component: () => import("@/views/VerifyEmailView.vue"),
      },
      {
        path: "/analyses",
        name: "analyses",
        component: () => import("@/views/AnalysesView.vue"),
        meta: { requiresAuth: true },
      },
      {
        path: "/analyses/:id",
        name: "analysis",
        component: () => import("@/views/AnalysisView.vue"),
        meta: { requiresAuth: true },
      },
      {
        path: "/terms",
        name: "terms",
        component: () => import("@/views/TermsView.vue"),
      },
      {
        path: "/articles",
        name: "articles",
        component: ArticlesView,
      },
      {
        path: "/articles/:slug",
        name: "article",
        component: ArticleView,
      },
      {
        path: "/:pathMatch(.*)*",
        name: "not-found",
        component: () => import("@/views/NotFoundView.vue"),
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

  // ADR-0005: the same descriptor that the prerender build injected drives
  // client-side navigation. Public and private pages share this one path.
  router.afterEach((to) => {
    if (!updateHead || typeof document === "undefined") return;
    const slug = typeof to.params.slug === "string" ? to.params.slug : "";
    let descriptor = descriptorForRoute(to.name);
    if (to.name === "article") {
      descriptor = descriptorForArticleSlug(slug);
    } else if (to.name === "articles") {
      descriptor = articlesListDescriptor(defaultArticleCollection());
    }
    applyHead(descriptor, resolveSiteOrigin(), document);
  });

  return router;
}
