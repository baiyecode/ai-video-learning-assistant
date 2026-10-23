# AI 视频学习助手

解析公开视频、下载文件、导出字幕，并基于字幕生成简体中文摘要与思维导图的单上下文产品。

当前状态：**Ticket #2 工程骨架**。前后端可运行、测试接缝就绪；业务功能由后续 ticket 逐步填充。

## 目录结构

```
backend/                 FastAPI 模块化单体（Python 3.12+，uv 管理）
  app/
    main.py              create_app(settings, adapters) 组合根 + ASGI 入口
    config.py            pydantic-settings（APP_ 环境变量前缀）
    db.py                SQLAlchemy 2 async + SQLite WAL、init_db()
    errors.py            AppError + 统一错误响应 + 异常处理器
    logging_setup.py     JSON 日志 + request_id 中间件/contextvar
    ports.py             VideoSource / MediaStore / Summarizer / Clock / BudgetLedger
    container.py         Adapters 容器与 build_production_adapters()
    deps.py              get_settings / get_adapters / get_session / get_clock
    adapters/            生产适配器（未实现的在调用时抛 NotImplementedError）
    modules/             catalog / identity / media / analysis / ops 的空路由器
  tests/                 HTTP 接缝测试、fakes.py 测试替身
frontend/                Vue 3 + Vite + TypeScript + Tailwind + Pinia + vue-router
  src/lib/api.ts         统一 fetch 封装（错误解析、401 刷新一次）
  src/lib/sse.ts         fetch 版 SSE 解析器 + 断线重连（带 Last-Event-ID）
  src/layouts/           共享布局；components/AppFooter.vue
  e2e/                   Playwright 黄金路径骨架（默认跳过）
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

Playwright 黄金路径默认跳过（需要浏览器与两个 dev server，且后续 ticket 才把步骤补全）：

```bash
cd frontend
npx playwright install chromium          # 首次
PLAYWRIGHT_E2E=1 npx playwright test     # 后端 + 前端 dev server 运行中时
```

## Docker Compose

```bash
cp .env.example .env      # 至少修改 APP_SECRET_KEY
docker compose config     # 校验配置
docker compose up --build # 前端 http://127.0.0.1:8080 ，健康检查 /health
```

`web` 由 nginx 提供 SPA 静态文件，并把 `/api/` 与 `/health` 反向代理到 `api:8000`（SSE 已关闭缓冲）。SQLite 与媒体文件放在 `app-data` 卷的 `/data`。

## 约定（后续 ticket 必须遵守）

- **路由**：所有业务路由在 `/api` 下，只有 `/health` 例外。新增接口写进所属模块的 `router.py`；`main.py` 已 include 全部模块，不需要再改。
- **模型**：各模块的 `models.py`，在 `models_registry.py` 中 import 后由 `init_db()` 建表。
- **错误**：业务失败抛 `AppError(status, code, message, details)`，响应恒为
  `{"error": {"code", "message", "details", "request_id"}}`；未处理异常返回 `internal_error` 且不泄露堆栈。
  stable code 见 `app/errors.py::ErrorCode`。
- **适配器**：业务模块只依赖 `app/ports.py` 的 Protocol；测试用 `tests/fakes.py` 的假实现，经 `create_app(settings, adapters)` 注入。
- **测试**：`tests/conftest.py` 的 `client` fixture 使用临时 SQLite + `httpx.ASGITransport` + `asgi-lifespan`；不得访问真实网络或外部 SDK。
- **时间**：`Clock.today()` 是 Asia/Shanghai 日历日（Quota）；`now()` 是 UTC 感知时间。

## 已知占位

- `build_production_adapters()` 返回的 yt-dlp / 文件系统 / DeepSeek / 预算适配器在**调用时**抛 `NotImplementedError`（各自 ticket 实现），不影响导入与启动。
- 前端 `stores/auth.ts` 的会话恢复与登录页由 ticket #7 完成；`lib/api.ts` 已提供 401 刷新钩子。
- `/terms` 为占位页面，正式条款与举报入口由 ticket #14 完成。
