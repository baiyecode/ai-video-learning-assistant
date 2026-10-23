## Problem Statement

用户想把公开视频保存到本地（离线看教程、备份自己的作品），但各平台下载入口分散，有的不提供下载、有的限制清晰度、有的要求安装客户端。同时，长视频（例如 2 小时的技术分享）在没有摘要的情况下很难判断是否值得投入时间，用户往往需要先花大量时间浏览，才能决定要不要看。

现有工具通常只解决其中一半问题：下载器不懂内容，AI 总结工具不提供可保存的文件，而且大多数没有配额与账户体系，无法作为可持续的产品运营。

## Solution

P1 交付一个可上线的单视频工作流：

访客粘贴一个 B 站或 YouTube 的视频链接，系统解析标题、封面、时长与可选清晰度；访客可以直接发起服务端 Download，并在完成后通过临时链接保存文件，也可以查看与导出 Subtitle。登录 Account 后，用户可以对同一个 Video 发起 Analysis：系统基于平台提供的 Subtitle 流式生成 Markdown 摘要，并生成可交互、可导出的思维导图。免费 Account 每天有 3 次 Analysis 配额，按 Asia/Shanghai 自然日重置；失败的 Analysis 不消耗配额。

P1 不包含支付、邮箱验证、抖音专用解析、ASR、AI 问答与 SEO/GEO，这些留给后续阶段。

## User Stories

### 访客：解析与下载

1. 作为访客，我想粘贴一个视频链接并立即解析，以便确认平台是否支持。
2. 作为访客，我想看到标题、封面、时长和来源 Platform，以便确认这是目标 Video。
3. 作为访客，我想看到可选的清晰度与格式，以便在画质和文件体积之间取舍。
4. 作为访客，我想看到每种格式的大致文件大小，以便决定下载哪一个。
5. 作为访客，我想在发起 Download 前看到「仅限下载你有权保存的内容」的提示，以便合规使用。
6. 作为访客，我想在提交播放列表、合集或不支持的链接时被明确拒绝，以便知道产品边界。
7. 作为访客，我想在解析失败时看到可理解的原因，而不是堆栈信息，以便判断是否值得重试。
8. 作为访客，我想在触发频率限制时知道何时可以再试，以便安排操作。
9. 作为访客，我想在尝试发起 Analysis 时被引导登录，以便使用 AI 能力。

### 访客：Download 与 Subtitle

10. 作为访客，我想选定清晰度后由服务端生成文件，以便不用保持页面打开。
11. 作为访客，我想看到 Download 的排队、下载中、合并中、完成、失败状态，以便知道还要等多久。
12. 作为访客，我想在完成后通过临时链接保存文件，以便离线观看。
13. 作为访客，我想在链接失效前看到剩余有效时间，以便及时保存。
14. 作为访客，我想在下载中断后从断点继续，以便不重复传输大文件。
15. 作为访客，我想在 Download 失败时看到原因和手动重试入口，以便自行恢复。
16. 作为访客，我想在同时下载过多时进入队列而不是直接失败，以便稳定获得结果。
17. 作为访客，我想查看 Subtitle 的完整文本，以便快速浏览内容。
18. 作为访客，我想把 Subtitle 导出为 SRT、VTT 或 TXT，以便自行整理和学习。
19. 作为访客，我想在 Video 没有可用 Subtitle 时看到明确提示，以便理解为什么无法 AI 总结。
20. 作为访客，我想在文件被清理后看到明确提示，以便重新生成。

### Account：注册、登录与会话

21. 作为新用户，我想用邮箱和密码注册 Account，以便获得 Quota 并保存 Analysis。
22. 作为用户，我想在注册时得到明确的密码强度要求，以便一次通过。
23. 作为用户，我想用邮箱和密码登录，以便继续之前的 Analysis。
24. 作为用户，我想在一段时间内保持登录，以便不用反复输入密码。
25. 作为用户，我想在 access token 过期时自动刷新 Session，以便不中断操作。
26. 作为用户，我想在登出后当前 Session 立即失效，以便保护 Account。
27. 作为用户，我想在登录失败时得到不泄露邮箱是否存在的提示，以便账户安全。
28. 作为用户，我想只看到自己的 Analysis 列表与结果，以便隐私受到保护。
29. 作为用户，我想看到今天剩余的免费 Analysis 次数，以便规划使用。
30. 作为用户，我想在 Quota 用尽时看到重置时间，以便知道何时再来。
31. 作为用户，我想在连续快速操作时被限流而不是被静默忽略，以便知道发生了什么。

### Account：Analysis

32. 作为用户，我想对已解析的 Video 发起 Analysis，以便获得摘要和思维导图。
33. 作为用户，我想实时看到摘要流式输出，以便不必等待整段生成完成。
34. 作为用户，我想摘要以 Markdown 排版展示，以便阅读结构清晰的内容。
35. 作为用户，我想看到可交互的思维导图，以便快速把握视频结构。
36. 作为用户，我想全屏查看、缩放和拖拽思维导图，以便查看细节。
37. 作为用户，我想把思维导图导出为 PNG 或 SVG，以便保存和分享。
38. 作为用户，我想在生成失败时不被扣除 Quota，以便不因系统问题受损。
39. 作为用户，我想在刷新或重新打开页面后仍能看到已生成的 Analysis，以便不重复消耗 Quota。
40. 作为用户，我想在查看已有 Analysis 时不消耗 Quota，以便反复复习。
41. 作为用户，我想在明确选择重新分析时被告知会消耗 1 次 Quota，以便知情决策。
42. 作为用户，我想在无 Subtitle 的 Video 上被拒绝 Analysis 并说明原因，以便理解限制。
43. 作为用户，我想在字幕很长时仍得到覆盖全片的摘要，以便长视频同样可用。
44. 作为用户，我想在多个标签页重复点击时不会重复扣除 Quota，以便避免误操作。
45. 作为用户，我想在流式连接中断后重新获取已完成的结果，以便网络波动不影响使用。
46. 作为用户，我想知道摘要基于人工字幕还是自动字幕生成，以便判断可信度。

### 运维与产品边界

47. 作为运维者，我想通过健康检查确认服务、数据库与磁盘可写，以便快速发现故障。
48. 作为运维者，我想通过结构化日志和 request_id 定位一次失败，以便排障。
49. 作为运维者，我想每日自动备份数据库，以便灾难恢复。
50. 作为运维者，我想临时媒体文件在 1 小时后自动清理，以便控制磁盘占用。
51. 作为运维者，我想全局 AI 日预算触顶后暂停免费 Analysis，以便控制成本。
52. 作为运维者，我想在服务重启后把中断的 Download 任务标记为失败，以便状态不悬挂。
53. 作为产品运营者，我想在使用条款中说明临时文件策略与滥用举报入口，以便降低合规风险。
54. 作为产品运营者，我想拒绝 DRM 保护内容与会员专属内容的解析请求，以便守住产品边界。

## Implementation Decisions

### 架构与模块

- 采用模块化单体：FastAPI 后端 + Vue 3 SPA 前端，单机 Docker Compose 部署，SQLite（WAL）。
- 后端按职责划分模块：**Identity**（Account、Session）、**Catalog**（Video 解析与身份归一化、Subtitle）、**Media**（Download 任务、文件存储与清理）、**Analysis**（配额、摘要与导图生成）、**Platform Adapters**（yt-dlp、DeepSeek、文件系统）、**Shared**（配置、错误、日志、限流）。
- 前端模块：链接与解析页、下载任务页、Analysis 页、认证页、条款页；状态管理使用 Pinia。
- 后台任务在 API 进程内用 asyncio 队列执行（下载队列、清理任务、预算统计），不引入 Celery/Redis；服务重启时将未完成任务标记为失败。

### 领域模型

- **Video** 全站共享，身份为 `Platform + 平台内 Video ID`。URL 仅作为输入，解析时跟随已知短链、移除追踪参数与时间戳；同一 Video 的不同链接命中同一条记录。
- **Subtitle** 随 Video 存储，优先人工字幕，其次自动字幕；语言偏好按 `zh-Hans`、`zh`、`en` 的顺序选择。存储标准化 cue 与纯文本，并记录来源类型。
- **Analysis** 归属 Account，固化生成时使用的 Subtitle 版本；Video 的 Subtitle 后续更新不回溯修改已有 Analysis。
- **Quota** 以 Analysis 为单位，按 `Asia/Shanghai` 自然日计算；创建 Analysis 时预留 1 次，成功则消耗，失败则释放。
- **Download** 不要求登录；访客任务不产生长期历史记录。任务状态：`queued`、`downloading`、`merging`、`ready`、`failed`、`expired`。
- **Session** 由 refresh token 代表，可在数据库吊销；access token 不落库。

### API 契约

统一错误响应：`{ "error": { "code": "...", "message": "...", "details": {...} } }`。所有错误使用稳定 code，消息面向用户，不返回堆栈。

- `POST /api/videos/resolve`：入参 `{ url }`；返回 Video 基本信息、可选格式列表、Subtitle 可用性与来源、是否可 Analysis、以及使用条款提示。仅接受单个视频链接，拒绝播放列表与合集。
- `GET /api/videos/{video_id}`：返回缓存的 Video 元数据；格式快照有效期 10 分钟，过期后需重新解析。
- `GET /api/videos/{video_id}/subtitles?format=srt|vtt|txt`：导出 Subtitle；无字幕返回 `subtitles_unavailable`。
- `POST /api/downloads`：入参 `{ video_id, format_id }`；返回 Download 任务；访客可用，按 IP 限流。
- `GET /api/downloads/{download_id}`：返回任务状态、进度、失败原因；`ready` 时返回 15 分钟有效的签名 URL 与文件过期时间。
- `POST /api/downloads/{download_id}/retry`：手动重试，最多 3 次。
- `POST /api/auth/register`、`POST /api/auth/login`、`POST /api/auth/refresh`、`POST /api/auth/logout`：refresh token 通过 HttpOnly Cookie 传递；refresh 轮换，登出吊销当前 Session。
- `GET /api/me`：返回 Account 基本信息、今日 Quota 使用量与剩余量、Quota 重置时间。
- `POST /api/analyses`：入参 `{ video_id, force?: boolean }`；返回 Analysis 标识与状态。若同一 Account 对同一 Video 已存在进行中的 Analysis，则返回该 Analysis 而不重复预留 Quota；若已有完成结果且未 `force`，直接返回既有结果。
- `GET /api/analyses/{analysis_id}`：返回归属校验后的 Analysis 全量结果（摘要 Markdown、思维导图 Markdown、状态、字幕来源）。
- `GET /api/analyses/{analysis_id}/stream`：SSE。事件顺序为 `meta` → 若干 `delta` → `mindmap` → `done`；失败发 `error`。连接中断不取消服务端生成，重连时先补发已持久化的内容再继续。
- `GET /api/analyses`：返回当前 Account 的 Analysis 列表，按创建时间倒序。
- `GET /health`：返回服务、数据库、磁盘可写状态。

### Download 执行

- 服务端用 yt-dlp 下载、ffmpeg 合并音视频；单 Video 时长上限 2 小时、文件上限 2GB，超限在创建任务前拒绝。
- 全局并发上限 5，按创建顺序 FIFO；访客每 IP 同时 1 个、每小时 5 个；登录用户每 Account 同时 2 个。
- 任务执行时重新解析格式，避免使用过期的平台直链；下载完成写入临时目录，完成后生成签名 URL。
- 文件保留 1 小时，签名 URL 有效期 15 分钟，支持 Range 请求；清理任务定期删除过期文件并把任务标记为 `expired`。
- 仅支持单视频 URL，不支持播放列表、直播与 DRM 内容。

### Analysis 生成

- 通过 OpenAI 兼容协议调用 DeepSeek，模型、`base_url`、密钥均由服务端配置；不做多供应商路由与自动降级。
- Subtitle 先按 cue 边界切块，超过阈值时分块摘要再归并，确保 2 小时视频也能覆盖全片；最终输出简体中文。
- 一次生成调用同时产出「摘要」与「思维导图」两个 Markdown 区块；摘要增量通过 SSE 推送，生成结束后服务端解析导图区块并发 `mindmap` 事件。
- 输出上限与单块字符数由配置控制；输入超限时显式提示用户结果基于截断内容，不静默丢弃。
- 超时与失败处理：流式空闲超时、总时长上限、上游错误均转为 `analysis_failed`；失败释放 Quota。
- 思维导图由前端 markmap 渲染；PNG/SVG 导出在浏览器端完成。

### 认证、配额与限流

- 密码使用 bcrypt 存储；最低 8 位，不强制字符组合；注册与登录按 IP 限流。
- access token 15 分钟，内存保存；refresh token 7 天，HttpOnly + Secure + SameSite=Lax，数据库只存哈希，支持轮换；登出与封禁立即吊销。
- 刷新与登出校验 Origin；access token 通过 `Authorization: Bearer` 传递。
- 免费 Account 每日 3 次 Analysis；Viewer 查看既有结果不计次；失败不计次；重复点击复用进行中的 Analysis。
- 限流默认值：解析 10 次/分钟/IP，创建 Download 3 次/分钟/IP，登录 10 次/15 分钟/IP，注册 5 次/小时/IP，Analysis 每 Account 每 10 秒 1 次。
- 全局 AI 日预算（默认 10 美元）触顶后，免费 Account 的 Analysis 返回 `budget_exhausted`，既有结果仍可查看。

### 安全与合规

- 仅接受 `http/https` 视频 URL；拒绝私有地址与内网目标，只允许 yt-dlp 能识别的提取器，防止 SSRF。
- Markdown 渲染前消毒，防止 XSS；思维导图输入同样消毒。
- 临时文件使用随机名，下载 URL 使用带过期时间的 HMAC 签名。
- CORS 使用显式允许列表；密钥只存在于服务端环境变量。
- 页面展示「仅限个人备份或已获授权内容」提示，提供使用条款与滥用举报入口；不提供绕过 DRM 或会员权限的能力。

### 可观测性与运维

- JSON 结构化日志，每个请求带 request_id；错误日志包含错误 code。
- 后端与前端接入 Sentry；`/health` 检查数据库与磁盘。
- SQLite 使用 WAL；每日备份到宿主机卷；Docker `restart: unless-stopped`。
- 前端构建产物由 Nginx 提供；API 与静态资源同域部署。

## Testing Decisions

### 接缝

- **主接缝：FastAPI HTTP API**。测试通过进程内 ASGI 调用，不启动真实服务器，不访问真实网络。
- **次接缝：浏览器**。只保留一条 Playwright 黄金路径，验证真实前端与后端的组合。
- 不新增前端 fetch 层或组件级网络接缝；纯逻辑（SSE 解析、Markdown 区块切分、配额展示）用 Vitest 覆盖，不属于集成接缝。

### 测试替身

- `VideoSource`：解析元数据、格式与 Subtitle；测试中返回固定样本。
- `MediaStore`：执行下载、合并、签名 URL 与清理；测试中用可控假实现模拟成功、失败、慢速与磁盘不足。
- `Summarizer`：流式生成摘要与导图；测试中按脚本产出增量、超时与错误。
- `Clock`：固定「当前时间」，覆盖 Asia/Shanghai 跨日、签名过期、文件过期。
- `BudgetLedger`：可注入日预算与已消耗额度，验证触顶行为。
- 生产环境在组装根注入真实适配器；业务模块不直接 import 外部 SDK。

### 必须具备的测试

- Video 身份归一化：短链、追踪参数、时间戳、不同清晰度链接归一到同一 Video；播放列表与不支持链接被拒绝。
- 认证：注册、登录、刷新轮换、登出吊销、归属校验、密码错误不泄露账户存在性。
- Quota：成功消耗、失败释放、跨日重置、并发重复请求只预留一次、查看既有结果不消耗。
- Analysis：SSE 事件顺序、断线重连补发、长字幕分块归并、无字幕拒绝、失败状态与错误 code。
- Download：排队与并发上限、进度状态流转、重试上限、超时长/超大文件拒绝、签名 URL 过期、Range 请求、清理后状态。
- 安全：SSRF 拒绝、Markdown 消毒、越权读取他人 Analysis 被拒绝。
- 运维：预算触顶后免费用户被拦截、服务重启后未完成任务标记失败、健康检查失败场景。

### 前端测试

- Playwright 黄金路径：访客解析 → 发起 Download → 等待完成 → 登录 → 发起 Analysis → 看到流式摘要与导图 → 导出 Subtitle。后端以假适配器模式启动，全程无真实外部调用。
- Vitest 覆盖 SSE 解析器、摘要/导图区块切分、时间与配额格式化。

### 既有先例

仓库当前没有应用代码，无既有测试先例。本 spec 同时确立约定：外部系统一律通过端口注入，集成测试只用进程内 HTTP 接缝与测试替身，CI 不依赖真实平台、DeepSeek 或网络。

## Out of Scope

- Stripe 支付、VIP Membership、订单记录与权益判定（P2）。
- 邮箱验证、找回密码、社交登录、CAPTCHA（P2）。
- 抖音专用解析模块；P1 只依赖 yt-dlp 稳定覆盖的平台（P2）。
- 服务端语音转写（ASR）；无 Subtitle 的视频在 P1 不支持 Analysis。
- AI 视频问答（P1 之后）。
- SEO/GEO、TDK、sitemap、结构化数据、预渲染文章（P3）。
- 多语言界面；P1–P2 仅简体中文。
- 播放列表、合集、批量链接、直播、DRM 内容、会员专属内容。
- 多实例横向扩展、对象存储、独立任务队列、Prometheus/Grafana。
- 管理后台、数据看板、用户自助删除 Account、Analysis 分享。
- 访客下载历史、批量导出、字幕编辑与重新打轴。
- 视频转码、剪辑、画质增强等下载之外的媒体处理。

## Further Notes

- P2 将补充 Stripe 月订阅、邮箱验证与抖音模块；P3 再做 SEO/GEO。相关架构取舍见 ADR-0001 至 ADR-0005。
- 术语以 `GLOSSARY.md` 为准：使用 Analysis、Quota、Visitor、Account、Session、Download、Subtitle、Platform、Video、VIP Membership，避免同义替换。
- 待确认的运营参数：DeepSeek 实际单价与日预算、平台使用条款与法律意见、单块字符阈值与输出 token 上限。这些均有配置项，不阻塞实现。
- 本 spec 发布到 GitHub Issues，并标记 `ready-for-agent`。
