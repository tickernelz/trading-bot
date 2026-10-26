"""Stricter locality than control.is_local: the Host and Origin headers must also name loopback."""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

from starlette.requests import HTTPConnection

from gateway.control import is_local

EXTRA_RELAY_HEADERS = (
    "x-forwarded-proto",
    "x-forwarded-server",
    "x-original-forwarded-for",
    "via",
    "cdn-loop",
    "cf-visitor",
    "cf-ipcountry",
)


def loopback_name(host: str | None) -> bool:
    if not host:
        return False
    name = host.strip("[]").lower()
    if name == "localhost":
        return True
    try:
        return ipaddress.ip_address(name).is_loopback
    except ValueError:
        return False


def is_local_request(request: HTTPConnection) -> bool:
    """control.is_local plus: no further relay header, a loopback Host, and a loopback Origin when one is sent."""
    if not is_local(request):
        return False
    if any(name in request.headers for name in EXTRA_RELAY_HEADERS):
        return False
    if not loopback_name(urlsplit("//" + request.headers.get("host", "")).hostname):
        return False
    origin = request.headers.get("origin")
    return origin is None or loopback_name(urlsplit(origin).hostname)
