from __future__ import annotations

import unittest

from unittest.mock import patch

from status_watcher.discovery import discover_source


class DiscoveryTests(unittest.TestCase):
    def test_discovers_statuspage_and_compresses_to_preset(self) -> None:
        summary = {"page": {"name": "Claude"}, "status": {"description": "Operational"}, "components": []}
        incidents = {"incidents": []}

        with patch(
            "status_watcher.discovery.fetch_statuspage_json",
            side_effect=[summary, incidents],
        ):
            result = discover_source("Claude", "https://status.claude.com")

        self.assertEqual(result.spec.type, "statuspage")
        self.assertEqual(result.spec.url, "https://status.claude.com")
        self.assertEqual(result.preset, "claude")
        self.assertEqual(result.config_entry, {"preset": "claude"})

    def test_discovers_feed_from_xml_payload(self) -> None:
        atom = b"""<?xml version='1.0'?><feed xmlns='http://www.w3.org/2005/Atom'><entry><title>Operational</title><updated>2026-03-25T12:00:00Z</updated><summary>All systems operational.</summary></entry></feed>"""

        with patch("status_watcher.discovery.fetch_statuspage_json", side_effect=RuntimeError("not statuspage")), patch(
            "status_watcher.discovery.fetch_url",
            return_value=atom,
        ):
            result = discover_source("Example Feed", "https://example.com/feed.atom")

        self.assertEqual(result.spec.type, "feed")
        self.assertEqual(result.config_entry, {"name": "Example Feed", "url": "https://example.com/feed.atom"})

    def test_discovers_html_and_infers_selectors(self) -> None:
        payload = b"""
        <html>
          <body>
            <section class='incident'>Investigating API latency</section>
            <section data-component-id='api'>API Operational</section>
          </body>
        </html>
        """

        with patch("status_watcher.discovery.fetch_statuspage_json", side_effect=RuntimeError("not statuspage")), patch(
            "status_watcher.discovery.fetch_url",
            return_value=payload,
        ):
            result = discover_source("Example HTML", "https://status.example.com")

        self.assertEqual(result.spec.type, "html")
        self.assertEqual(result.spec.options["selectors"], [".incident"])
        self.assertEqual(result.spec.options["component_selectors"], ["[data-component-id]"])


if __name__ == "__main__":
    unittest.main()
