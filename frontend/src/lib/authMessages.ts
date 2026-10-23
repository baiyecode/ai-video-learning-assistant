/** Chinese user-facing messages for stable auth error codes. */
const AUTH_MESSAGES: Record<string, string> = {
  invalid_credentials: "邮箱或密码不正确",
  email_taken: "该邮箱已注册，请直接登录",
  weak_password: "密码至少需要 8 位",
  invalid_request: "请检查邮箱格式与密码",
  auth_required: "登录状态已失效，请重新登录",
  session_invalid: "登录状态已失效，请重新登录",
  too_many_requests: "尝试过于频繁，请稍后再试",
  service_unavailable: "服务暂时不可用，请稍后再试",
  internal_error: "服务器内部错误，请稍后重试",
};

const GENERIC_MESSAGE = "操作失败，请稍后重试";

export function authErrorMessage(code: string | null | undefined): string {
  if (code && AUTH_MESSAGES[code]) return AUTH_MESSAGES[code];
  return GENERIC_MESSAGE;
}
