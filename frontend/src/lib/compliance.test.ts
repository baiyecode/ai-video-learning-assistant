import { describe, expect, it } from "vitest";

import {
  COMPLIANCE_STATEMENT,
  COMPLIANCE_STORAGE_KEY,
  acknowledgeCompliance,
  complianceMessageForCode,
  isComplianceAcknowledged,
  resetComplianceAcknowledgement,
  type StorageLike,
} from "@/lib/compliance";

function memoryStorage(): StorageLike {
  const data = new Map<string, string>();
  return {
    getItem: (key) => data.get(key) ?? null,
    setItem: (key, value) => {
      data.set(key, value);
    },
    removeItem: (key) => {
      data.delete(key);
    },
  };
}

const failingStorage: StorageLike = {
  getItem: () => {
    throw new Error("blocked");
  },
  setItem: () => {
    throw new Error("blocked");
  },
  removeItem: () => {
    throw new Error("blocked");
  },
};

describe("compliance gate", () => {
  it("shows on the first visit because nothing is acknowledged yet", () => {
    const storage = memoryStorage();

    expect(COMPLIANCE_STATEMENT).toBe("仅限个人备份或已获授权内容");
    expect(isComplianceAcknowledged(storage)).toBe(false);
  });

  it("persists acknowledgement across reads", () => {
    const storage = memoryStorage();

    acknowledgeCompliance(storage);

    expect(isComplianceAcknowledged(storage)).toBe(true);
    expect(storage.getItem(COMPLIANCE_STORAGE_KEY)).toBe("1");
  });

  it("reset makes the gate show again", () => {
    const storage = memoryStorage();
    acknowledgeCompliance(storage);

    resetComplianceAcknowledgement(storage);

    expect(isComplianceAcknowledged(storage)).toBe(false);
    expect(storage.getItem(COMPLIANCE_STORAGE_KEY)).toBeNull();
  });

  it("treats unavailable storage as not acknowledged instead of throwing", () => {
    expect(isComplianceAcknowledged(failingStorage)).toBe(false);
    expect(() => acknowledgeCompliance(failingStorage)).not.toThrow();
    expect(() => resetComplianceAcknowledgement(failingStorage)).not.toThrow();
    expect(isComplianceAcknowledged(null)).toBe(false);
  });

  it("maps protected-content errors to explicit no-bypass copy", () => {
    expect(complianceMessageForCode("drm_protected")).toContain("不提供绕过 DRM");
    expect(complianceMessageForCode("members_only")).toContain("不提供绕过会员权限");
    expect(complianceMessageForCode("unsupported_url")).toBeNull();
  });
});
