# P3: SEO/GEO、静态营销页与文章

## Problem Statement

P1 与 P2 已经交付了完整的产品能力：Visitor 可以解析 Video、导出 Subtitle、发起服务端 Download；Account 可以注册登录、验证邮箱、生成 Analysis，并通过 VIP Membership 解除 Quota。但产品目前对搜索者与 AI 答案引擎几乎不可见。

现状是：前端只有一个 SPA 外壳，初始 HTML 只有通用的 title 与 description；功能、指南、价格与文章没有可被抓取的正文；没有 sitemap、robots.txt、canonical、结构化数据或面向 AI 的内容索引。私有页面虽然在路由层切换了 `noindex`，但那只是浏览器执行 JavaScript 之后的结果，不带 JS 的爬虫看到的仍是一个可索引的空壳。营销面也只有首页三行介绍与一个定价页，无法承接「B 站字幕怎么下载」「长视频怎么快速总结」这类真实搜索需求。

结果是获客只能依赖口碑或投放，AI 助手在回答相关问题时也无法准确引用产品的能力、价格与限制。ADR-0005 已经把 P3 定义为「保留 Vue SPA，营销页与文章在构建期预渲染」，但这条决策尚未落地。

## Solution

继续使用 Vue 3 + Vite SPA，不引入 Nuxt 或运行时 SSR（ADR-0005）。在构建期把公开的营销页与文章页预渲染为静态 HTML，并同时生成 sitemap、robots.txt、`llms.txt`、canonical 与结构化数据；私有页面改用带 `noindex` 的 SPA 外壳，未知路径返回真正的 404。

具体交付：

1. **公开静态页**：首页（工具保留在 `/`，下方增加营销内容）、功能页、使用指南、FAQ、价格页、使用条款、文章列表与文章详情。
2. **内容系统**：以 Markdown + frontmatter 为唯一内容源，构建期校验标题、描述、日期、slug、内链与安全边界；首发 4 篇种子文章。
3. **GEO 产物**：每页唯一且可抓取的 head、JSON-LD、`llms.txt`、语义化正文与可引用的产品事实；私有页与 404 明确排除。
4. **单一测试接缝**：在临时目录生成完整站点，断言真实产物（HTML、head、JSON-LD、sitemap、robots、`llms.txt`、内链、404、应用外壳），现有 Playwright 黄金路径继续覆盖 SPA 行为。

不改变后端 API、数据库、下载队列、Analysis 流式链路与 Stripe 返回地址；单 VPS + SQLite 的部署边界保持不变。

## User Stories

### 搜索者与新访客

1. 作为搜索「B 站视频字幕怎么下载」的用户，我想落在一个直接回答问题的页面上，以便不用先注册就能判断产品是否适合我。
2. 作为搜索者，我想在搜索结果里看到每页独特且准确的标题与描述，以便选择真正相关的页面。
3. 作为搜索者，我想在 JavaScript 加载失败或被禁用时仍能阅读营销页与文章正文，以便内容不会因为脚本问题而消失。
4. 作为搜索者，我想同一个页面只有一个 canonical 地址，以便分享与收录不会分裂成多个 URL。
5. 作为新访客，我想在首页看到产品能做什么、支持哪些 Platform、有哪些限制，以便决定是否试用。
6. 作为新访客，我想有独立的「功能」页详细说明解析、下载、字幕与 AI 分析，以便与其他工具比较。
7. 作为新访客，我想有一步一图的「使用指南」，以便知道从页面地址到 Subtitle、Download 与 Analysis 的完整路径。
8. 作为新访客，我想有覆盖价格、Quota、Subtitle、DRM 与文件保留的 FAQ，以便不注册也能得到答案。
9. 作为新访客，我想阅读针对具体学习场景的文章，以便在试用前建立对产品价值的理解。
10. 作为手机用户，我想导航与正文在小屏上不横向溢出，以便顺畅阅读与分享。
11. 作为分享者，我想文章与章节可以直接深链，以便把某个具体答案发给别人。
12. 作为访客，我想每个营销页都有回到工具的明确 CTA，以便看完说明后立即试用。

### AI 答案引擎与 GEO

13. 作为 AI 答案引擎，我想看到语义化的 HTML（单一 H1、清晰的 H2/H3、列表与表格），以便准确抽取答案。
14. 作为 AI 答案引擎，我想看到 SoftwareApplication、Offer、FAQPage、HowTo、BlogPosting 与 BreadcrumbList 等 JSON-LD，以便理解产品、价格与内容之间的关系。
15. 作为 AI 答案引擎，我想通过 `llms.txt` 获得权威页面的绝对链接与一句话摘要，以便发现并引用正确内容。
16. 作为 AI 答案引擎，我想在文章首段看到对标题问题的直接回答，以便生成可引用的摘要。
17. 作为 AI 答案引擎，我想看到明确的限制、价格、保留期限与支持平台等产品事实，以便摘要不产生过度承诺。
18. 作为 AI 答案引擎，我想私有页面、登录页与 404 被明确排除，以便不会把账户相关页面当成公开内容引用。
19. 作为产品，我想全站使用一致的产品名、定义与术语，以便搜索结果与 AI 摘要建立稳定的品牌实体。
20. 作为产品，我想文章与产品页互相内链，以便爬虫与读者都能发现相关内容。

### 内容作者与运营者

21. 作为内容作者，我想只写一个 Markdown 文件并填写 frontmatter 就能发布文章，以便不需要改代码。
22. 作为内容作者，我想文件名直接决定 URL slug，以便不用维护两份 slug。
23. 作为内容作者，我想构建时校验必填字段、日期顺序、重复标题/描述/slug 与过短正文，以便坏内容不会上线。
24. 作为内容作者，我想草稿自动排除在页面、sitemap 与 `llms.txt` 之外，以便未完成的内容不会被发布。
25. 作为内容作者，我想文章自动生成目录与稳定的标题锚点，以便读者在长文中跳转。
26. 作为内容作者，我想文章显示发布日期、更新日期与署名，以便读者判断内容时效。
27. 作为内容作者，我想 Markdown 渲染结果经过清理，脚本、iframe、表单与事件处理器不会进入页面，以便内容不会引入 XSS。
28. 作为内容作者，我想文章末尾自动出现相关文章与产品 CTA，以便读者继续阅读或试用。
29. 作为内容作者，我想构建失败时看到具体文件名与原因，以便快速修复。
30. 作为运营者，我想文章的标题、描述、日期与标签自动流入页面 head、JSON-LD、sitemap 与 `llms.txt`，以便不需要手工同步多处。
31. 作为运营者，我想首发内容有明确的选题、目标查询与事实边界，以便 SEO 不是靠堆关键词而是靠可用的答案。
32. 作为运营者，我想产品价格与限制只在一处定义并复用到页面与结构化数据，以便调价时不会出现不一致。

### 搜索引擎与部署

33. 作为搜索引擎，我想 `sitemap.xml` 只包含公开的 canonical URL，并为文章提供真实的 `lastmod`，以便高效抓取。
34. 作为搜索引擎，我想 `robots.txt` 指向 sitemap 并排除私有路径，以便不浪费抓取预算。
35. 作为搜索引擎，我想未知路径返回 HTTP 404 与 404 页面，以便错误页不会被当成首页收录。
36. 作为搜索引擎，我想私有应用路由同时通过 meta 与响应头声明 `noindex`，以便不依赖客户端 JavaScript。
37. 作为搜索引擎，我想内部链接在构建期被校验，以便上线后不会出现大量死链。
38. 作为部署者，我想只配置一个 `SITE_ORIGIN` 就同时决定 canonical、OG、sitemap 与 `llms.txt` 的绝对地址，以便全站一致。
39. 作为部署者，我想构建拒绝格式非法的站点地址，以便不会发布错误的绝对 URL。
40. 作为部署者，我想 localhost/回环地址构建时自动输出「禁止全部抓取」的 robots，以便测试环境不会被搜索引擎收录。
41. 作为部署者，我想 nginx 直接提供 `.html` 文件且 canonical 不带尾斜杠，以便地址与产物一致。
42. 作为部署者，我想私有路由的深链仍能回到 SPA，以便刷新与邮件链接不会 404。
43. 作为部署者，我想 HTML 不被中间缓存、静态资源仍长期缓存，以便内容更新立即生效且不牺牲性能。
44. 作为部署者，我想预渲染与校验包含在现有构建命令里，以便 Docker 与发布流程不需要额外步骤。
45. 作为部署者，我想任一页面渲染失败时构建直接失败并指出路由，以便坏产物不会上线。

### 现有用户与回归

46. 作为现有用户，我想工具继续留在 `/`，以便书签、Stripe 支付返回地址与登录回跳都不变。
47. 作为现有用户，我想解析出结果后营销区块让位给结果，以便日常使用不被营销内容打断。
48. 作为现有用户，我想登录、个人中心、Analysis 历史与邮箱验证页继续保持 SPA 与 `noindex`，以便账户数据不进入搜索。
49. 作为现有用户，我想客户端跳转时 title、description、canonical 与 robots 同步更新，以便标签页与分享链接始终正确。
50. 作为现有用户，我想定价页的登录、结账与订阅状态行为完全不变，以便升级路径不受 SEO 改造影响。
51. 作为键盘或屏幕阅读器用户，我想营销页有语义地标、跳转主内容的链接与可聚焦导航，以便不使用鼠标也能浏览。
52. 作为现有用户，我想解析、下载、字幕、Analysis 与 SSE 行为零变化，以便 P3 只影响公开内容层。

### 品牌与分享

53. 作为分享者，我想链接在社交平台展示统一的标题、描述与品牌分享图，以便预览可信。
54. 作为分享者，我想文章预览带发布/更新时间，以便对方知道内容是否新鲜。
55. 作为用户，我想标签页有可识别的 favicon，以便在多个标签中快速找到产品。
56. 作为运营者，我想全站标题与描述唯一，以便页面之间不会互相竞争同一查询。
57. 作为产品，我想营销文案只陈述真实支持的 Platform、限制与价格，以便不因过度承诺损害信任。

## Implementation Decisions

### 页面与可索引范围

首页继续是工具，不迁移到 `/app`；这样 Stripe 的 `/?checkout=...` 返回地址、现有书签、登录回跳与黄金路径都不需要改。营销内容作为首页的下半部分，在「还没有解析结果」时展示，解析成功后隐藏，让结果区重新成为焦点。

| URL | 页面 | 索引策略 | 说明 |
|---|---|---|---|
| `/` | 首页 + 工具 | `index,follow` | 工具在最上方；下方为价值主张、三步流程、功能、支持平台、限制、价格入口、FAQ 摘要、最新文章与合规提示 |
| `/features` | 功能 | `index,follow` | 解析、Download、Subtitle 导出、Analysis、思维导图、历史与 VIP 的详细说明 |
| `/guide` | 使用指南 | `index,follow` | 三步操作、平台差异、常见故障与限制；配 HowTo 结构化数据 |
| `/faq` | 常见问题 | `index,follow` | 至少 12 个问答，覆盖价格、Quota、Subtitle、DRM、保留、邮箱验证、举报等 |
| `/pricing` | 价格 | `index,follow` | 保留现有登录/结账逻辑，增加免费与 VIP 对比、计费事实与 FAQ |
| `/terms` | 使用条款 | `index,follow` | 保留现有条款与举报表单，补齐 SEO head |
| `/articles` | 文章列表 | `index,follow` | 按发布日期倒序，展示标题、描述、日期、标签与阅读时间 |
| `/articles/:slug` | 文章详情 | `index,follow` | 正文、目录、署名、发布/更新日期、相关文章与 CTA |
| `/login` | 登录 | `noindex,nofollow` | 使用无索引 SPA 外壳 |
| `/account` | 个人中心 | `noindex,nofollow` | 使用无索引 SPA 外壳 |
| `/analyses`、`/analyses/:id` | Analysis 历史/详情 | `noindex,nofollow` | 使用无索引 SPA 外壳 |
| `/verify-email` | 邮箱验证 | `noindex,nofollow` | 使用无索引 SPA 外壳 |
| 未知路径 | 404 | HTTP 404 + `noindex,nofollow` | 独立的 404 静态页，不再回落到首页 |

不做公开的 Video 页或 Analysis 页：用户内容不进入搜索，隐私边界保持现状。也不做平台落地页（B 站、YouTube、抖音各自一页），首期用指南与文章承接平台相关查询，避免薄内容与重复页。

### 渲染与构建管线

- 开发模式仍是现有 SPA：`npm run dev` 不启动 SSR，文章与营销页通过同一套路由与内容集合渲染。
- 构建模式新增构建期预渲染：类型检查 → 客户端构建（产出 shell、资源清单与静态资源）→ 服务端渲染（逐路由 `renderToString`）→ 注入 head 与正文 → 生成 sitemap/robots/`llms.txt`/应用外壳/404 → 产物校验。任一步失败都让构建非零退出。
- 预渲染 HTML 是爬虫与无 JS 用户的阅读面；浏览器加载后仍按现有方式挂载 SPA，不做 hydration。这样认证状态、订阅状态与工具交互在挂载后由现有 store 决定，不会出现 hydration mismatch。代价是挂载时 DOM 会被替换一次；对当前站点规模可接受。
- 文章正文复用现有 Markdown 渲染与清理链路。构建与测试进程需要 DOM shim 才能运行清理器（项目已把 jsdom 作为开发依赖）；不得访问网络。
- 首期文章数量很小，正文随构建打包，不引入 CMS、数据库或运行时内容接口。新增或修改文章需要重新构建发布（与 ADR-0005 的后果一致）。
- 预渲染与校验只读取仓库内内容与本地资源，不依赖后端启动，也不访问真实 Platform 或 AI 服务。

### SEO 描述符：构建期与运行时的唯一真相源

新增一个页面注册表，为每个公开路由声明一条 SEO 描述符：`title`、`description`、`path`、`robots`、OG 类型、面包屑、JSON-LD 与文章日期。文章描述符由文章元数据派生；私有路由与 404 使用固定的无索引描述符。

同一描述符同时驱动：

- 构建期注入到静态 HTML 的 `<head>`；
- 客户端路由切换时的 head 更新（替换现有只改 title/robots 的逻辑）。

head 约定：

- `<title>` 格式为「页面标题 · AI 视频学习助手」；首页只出现一次产品名。全站标题唯一，最终长度不超过 60 个字符。
- `meta[name=description]` 全站唯一，长度 70–160 个字符，必须具体描述该页而不是重复口号。
- `link[rel=canonical]` 使用绝对地址，源自烘焙进构建的 `VITE_SITE_ORIGIN`；首页为 `origin/`，其余页面不带尾斜杠。
- 公开页 `meta[name=robots]` 为 `index,follow,max-image-preview:large`；私有页与 404 为 `noindex,nofollow`。
- Open Graph：`og:type`（`website` 或 `article`）、`og:site_name`、`og:title`、`og:description`、`og:url`、`og:image`、`og:locale=zh_CN`；文章额外提供 `article:published_time` 与 `article:modified_time`。
- Twitter Card 使用 `summary_large_image`，标题、描述与图片复用 OG 值。
- 文章页提供 `<html lang="zh-CN">`（现有）与可见的署名、发布日期、更新日期。
- 不使用 `meta[keywords]`，不做关键词堆砌。
- 运行时更新必须替换而不是追加受管标签，避免重复 canonical/OG/JSON-LD。

### 结构化数据

- `/`：`WebSite` + `SoftwareApplication`，包含产品名、描述、`applicationCategory`、`operatingSystem=Web`、`featureList` 与 `offers`。
- `/pricing`：复用 `SoftwareApplication` 与 `Offer`，价格来自前端唯一的展示常量（`$4.99/月`，USD）；页面可见价格与结构化数据必须一致，实际扣款仍以支付方结账页为准。
- `/faq`：`FAQPage`，每个 `Question`/`Answer` 必须与页面可见问答逐字对应。
- `/guide`：`HowTo`，步骤必须与页面可见的三步一致。
- `/articles`：`Blog` + `BreadcrumbList`。
- `/articles/:slug`：`BlogPosting` + `BreadcrumbList`，包含 `headline`、`description`、`datePublished`、`dateModified`、`author`（组织）、`publisher`、`mainEntityOfPage`、`image`、`inLanguage=zh-CN`、标签。
- `/features`、`/terms`：`WebPage` + `BreadcrumbList`。
- 全站使用 `Organization` 作为 publisher，复用品牌图标作为 logo。
- 禁止 `AggregateRating`、`Review` 与虚构作者/客户评价；没有真实数据就不生成。
- JSON-LD 必须由构建期写入 HTML（不是只在客户端注入），必须是合法 JSON，日期来自 frontmatter。

### 内容模型与创作流程

文章源为 Markdown 文件，文件名即 slug。slug 只允许小写 ASCII、数字与连字符，全站唯一。frontmatter 是刻意收窄的 schema：

```yaml
title: B 站视频字幕怎么下载？导出 SRT、VTT 与 TXT 的完整步骤
description: 一段 70–160 字的页面摘要
published: 2026-10-25
updated: 2026-10-25        # 可选，必须不早于 published
tags: [B站, 字幕]         # 可选
draft: false              # 可选，默认 false
```

- 必填：`title`、`description`、`published`。日期为 `YYYY-MM-DD`。
- 构建校验：必填字段、日期格式与顺序、slug 规则、全站标题/描述唯一、描述长度、正文长度下限（不少于 500 个非空白字符）、外部图片拒绝、内部链接目标存在。失败信息必须包含文件名与原因。
- 草稿（`draft: true`）不生成页面、不进入文章列表、sitemap 或 `llms.txt`。
- 正文经现有 Markdown 渲染器处理并清理：`script`、`iframe`、`form`、事件处理器与 `javascript:` 链接不得进入产物；外部链接补 `rel="noopener noreferrer"`。
- 文章自动生成 H2/H3 目录与稳定锚点；显示「AI 视频学习助手团队」署名、发布/更新日期与按字符数估算的阅读时间。
- 相关文章优先按共享标签选择，不足时用最新文章补齐；文章末尾必须有回到工具与至少一个相关页面的 CTA。
- 全站内容使用简体中文，术语遵守 `GLOSSARY.md`：提交的地址叫「页面地址」而不是「视频链接」；Video、Platform、Subtitle、Analysis、Quota、Visitor、VIP Membership、Download、Account 的用法保持一致。新增 **Article**（构建期发布的公开内容页）与 **Marketing Page**（无需登录、可索引的静态页）两个术语。

首发 4 篇种子文章，每篇不少于 800 个中文字符、首段直接回答标题问题、至少 3 个内链、至少一个列表或表格，并明确事实边界：

1. `bilibili-subtitle-download`：B 站 Subtitle 的导出步骤与 SRT/VTT/TXT 用法；人工与自动字幕的差异；不做 ASR。
2. `youtube-study-notes`：用 YouTube 字幕做学习笔记的导出、整理与复盘工作流；如何接 AI 摘要。
3. `ai-video-summary-mindmap`：长视频 Analysis 的摘要与思维导图；分块归并、无 Subtitle 则不能 Analysis、Quota 与 VIP 的关系。
4. `douyin-video-parsing`：抖音解析的灰度范围、单清晰度带水印产物、无 Subtitle 时不能 Analysis、开关关闭时的表现与回滚说明。

内容标准：首段给结论；H2 尽量写成用户会问的问题；给出具体数值（单视频 2 小时/2GB、下载链接 15 分钟有效、文件最多保留 1 小时、免费 Account 每日 3 次 Analysis、VIP `$4.99/月`）；更新日期必须真实；不写「支持所有平台」「无水印」「自动转写」「永久免费」「DRM 破解」「100% 成功」等无法兑现的承诺；不使用虚构评价、评分或专家身份。

### GEO 产物

- 根路径生成 `llms.txt`（Markdown/纯文本，UTF-8），按 llmstxt.org 的信息层级包含：H1 产品名、一句话摘要、产品页链接、指南与 FAQ 链接、全部已发布文章链接与一句话描述、价格与使用边界、条款/举报入口。只使用公开页面的绝对 URL。
- 正文优先使用可抽取的结构：定义句、编号步骤、对照表、限制清单、明确的「不支持」说明。
- 每个营销页与文章都提供一句可独立引用的产品事实，避免只有营销口号。
- 结构化数据、语义化 HTML 与 `llms.txt` 共同构成 GEO 面；不承诺 Google FAQ/HowTo 富结果（其展示规则由搜索引擎决定），但 schema 仍用于实体与关系理解。
- 不做关键词堆砌、隐藏文本、 doorway page 或程序化薄页。

### 路由、404 与静态服务

- 每个公开路由生成一个可被直接访问的 `.html` 文件（首页为根 `index.html`），canonical 不带尾斜杠；nginx 按「精确文件 → `.html` 扩展 → 目录 → 404」的顺序查找。
- 私有应用路由统一回落到一个无索引的 `app.html` 外壳，带 `meta[name=robots]=noindex,nofollow` 与 `X-Robots-Tag: noindex, nofollow`；查询串（如 `next`）必须保留。
- 未知路径返回 HTTP 404 与 `404.html`，404 页本身也带 `noindex`，不再回落到首页。
- HTML 响应保持 `Cache-Control: no-cache`；带哈希的静态资源继续长期 immutable 缓存。`sitemap.xml`、`robots.txt`、`llms.txt` 可按短周期缓存。
- gzip 覆盖 HTML、CSS、JS、JSON、XML 与纯文本（`llms.txt`/`robots.txt`）。
- `/api/` 与 `/health` 的代理行为不变。
- 部署文档必须给出可直接执行的验证命令：公开页 200、文章 200、未知路径 404、私有路由带 noindex 头、`/health` 仍正常。

### 站点地址与部署配置

- 新增构建期站点地址：`.env` 中的 `SITE_ORIGIN` 传入容器的构建参数 `VITE_SITE_ORIGIN`，前端在构建时把它烘焙进 SEO 描述符。只允许绝对 http(s) origin，不允许路径、查询串或尾斜杠；格式非法时构建失败。
- 本地 compose 默认 `http://localhost:8080`，本地 Vite 开发未设置时回退到 `http://localhost:5173` 并给出警告。若 origin 是 localhost/127.0.0.1/回环地址，`robots.txt` 输出 `Disallow: /` 并给出构建警告，避免测试环境被收录。
- 生产必须设置为公网 https origin，并与后端 `APP_FRONTEND_BASE_URL` 保持一致；否则验证邮件链接与 canonical 会指向不同地址。
- Docker 构建参数、compose 环境、`.env.example`、README 部署清单同步更新。构建命令仍是 `npm run build`，预渲染与产物校验包含在其中。
- 不新增后端配置、API、数据库表或依赖注入端口；SEO 完全是前端构建产物。

### 页面内容与导航

- 首页保留工具与现有 H1 的「粘贴视频地址」动作语义，同时让标题包含下载、字幕、AI 摘要等核心词；无解析结果时展示营销区块，有结果后隐藏。营销区块包含：价值主张、三步流程、六项功能、支持 Platform、关键限制、价格入口、5 条 FAQ 摘要、最新 3 篇文章与合规提示。
- 功能页按六项能力展开，每项给出「解决什么问题 + 如何使用 + 限制」，并链接到指南或文章。
- 使用指南用有序步骤说明：粘贴页面地址并解析 → 选择清度下载或导出 Subtitle → 登录后生成 Analysis；补充平台差异、无 Subtitle、DRM/会员专属、链接过期、Quota 用尽与邮箱未验证的排查。
- FAQ 至少 12 条，答案必须与后端真实行为一致：支持 B 站/YouTube，抖音按灰度开关；免费 Account 每日 3 次 Analysis；VIP `$4.99/月` 且可随时取消；无 Subtitle 不能 Analysis；不做 ASR；下载文件最多保留 1 小时、链接 15 分钟有效；单视频 2 小时/2GB；Analysis 私有；举报入口在条款页。
- 价格页保留现有 Checkout/Portal 逻辑，只增加免费与 VIP 对比、计费与取消说明、迷你 FAQ。
- 页头导航包含首页、功能、使用指南、文章、价格与现有认证入口；页脚包含功能、指南、FAQ、文章、条款与举报。小屏不得横向溢出，导航可换行或折叠。
- 所有页使用现有 Tailwind slate 视觉语言，不重做设计系统；一个页面只有一个 H1，标题层级连续；图片必须有 alt；增加「跳到主要内容」链接。
- 新增品牌资产：SVG favicon、512×512 品牌图标（同时作为 Organization logo 与 apple-touch-icon）、1200×630 PNG 分享图（全站复用，文章不单独生成）。分享图只呈现产品名与一句话价值，不使用可能暗示未支持能力的截图。
- 无 JS 时营销页与文章仍可读；工具区域显示「本工具需要 JavaScript」的提示，不影响阅读与导航。

### 兼容与回归

- 现有路由、认证、SSE、下载队列、配额、Stripe Checkout/Portal 与邮箱验证行为不变。
- 首页 H1 若因关键词调整而变动，必须同步更新 Playwright 断言，但「粘贴视频地址」这一动作语义保留。
- 私有页的 `noindex` 从「仅客户端」升级为「静态外壳 meta + 响应头 + 客户端」三重声明。
- 不引入运行时 SSR 服务、Nuxt、CMS 或新的后端依赖；jsdom 仅用于构建/测试进程。
- 更新 README：P3 状态、构建与测试命令、内容创作流程、SEO/GEO 产物说明、部署清单与验证命令；移除「ADR-0005 属于 P3、尚未实现」的条目，保留「无 CI」说明。
- ADR-0005 继续有效，不需要新 ADR；若实现中发现预渲染与现有 SPA 行为冲突，应先记录冲突再调整。

## Testing Decisions

- **只测外部行为**：断言生成站点的可见产物（HTML、head、JSON-LD、sitemap、robots、`llms.txt`、HTTP 语义），不断言内部辅助函数的调用顺序或私有实现。
- **单一接缝**：站点构建器接受站点地址、内容目录、HTML 外壳与资源清单，向临时目录产出完整站点。单元测试直接调用它，不跑完整 Vite 构建；真实内容参与校验，失败场景用临时 fixture 内容目录。构建命令复用同一路径，并在真实构建后再次校验产物。
- **必须具备的测试**：
  - 产出的公开页集合与索引策略正确；私有路由不生成独立公开页；`app.html` 与 `404.html` 存在且为 `noindex`。
  - 每个公开页恰好一个 `<title>` 与一个 H1；标题与描述全站唯一且在长度范围内；canonical 为绝对地址且无尾斜杠；robots 为 `index,follow`。
  - 每页 JSON-LD 可解析、包含预期 `@type` 与必填字段；文章 JSON-LD 的日期与 frontmatter 一致；FAQ/HowTo 与可见内容一致。
  - 文章页包含 OG `article:*` 与 Twitter Card；文章目录锚点存在；相关文章与 CTA 存在。
  - `sitemap.xml` 是合法 XML，只含公开 canonical URL，文章 `lastmod` 正确，草稿与私有页不出现。
  - `robots.txt` 指向 sitemap、排除私有路径；loopback origin 时输出 `Disallow: /`；非法 origin 让构建失败。
  - `llms.txt` 包含产品摘要、关键页面与全部已发布文章，不含草稿或私有 URL。
  - 所有内部链接解析到已产出的页面、允许的应用路由或存在的锚点；指向草稿或不存在文章的内链让构建失败。
  - 内容校验：缺必填字段、日期倒序、重复标题/描述/slug、非法 slug、过短正文、外部图片、危险 HTML 都失败，且错误信息包含文件名。
  - Markdown 清理：`<script>`、`<iframe>`、表单与 `javascript:` 链接不出现在产物中。
  - 未知路径的 404 页面带 `noindex`；`app.html` 不包含文章或营销正文。
- **前端端到端**：在现有 Playwright 黄金路径之外，增加一条轻量导航用例：`/features` → `/guide` → `/faq` → `/articles` → 文章详情 → 回到 `/`，断言 H1、目录、标题更新、无控制台错误；保留私有 Analysis 页 `noindex` 断言；断言解析出结果后首页营销区块隐藏。端到端跑在开发服务器上，验证 SPA 行为；预渲染产物由上述构建接缝覆盖。
- **后端**：无代码改动，但合并前必须运行现有 `uv run pytest -q` 与 `uv run ruff check .`，证明 P3 未影响 API 接缝。
- **命令**：`npm run build`（含预渲染与产物校验）、`npm run typecheck`、`npm run test:unit -- --run`、`PLAYWRIGHT_E2E=1 npx playwright test`。
- **既有先例**：`src/lib/*.test.ts` 的纯行为测试、Playwright 黄金路径、后端 `tests/test_seam.py` 的「只测接缝」风格。P3 新增测试保持同一粒度，不引入网络、真实 DNS、Stripe 或 AI 调用。

## Out of Scope

- Nuxt、运行时 SSR、hydration、边缘渲染与动态 SEO 服务。
- 公开 Video/Analysis 页面、用户内容索引、个人主页或公开分享页。
- CMS/后台编辑器、定时发布、多人协作、评论、站内搜索、标签页、RSS/Atom 与邮件订阅。
- 多语言、hreflang、AMP、地区化落地页。
- 平台专属落地页（B 站/YouTube/抖音各一页）；首期由指南与文章承接。
- 隐私政策页、Cookie 同意、数据分析/统计、Search Console/Bing 验证、排名与反链监测、A/B 测试、付费投放。
- 为每篇文章生成独立分享图或内容配图。
- 后端 API、数据库、SQLite、下载/Analysis 链路与 Stripe 配置变更。
- CI 流水线；仍按 README 的命令手动执行。
- 对 Google FAQ/HowTo 富结果、AI 引用或排名结果的任何保证。

## Further Notes

- 部署前必须把 `SITE_ORIGIN` 与 `APP_FRONTEND_BASE_URL` 同时设为公网 https origin；本地 localhost 构建会主动禁止抓取，不能用来验证收录。
- 首次上线后建议手动：提交 sitemap、用 URL Inspection 检查首页/价格/一篇代表文章、用社交平台调试器检查 OG、`curl` 检查 robots 与 404、确认私有路由带 `X-Robots-Tag`。这些是发布检查项，不进入自动化测试。
- `llms.txt` 仍是新兴约定，搜索引擎与 AI 平台是否读取不可控；它的价值在于提供一份可机读的权威索引，不能替代正常 SEO。
- 价格以 Stripe 结账页为最终真相；前端展示常量、结构化数据与价格页文案必须一起调整，避免价格不一致。
- 内容节奏建议每月 1–2 篇，优先回答真实搜索问题；更新旧文时修改 `updated` 而不是伪造新发布日期。
- 抖音仍受 `APP_DOUYIN_ENABLED` 控制；营销文案只能描述灰度事实，不能把灰度能力写成全量支持。
- 预渲染的主要风险是 Node 环境下的 Markdown 清理器（需要 DOM shim）、canonical origin 配错、nginx `.html` 查找顺序以及首页营销区块的显示条件；实现时先用最小页面跑通构建产物校验，再扩展内容与页面。
- 建议按以下切片实施：P3-01 内容集合与文章页（含 4 篇种子文章）；P3-02 SEO 描述符、预渲染与品牌资产；P3-03 营销页、首页区块与导航；P3-04 sitemap/robots/`llms.txt` 与内链校验；P3-05 nginx、应用外壳、404、origin 配置与部署文档；P3-06 构建产物测试与 Playwright 回归。测试随切片同步落地，不集中到最后。
- 归档说明：本 spec 为 GitHub Issue #29（2026-10-25 发布并关闭）的仓库副本，P3 实现经 PR #39 合入 `main`（merge commit `b1532cf`）。后续价格/配额单一来源与文章模板化由 #41、#45 收口，正文保留发布时表述。
