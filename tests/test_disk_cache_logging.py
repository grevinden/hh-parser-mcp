"""Tests for :class:`server.LoggingFileTreeStore`.

The response-caching middleware owns the decision to consult the disk; this
store only reports it. The log line is the only way to tell "the disk answered"
from "the disk was empty and a slower tier took over", so its content is part
of the contract: sizes and keys, never the cached page itself.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import pytest
from key_value.aio.stores.filetree import (
    FileTreeV1CollectionSanitizationStrategy,
    FileTreeV1KeySanitizationStrategy,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server import LoggingFileTreeStore, _approx_bytes  # noqa: E402

BODY = "Тело страницы. " * 40


def _store(tmp_path: Path) -> LoggingFileTreeStore:
    return LoggingFileTreeStore(
        logger=logging.getLogger("hh_mcp.server.test"),
        data_directory=tmp_path,
        key_sanitization_strategy=FileTreeV1KeySanitizationStrategy(tmp_path),
        collection_sanitization_strategy=FileTreeV1CollectionSanitizationStrategy(
            tmp_path
        ),
    )


class TestApproxBytes:
    """Size estimates for log lines, computed without serializing."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("abc", 3),
            ({"text": "abcd"}, 8),
            # "content" + "type" + "text" + "text" + "abcd"
            ({"content": [{"type": "text", "text": "abcd"}]}, 23),
            ([], 0),
            (12345, 5),
        ],
    )
    def test_sums_leaves(self, value, expected):
        assert _approx_bytes(value) == expected

    def test_nested_mapping(self):
        assert _approx_bytes({"a": {"b": "xy"}}) == 4


class TestLogging:
    """Every read, miss and write is reported."""

    def test_miss_is_logged(self, tmp_path, caplog):
        store = _store(tmp_path)
        with caplog.at_level("INFO", logger="hh_mcp.server.test"):
            asyncio.run(store.get("absent-key"))
        assert "disk cache miss" in caplog.text
        assert "absent-key" in caplog.text

    def test_write_and_hit_are_logged(self, tmp_path, caplog):
        store = _store(tmp_path)
        payload = {"content": [{"type": "text", "text": BODY}]}

        with caplog.at_level("INFO", logger="hh_mcp.server.test"):
            asyncio.run(store.put("k1", payload, ttl=3600))
            value = asyncio.run(store.get("k1"))

        assert value == payload
        assert "disk cache write" in caplog.text
        assert "disk cache hit" in caplog.text
        assert "ttl=3600" in caplog.text

    def test_hit_reports_a_size(self, tmp_path, caplog):
        store = _store(tmp_path)
        asyncio.run(store.put("k2", {"content": BODY}))

        with caplog.at_level("INFO", logger="hh_mcp.server.test"):
            asyncio.run(store.get("k2"))

        sizes = [
            int(line.rsplit("bytes=", 1)[1].split()[0])
            for line in caplog.text.splitlines()
            if "disk cache hit" in line
        ]
        assert sizes and sizes[0] > len(BODY)

    def test_cached_text_is_not_logged(self, tmp_path, caplog):
        store = _store(tmp_path)
        asyncio.run(store.put("k3", {"content": BODY}))
        with caplog.at_level("DEBUG"):
            asyncio.run(store.get("k3"))
        assert "Тело страницы" not in caplog.text

    def test_store_behaves_like_the_base_store(self, tmp_path):
        """Logging must not change what the middleware gets back."""
        store = _store(tmp_path)
        payload = {"content": [{"type": "text", "text": BODY}]}
        asyncio.run(store.put("k4", payload))
        assert asyncio.run(store.get("k4")) == payload
        assert asyncio.run(store.get("missing")) is None