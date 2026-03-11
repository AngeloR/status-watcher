from __future__ import annotations

import unittest

from status_watcher.domain import classify_entry, normalize_incident_key
from status_watcher.models import FeedEntry


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


if __name__ == "__main__":
    unittest.main()
