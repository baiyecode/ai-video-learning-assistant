"""Demo-mode observation routes for the Playwright golden path (ticket P2-09).

The golden path has to do two things a browser cannot do on its own: read the one-time
email verification link out of the fake mailer, and prove that the fake inbox actually
received mail. Both live behind :func:`app.config.Settings.fake_adapters`, so a real
deployment exposes no mailbox at all - the route answers 404 like any unknown path.

Mounted by ``app.modules.ops.router`` at its full path (ops owns the root router), never
by ``main.py``.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.config import Settings
from app.container import Adapters
from app.adapters.demo import DemoEmailSender
from app.deps import get_adapters, get_settings
from app.errors import AppError, ErrorCode

router = APIRouter(tags=["demo"])

_TOKEN_QUERY = re.compile(r"[?&]token=([^\s)\"]+)")


class DemoEmailOut(BaseModel):
    """One message the fake mailer would have delivered.

    ``verification_token`` is the convenience read of the link already inside ``body``:
    the golden path could regex it out itself, but the token is the one value that makes
    the mailbox actionable, so the route hands it over next to the raw copy it contains.
    """

    to: str
    subject: str
    body: str
    verification_token: str | None = None


def _require_demo_mode(settings: Settings) -> None:
    if not settings.fake_adapters:
        raise AppError(404, ErrorCode.NOT_FOUND, "该接口仅在假适配器模式下可用")


@router.get(
    "/api/demo/inbox",
    response_model=list[DemoEmailOut],
    summary="Fake mailer inbox (demo mode only)",
)
async def read_inbox(
    to: str | None = Query(default=None, description="Narrow the inbox to one address"),
    settings: Settings = Depends(get_settings),
    adapters: Adapters = Depends(get_adapters),
) -> list[DemoEmailOut]:
    """Newest-first view of everything the fake mailer "delivered" in this process."""
    _require_demo_mode(settings)
    sender = adapters.email_sender
    if sender is None or not isinstance(sender, DemoEmailSender):
        raise AppError(404, ErrorCode.NOT_FOUND, "该接口仅在假适配器模式下可用")
    return [
        DemoEmailOut(
            to=message.to,
            subject=message.subject,
            body=message.body,
            verification_token=_token_of(message.body),
        )
        for message in sender.messages_for(to)
    ]


def _token_of(body: str) -> str | None:
    matched = _TOKEN_QUERY.search(body)
    return matched.group(1) if matched else None
