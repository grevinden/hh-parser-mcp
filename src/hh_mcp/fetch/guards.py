"""SSRF guard: URL validation.

Stateless; parses with ``httpx2.URL`` (already a project dependency).
Rejection rules (back-compat: same 5 rules and same message format as the
old module):

1. non-``http(s)`` scheme
2. userinfo (username or password) in the URL
3. empty host
4. host is ``localhost`` or ends with ``.localhost``
5. host ends with ``.local``
"""

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
        """Return a normalized absolute http(s) URL.

        Args:
            url:
                Candidate URL string.

        Returns:
            str
                The URL as parsed by :class:`httpx2.URL` (str form).

        Raises:
            InvalidURLError:
                Not a str, empty, absent scheme, or unparseable.
            SSRError:
                Non-http(s) scheme, userinfo in URL, empty host, host ends
                with ``localhost`` / ``.localhost`` / ``.local``.
        """
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
# Back-compat shim
# ---------------------------------------------------------------------------


def validate_url(url: str) -> None:
    """Validate that *url* targets a public, reachable address.

    Blocks non-http(s) schemes, userinfo in the URL, empty hosts, and
    ``localhost`` / ``.localhost`` / ``.local`` hostnames.

    Args:
        url:
            Candidate URL string.

    Raises:
        SSRError:
            On any violation (back-compat behavior).
        InvalidURLError:
            On non-string input (new; the old code raised ``ValueError``
            for this case anyway via ``httpx2.URL``).
    """
    UrlGuard().validate(url)
