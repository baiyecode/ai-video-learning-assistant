# 采用可吊销的混合 JWT Session

认证使用 15 分钟有效的无状态 access token（存于内存）加 7 天有效的 refresh token（HttpOnly、Secure、SameSite=Lax Cookie），refresh token 在数据库中只存哈希并支持轮换，登出或封禁时吊销当前 Session。这偏离了“纯无状态 JWT”的原始描述，因为纯无状态 token 无法主动注销，账户被盗后只能等待过期。

**考虑过的替代方案**：纯无状态 JWT（实现最简单，但无法注销）；传统服务端 Session Cookie（每个请求都要查库）。

**Consequences**：刷新路径需要数据库查询，普通 API 请求不需要；数据库中必须有可吊销的 Session 记录。
