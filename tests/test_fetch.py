from __future__ import annotations

import tempfile
import unittest
import urllib.error

from pathlib import Path
from unittest.mock import patch

from status_watcher.models import SourceSpec
from status_watcher.sources.base import fetch_url, store_cached_response
from status_watcher.sources.feed import FeedSourceAdapter
from status_watcher.sources.statuspage import fetch_statuspage_json


class _Response:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return self.payload


class FetchReliabilityTests(unittest.TestCase):
    def test_fetch_url_retries_transient_network_errors(self) -> None:
        attempts = [
            urllib.error.URLError("temporary failure"),
            urllib.error.URLError("temporary failure"),
            _Response(b"ok"),
        ]

        def fake_urlopen(request, timeout):
            current = attempts.pop(0)
            if isinstance(current, Exception):
                raise current
            return current

        with patch("status_watcher.sources.base.urllib.request.urlopen", side_effect=fake_urlopen) as mocked, patch(
            "status_watcher.sources.base.time.sleep"
        ):
            payload = fetch_url("https://example.com/status")

        self.assertEqual(payload, b"ok")
        self.assertEqual(mocked.call_count, 3)

    def test_fetch_url_falls_back_to_cached_response_after_retries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "cached.bin"
            with patch("status_watcher.sources.base.cache_path_for_url", return_value=cache_path):
                store_cached_response("https://example.com/status", b"cached")
                with patch(
                    "status_watcher.sources.base.urllib.request.urlopen",
                    side_effect=urllib.error.URLError("offline"),
                ), patch("status_watcher.sources.base.time.sleep"):
                    payload = fetch_url("https://example.com/status")

        self.assertEqual(payload, b"cached")

    def test_feed_adapter_uses_cached_payload_when_fresh_response_is_malformed(self) -> None:
        spec = SourceSpec(name="Example", type="feed", url="https://example.com/feed.xml")
        cached = b"""<?xml version='1.0'?><feed xmlns='http://www.w3.org/2005/Atom'><entry><title>Operational</title><updated>2026-03-25T12:00:00Z</updated><summary>All systems operational.</summary></entry></feed>"""

        with patch("status_watcher.sources.feed.fetch_url", return_value=b"<broken xml"), patch(
            "status_watcher.sources.feed.load_cached_response", return_value=cached
        ), patch("status_watcher.sources.feed.store_cached_response"):
            snapshot = FeedSourceAdapter().load(spec)

        self.assertEqual(snapshot.entries[0].title, "Operational")

    def test_statuspage_json_uses_cached_payload_when_fresh_response_is_malformed(self) -> None:
        cached = b'{"page": {"id": "abc"}}'
        with patch("status_watcher.sources.statuspage.fetch_url", return_value=b"not-json"), patch(
            "status_watcher.sources.statuspage.load_cached_response", return_value=cached
        ), patch("status_watcher.sources.statuspage.store_cached_response"):
            payload = fetch_statuspage_json("https://status.example.com", "summary.json")

        self.assertEqual(payload["page"]["id"], "abc")


if __name__ == "__main__":
    unittest.main()
