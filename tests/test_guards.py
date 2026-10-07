"""Tests for the SSRF guard."""

from __future__ import annotations

import pytest

from hh_mcp.fetch.errors import InvalidURLError, SSRError
from hh_mcp.fetch.guards import UrlGuard, validate_url


# ---------------------------------------------------------------------------
# UrlGuard
# ---------------------------------------------------------------------------


class TestUrlGuardValidate:
    """Spec §3.3 — SSRF rejection rules (5 rules, case-insensitive host)."""

    @pytest.fixture
    def guard(self) -> UrlGuard:
        return UrlGuard()

    # --- InvalidURLError cases ---

    @pytest.mark.parametrize(
        "bad_input",
        [
            None,
            42,
            "",
            [],
            object(),
        ],
    )
    def test_non_string_or_empty(self, guard: UrlGuard, bad_input) -> None:
        with pytest.raises(InvalidURLError):
            guard.validate(bad_input)  # type: ignore[arg-type]

    def test_no_scheme(self, guard: UrlGuard) -> None:
        with pytest.raises(InvalidURLError, match="no scheme"):
            guard.validate("example.com/path")

    def test_unparseable_url(self, guard: UrlGuard) -> None:
        """Invalid URL format that httpx2 rejects."""
        with pytest.raises(InvalidURLError, match="unparseable"):
            guard.validate("http://[::1")

    # --- SSRError cases: scheme ---

    @pytest.mark.parametrize(
        "bad_scheme",
        [
            "ftp://example.com",
            "file:///etc/passwd",
            "data:text/plain,hello",
            "javascript:alert(1)",
            "gopher://example.com",
        ],
    )
    def test_non_http_scheme(self, guard: UrlGuard, bad_scheme) -> None:
        with pytest.raises(SSRError, match="unsupported scheme"):
            guard.validate(bad_scheme)

    # --- SSRError: userinfo ---

    @pytest.mark.parametrize(
        "url_with_userinfo",
        [
            "http://user@example.com",
            "http://user:pass@example.com",
            "http://user:password@example.com/path",
            "https://user@example.com:8080/path",
            "http://admin:secret@evil.local",
        ],
    )
    def test_userinfo_rejected(self, guard: UrlGuard, url_with_userinfo) -> None:
        with pytest.raises(SSRError, match="userinfo"):
            guard.validate(url_with_userinfo)

    # --- SSRError: empty host ---

    @pytest.mark.parametrize(
        "empty_host_url",
        [
            "http:///path",
            "https:///path",
        ],
    )
    def test_empty_host(self, guard: UrlGuard, empty_host_url) -> None:
        with pytest.raises(SSRError, match="empty host"):
            guard.validate(empty_host_url)

    # --- SSRError: localhost / .localhost ---

    @pytest.mark.parametrize(
        "localhost_url",
        [
            "http://localhost",
            "http://localhost:8080",
            "https://localhost/path",
            "http://www.localhost/path",
            "http://sub.localhost/path",
            "https://foo.localhost:3000",
            # Case-insensitive variants
            "http://LOCALHOST",
            "http://LocalHost",
            "http://Sub.LOCALHOST/path",
        ],
    )
    def test_localhost_rejected(self, guard: UrlGuard, localhost_url) -> None:
        with pytest.raises(SSRError, match="localhost"):
            guard.validate(localhost_url)

    # --- SSRError: .local ---

    @pytest.mark.parametrize(
        "local_url",
        [
            "http://example.local",
            "https://example.local/path",
            "http://sub.example.local/path",
            "http://test.local:8080",
            # Case-insensitive variants
            "http://EXAMPLE.LOCAL",
            "http://Example.LOCAL/path",
        ],
    )
    def test_local_rejected(self, guard: UrlGuard, local_url) -> None:
        with pytest.raises(SSRError, match=r"\.local"):
            guard.validate(local_url)

    # --- Valid URLs ---

    @pytest.mark.parametrize(
        "valid_url",
        [
            "http://example.com",
            "https://example.com",
            "http://example.com:8080/path?q=1",
            "https://sub.example.com/path/to/page.html",
            "http://127.0.0.1",  # IP addresses are allowed (no hostname rule for IPs)
            "https://192.168.1.1:8080/admin",
            "http://example.com/path#fragment",
            "https://example.com/path;params?query=value",
        ],
    )
    def test_valid_urls(self, guard: UrlGuard, valid_url) -> None:
        result = guard.validate(valid_url)
        assert isinstance(result, str)
        assert result.startswith("http")

    def test_normalized_return_value(self, guard: UrlGuard) -> None:
        """UrlGuard returns the httpx2.URL str form (normalized)."""
        result = guard.validate("HTTP://EXAMPLE.COM:80/path")
        # httpx2 may normalize scheme/host/case
        assert isinstance(result, str)
        assert "://" in result

    # --- Edge: malformed but passes httpx2 parse ---

    def test_malformed_but_accepted(self, guard: UrlGuard) -> None:
        """Some malformed URLs may still pass httpx2 URL parse – they're accepted."""
        result = guard.validate("http://example.com/pa th")
        assert isinstance(result, str)
        assert "example.com" in result


# ---------------------------------------------------------------------------
# validate_url back-compat shim
# ---------------------------------------------------------------------------


class TestValidateUrlShim:
    """§8: validate_url must still work as a module-level function."""

    def test_valid(self) -> None:
        validate_url("https://example.com")

    def test_rejects_ssrf(self) -> None:
        with pytest.raises(SSRError):
            validate_url("http://localhost:8080")

    def test_rejects_non_http(self) -> None:
        with pytest.raises(SSRError):
            validate_url("ftp://example.com")

    def test_rejects_empty_string(self) -> None:
        with pytest.raises((InvalidURLError, SSRError)):
            validate_url("")

    def test_rejects_non_string(self) -> None:
        with pytest.raises(InvalidURLError):
            validate_url(None)  # type: ignore[arg-type]