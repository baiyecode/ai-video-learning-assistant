---
title: 长视频的 AI 摘要与思维导图：分块归并、Quota 与限制
description: 长视频的 AI 摘要与思维导图怎么做：Analysis 读取 Subtitle 分块归并，没有字幕则无法生成。本文说明免费 Account 每日 {{DAILY_FREE_QUOTA}} 次、VIP {{MONTHLY_PRICE_USD}}不限次、失败不消耗 Quota 与结果仅本人可见。
published: 2026-10-23
updated: 2026-10-23
tags: [AI 摘要, 思维导图, Analysis]
---

长视频的 Analysis 会以 视频 自带的 Subtitle 为唯一文本依据：先按时间轴分块生成段落摘要，再把各块归并成一份全局摘要与思维导图。没有 Subtitle 的 视频 不能发起 Analysis，因为本工具不做 ASR。免费 Account 每个 Asia/Shanghai 自然日 {{DAILY_FREE_QUOTA}} 次 Analysis，VIP Membership 为 {{MONTHLY_PRICE_USD}}、Analysis 不限次，失败不消耗 Quota。

## 长视频的摘要与思维导图怎么生成

Analysis 处理的是一条 视频 的全部 Subtitle，而不是先让你自己挑片段。整体思路是「分块、块内摘要、归并、结构化」：

1. 判断能否分析：读取时长、清晰度与 Subtitle，并确认这条 视频 不是 DRM、不是会员专属。
2. 分块：按时间轴把 Subtitle 切成若干连续片段，尽量落在章节或话题切换处，避免一句话被切断。
3. 块内摘要：每个片段提炼要点，保留关键数字、结论与例子，丢掉口头语和重复表述。
4. 归并：把各块要点按主题合并，补上前后因果关系，形成一条从头到尾的叙述线。
5. 结构化：一级分支对应章节或大主题，二级分支写要点，三级分支放例子与数字，最终得到思维导图。
6. 保存：结果写入账号里的 Analysis 记录，之后可以随时回看，不需要重新生成。

| 阶段 | 输入 | 输出 |
| --- | --- | --- |
| 分块 | 完整 Subtitle | 按时间轴排列的连续片段 |
| 块内摘要 | 单个片段 | 要点列表 |
| 归并 | 各块要点 | 一份全局摘要 |
| 结构化 | 全局摘要 | 可折叠的思维导图 |

分块归并解决的是「一次读不完」的问题：两小时的讲座如果直接压成一段摘要，细节会被抹平；先保块内要点再归并，才能既保留局部结论，又有全局结构。

## 为什么没有 Subtitle 就不能做 Analysis

Subtitle 是 Analysis 的唯一文本依据。本工具不做 ASR，不会从音轨生成文字，因此：

- 解析结果没有 Subtitle 时，页面会禁用发起入口，并提示这条 视频 没有可用字幕。
- 即使强行请求，服务端也会以 409 拒绝，错误代码为 `subtitles_unavailable`。
- DRM 与会员专属内容同样不进入分析流程，这类 视频 连解析都会被拒绝。

YouTube 的自动生成字幕也算 Subtitle，可以分析，但摘要质量会受字幕准确度限制；B 站的人工字幕通常更可靠。两种字幕的差异见 [B 站字幕下载指南](/articles/bilibili-subtitle-download)。

## 2 小时 / 2 GB 是下载上限，不是 Analysis 的计量方式

很容易混淆的一条边界：单个 视频 的 Download 上限是 2 小时、2 GB，超出范围会直接拒绝下载；下载链接 15 分钟内有效，服务端文件最多保留 1 小时。这些是 Download 的限制。

Analysis 的计量单位是「一次新的 Analysis」，按次消耗 Quota，与视频文件大小无关。一个 1.5 小时的讲座和一个 10 分钟的讲解，只要各自成功生成一次，消耗的都是 1 次 Quota。具体能力说明见 [功能页](/features)。

## Quota 与 VIP Membership 怎么算

| 情形 | 是否消耗 Quota |
| --- | --- |
| 发起一次新的 Analysis 并成功 | 消耗 1 次 |
| Analysis 生成失败 | 不消耗，配额退回 |
| 查看已有或正在进行的 Analysis | 不消耗 |
| 解析 视频、导出 Subtitle、Download | 不消耗 |

- 免费 Account：每个 Asia/Shanghai 自然日 {{DAILY_FREE_QUOTA}} 次 Analysis，跨日重置。
- VIP Membership：{{MONTHLY_PRICE_USD}}，Analysis 不限次；在个人中心打开 Stripe 客户门户即可取消，取消后当前计费周期结束前仍享有权益。
- 邮箱验证：未验证邮箱时发起 Analysis 会被拒绝（错误代码 `email_not_verified`）；验证邮箱不影响解析、Download 与导出 Subtitle。

价格与扣款以结账页为准，规则说明见 [价格页](/pricing)。

## 分析结果谁会看到

Analysis 记录绑定在你的 Account 上，只有登录后的本人可以查看。我们不生成公开的 Analysis 页面，结果不会进入搜索结果，也不会出现在文章或分享链接里。需要把结论发给别人时，建议分享你自己整理的笔记，而不是账号里的记录。相关隐私与使用边界见 [使用条款](/terms)。

## 怎么用摘要和思维导图复盘

- 先只看思维导图的一级分支，回忆每个分支讲了什么，再展开二级分支核对。
- 讲不清的分支回到 Subtitle 原文定位，不要只依赖摘要里的措辞。
- 把摘要改写成问题清单，下次看同主题 视频 前先自测一遍。
- 长视频建议每 20 到 30 分钟暂停一次，用块摘要核对当前理解，再继续往下看。

如果你更习惯先做手写笔记再生成摘要，可以接着读[用 YouTube 字幕做学习笔记](/articles/youtube-study-notes)。

## 常见问题

### 有自动字幕也能 Analysis 吗？

可以。自动生成字幕同样是 Subtitle，但摘要质量受识别准确度影响，关键结论建议回到原文核对。

### 生成失败会扣 Quota 吗？

不会。失败时配额退回，可以直接重试；只有成功生成的 Analysis 才计入当天的 Quota。

### VIP 取消后立刻失效吗？

不会。取消后当前计费周期结束前仍然有效，之后回到免费 Account 的每日 {{DAILY_FREE_QUOTA}} 次。

### Analysis 结果能公开分享吗？

不能。记录仅本人可见，产品不提供公开 Analysis 页面。
