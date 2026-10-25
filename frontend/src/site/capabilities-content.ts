/**
 * The six product capabilities are the single source for both the home page
 * cards and the `/features` sections. Titles and claims live here so the two
 * Marketing Pages cannot drift apart; the home page renders ``summary`` and the
 * features page expands the same entry into problem/usage/limit.
 */
export interface Capability {
  title: string;
  /** One-paragraph summary shown in the home page's capability grid. */
  summary: string;
  problem: string;
  usage: string;
  limit: string;
}

export const capabilities: readonly Capability[] = [
  {
    title: "解析",
    summary: "先确认一个页面地址能否下载、导出字幕或生成 Analysis，而不是反复试错。",
    problem: "先确认一个页面地址能否下载或分析，而不是反复试错。",
    usage:
      "粘贴 B 站或 YouTube 的页面地址，点击「解析视频」。抖音仅在部署开启灰度时可用；播放列表、直播、DRM 与会员专属内容不在支持范围内。",
    limit: "单个视频最长 2 小时、最大 2 GB。",
  },
  {
    title: "Download",
    summary: "选择清晰度与格式，由服务端转存并交付；链接 15 分钟内有效，文件最多保留 1 小时。",
    problem: "把公开视频保存到本地，用于个人备份或已获授权的内容。",
    usage:
      "解析后选择清晰度与格式，再点击保存。下载链接 15 分钟内有效，服务端文件最多保留 1 小时，过期后重新解析即可。",
    limit: "访客每小时最多发起 5 次 Download，请按需使用。",
  },
  {
    title: "Subtitle 导出",
    summary: "把已有字幕导出为 SRT、VTT 或 TXT，并标出人工字幕与平台自动生成字幕。",
    problem: "把已有字幕整理成可编辑的文本，用于笔记、校对或归档。",
    usage:
      "选择 SRT、VTT 或 TXT 格式导出；页面会标出字幕是人工上传还是平台自动生成，方便判断准确性。",
    limit: "不做 ASR：视频本身没有可用字幕时，无法导出字幕，也无法发起 Analysis。",
  },
  {
    title: "Analysis",
    summary: "基于 Subtitle 生成简体中文摘要；免费 Account 每日 3 次 Analysis，结果仅自己可见。",
    problem: "长视频没时间完整看完，希望先读到结构化的简体中文要点。",
    usage:
      "登录并验证邮箱后，对带字幕的视频发起 Analysis，基于字幕生成摘要。免费账号每个自然日 3 次，Analysis 默认仅自己可见。",
    limit: "没有字幕的视频不能分析；Quota 在成功创建时消耗，失败会退回。",
  },
  {
    title: "思维导图",
    summary: "把 Analysis 结果整理成可展开的主题结构，便于复盘与讲解。",
    problem: "把摘要变成可展开的结构，便于复盘和讲解。",
    usage:
      "Analysis 完成后打开思维导图，按主题层级浏览内容，也可以配合摘要一起阅读。",
    limit: "思维导图来自 Analysis 结果；没有 Analysis 就没有导图。",
  },
  {
    title: "历史与 VIP",
    summary: "在「我的分析」找回历史结果；VIP 会员解除每日 Analysis 的 Quota 限制。",
    problem: "找回过去生成的内容，并在需要时解除每日 Analysis 的 Quota 限制。",
    usage:
      "「我的分析」保留你的 Analysis 历史。VIP 会员 $4.99/月，Analysis 不限次；支付由 Stripe 托管，可随时取消，取消后在当期结束前仍可使用。",
    limit: "免费账号每天 3 次 Analysis；价格与扣款以支付方结账页展示为准。",
  },
];
