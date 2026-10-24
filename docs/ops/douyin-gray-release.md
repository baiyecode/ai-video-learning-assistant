# 抖音灰度开关与回滚手册（P2-10 运维文档）

抖音解析（ticket #23 / P2-07）随代码一起发布，但**默认关闭**：打开与收回只改一个
环境变量，不改代码、不重新构建镜像。本文说明灰度步骤、一键回滚与出问题时应该盯的
错误码和日志字段。

## 开关是什么

- 变量：`APP_DOUYIN_ENABLED`（对应 `backend/app/config.py` 的 `douyin_enabled`，默认 `false`）。
- 关闭时：抖音页面地址与 `v.douyin.com` 短链在 URL 校验层被拒绝，返回
  `422 platform_not_enabled`，用户文案为「抖音暂未开放」（`app/messages.py`），
  与「不受支持的链接」（`unsupported_url`）明确区分。
- 打开时：抖音进入受支持 Platform 列表，走 yt-dlp 的抖音专用解析分支；
  解析产物为带水印的单清晰度 Download（ADR-0003 的服务端代理模型不变）。
- B 站 / YouTube 的行为与该开关无关，风险只隔离在抖音这一个 Platform 上。

## 灰度打开（docker compose 部署）

1. 在根目录 `.env` 中设置 `APP_DOUYIN_ENABLED=true`（`docker-compose.yml` 已把该变量
   透传给 `api` 服务，默认值是 `false`）。
2. 重建并重启 api 容器使新环境生效：

   ```bash
   docker compose up -d api
   ```

   （仅改环境变量时 compose 会检测到配置变化并重建容器，这一步就是「重启生效」；
   无需 `--build`。）
3. 冒烟验证：`POST /api/videos/resolve` 提交一个抖音页面地址，应返回解析出的 Video
   而不是 `platform_not_enabled`；或先 `GET /health` 确认服务健康。

本地 uvicorn 开发同理：改 `backend/.env`（或导出环境变量）后重启进程。

## 一键回滚

1. 把 `.env` 中的 `APP_DOUYIN_ENABLED` 改回 `false`（或删除该行，默认即关闭）。
2. `docker compose up -d api` 重建生效。

回滚后的语义：新的抖音地址立刻恢复被 `422 platform_not_enabled` 拒绝；已经解析入库的
抖音 Video、Subtitle 与既有 Analysis 记录仍可查看（数据不随开关删除）。如需清理存量
抖音数据，属于独立运维操作，不在开关语义之内。

## 出问题时盯什么

### 错误码（统一信封 `error.code`，响应头与 `error.request_id` 可关联日志）

| 错误码 | 状态 | 含义与处置 |
|---|---|---|
| `platform_not_enabled` | 422 | 开关关闭时的抖音地址拒绝，属预期行为，不是故障 |
| `unsupported_url` | 422 | 非白名单 host / 非法形态；若大量出现，检查用户粘贴的分享文案 |
| `video_unavailable` | 404 | 抖音侧视频不存在、已删除或私密 |
| `resolve_failed` | 502 | yt-dlp 抖音 extractor 失败（页面结构变更的典型信号）；失败率异常即回滚 |
| `subtitles_unavailable` | 409 | 无字幕的抖音 Video 无法 Analysis（P2 不做 ASR），属预期 |

### 日志字段（stdout 单行 JSON，`docker compose logs api`）

- 每个请求都有 `request_id`、`method`、`path`、`status`、`duration_ms`；
  错误行带 `error_code`。定位一次失败：
  `docker compose logs api | grep <request_id>`。
- 抖音灰度决策建议按小时聚合 `path == "/api/videos/resolve"` 的 `status` 分布，
  502/`resolve_failed` 占比明显上升就回滚开关。
- 计费侧结构化日志（与 Stripe 事件对账用）：
  - `event` 取值 `billing_membership_changed` / `billing_event_duplicate_ignored` /
    `billing_event_stale_ignored`，均带 Stripe 的 `event_id`；
  - `BillingEvent` 表的唯一列 `event_id` 是幂等门：重复投递与乱序事件都可在
    `billing_events` 表中审计到（`applied` 列区分是否改变了状态）；
  - Stripe SDK 失败记为 `stripe_checkout_failed` / `stripe_portal_failed`。
- 邮件侧：验证邮件重发限流命中为 `429 too_many_requests`（scope
  `auth.verification.request`）；开发环境未配 SMTP 时是 503「邮件服务未配置」。

## 部署启动校验（P2-10）

`APP_ENV=production` 时应用在绑定端口前执行 `Settings.validate_production_secrets()`，
缺以下任何一项都会**拒绝启动**，`docker compose logs api` 首屏的 RuntimeError 直接点名
缺失变量（容器会反复重启，直到配置补齐——这是有意为之，绝不带半套配置上线）：

- `APP_SECRET_KEY` / `APP_JWT_SECRET`：弱值或开发默认值；
- `APP_STRIPE_API_KEY`、`APP_STRIPE_WEBHOOK_SECRET`、`APP_STRIPE_PRICE_ID`：三项缺一即拒；
- `APP_SMTP_HOST`、`APP_SMTP_FROM`：邮件发送最小配置（username/password 可缺省）；
- `APP_FAKE_ADAPTERS=true`：测试专用开关，生产永远拒绝。

开发/测试环境不受影响：Stripe 与 SMTP 留空时对应请求返回可理解的 503，
`APP_FAKE_ADAPTERS=1`（Playwright 黄金路径）使用假网关与内存收件箱。

从 P1 部署升级时还需执行一次幂等迁移脚本为 `accounts` 补邮箱验证列：

```bash
docker compose exec api python -m scripts.migrate_p2
```

## 相关清单

- 全量环境变量：根目录 `.env.example` 与 `docker-compose.yml` 的 `api.environment`
  （两处与 `backend/app/config.py` 同步，见 ticket P2-10）。
- 定价展示值 `APP_SUBSCRIPTION_MONTHLY_USD` 仅为 UI 标价，实际扣款
  **以支付方（Stripe）配置为准**；调价时同步 Stripe Price 与该值。
