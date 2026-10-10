"""SSRF guard: URL validation."""

from __future__ import annotations

import httpx2 as httpx

from .errors import InvalidURLError, SSRError

__all__ = [
    "UrlGuard",
    "validate_url",
]


# ---------------------------------------------------------------------------
# Guard
# ---------------------------------------------------------------------------


class UrlGuard:
    """SSRF guard. Stateless; constructed with no args."""

    def validate(self, url: str) -> str:
        """Return a normalized absolute http(s) URL."""
        if not isinstance(url, str) or not url:
            raise InvalidURLError("url must be a non-empty string")

        try:
            parsed = httpx.URL(url)
        except httpx.InvalidURL as exc:
            raise InvalidURLError(f"unparseable URL: {url!r}") from exc

        if not parsed.scheme:
            raise InvalidURLError(f"no scheme in URL: {url!r}")

        # Scheme
        if parsed.scheme not in ("http", "https"):
            raise SSRError(f"unsupported scheme {parsed.scheme!r}")

        # Userinfo
        if parsed.username or parsed.password:
            raise SSRError("userinfo not allowed in URL")

        host = parsed.host
        if not host:
            raise SSRError("empty host")

        # Hostname patterns
        host_lower = host.lower()
        if host_lower == "localhost" or host_lower.endswith(".localhost"):
            raise SSRError("localhost is not allowed")
        if host_lower.endswith(".local"):
            raise SSRError(".local hostnames are not allowed")

        return str(parsed)


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------


def validate_url(url: str) -> None:
    """Validate *url* with :class:`UrlGuard`, discarding the normalized form."""
    UrlGuard().validate(url)
