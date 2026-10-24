# Video 全局共享，Analysis 归属 Account

同一个 Video 的元数据与 Subtitle 在全站只存一份并按 Platform + 平台内 ID 去重；Analysis 则按 Account 独立记录，其他用户不可见。这样避免重复解析与重复的 AI 调用成本，代价是共享数据变更会影响所有引用方，并且所有 Analysis 查询必须强制携带 Account 过滤。

**考虑过的替代方案**：每个 Account 独立解析与存储（隐私边界更硬，但成本随用户数线性增长）。

**Consequences**：Analysis 固化其生成时使用的 Subtitle 版本，之后 Video 的 Subtitle 更新不回溯重写已有 Analysis；重新分析会产生新的 Analysis 并消耗 Quota。
