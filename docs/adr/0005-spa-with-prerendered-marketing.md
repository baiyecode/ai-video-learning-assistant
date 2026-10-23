# 保留 Vue SPA，营销页采用构建期预渲染

应用主体保持 Vue 3 + Vite 的单页应用；SEO/GEO 所需的营销页与文章页在构建期预渲染为静态 HTML，并生成 sitemap 与结构化数据；视频分析页设置 noindex。没有迁移到 Nuxt，因为 SSR 会重写前端架构并引入服务端渲染运维，而 MVP 的 SEO 需求只覆盖少量静态页面。

**考虑过的替代方案**：Nuxt SSR（动态 SEO 能力更强，但改造与运维成本高）；独立 SSR 服务（架构更复杂）。

**Consequences**：动态路由不具备 SEO 能力；GEO 文章以 Markdown 为源、在构建时生成，新增文章需要重新构建发布。
