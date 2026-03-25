from __future__ import annotations

import unittest

from status_watcher.sources.statuspage import normalize_statuspage_base, parse_statuspage_entries


class StatuspageTests(unittest.TestCase):
    def test_normalize_statuspage_base_accepts_public_or_api_urls(self) -> None:
        self.assertEqual(normalize_statuspage_base("https://status.claude.com"), "https://status.claude.com")
        self.assertEqual(
            normalize_statuspage_base("https://status.claude.com/api/v2/summary.json"),
            "https://status.claude.com",
        )

    def test_parse_statuspage_entries_keeps_active_and_recent_incident_updates(self) -> None:
        summary_payload = {
            "page": {"url": "https://status.example.com", "updated_at": "2026-03-25T16:58:51.250Z"},
            "components": [
                {"name": "App", "status": "partial_outage", "updated_at": "2026-03-25T16:58:26.477Z"}
            ],
            "incidents": [
                {
                    "id": "active-1",
                    "name": "Elevated errors on App",
                    "status": "investigating",
                    "updated_at": "2026-03-25T16:58:26.516Z",
                    "shortlink": "https://stspg.io/active-1",
                    "components": [{"name": "App"}],
                    "incident_updates": [
                        {
                            "status": "investigating",
                            "body": "We are currently investigating this issue.",
                            "display_at": "2026-03-25T16:58:26.513Z",
                            "affected_components": [{"name": "App"}],
                        }
                    ],
                }
            ],
            "scheduled_maintenances": [],
            "status": {"indicator": "minor", "description": "Minor Service Outage"},
        }
        incidents_payload = {
            "incidents": [
                {
                    "id": "active-1",
                    "name": "Elevated errors on App",
                    "status": "investigating",
                    "updated_at": "2026-03-25T16:58:26.516Z",
                    "shortlink": "https://stspg.io/active-1",
                    "components": [{"name": "App"}],
                    "incident_updates": [
                        {
                            "status": "investigating",
                            "body": "We are currently investigating this issue.",
                            "display_at": "2026-03-25T16:58:26.513Z",
                            "affected_components": [{"name": "App"}],
                        }
                    ],
                },
                {
                    "id": "resolved-1",
                    "name": "Earlier outage",
                    "status": "resolved",
                    "updated_at": "2026-03-25T15:43:20.034Z",
                    "shortlink": "https://stspg.io/resolved-1",
                    "components": [{"name": "App"}],
                    "incident_updates": [
                        {
                            "status": "resolved",
                            "body": "This incident has been resolved.",
                            "display_at": "2026-03-25T15:43:20.034Z",
                            "affected_components": [{"name": "App"}],
                        }
                    ],
                },
            ]
        }

        entries = parse_statuspage_entries(summary_payload, incidents_payload, recent_incidents=2)

        titles = [entry.title for entry in entries]
        self.assertIn("Investigating - Elevated errors on App", titles)
        self.assertIn("Resolved - Earlier outage", titles)
        self.assertIn("Partial outage - App", titles)

    def test_parse_statuspage_entries_synthesizes_operational_entry_when_empty(self) -> None:
        summary_payload = {
            "page": {"url": "https://status.example.com", "updated_at": "2026-03-25T16:58:51.250Z"},
            "components": [{"name": "App", "status": "operational"}],
            "incidents": [],
            "scheduled_maintenances": [],
            "status": {"indicator": "none", "description": "All Systems Operational"},
        }
        incidents_payload = {"incidents": []}

        entries = parse_statuspage_entries(summary_payload, incidents_payload, recent_incidents=0)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].title, "All Systems Operational")
        self.assertIn("operational", entries[0].summary.lower())


if __name__ == "__main__":
    unittest.main()
