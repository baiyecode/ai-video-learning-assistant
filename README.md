# AI 视频学习助手

解析公开视频、下载文件、导出字幕，并基于字幕生成简体中文摘要与思维导图的单上下文产品。

当前状态：**P1 已完成**（GitHub issues #2–#14）。访客可解析、导出字幕、服务端下载；账号可流式生成摘要与思维导图，并受每日 Quota、限流与 AI 预算约束。P2（VIP Membership 等）尚未开始。

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
    ports.py             VideoSource / MediaStore / Summarizer / Clock / BudgetLedger / EmailSender
    container.py         Adapters 容器与 build_production_adapters()
    deps.py              get_settings / get_adapters / get_session / get_clock
    adapters/            生产适配器：yt-dlp 解析、文件系统媒体、DeepSeek 摘要、系统时钟、SQLite 预算账本、SMTP 发信
    modules/             catalog（Video/Subtitle）、identity（Account/Session/邮箱验证）、media（Download）、analysis（Analysis/Quota）、ops（/health、举报、Sentry）
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
- 限流（内存滑窗，超限返回 429 `too_many_requests` 并带 `Retry-After`）：解析 10 次/分/IP、创建下载 3 次/分/IP（叠加 #6 的每小时与并发上限）、登录 10 次/15 分/IP、注册 5 次/小时/IP、创建分析 1 次/10 秒/账号；对应 `APP_RATE_LIMIT_*` 可调。
- 安全边界：仅接受 Bilibili/YouTube 的 http(s) 链接，拒绝凭据、非标准端口、localhost、内网/回环/链路本地/云元数据地址及解析到私有地址的主机；Markdown 与思维导图渲染前会清理脚本、事件处理器和 `javascript:` 链接。

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
完整跑通「访客解析 → 导出字幕 → 服务端下载 → 注册 → 流式 Analysis 与思维导图」：

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

- VIP Membership（订阅后 Analysis 不受 Quota 限制）属于 P2，`Quota` 目前对所有 Account 一视同仁。
- ADR-0005 的营销页构建期预渲染与 sitemap 属于 P3；当前只在路由层为私有页面下发 `noindex`（见 `src/router/index.ts`）。
- 没有 CI 流水线：`backend` 的 pytest/ruff 与 `frontend` 的 vitest/build/Playwright 需按上面的命令手动执行。
