"""User-facing copy for conditions more than one module can raise.

One condition, one sentence: the same rejection has to read identically whether it
surfaces while resolving, downloading or analysing, otherwise users learn that
different screens mean different things. Copy a single module ever shows stays in
that module instead.

Vocabulary follows ``GLOSSARY.md``: the entity is a 视频, and the text a user pastes
is its 页面地址 (never 视频链接, which is not the name of the Video).
"""

from __future__ import annotations

VIDEO_NOT_FOUND = "视频不存在，请重新解析"
FORMATS_EXPIRED = "格式信息已过期，请重新解析该视频"
RESOLVE_FAILED = "视频解析失败，请稍后重试"

DRM_PROTECTED = "该视频受 DRM 保护，本产品不提供绕过 DRM 的解析或下载"
MEMBERS_ONLY = "该视频为会员专属内容，本产品不提供绕过会员权限的解析或下载"
SUBTITLES_UNAVAILABLE = "该视频没有可用字幕，暂不支持 AI 分析"

UNSUPPORTED_URL = "暂不支持该地址，请粘贴 B 站或 YouTube 视频的页面地址"
UNSUPPORTED_PLATFORM = "暂不支持该平台，请粘贴 B 站或 YouTube 视频的页面地址"
# Feature-switch rejection: the platform is recognised but not opened yet (ticket #23).
PLATFORM_NOT_ENABLED = "抖音暂未开放"
PLAYLIST_NOT_SUPPORTED = "暂不支持播放列表、合集或收藏夹，请粘贴单个视频的页面地址"
LIVE_NOT_SUPPORTED = "暂不支持直播，请粘贴已发布视频的页面地址"

DOWNLOAD_FAILED = "下载失败，请稍后重试"
DOWNLOAD_TIMEOUT = "下载超时，请稍后重试"
DOWNLOAD_INTERRUPTED = "服务重启导致任务中断，请重试"
FILE_EXPIRED = "文件已过期，请重新发起下载"

# Email verification (ticket #22): Analysis is gated on a verified email, but login,
# resolve, Subtitle viewing and Download are not. The same sentence should read
# identically wherever the gate fires, so it lives here.
EMAIL_NOT_VERIFIED = "请先验证邮箱后再发起 Analysis"
