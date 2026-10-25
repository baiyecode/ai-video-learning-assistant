/**
 * FAQ copy is user-visible marketing surface, so its vocabulary is contract:
 * ``GLOSSARY.md`` puts 转写文本 on Subtitle's _Avoid_ list, and README calls the
 * address a user pastes 页面地址 (never 视频地址). The product fact behind the
 * reworded entry — no ASR — is asserted from the entry itself, so a wording fix
 * can never quietly delete the boundary it states.
 */
import { describe, expect, it } from "vitest";

import { faqItems, homeFaqItems } from "@/site/faq-content";

describe("FAQ copy follows the glossary vocabulary", () => {
  it("never reaches for the Subtitle avoid word 转写文本", () => {
    for (const item of faqItems) {
      expect(item.question, item.question).not.toContain("转写");
      expect(item.answer, item.answer).not.toContain("转写");
    }
  });

  it("never calls the pasted address 视频地址", () => {
    for (const item of [...faqItems, ...homeFaqItems]) {
      expect(item.question, item.question).not.toContain("视频地址");
      expect(item.answer, item.answer).not.toContain("视频地址");
    }
  });

  it("still answers the no-ASR boundary with the Subtitle term", () => {
    const entry = faqItems.find((item) => item.answer.includes("不做 ASR"));

    expect(entry).toBeDefined();
    expect(entry?.question).toContain("字幕");
    expect(entry?.answer).toContain("不做 ASR");
    expect(entry?.answer).toContain("Subtitle");
  });
});
