/**
 * The public/indexable split (issue #42 gap 5): ``public`` is membership in the
 * prerendered Marketing Page surface, ``indexable`` additionally requires the
 * index robots directive. A future noindex Marketing Page must keep its prerendered
 * artifact and only *deliberately* leave the sitemap — never silently drop out.
 */
import { describe, expect, it } from "vitest";

import { buildSitemapXml } from "@/site/discovery";
import {
  INDEX_ROBOTS,
  NOINDEX_ROBOTS,
  SeoDescriptorError,
  descriptorForRoute,
  headTags,
  indexableDescriptors,
  isIndexableDescriptor,
  isPublicDescriptor,
  notFoundDescriptor,
  pageDescriptors,
  publicDescriptors,
  validateDescriptors,
  type PageDescriptor,
} from "@/site/seo";

const ORIGIN = "https://example.com";

function fixture(overrides: Partial<PageDescriptor>): PageDescriptor {
  return {
    name: "fixture-page",
    path: "/fixture",
    title: "测试页面",
    description:
      "这是一段用于验证 public 与 indexable 两个谓词拆分的测试描述，长度需要落在七十到一百六十个字符之间，以便通过构建期的描述校验规则；它只服务于单元测试。",
    public: true,
    robots: INDEX_ROBOTS,
    ogType: "website",
    ...overrides,
  };
}

describe("isPublicDescriptor / isIndexableDescriptor", () => {
  it("treats a noindex Marketing Page as public but not indexable", () => {
    const hidden = fixture({ name: "hidden-page", path: "/hidden", robots: NOINDEX_ROBOTS });

    expect(isPublicDescriptor(hidden)).toBe(true);
    expect(isIndexableDescriptor(hidden)).toBe(false);
  });

  it("keeps the registry's explicit split: marketing pages public, app routes private", () => {
    expect(publicDescriptors(pageDescriptors).map((descriptor) => descriptor.path)).toEqual([
      "/",
      "/features",
      "/guide",
      "/faq",
      "/pricing",
      "/terms",
    ]);
    for (const name of ["login", "account", "verify-email", "analyses", "analysis", "not-found"]) {
      const descriptor = descriptorForRoute(name);
      expect(isPublicDescriptor(descriptor), name).toBe(false);
      expect(isIndexableDescriptor(descriptor), name).toBe(false);
    }
  });

  it("requires both halves for indexable: public plus the index robots directive", () => {
    expect(isIndexableDescriptor(fixture({}))).toBe(true);
    expect(isIndexableDescriptor(fixture({ robots: NOINDEX_ROBOTS }))).toBe(false);
    expect(isIndexableDescriptor(fixture({ public: false }))).toBe(false);
    expect(isPublicDescriptor(fixture({ public: false }))).toBe(false);
  });
});

describe("prerender and sitemap sets", () => {
  it("keeps a noindex Marketing Page in the prerender set and out of the sitemap", () => {
    const hidden = fixture({ name: "hidden-page", path: "/hidden", robots: NOINDEX_ROBOTS });
    const open = fixture({ name: "open-page", path: "/open" });
    const privatePage = fixture({
      name: "private-page",
      path: "/private-route",
      public: false,
      robots: NOINDEX_ROBOTS,
    });

    expect(publicDescriptors([hidden, open, privatePage]).map((d) => d.path)).toEqual([
      "/hidden",
      "/open",
    ]);
    expect(indexableDescriptors([hidden, open, privatePage]).map((d) => d.path)).toEqual(["/open"]);

    const sitemap = buildSitemapXml(ORIGIN, [hidden, open, privatePage]);
    expect(sitemap).toContain(`${ORIGIN}/open`);
    expect(sitemap).not.toContain(`${ORIGIN}/hidden`);
    expect(sitemap).not.toContain(`${ORIGIN}/private-route`);
  });
});

describe("headTags with the split predicates", () => {
  it("gives a public noindex page the unindexed head without canonical or OG tags", () => {
    const tags = headTags(fixture({ robots: NOINDEX_ROBOTS }), ORIGIN);

    expect(tags.some((tag) => tag.tag === "link" && tag.attrs.rel === "canonical")).toBe(false);
    expect(tags.some((tag) => tag.attrs.name === "robots" && tag.attrs.content === NOINDEX_ROBOTS)).toBe(
      true,
    );
    expect(tags.some((tag) => tag.attrs.property === "og:title")).toBe(false);
  });
});

describe("validateDescriptors with the public flag", () => {
  it("rejects a private descriptor that claims the index robots directive", () => {
    const contradictory = fixture({ name: "contradictory", path: "/x", public: false });

    expect(() => validateDescriptors([contradictory])).toThrow(SeoDescriptorError);
  });

  it("still accepts the real registry and an indexable fixture", () => {
    expect(() => validateDescriptors(pageDescriptors)).not.toThrow();
    expect(() => validateDescriptors([fixture({})])).not.toThrow();
  });
});

describe("notFoundDescriptor", () => {
  it("is the checked registry entry, not an unchecked cast", () => {
    expect(notFoundDescriptor.name).toBe("not-found");
    expect(notFoundDescriptor.path).toBe("*");
    expect(isPublicDescriptor(notFoundDescriptor)).toBe(false);
  });
});
