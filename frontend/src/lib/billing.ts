/**
 * Subscription DTO and the single VIP derivation for the frontend.
 *
 * Mirrors `GET /api/me/membership`: the backend is the only subscription truth and
 * VIP is derived from the recorded status, never from a stored flag.
 */

export interface MembershipDto {
  status: string;
  period_end: string | null;
  portal_url: string | null;
}

export const FREE_STATUS = "free";

const VIP_STATUSES: ReadonlySet<string> = new Set(["active", "trial_ending"]);

export function isVipMembership(membership: MembershipDto | null): boolean {
  return membership !== null && VIP_STATUSES.has(membership.status);
}
