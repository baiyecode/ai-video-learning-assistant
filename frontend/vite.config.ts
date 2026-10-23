import { fileURLToPath, URL } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vitest/config";

const apiTarget = process.env.VITE_PROXY_TARGET ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [vue(), tailwindcss()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": { target: apiTarget, changeOrigin: true },
      "/health": { target: apiTarget, changeOrigin: true },
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes("node_modules/markmap-lib") || id.includes("node_modules/markmap-common")) {
            return "markmap-lib";
          }
          if (id.includes("node_modules/markmap-view")) return "markmap-view";
          if (id.includes("node_modules/d3")) return "d3";
          if (id.includes("node_modules/katex")) return "katex";
          if (id.includes("node_modules/highlight.js")) return "highlight";
          if (id.includes("node_modules/markdown-it") || id.includes("node_modules/prismjs")) {
            return "markdown-it";
          }
        },
      },
    },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
    restoreMocks: true,
  },
});
