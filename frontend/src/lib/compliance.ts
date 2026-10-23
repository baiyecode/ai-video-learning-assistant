/**
 * First-Download compliance gate.
 *
 * The statement is shown once before the first Download; acknowledgement lives in
 * ``localStorage`` so it survives reloads. All helpers accept an injectable storage so
 * the gate logic stays unit-testable without a browser.
 */

export const COMPLIANCE_STATEMENT = "仅限个人备份或已获授权内容";
export const COMPLIANCE_STORAGE_KEY = "ai-video-learning-assistant:compliance-acknowledged";

const ACKNOWLEDGED_VALUE = "1";

export interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

/** ``localStorage`` when available; ``null`` in SSR or privacy modes that throw. */
export function defaultStorage(): StorageLike | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

export function isComplianceAcknowledged(storage: StorageLike | null = defaultStorage()): boolean {
  if (!storage) return false;
  try {
    return storage.getItem(COMPLIANCE_STORAGE_KEY) === ACKNOWLEDGED_VALUE;
  } catch {
    return false;
  }
}

export function acknowledgeCompliance(storage: StorageLike | null = defaultStorage()): void {
  if (!storage) return;
  try {
    storage.setItem(COMPLIANCE_STORAGE_KEY, ACKNOWLEDGED_VALUE);
  } catch {
    // Storage unavailable: the gate simply shows again next time.
  }
}

export function resetComplianceAcknowledgement(storage: StorageLike | null = defaultStorage()): void {
  if (!storage) return;
  try {
    storage.removeItem(COMPLIANCE_STORAGE_KEY);
  } catch {
    // Nothing to clean up when storage is unavailable.
  }
}

/**
 * Explicit UI copy for protected content. The backend is authoritative; this map makes
 * sure the refusal also explains the product boundary in the interface.
 */
export function complianceMessageForCode(code: string): string | null {
  if (code === "drm_protected") {
    return "该视频受 DRM 保护，本产品不提供绕过 DRM 的解析或下载，请通过平台官方渠道观看。";
  }
  if (code === "members_only") {
    return "该视频为会员专属内容，本产品不提供绕过会员权限的解析或下载，请通过平台官方渠道观看。";
  }
  return null;
}
