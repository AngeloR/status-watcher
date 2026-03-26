from __future__ import annotations

import datetime as dt
import unittest

from status_watcher.domain import classify_entry, infer_service_status, normalize_incident_key
from status_watcher.models import ComponentSnapshot, FeedEntry


class DomainTests(unittest.TestCase):
    def test_normalize_incident_key_matches_gcp_style_active_and_resolved_updates(self) -> None:
        active = normalize_incident_key(
            "Issue impacting multiple GCP services",
            "We are experiencing an issue with multiple dependent GCP services.",
        )
        resolved = normalize_incident_key(
            "Issue impacting multiple GCP services resolved",
            "The issue with multiple dependent GCP services has been resolved.",
        )

        self.assertEqual(active, resolved)

    def test_resolved_entry_wins_over_monitoring_wording(self) -> None:
        entry = FeedEntry(
            title="Resolved - Incident on GCP",
            summary="The issue has been resolved and we are monitoring recovery.",
            updated=None,
        )

        classified = classify_entry(entry)

        self.assertEqual(classified["state"], "resolved")

    def test_active_title_wins_when_summary_mentions_possible_resolution(self) -> None:
        entry = FeedEntry(
            title="Investigating - Elevated connection reset errors in Cowork",
            summary="This issue can be resolved by restarting the Claude Desktop application.",
            updated=None,
        )

        classified = classify_entry(entry)

        self.assertEqual(classified["state"], "issue")

    def test_no_active_events_wording_does_not_mark_entry_as_degraded(self) -> None:
        entry = FeedEntry(
            title="There are currently no active events",
            summary="Use Azure Service Health to view other issues that may be impacting your services.",
            updated=None,
        )

        classified = classify_entry(entry)

        self.assertEqual(classified["state"], "unknown")

    def test_infer_service_status_keeps_multiple_live_incidents(self) -> None:
        now = dt.datetime(2026, 3, 25, 14, 33, tzinfo=dt.timezone.utc)
        entries = [
            FeedEntry(
                title="Identified - Elevated Errors on claude.ai",
                summary="The issue has been identified and a fix is being implemented.",
                updated=now,
            ),
            FeedEntry(
                title="Investigating - Elevated Errors on claude.ai",
                summary="We are currently investigating this issue.",
                updated=now - dt.timedelta(minutes=40),
            ),
            FeedEntry(
                title="Investigating - Elevated connection reset errors in Cowork",
                summary="We are currently investigating this issue.",
                updated=now - dt.timedelta(minutes=5),
            ),
        ]

        status = infer_service_status("Claude", "https://status.claude.com/history.atom", entries)

        self.assertEqual(status.severity, "issue")
        self.assertEqual(status.headline, "2 live incidents")
        self.assertEqual(len(status.current_incidents), 2)
        self.assertEqual(status.current_incidents[0].title, "Identified - Elevated Errors on claude.ai")
        self.assertEqual(status.current_incidents[1].title, "Investigating - Elevated connection reset errors in Cowork")

    def test_infer_service_status_uses_components_when_no_incidents_exist(self) -> None:
        now = dt.datetime(2026, 3, 25, 14, 33, tzinfo=dt.timezone.utc)
        components = [
            ComponentSnapshot(
                name="API",
                status="issue",
                label="Major outage",
                updated=now,
                details="API is currently unavailable.",
            ),
            ComponentSnapshot(
                name="Dashboard",
                status="operational",
                label="Operational",
                updated=now,
            ),
        ]

        status = infer_service_status("Example", "https://status.example.com", [], components)

        self.assertEqual(status.severity, "issue")
        self.assertEqual(status.headline, "API major outage")
        self.assertEqual(len(status.components), 2)
        self.assertIn("unavailable", status.details.lower())


if __name__ == "__main__":
    unittest.main()
