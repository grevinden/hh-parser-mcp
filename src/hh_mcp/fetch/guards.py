"""SSRF guard: URL validation against an allowlist of hosts."""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable

import httpx2 as httpx

from .config import INTERNAL_ROOT_DOMAINS
from .errors import InvalidURLError, SSRError

__all__ = [
    "ALLOWED_HOSTS",
    "UrlGuard",
    "validate_url",
]

#: Hosts the pipeline may reach: hh.ru and its subdomains, shared with the
#: link-stripping policy so "what is hh.ru" has a single answer.
ALLOWED_HOSTS: tuple[str, ...] = INTERNAL_ROOT_DOMAINS


def _is_ip_literal(host: str) -> bool:
    """Return ``True`` for dotted IPv4/IPv6 and integer/hex forms."""
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    try:
        ipaddress.ip_address(int(host, 0))
        return True
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# Guard
# ---------------------------------------------------------------------------


class UrlGuard:
    """Reject any URL that does not target an allowed host.

    The check runs on the entry URL and on every redirect hop, so a public
    host cannot bounce the request to a private address.
    """

    def __init__(self, allowed_hosts: Iterable[str] = ALLOWED_HOSTS) -> None:
        """Fix the host allowlist; a host matches exactly or as ``*.host``."""
        self._allowed = tuple(h.strip().casefold() for h in allowed_hosts)

    def validate(self, url: str) -> str:
        """Return a normalized absolute http(s) URL to an allowed host."""
        if not isinstance(url, str) or not url:
            raise InvalidURLError("url must be a non-empty string")

        try:
            parsed = httpx.URL(url)
        except httpx.InvalidURL as exc:
            raise InvalidURLError(f"unparseable URL: {url!r}") from exc

        if not parsed.scheme:
            raise InvalidURLError(f"no scheme in URL: {url!r}")

        if parsed.scheme not in ("http", "https"):
            raise SSRError(f"unsupported scheme {parsed.scheme!r}")

        if parsed.username or parsed.password:
            raise SSRError("userinfo not allowed in URL")

        host = parsed.host
        if not host:
            raise SSRError("empty host")

        self._check_host(host)
        return str(parsed)

    def _check_host(self, host: str) -> None:
        """Raise unless *host* is an allowed, non-literal hostname."""
        host = host.strip("[]").casefold()

        if host == "localhost" or host.endswith(".localhost"):
            raise SSRError("localhost is not allowed")
        if host.endswith(".local"):
            raise SSRError(".local hostnames are not allowed")

        # IP literals skip DNS; the decimal/hex forms encode an address the
        # allowlist check below would not recognise.
        if _is_ip_literal(host):
            raise SSRError("IP literals are not allowed")

        for allowed in self._allowed:
            if host == allowed or host.endswith("." + allowed):
                return
        raise SSRError(f"host {host!r} is not in the allowlist")


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------


def validate_url(url: str) -> None:
    """Validate *url* with :class:`UrlGuard`, discarding the normalized form."""
    UrlGuard().validate(url)
