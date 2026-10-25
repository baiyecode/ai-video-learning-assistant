/**
 * The single FAQ source: the `/faq` page, the home summary and the FAQPage
 * JSON-LD all read this list, so visible copy and structured data cannot drift.
 *
 * Every answer stays inside verified product behaviour (see recon §1): no ASR,
 * no platform-wide promises, no DRM bypass, no invented permanence.
 */
import { PRICE_BENEFIT, PRICE_HEADLINE } from "@/lib/billing";

export interface FaqItem {
  question: string;
  answer: string;
}

/** The home page shows this many entries before linking to the full FAQ. */
export const HOME_FAQ_COUNT = 5;

export const faqItems: readonly FaqItem[] = [
  {
    question: "支持哪些 Platform？",
    answer:
      "B 站与 YouTube 始终可用。抖音仅在部署开启灰度（APP_DOUYIN_ENABLED）时可用；灰度关闭时提交抖音页面地址会返回「抖音暂未开放」。",
  },
  {
    question: "免费账号每天可以做几次 Analysis？",
    answer:
      "每个 Account 每个 Asia/Shanghai 自然日 3 次 Analysis。只有成功创建新的 Analysis 才消耗 Quota，失败会退回；查看已有结果不消耗 Quota。",
  },
  {
    question: "VIP 会员多少钱？可以随时取消吗？",
    answer: `VIP 会员 ${PRICE_HEADLINE}（USD），按月自动续费，解锁「${PRICE_BENEFIT}」。可在个人中心的订阅管理进入 Stripe 门户随时取消；取消后 VIP 保留至当期结束，之后恢复免费 Quota。`,
  },
  {
    question: "没有 Subtitle 的视频能生成 Analysis 吗？",
    answer:
      "不能。Analysis 只读取 Platform 提供的 Subtitle；视频没有可用字幕时，仍然可以下载文件，但不能导出字幕，也不能发起 Analysis。",
  },
  {
    question: "下载文件会保留多久？下载链接多久有效？",
    answer:
      "服务端文件最多保留 1 小时，下载链接 15 分钟内有效。过期后重新解析同一个页面地址即可生成新的链接。",
  },
  {
    question: "抖音解析为什么有时不可用？",
    answer:
      "抖音是灰度能力，默认关闭，由部署开关 APP_DOUYIN_ENABLED 控制。开启后抖音只提供单一清晰度的带水印产物；没有 Subtitle 时同样不能发起 Analysis。",
  },
  {
    question: "会为没有字幕的视频生成转写文本吗？",
    answer:
      "不会。本工具不做 ASR，也不会生成转写文本；Subtitle 与 Analysis 都依赖 Platform 已经提供的字幕。",
  },
  {
    question: "单个视频有什么大小与时长限制？",
    answer:
      "单个视频最长 2 小时、最大 2 GB；播放列表、直播、DRM 内容与会员专属内容不在支持范围内。",
  },
  {
    question: "Analysis 结果会被公开吗？",
    answer:
      "不会。Analysis 与思维导图是你的私有内容，仅你自己可见，相关页面使用 noindex，不会进入搜索结果。",
  },
  {
    question: "在哪里举报侵权或滥用内容？",
    answer:
      "使用条款页的举报表单（/terms#report）提供入口，也可以从页脚的「举报」链接进入；提交成功后会返回举报编号。",
  },
  {
    question: "为什么提示需要先验证邮箱？",
    answer:
      "发起 Analysis 前需要验证邮箱；解析、Download 与 Subtitle 导出不受影响。请在个人中心重新发送验证邮件，并打开邮件中的链接。",
  },
  {
    question: "解析或 Download 失败了怎么办？",
    answer:
      "先确认页面地址属于支持的 Platform，且内容不是播放列表、直播、DRM 或会员专属；下载链接 15 分钟后会过期，重新解析即可。Visitor 每小时最多发起 5 次 Download。",
  },
  {
    question: "今日 Analysis 的 Quota 用完了怎么办？",
    answer:
      "免费 Account 的 Quota 会在下一个 Asia/Shanghai 自然日重置；也可以升级 VIP 会员解除每日 Quota 限制。",
  },
];

/** The home summary keeps the five most common entry questions, in FAQ order. */
export const homeFaqItems: readonly FaqItem[] = faqItems.slice(0, HOME_FAQ_COUNT);
