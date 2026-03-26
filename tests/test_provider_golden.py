from __future__ import annotations

import unittest

from unittest.mock import patch

from status_watcher.domain import infer_service_status
from status_watcher.models import SourceSpec
from status_watcher.sources.html_page import HtmlSourceAdapter
from status_watcher.sources.json_api import JsonSourceAdapter
from status_watcher.sources.statuspage import parse_statuspage_components, parse_statuspage_entries
from tests.fixture_utils import load_fixture_bytes, load_fixture_json


class ProviderGoldenTests(unittest.TestCase):
    def test_claude_statuspage_fixture_matches_expected_snapshot(self) -> None:
        summary = load_fixture_json("providers", "claude_statuspage_summary.json")
        incidents = load_fixture_json("providers", "claude_statuspage_incidents.json")

        entries = parse_statuspage_entries(summary, incidents, recent_incidents=5)
        components = parse_statuspage_components(summary)
        status = infer_service_status("Claude", "https://status.claude.com", entries, components)

        self.assertEqual(status.severity, "issue")
        self.assertEqual(status.headline, "Investigating - Elevated connection reset errors in Cowork")
        self.assertEqual(len(status.current_incidents), 1)
        self.assertEqual(status.current_incidents[0].title, "Investigating - Elevated connection reset errors in Cowork")
        self.assertCountEqual(
            [component.name for component in status.components],
            [
                "claude.ai",
                "platform.claude.com (formerly console.anthropic.com)",
                "Claude API (api.anthropic.com)",
                "Claude Code",
                "Claude for Government",
            ],
        )

    def test_github_status_json_fixture_matches_expected_snapshot(self) -> None:
        spec = SourceSpec(
            name="GitHub",
            type="json",
            url="https://www.githubstatus.com/api/v2/status.json",
            options={
                "entries_path": "",
                "title_path": "status.description",
                "summary_path": "page.name",
                "updated_path": "page.updated_at",
            },
        )

        with patch(
            "status_watcher.sources.json_api.fetch_url",
            return_value=load_fixture_bytes("providers", "github_status.json"),
        ), patch("status_watcher.sources.json_api.store_cached_response"):
            snapshot = JsonSourceAdapter().load(spec)

        status = infer_service_status(spec.name, spec.url, snapshot.entries, snapshot.components)
        self.assertEqual(len(snapshot.entries), 1)
        self.assertEqual(snapshot.entries[0].title, "All Systems Operational")
        self.assertEqual(snapshot.entries[0].summary, "GitHub")
        self.assertEqual(status.severity, "operational")
        self.assertEqual(status.headline, "Operational")

    def test_claude_status_html_fixture_matches_expected_snapshot(self) -> None:
        spec = SourceSpec(
            name="Claude",
            type="html",
            url="https://status.claude.com",
            options={
                "selectors": [".unresolved-incident"],
                "component_selectors": ["[data-component-id]"],
            },
        )

        with patch(
            "status_watcher.sources.html_page.fetch_url",
            return_value=load_fixture_bytes("providers", "claude_status.html"),
        ):
            snapshot = HtmlSourceAdapter().load(spec)

        status = infer_service_status(spec.name, spec.url, snapshot.entries, snapshot.components)
        self.assertEqual(len(snapshot.entries), 1)
        self.assertEqual(snapshot.entries[0].title, "Elevated connection reset errors in Cowork")
        self.assertEqual(len(snapshot.components), 5)
        self.assertEqual(snapshot.components[0].name, "claude.ai")
        self.assertTrue(all(component.status == "operational" for component in snapshot.components))
        self.assertEqual(status.severity, "issue")
        self.assertEqual(status.headline, "Elevated connection reset errors in Cowork")


if __name__ == "__main__":
    unittest.main()
