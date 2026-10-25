# AI 万能视频下载总结器

一个把公开视频解析、下载与 AI 理解结合起来的单上下文产品：用户提交视频的页面地址，获得可下载文件、字幕与基于字幕的 AI 分析。

## Language

**Video**:
一个可被解析的媒体作品，由来源平台与平台内唯一 ID 确定身份。
_Avoid_: 视频链接, URL, 资源

**Platform**:
Video 的来源站点（如 B 站、YouTube、抖音），提供解析、字幕与清晰度信息。
_Avoid_: 网站, 渠道

**Subtitle**:
Platform 提供的文本轨道，可能为人工或自动生成；是 Analysis 的唯一文本依据。
_Avoid_: 字幕文件（指导出产物时）, 转写文本

**Analysis**:
针对单个 Video 的一次「字幕提取 + 摘要 + 思维导图」执行，是配额与计费计量的单位。
_Avoid_: AI 总结次数, 调用次数, 生成

**Quota**:
一个 Account 在一个 Asia/Shanghai 自然日内可执行的 Analysis 上限；失败或查看既有结果不消耗 Quota。
_Avoid_: 次数, 额度

**Visitor**:
未登录的使用者，可以解析与下载 Video，但不能发起 Analysis。
_Avoid_: 匿名用户, 游客, guest

**VIP Membership**:
由有效订阅赋予的账户权益，Analysis 不受 Quota 限制。
_Avoid_: 永久会员, 买断, is_vip

**Download**:
将一个 Video 的选定清晰度与格式由服务端转存并交付给用户的行为。
_Avoid_: 直链, 缓存文件

**Account**:
注册用户身份，拥有 Quota、Analysis 记录与 VIP Membership。
_Avoid_: 用户（在需要区分访客时）, 会员

**Session**:
由 refresh token 代表的、可被主动吊销的登录状态。
_Avoid_: token, 登录凭证

**Article**:
构建期从 `frontend/content/articles/*.md` 发布的一篇公开内容页，URL 由文件名 slug 决定，frontmatter 是标题、描述与日期的唯一来源。
_Avoid_: 博客文章（指代发布单元时）, post, 内容页

**Marketing Page**:
无需登录即可访问、可被搜索引擎索引的静态预渲染页面。
_Avoid_: 落地页, landing page, 官网首页（泛指时）
