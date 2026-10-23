"""Request metadata helpers shared by every HTTP module."""

from __future__ import annotations

from fastapi import Request


def client_ip(request: Request) -> str | None:
    """The client address as seen by our own reverse proxy.

    ``X-Real-IP`` is set by nginx and wins. Otherwise the *rightmost*
    ``X-Forwarded-For`` entry is used: proxies append the address they received the
    request from, so the rightmost value is the one our proxy observed. The leftmost
    entry is client-supplied and must never influence rate-limit keys or ownership.
    Finally fall back to the socket peer (direct connections, tests).
    """
    real_ip = request.headers.get("x-real-ip")
    if real_ip and real_ip.strip():
        return real_ip.strip()

    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
        if hops:
            return hops[-1]

    client = request.client
    return client.host if client is not None else None
