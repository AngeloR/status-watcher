from __future__ import annotations

import unittest

from unittest.mock import patch

from status_watcher.domain import infer_service_status
from status_watcher.presets import source_spec_from_preset
from status_watcher.sources import load_source_snapshot
from tests.fixture_utils import load_fixture_bytes


STATUSPAGE_PROVIDER_CASES = [
    ("claude", 5),
    ("openai", 20),
    ("github", 10),
    ("vercel", 50),
    ("linear", 5),
]


class ProviderGoldenTests(unittest.TestCase):
    def test_claude_statuspage_fixture_matches_expected_snapshot(self) -> None:
        spec = source_spec_from_preset("claude", options={"recent_incidents": 5})

        with patch(
            "status_watcher.sources.statuspage.fetch_url",
            side_effect=self.statuspage_fetcher("claude"),
        ), patch("status_watcher.sources.statuspage.store_cached_response"):
            snapshot = load_source_snapshot(spec)

        status = infer_service_status(spec.name, spec.url, snapshot.entries, snapshot.components)

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

    def test_statuspage_provider_presets_load_real_fixture_catalog(self) -> None:
        for preset_name, min_components in STATUSPAGE_PROVIDER_CASES:
            with self.subTest(preset=preset_name):
                spec = source_spec_from_preset(preset_name, options={"recent_incidents": 5})

                with patch(
                    "status_watcher.sources.statuspage.fetch_url",
                    side_effect=self.statuspage_fetcher(preset_name),
                ), patch("status_watcher.sources.statuspage.store_cached_response"):
                    snapshot = load_source_snapshot(spec)

                status = infer_service_status(spec.name, spec.url, snapshot.entries, snapshot.components)
                self.assertTrue(snapshot.entries)
                self.assertGreaterEqual(len(snapshot.components), min_components)
                self.assertEqual(status.name, spec.name)
                self.assertIn(status.severity, {"operational", "degraded", "issue"})
                self.assertTrue(all(component.name for component in snapshot.components))

    def test_github_status_json_fixture_matches_expected_snapshot(self) -> None:
        spec = source_spec_from_preset("github-json")

        with patch(
            "status_watcher.sources.json_api.fetch_url",
            return_value=load_fixture_bytes("providers", "github_status.json"),
        ), patch("status_watcher.sources.json_api.store_cached_response"):
            snapshot = load_source_snapshot(spec)

        status = infer_service_status(spec.name, spec.url, snapshot.entries, snapshot.components)
        self.assertEqual(len(snapshot.entries), 1)
        self.assertEqual(snapshot.entries[0].title, "All Systems Operational")
        self.assertEqual(snapshot.entries[0].summary, "GitHub")
        self.assertEqual(status.severity, "operational")
        self.assertEqual(status.headline, "Operational")

    def test_claude_status_html_fixture_matches_expected_snapshot(self) -> None:
        spec = source_spec_from_preset("claude-html")

        with patch(
            "status_watcher.sources.html_page.fetch_url",
            return_value=load_fixture_bytes("providers", "claude_status.html"),
        ):
            snapshot = load_source_snapshot(spec)

        status = infer_service_status(spec.name, spec.url, snapshot.entries, snapshot.components)
        self.assertEqual(len(snapshot.entries), 1)
        self.assertEqual(snapshot.entries[0].title, "Elevated connection reset errors in Cowork")
        self.assertEqual(len(snapshot.components), 5)
        self.assertEqual(snapshot.components[0].name, "claude.ai")
        self.assertTrue(all(component.status == "operational" for component in snapshot.components))
        self.assertEqual(status.severity, "issue")
        self.assertEqual(status.headline, "Elevated connection reset errors in Cowork")

    def statuspage_fetcher(self, provider_name: str):
        summary = load_fixture_bytes("providers", f"{provider_name}_statuspage_summary.json")
        incidents = load_fixture_bytes("providers", f"{provider_name}_statuspage_incidents.json")

        def fetcher(url: str, accept: str = "", headers: dict[str, str] | None = None) -> bytes:
            del accept, headers
            if url.endswith("/summary.json"):
                return summary
            if url.endswith("/incidents.json"):
                return incidents
            raise AssertionError(f"Unexpected URL: {url}")

        return fetcher


if __name__ == "__main__":
    unittest.main()
