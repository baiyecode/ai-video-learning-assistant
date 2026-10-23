/** Shared client-side validation rules (mirrors the backend contract). */

export const PASSWORD_MIN_LENGTH = 8;

/** Returns a Chinese hint, or ``null`` when the password is acceptable. */
export function validatePassword(password: string): string | null {
  if (Array.from(password).length < PASSWORD_MIN_LENGTH) {
    return `密码至少需要 ${PASSWORD_MIN_LENGTH} 位`;
  }
  return null;
}
