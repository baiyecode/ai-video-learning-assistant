/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE?: string;
  readonly VITE_PROXY_TARGET?: string;
  readonly VITE_SENTRY_DSN?: string;
  /** Build-time public origin for canonical/OG URLs (SEO descriptors). */
  readonly VITE_SITE_ORIGIN?: string;
  /** Build-time free Analysis Quota, mirrored from backend ``APP_ANALYSIS_DAILY_QUOTA``. */
  readonly VITE_ANALYSIS_DAILY_QUOTA?: string;
  /** Build-time display monthly USD, mirrored from backend ``APP_SUBSCRIPTION_MONTHLY_USD``. */
  readonly VITE_SUBSCRIPTION_MONTHLY_USD?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
