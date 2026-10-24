# P2: Stripe 订阅、邮箱验证与抖音解析

## Problem Statement

P1 跑通了「解析 → 字幕 → Analysis → 服务端 Download」的主链路，但产品还没有收入，运营者无法把服务器与 DeepSeek 成本转化为可持续的商业模式；免费 Account 每天只有 3 次 Analysis，重度用户没有付费出路。同时，注册只凭邮箱字符串、不验证所有权，带来冒用他人邮箱、垃圾 Account 与无法找回密码的问题。用户也频繁询问抖音 Video 的支持，但抖音的页面结构与 B 站/YouTube 差异大，直接放开风险高，需要一条可灰度、可回滚的路径。

## Solution

P2 交付三块可独立开关的能力，全部保持现有单进程 + SQLite 架构（ADR-0001）：

1. **VIP Membership 订阅**：Account 以 $4.99/月通过 Stripe Checkout 升级，Active 订阅的 Analysis 不受 Quota 限制；订阅生命周期（续订、取消、逾期失效）由 Stripe Webhook 事件驱动，用户可随时从产品内跳转到 Stripe 客户门户管理。
2. **邮箱验证**：注册后发送带验证链接的邮件，Account 拥有已验证邮箱后才能发起 Analysis；登录、解析与 Download 不受验证状态影响，验证邮件可重发且有频率限制。
3. **抖音专用解析**：在 Platform 注册表与 Settings 功能开关（默认关闭）之后，为抖音 URL 提供专用解析分支，产出带水印的单清晰度 Download；打开开关即支持，关闭即在 URL 校验层明确拒绝，零代码回滚。

测试沿用唯一接缝：进程内 ASGI HTTP API + 注入式 fake 适配器；Stripe 与邮件通过两个新端口（`BillingGateway`、`EmailSender`）注入，抖音只扩展既有 `VideoSource` 假适配器。

## User Stories

### Account：订阅与 VIP Membership

1. 作为免费 Account，我想在 Quota 用尽时看到升级入口和价格，以便决定是否为 AI 能力付费。
2. 作为 Account，我想在定价页看到「$4.99/月、Analysis 不限次」的单一条款，以便无需比较套餐直接决策。
3. 作为 Account，我想点击升级后跳转到 Stripe 托管的 Checkout 页完成支付，以便不在本产品内输入或存储卡号。
4. 作为付款成功者，我想回到产品后立即看到 VIP Membership 生效与「配额已解除」的状态，以便马上继续使用。
5. 作为 Account，我想在订阅生效前浏览到当前仍是免费 Quota 的明确提示，以便不误以为已付费。
6. 作为 VIP，我想发起 Analysis 时不再被 Quota 拦截，以便不受每日 3 次限制地学习。
7. 作为 VIP，我想查看当前订阅状态（Active、Trial、Past Due、Canceled 等）与下次续费日期，以便掌握自己的账务。
8. 作为 VIP，我想取消订阅后仍可用到当期结束，以便已获得的服务不被切断。
9. 作为 VIP，我想在取消后、到期前看到「将于某日失去 VIP」的预告，以便提前决定恢复。
10. 作为订阅到期或被停订的用户，我想在下一次请求时被自动降回免费 Quota 而无需任何操作，以便状态始终与实际账务一致。
11. 作为有扣款未成功（Past Due）的用户，我想在产品内看到明确警示，以便尽快在 Stripe 门户更新支付方式。
12. 作为 Account，我想从订阅管理入口进入 Stripe 客户门户更换卡或申请发票，以便不经过本产品处理任何支付数据。
13. 作为用户，我想在浏览器支付回调被中断后仍能在 Account 页看到真实订阅状态，以便状态以 Stripe 为准而不依赖前端跳转。
14. 作为产品，我想对同一 Stripe 事件只生效一次（重复投递幂等），以便 Webhook 重试不会带来双重权益或双重扣减。
15. 作为产品，我想对乱序到达的事件按「较新状态胜出」处理，以便旧事件重放不会把订阅状态回退。
16. 作为运营者，我想在缺少 Stripe 密钥时生产环境拒绝启动，以便绝不带着半套支付配置上线。

### Account：邮箱验证

17. 作为新注册者，我想注册后立刻收到一封验证邮件，以便确认邮箱属于我。
18. 作为新注册者，我想点击邮件中的链接即完成验证并跳回产品，以便流程不离开浏览器。
19. 作为未验证邮箱的 Account，我想仍能登录、解析 Video、查看 Subtitle 与发起 Download，以便验证只作为 Analysis 的门槛而不是全站门槛。
20. 作为未验证邮箱的 Account，我想在尝试发起 Analysis 时看到「请先验证邮箱」的可操作提示与重发入口，以便一步完成补救。
21. 作为收不到邮件的注册者，我想在限制内重发验证邮件，以便应对误投与垃圾箱。
22. 作为注册者，我想在他人（或自己）已注册的邮箱上收到「如果这是你本人操作」的提示而不是错误暴露，以便不泄露邮箱是否已注册。
23. 作为用户，我想验证链接是一次性的：验证成功或 Account 改密后即失效，以便链接不会被二次利用。
24. 作为用户，我想使用过期链接时得到「已过期，请重新发送」的明确提示，以便自行恢复。
25. 作为运营者，我想验证 Token 有较短的有效期上限（例如 24 小时），以便积压的邀请链接不会永久有效。
26. 作为运营者，我想对发信与验证链接命中分别施加频率限制，以便避免被用作免费邮件群发通道。
27. 作为运营者，我想在真实邮件服务未配置时（开发/测试环境）以可观测的假发送器代替，以便流程可测且不会误发真实邮件。

### 平台扩展：抖音解析（功能开关）

28. 作为抖音用户，我想粘贴抖音视频页或短链并解析出标题、封面与时长，以便像 B 站一样使用本产品。
29. 作为抖音用户，我想在开关关闭时看到「抖音暂未开放」的明确文案而不是「链接不受支持」，以便知道这是计划中的能力。
30. 作为抖音用户，我只能得到服务端提供的带水印单清晰度 Download，以便产物符合平台的分发限制。
31. 作为产品，我想在不部署代码的前提下用开关放开或收回抖音支持，以便灰度发布与一键回滚。
32. 作为产品，我想在抖音 URL 被支持时走专用解析分支、其他平台不受影响，以便风险只隔离在这一个 Platform。
33. 作为抖音用户，我想在无 Subtitle 的抖音 Video 上看到与现有规则一致的「无法 Analysis」提示，以便理解 P2 仍不做 ASR。
34. 作为运营者，我想在抖音解析失败率异常时通过既有结构化日志与错误码定位，以便快速决定关开关。

### 前端与运营

35. 作为 Account，我想在侧栏或个人中心持续看到剩余 Quota 与订阅状态，以便随时知道自己处于哪一档。
36. 作为前端，我想对 Quota 拦截（429）、未验证邮箱（403）、Past Due 等返回码分别呈现不同文案与入口，以便用户下一步明确。
37. 作为前端，我想在 Quota 用尽时直接显示升级 CTA，以便付费转化发生在需求最强的时刻。
38. 作为运维者，我想订阅状态变化被记录在结构化日志并可追溯到 Stripe 事件 ID，以便账务争议可复核。

## Implementation Decisions

### 架构与模块

- 新增业务模块 `billing`（与 `identity`/`analysis`/`catalog`/`media`/`ops` 同构）：订阅记录、VIP Membership 判定、Checkout 与 Webhook 路由。
- 新增业务模块 `email_verification`（并入 identity 的账号生命周期）：验证 Token 的签发、消费与重发。
- 抖音不新建模块：在现有 catalog 的 URL 校验（SSRF/平台白名单）与 `VideoSource` 适配器内按 Platform 分支，Platform 注册表是唯一的「支持列表」真相源。

### 端口与适配器（唯一的注入面）

- 端口 `BillingGateway` 与 `EmailSender` 以 Protocol 形式加入现有 `Adapters` 容器；生产适配器分别包 Stripe SDK 与 SMTP/HTTP 邮件服务，测试与 Playwright 黄金路径注入 fake（内存收件箱、可编程 Stripe 事件）。
- Stripe Webhook 的签名验签与事件解码发生在 `BillingGateway` 适配器内部，路由只消费验签后的领域事件（类型 + 载荷 + 事件 ID + created 时间）；测试通过既有 `client` fixture 以 HTTP POST 调用 `/billing/webhook`，无需 stripe-cli、不开端口。
- 抖音专用解析扩展 `VideoSource` 的 fake 适配器（多识别一种 douyin URL 形态），不新增端口。

### 数据模型

- `Account`：新增邮箱验证状态字段（`email_verified_at`），并保留验证 Token 的哈希与过期时间；旧 Account 上线时视为未验证（Analysis 需先走一次验证）。
- 新增 `Subscription`：`account_id`、Stripe Customer ID、Stripe Subscription ID、`status`、`current_period_end`、`price_id`。以 Stripe ID 为幂等外键，Account 为唯一归属。VIP Membership 是 `Subscription.status ∈ {active, trial_ending}` 的派生态，不冗余存储 `is_vip`（与 GLOSSARY 一致）。
- 新增 `BillingEvent`：记录已处理的 Stripe `event_id`、事件类型与处理时间；既是幂等表，也是账务审计线索。

### 配额与权益

- Quota 判定改造保持单一入口：`quota.reserve` 增加「VIP 免限」短路——Active 订阅时以「无限」上限走同一段原子 upsert 逻辑，`QuotaSnapshot.daily_limit` 用哨兵值表达无限并在响应 schema 中与 `membership` 状态一并返回。
- 失败的 Analysis 不消耗配额的既有规则对 VIP 同样适用（回滚 reserved 计数）。

### 状态机

订阅状态只由 Webhook 事件推进，本地不猜测（来自设计草图，非可执行代码）：

```
none ──checkout.session.completed──▶ active
active ──invoice.payment_failed──▶ past_due
past_due ──invoice.payment_succeeded──▶ active
active/trial ──customer.subscription.deleted | current_period_end 过期──▶ canceled → none
```

- 乱序防护：每次写入比较事件的 `created` 与本地已记录的最新事件时间，较旧事件只记 `BillingEvent`、不改状态。
- 幂等：`BillingEvent.event_id` 唯一约束，冲突即视为已处理并返回 2xx。

### API 契约（对外可见行为）

- `POST /billing/checkout`：需登录；创建 Checkout Session 并返回其 URL（前端整页跳转）。
- `GET /me/membership`：返回 `{ status, period_end, portal_url }`，是前端唯一的订阅状态来源；不读 URL 查询参数判定成功。
- `POST /billing/portal`：返回 Stripe 客户门户 URL。
- `POST /billing/webhook`：无鉴权、以签名验签为准，恒定快速返回，处理失败靠 Stripe 重试。
- `POST /auth/verification/request`（重发）、`POST /auth/verification/confirm`（带 token，成功即置 `email_verified_at`）。
- Analysis 创建新增前置校验顺序：已登录 → 邮箱已验证（否则 `403 EMAIL_NOT_VERIFIED`）→ Quota/VIP → 限流。

### 配置与开关

- 新增 Settings 字段（沿用 `APP_` 前缀约定）：`stripe_api_key`、`stripe_webhook_secret`、`stripe_price_id`、`subscription_monthly_usd`（默认 4.99，仅展示用）、`douyin_enabled`（默认 `false`）、邮件服务与验证 Token TTL。
- 生产启动校验扩展既有 `validate_production_secrets`：`env=production` 且缺 Stripe/邮件密钥时拒绝启动；开发环境允许缺密钥（此时 billing 路由返回 503 而非崩溃）。
- 抖音开关关闭时在 URL 校验层返回专用错误码 `PLATFORM_NOT_ENABLED`，前端映射为「暂未开放」。

### 前端

- 新增 `billing` store（订阅状态 + membership 拉取）、定价/升级视图、Account 页的订阅区块、未验证邮箱横幅与重发按钮；Quota 用尽处显示升级 CTA。
- 沿用既有 SSE/HTTP 客户端与 cookie 认证策略（ADR-0004），不引入新的鉴权形态。

## Testing Decisions

- **只测外部行为**：断言 HTTP 状态码、响应 schema、数据库派生态（`GET /me/membership`）、Analysis 是否放行、邮件是否进入内存收件箱、URL 是否被拒绝；不断言适配器内部调用序列、ORM 事件或私有函数。
- **接缝唯一**：全部走既有 `client`/`adapters` fixtures（进程内 ASGI + fake 适配器）与 `tests/fakes.py` 扩展，Stripe/邮件/抖音各自通过端口注入替身；不开真实网络，不依赖 stripe-cli 与 SMTP。
- **将测的模块**：
  - `billing`：Checkout 创建（登录要求）、Webhook 状态机推进（含重复投递幂等、乱序不回退）、VIP 解除 Quota、到期/取消自动降级、Past Due 呈现、缺密钥时的行为。
  - `identity` + 邮箱验证：注册触发发信、token 消费（一次性、过期、改密后失效）、未验证可登录/下载但不可 Analysis、重发限制、不泄露邮箱存在性。
  - `analysis`/`quota`：VIP 免限短路、失败回滚、`QuotaSnapshot` 无限语义、既有多标签页不重复扣减的回归。
  - `catalog`：抖音开关开/关的 URL 校验行为、专用分支的 resolve 结果、既有平台不受影响、SSRF 回归。
  - 前端：`billing`/`auth` store 单测（状态流转，mock HTTP）；Playwright 黄金路径扩展「免费 Quota 用尽 → 升级 → VIP 无限制」一条链路的假适配器版本。
- **既有先例**：`test_analysis_history.py`（配额扣减与回滚）、`test_identity.py`（认证与 Session 生命周期）、`test_catalog_urls.py` + `test_catalog_ssrf.py`（URL 平台判定）、`test_budget.py`（SQLite 台账）、`test_seam.py`（接缝本身）、`fakes.py` 的假适配器集合——P2 新增测试保持同一风格与粒度。

## Out of Scope

- 多档订阅、年付、试用自动转付费、优惠券与税费（Stripe 侧配置也不在本期内）。
- 抖音直播/合集、无水印下载与 ASR 转写；P2 仍只用平台已有 Subtitle。
- AI 问答（对话式提问），仍排在分期之后。
- 密码找回与第三方 OAuth 登录。
- 多实例、Redis 分布式限流与横向扩展（与 ADR-0001 冲突，届时需新 ADR）。
- SEO/GEO、静态营销页与文章（P3）。
- 退款、发票下载、Dunning 邮件文案（由 Stripe 门户与邮件模板承担）。

## Further Notes

- 单 VPS + SQLite 下，Webhook 写入是低频单进程操作，`BillingEvent` 唯一约束足以充当幂等门；无需消息队列。
- VIP 解除 Quota 后，DeepSeek 成本敞口由 `daily_budget_usd` 与限流承担；P2 依赖二者作为成本控制面。
- 抖音解析依赖 yt-dlp 对抖音 extractor 的稳定性，故功能开关默认关闭、可独立回滚是硬要求。
- 部署需新增：`stripe_api_key`、`stripe_webhook_secret`、`stripe_price_id`、邮件服务凭据、`douyin_enabled`；`docker-compose.yml` 的 env 清单需同步。
- 前置依赖：P1 的 `spec/p1` 分支需合并进 `main`（当前尚未 push）。
