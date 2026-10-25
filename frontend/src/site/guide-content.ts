/**
 * The three guide steps are the single source for both the visible ordered list
 * on `/guide` and the HowTo JSON-LD. Keeping them here means the page and the
 * structured data cannot disagree about what the workflow is.
 */
export interface GuideStep {
  title: string;
  text: string;
}

export const guideSteps: readonly GuideStep[] = [
  {
    title: "解析",
    text: "在首页输入框粘贴 B 站或 YouTube 的公开视频页面地址，点击「解析视频」，等待结果显示标题、时长与可选格式。",
  },
  {
    title: "下载或导出 Subtitle",
    text: "在结果区选择清晰度与格式后开始下载；也可以直接导出已有的 Subtitle（SRT、VTT 或 TXT）。下载链接 15 分钟内有效，服务端文件最多保留 1 小时。",
  },
  {
    title: "登录生成 Analysis",
    text: "登录并验证邮箱后，对带 Subtitle 的视频点击「AI 分析」，系统基于字幕生成简体中文摘要与思维导图；免费 Account 每日 3 次。",
  },
];
