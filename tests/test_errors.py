"""Tests for the fetch error hierarchy."""

from __future__ import annotations

from hh_mcp.fetch.errors import (
    ConversionError,
    FetchError,
    FetchTimeoutError,
    InvalidURLError,
    ParseError,
    ResponseTooLargeError,
    SSRError,
    TransportError,
    UnsupportedContentTypeError,
)


class TestErrorHierarchy:
    """Verify the error class hierarchy (§4 of the spec)."""

    def test_fetch_error_base(self) -> None:
        assert issubclass(FetchError, Exception)
        assert issubclass(TransportError, FetchError)
        assert issubclass(FetchTimeoutError, TransportError)
        assert issubclass(ResponseTooLargeError, TransportError)
        assert issubclass(UnsupportedContentTypeError, FetchError)
        assert issubclass(ParseError, FetchError)
        assert issubclass(ConversionError, FetchError)

    def test_value_error_subclasses(self) -> None:
        """SSRError and InvalidURLError must remain ValueError subclasses (back-compat)."""
        assert issubclass(SSRError, ValueError)
        assert not issubclass(SSRError, FetchError)
        assert issubclass(InvalidURLError, ValueError)
        assert not issubclass(InvalidURLError, FetchError)

    def test_ssrerror_not_fetch_error(self) -> None:
        """SSRError is deliberately NOT under FetchError per spec §4."""
        assert not issubclass(SSRError, FetchError)
        assert not issubclass(InvalidURLError, FetchError)

    def test_instantiation_and_cause(self) -> None:
        """Verify that TransportError and ConversionError support __cause__."""
        try:
            try:
                raise ValueError("original")
            except ValueError as exc:
                raise TransportError("wrapped") from exc
        except TransportError as e:
            assert isinstance(e.__cause__, ValueError)
            assert "wrapped" in str(e)

        try:
            try:
                raise RuntimeError("inner")
            except RuntimeError as exc:
                raise ConversionError("conversion failed") from exc
        except ConversionError as e:
            assert isinstance(e.__cause__, RuntimeError)
            assert "conversion failed" in str(e)

    def test_fetch_timeout_error(self) -> None:
        """FetchTimeoutError is a TransportError with a message."""
        err = FetchTimeoutError("timeout fetching example.com")
        assert isinstance(err, TransportError)
        assert isinstance(err, FetchError)
        assert "timeout" in str(err)

    def test_response_too_large_error(self) -> None:
        err = ResponseTooLargeError("response body exceeds 4194304 bytes")
        assert isinstance(err, TransportError)
        assert isinstance(err, FetchError)
        assert "4194304" in str(err)

    def test_unsupported_content_type_error(self) -> None:
        err = UnsupportedContentTypeError("unsupported Content-Type")
        assert isinstance(err, FetchError)
        assert not isinstance(err, TransportError)

    def test_parse_error(self) -> None:
        err = ParseError("invalid UTF-8 in response body")
        assert isinstance(err, FetchError)
        assert "UTF-8" in str(err)