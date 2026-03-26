from __future__ import annotations

import unittest

from unittest.mock import patch

from status_watcher.models import SourceSpec
from status_watcher.sources.html_page import HtmlSourceAdapter


class HtmlSourceAdapterTests(unittest.TestCase):
    def test_html_adapter_extracts_configured_entries_and_components(self) -> None:
        spec = SourceSpec(
            name="Example HTML",
            type="html",
            url="https://status.example.com",
            options={
                "selectors": [".incident"],
                "component_selectors": [".component"],
            },
        )
        payload = b"""
        <html>
          <head>
            <title>Example Status</title>
            <meta name='description' content='Example status page'>
          </head>
          <body>
            <section class='incident'>
              <h2>Investigating API errors</h2>
              <p>We are investigating elevated API errors.</p>
              <time datetime='2026-03-25T17:00:00Z'></time>
              <a href='/incidents/api-errors'>More</a>
            </section>
            <section class='component' data-status='partial_outage'>
              <strong>API</strong>
              <p>Requests are degraded.</p>
              <time datetime='2026-03-25T16:58:00Z'></time>
            </section>
          </body>
        </html>
        """

        with patch("status_watcher.sources.html_page.fetch_url", return_value=payload):
            snapshot = HtmlSourceAdapter().load(spec)

        self.assertEqual(len(snapshot.entries), 1)
        self.assertEqual(snapshot.entries[0].title, "Investigating API errors")
        self.assertIn("elevated API errors", snapshot.entries[0].summary)
        self.assertEqual(snapshot.entries[0].link, "https://status.example.com/incidents/api-errors")
        self.assertEqual(len(snapshot.components), 1)
        self.assertEqual(snapshot.components[0].name, "API")
        self.assertEqual(snapshot.components[0].status, "degraded")
        self.assertEqual(snapshot.components[0].label, "Partial outage")


if __name__ == "__main__":
    unittest.main()
