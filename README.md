# AI 视频学习助手

解析公开视频、下载文件、导出字幕，并基于字幕生成简体中文摘要与思维导图的单上下文产品。

当前状态：**P1 + P2 已完成**（GitHub issues #2–#14、#17–#26）。访客可解析、导出字幕、服务端下载；账号可流式生成摘要与思维导图，并受每日 Quota、限流与 AI 预算约束。P2 交付 VIP Membership（Stripe 订阅）、邮箱验证与抖音解析（`APP_DOUYIN_ENABLED` 默认关闭）。

## 目录结构

```
backend/                 FastAPI 模块化单体（Python 3.12+，uv 管理）
  app/
    main.py              create_app(settings, adapters) 组合根 + ASGI 入口
    config.py            pydantic-settings（APP_ 环境变量前缀）
    db.py                SQLAlchemy 2 async + SQLite WAL、init_db()
    errors.py            AppError + 统一错误响应 + 异常处理器
    messages.py          跨模块共用的用户可见文案（同一条件同一句话）
    timeutil.py          UTC 规范化与 Asia/Shanghai 日历日/次日零点
    ratelimit.py         内存滑动窗口限流（429 + Retry-After）
    logging_setup.py     JSON 日志 + request_id 中间件/contextvar
    ports.py             VideoSource / MediaStore / Summarizer / Clock / BudgetLedger / BillingGateway / EmailSender
    container.py         Adapters 容器与 build_production_adapters()
    deps.py              get_settings / get_adapters / get_session / get_clock
    adapters/            生产适配器：yt-dlp 解析（含抖音分支）、文件系统媒体、DeepSeek 摘要、系统时钟、SQLite 预算账本、SMTP 发信、Stripe 收单
    modules/             catalog（Video/Subtitle）、identity（Account/Session/邮箱验证）、billing（Subscription/BillingEvent/webhook）、media（Download）、analysis（Analysis/Quota）、ops（/health、举报、Sentry）
    modules/*/manager.py 下载队列与分析生成两条后台链路，由 main.py 的 lifespan 启动与停止
  scripts/backup.py      SQLite 在线备份 + 保留策略
  scripts/migrate_p2.py  幂等 DDL：为既有 accounts 补邮箱验证列（无 Alembic，create_all 不加列；升级 P2 后执行一次）
  tests/                 HTTP 接缝测试、fakes.py 测试替身
frontend/                Vue 3 + Vite + TypeScript + Tailwind + Pinia + vue-router
  src/lib/api.ts         统一 fetch 封装（错误解析、401 刷新一次）
  src/lib/sse.ts         fetch 版 SSE 解析器 + 断线重连（带 Last-Event-ID）
  src/layouts/           共享布局；components/AppFooter.vue
  e2e/                   Playwright 黄金路径（默认跳过）
docker-compose.yml       api + web（nginx 托管 SPA 并代理 /api、/health）
```

## 本地开发

### 后端

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

- 健康检查：`curl http://127.0.0.1:8000/health`（200 正常，503 降级）
- API 文档：`http://127.0.0.1:8000/api/docs`
- 配置来自 `APP_*` 环境变量或 `backend/.env`（参考根目录 `.env.example`）。
- 关键默认值：每日 AI 预算 `APP_DAILY_BUDGET_USD=10`（按北京时间自然日，超预算后新的分析返回 429 `budget_exhausted`，已有结果仍可查看），每次摘要调用估算 `APP_ANALYSIS_COST_PER_CALL_USD=0.01`，每个账号每日免费分析 `APP_ANALYSIS_DAILY_QUOTA=3`。
- 限流（内存滑窗，超限返回 429 `too_many_requests` 并带 `Retry-After`）：解析 10 次/分/IP、创建下载 3 次/分/IP（叠加 #6 的每小时与并发上限）、登录 10 次/15 分/IP、注册 5 次/小时/IP、创建分析 1 次/10 秒/账号、验证邮件重发 3 次/小时/账号；对应 `APP_RATE_LIMIT_*` 可调。
- 安全边界：仅接受 Bilibili/YouTube 的 http(s) 链接（抖音需 `APP_DOUYIN_ENABLED=true`，关闭时返回 422 `platform_not_enabled`「抖音暂未开放」），拒绝凭据、非标准端口、localhost、内网/回环/链路本地/云元数据地址及解析到私有地址的主机；Markdown 与思维导图渲染前会清理脚本、事件处理器和 `javascript:` 链接。

### 前端

```bash
cd frontend
npm install
npm run dev        # http://127.0.0.1:5173，/api 与 /health 代理到 127.0.0.1:8000
```

可用 `VITE_PROXY_TARGET` 覆盖后端地址。

## 测试与构建

```bash
# 后端：进程内 ASGI 接缝，不启动服务器、不访问网络
cd backend && uv run pytest -q
cd backend && uv run ruff check .

# 前端：纯逻辑单元测试（SSE 解析/重连）+ 类型检查 + 生产构建
cd frontend && npm run test:unit -- --run
cd frontend && npm run build
```

Playwright 黄金路径默认跳过。设置 `PLAYWRIGHT_E2E=1` 时它会用假适配器自动启动后端与前端 dev server，
跑通两条链路（`frontend/e2e/`）：

1. `golden-path.spec.ts`：访客解析 → 导出字幕 → 服务端下载 → 注册 → 登录 → 验证邮箱 → 流式 Analysis 与思维导图。
2. `golden-path-subscription.spec.ts`：免费 Quota 用尽（第 4 次 429 与升级 CTA）→ 定价页 → 假网关托管结账
   → 注入支付成功 webhook → 个人中心显示 VIP 与不限次 Quota → Analysis 不再受限；同一开关下另测
   抖音地址的解析与下载，以及 `/verify-email` 验证页。

假邮件收件箱通过 `GET /api/demo/inbox`（仅 `APP_FAKE_ADAPTERS=1` 暴露）交回一次性验证链接，
支付成功用与产品同一个 `POST /api/billing/webhook`（以 `whsec_demo` 签名）注入，因此不开任何真实端口。

```bash
cd frontend
npx playwright install chromium          # 首次
PLAYWRIGHT_E2E=1 npx playwright test
```

## Docker Compose

```bash
cp .env.example .env      # 至少修改 APP_SECRET_KEY
docker compose config     # 校验配置
docker compose up --build # 前端 http://127.0.0.1:8080 ，健康检查 /health
```

`web` 由 nginx 提供 SPA 静态文件，并把 `/api/` 与 `/health` 反向代理到 `api:8000`（SSE 已关闭缓冲）。SQLite 在 `app-data` 卷的 `/data`，下载的媒体文件在 `media` 卷的 `/media`，备份在 `backups` 卷的 `/backups`。`api`、`backup`、`web` 均为 `restart: unless-stopped`，时区 `Asia/Shanghai`。

### 生产部署清单（P2 新增项）

`APP_ENV=production` 时启动会执行 `Settings.validate_production_secrets()`（P2-10）：缺任何一项都**拒绝启动**并在日志中点名缺失变量，绝不带半套配置上线。开发/测试环境不受影响（缺 Stripe/SMTP 时相关请求返回可理解的 503；`APP_FAKE_ADAPTERS=1` 用假网关与内存收件箱，零配置）。

- 必填（缺一即拒启）：`APP_SECRET_KEY`（强随机值）、`APP_STRIPE_API_KEY`、`APP_STRIPE_WEBHOOK_SECRET`、`APP_STRIPE_PRICE_ID`、`APP_SMTP_HOST`、`APP_SMTP_FROM`（`APP_SMTP_USERNAME/PASSWORD` 可留空走免认证中继）。
- 开关与订阅：`APP_DOUYIN_ENABLED`（默认 `false`，灰度/回滚见 `docs/ops/douyin-gray-release.md`）；`APP_SUBSCRIPTION_MONTHLY_USD=4.99` 仅为前端标价，**实际扣款以支付方（Stripe）配置为准**，调价时两处同步。
- 邮件验证：`APP_EMAIL_VERIFICATION_TOKEN_TTL_HOURS=24`；`APP_FRONTEND_BASE_URL` 必须指向用户浏览器实际访问的地址（compose 默认 `http://localhost:8080`，正式域名部署时改为公网 origin，否则验证邮件里的链接打不开）。
- 限流：`APP_RATE_LIMIT_VERIFICATION_REQUEST_PER_HOUR=3`（发信防滥用）。
- CORS：compose 栈是同源部署（nginx 代理 `/api`），`APP_CORS_ORIGINS` 保持 `[]`；仅当浏览器直连 API 时才配置，本地 Vite 开发放行 5173 的方式见 `.env.example` 注释。
- 从 P1 部署升级：先 `docker compose up -d api`，再执行一次 `docker compose exec api python -m scripts.migrate_p2`（无 Alembic，`create_all` 不给既有表加列；新库无需执行）。

### 生产部署清单（P3 新增项：静态站点与站点地址）

前端在构建期把公开营销页与文章预渲染成静态 HTML，并生成 `sitemap.xml`、`robots.txt`、`llms.txt`；私有路由使用无索引外壳 `app.html`，未知路径返回真正的 404 页面 `404.html`。

- **`SITE_ORIGIN`**：写入 canonical、OG 与 sitemap 的公网 origin，经 compose 传入前端构建参数 `VITE_SITE_ORIGIN`（compose 默认 `http://localhost:8080`）。它必须是**裸 origin**：绝对 http(s) 地址，不带用户名密码、路径、查询串、hash 或尾斜杠；格式非法时 `npm run build` / `docker compose build web` 直接失败并打印变量名与非法值。本地 Vite 开发未设置时回退到 `http://localhost:5173` 并警告。
- **生产必须设置为公网 https origin，并与 `APP_FRONTEND_BASE_URL` 完全一致**，否则 canonical/OG 与实际访问地址分裂，验证邮件里的链接也会指向另一个 host。回环 origin（localhost/127.0.0.1/::1）会输出 `Disallow: /` 并在构建日志中警告，不能用来验证收录。
- nginx 行为：`/features`、`/guide`、`/faq`、`/pricing`、`/terms`、`/articles`、`/articles/<slug>` 按「精确文件 → `.html` → 目录 → 404」查找，直接 200 且不做尾斜杠跳转；`/login`、`/account`、`/analyses`、`/analyses/:id`、`/verify-email` 回落 `app.html`（查询串保留）并带 `X-Robots-Tag: noindex, nofollow`；未知路径返回 HTTP 404 + `404.html`，不再回落首页；HTML 为 `Cache-Control: no-cache`，`/assets/` 为 `immutable`，发现层文件缓存 1 小时；gzip 覆盖 HTML、CSS、JS、JSON、XML 与 `text/plain`。
- 构建与启动：`SITE_ORIGIN=https://example.com docker compose build web`，随后 `docker compose up -d`。非法值可这样确认会失败：`SITE_ORIGIN=https://example.com/path docker compose build web`。
- 部署后用下面的命令验证（`BASE` 换成实际访问地址；公开页 200、未知路径 404、私有 noindex、`/health`、发现层与缓存头）：

```bash
BASE=http://localhost:8080

# 公开静态页：均应为 200，且不出现 301/308 尾斜杠跳转
for p in / /features /guide /faq /pricing /terms /articles /articles/bilibili-subtitle-download; do
  curl -sS -o /dev/null -w "%{http_code} $p\n" "$BASE$p"
done
# canonical 与实际地址一致
curl -sS "$BASE/features" | grep -o '<link rel="canonical"[^>]*>'

# 未知路径：HTTP 404 + 404.html 正文 + noindex 头
curl -sS -i "$BASE/definitely-not-a-page" | grep -E '^HTTP/|^X-Robots-Tag'
curl -sS "$BASE/definitely-not-a-page" | grep -o '页面不存在'

# 私有路由：app.html 外壳 + noindex meta，且 X-Robots-Tag 为 noindex, nofollow
curl -sS -i "$BASE/login?next=/account" | grep -E '^HTTP/|^X-Robots-Tag|^Cache-Control'
curl -sS "$BASE/login?next=/account" | grep -o '<meta name="robots"[^>]*>'
for p in /account /analyses /analyses/00000000-0000-0000-0000-000000000000 /verify-email; do
  curl -sS -o /dev/null -w "%{http_code} %{redirect_url} $p\n" "$BASE$p"
done

# 健康检查（经 nginx 代理到 api）
curl -sS -i "$BASE/health" | head -n 5

# 发现层
curl -sS "$BASE/robots.txt" | head -n 12
curl -sS "$BASE/sitemap.xml" | head -n 5
curl -sS "$BASE/llms.txt" | head -n 5

# 缓存：HTML no-cache，带哈希资源 1 年 immutable
curl -sS -I "$BASE/" | grep -i cache-control
ASSET=$(curl -sS "$BASE/" | grep -o '/assets/[^"]*\.js' | head -n 1)
curl -sS -I "$BASE$ASSET" | grep -i -E 'cache-control|expires'

# gzip：HTML、CSS/JS、XML 与纯文本（llms.txt/robots.txt）
curl -sS -H 'Accept-Encoding: gzip' -I "$BASE/llms.txt" | grep -i content-encoding
curl -sS -H 'Accept-Encoding: gzip' -I "$BASE/sitemap.xml" | grep -i content-encoding
```


全部变量的名称与默认值以根目录 `.env.example` 为准，`docker-compose.yml` 的 `api.environment` 与其逐项同步。

## 运维

### 日志与 request_id

- 日志以单行 JSON 输出到 stdout：`timestamp`、`level`、`logger`、`message`、`request_id`，请求期间还包括 `method`、`path`、`status`、`duration_ms`，错误日志带 `error_code`。
- 每个请求都会获得 `X-Request-ID`（合法的入站值会被沿用），响应头与错误响应体 `error.request_id` 都返回该值。
- 定位一次失败请求：`docker compose logs api | grep <request_id>`，可看到 `request_completed` 与对应的 `app_error` / `unhandled_exception`。
- Sentry 可选：后端设置 `SENTRY_DSN` 后自动初始化（事件带 `request_id` tag），`SENTRY_TRACES_SAMPLE_RATE` 控制性能采样率；前端在构建时读取 `VITE_SENTRY_DSN`。任一为空则完全禁用，不发送任何数据。

### 健康检查

`GET /health` 返回 200（`status: "ok"`）或 503（`status: "degraded"`），`checks` 包含：

- `database`：`PRAGMA quick_check` 可读、临时写入成功、`journal_mode`（应为 `wal`）。
- `disk`：媒体目录（`APP_MEDIA_ROOT`，默认 `<APP_DATA_DIR>/media`）可创建并写入探针文件。
- `process`：进程存活与 PID。

`version` 为后端版本。Docker healthcheck 复用该接口，失败时容器会被标记 unhealthy 并按重启策略自动重启。

### 备份与恢复

`backup` 服务启动后立即执行一次，之后每 24 小时执行 `python -m scripts.backup`；使用 SQLite 在线备份 API，写入 `backups` 卷的 `app-YYYYmmdd-HHMMSS.db`，每个备份做 `PRAGMA integrity_check`，默认保留最近 7 份（`BACKUP_RETENTION`）。

```bash
# 手动触发一次
docker compose exec backup python -m scripts.backup
# 查看
docker compose exec backup ls -lh /backups
# 拷出宿主机
docker compose cp backup:/backups/app-20261023-020000.db ./app-backup.db
```

恢复（会丢失备份时间点之后的数据）：

```bash
docker compose stop api backup
docker compose cp ./app-backup.db api:/data/app.db
docker compose run --rm --entrypoint sh api -c 'rm -f /data/app.db-wal /data/app.db-shm'
docker compose start api backup
```

本地没有 Docker 时可直接运行：`cd backend && APP_DATABASE_URL=... BACKUP_DIR=... uv run python -m scripts.backup`。

## 约定（后续 ticket 必须遵守）

- **路由**：所有业务路由在 `/api` 下，只有 `/health` 例外。新增接口写进所属模块的 `router.py`；`main.py` 已 include 全部模块，不需要再改。
- **模型**：各模块的 `models.py`，在 `models_registry.py` 中 import 后由 `init_db()` 建表。
- **错误**：业务失败抛 `AppError(status, code, message, details)`，响应恒为
  `{"error": {"code", "message", "details", "request_id"}}`；未处理异常返回 `internal_error` 且不泄露堆栈。
  stable code 见 `app/errors.py::ErrorCode`。
- **适配器**：业务模块只依赖 `app/ports.py` 的 Protocol；测试用 `tests/fakes.py` 的假实现，经 `create_app(settings, adapters)` 注入。
  例外：bcrypt、PyJWT、sentry_sdk、yt-dlp 客户端等**基础设施库**可以直接 import 使用——端口只覆盖需要按环境替换的跨进程副作用（平台解析、媒体存储、AI 调用、时钟、预算账本），把哈希或签名也做成端口只会增加一层无实现的转发。
- **后台任务**：`DownloadManager` 与 `AnalysisManager` 只由 `main.py` 的 lifespan 创建并 `start()`，路由一律通过 `app.state.download_manager` / `app.state.analysis_manager` 取用。不要在路由里惰性自建实例：那样会绕过重启恢复与配额释放。
- **测试**：`tests/conftest.py` 的 `client` fixture 使用临时 SQLite + `httpx.ASGITransport` + `asgi-lifespan`；不得访问真实网络或外部 SDK。需要自定义 settings/adapters 时同样必须包 `LifespanManager`，否则拿不到 manager。
- **时间**：`Clock.today()` 是 Asia/Shanghai 日历日（Quota）；`now()` 是 UTC 感知时间。时区换算只走 `app/timeutil.py`（`as_utc` / `required_utc` / `shanghai_day` / `next_shanghai_midnight`），不要在模块里再建 `ZoneInfo` 或复制次日零点算法。
- **文案**：同一条件在多个模块出现的用户可见文案集中在 `app/messages.py`，模块独有的文案留在模块内；用词遵守 `GLOSSARY.md`（Video 叫「视频」，提交的地址叫「页面地址」，不叫「视频链接」）。

## 尚未实现

- ADR-0005 的营销页构建期预渲染、sitemap/robots/`llms.txt` 与无索引 `app.html`、`404.html` 已在 P3 落地；私有页的 `noindex` 现在是静态外壳 meta、响应头与客户端路由三重声明。
- 没有 CI 流水线：`backend` 的 pytest/ruff 与 `frontend` 的 vitest/build/Playwright 需按上面的命令手动执行。
