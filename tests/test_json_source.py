from __future__ import annotations

import unittest

from unittest.mock import patch

from status_watcher.models import SourceSpec
from status_watcher.sources.json_api import JsonSourceAdapter


class JsonSourceAdapterTests(unittest.TestCase):
    def test_json_adapter_extracts_entries_and_components_from_nested_paths(self) -> None:
        spec = SourceSpec(
            name="Example API",
            type="json",
            url="https://status.example.com/api/status.json",
            options={
                "entries_path": "data.events[]",
                "components_path": "data.components[]",
                "summary_path": "details.text",
            },
        )
        payload = b'''{
            "data": {
                "events": [
                    {
                        "title": "Investigating",
                        "details": {"text": "We are investigating elevated errors."},
                        "updated_at": "2026-03-25T17:00:00Z",
                        "link": "/incidents/1"
                    }
                ],
                "components": [
                    {
                        "name": "API",
                        "status": "major_outage",
                        "updated_at": "2026-03-25T16:58:00Z",
                        "description": "API requests are failing."
                    }
                ]
            }
        }'''

        with patch("status_watcher.sources.json_api.fetch_url", return_value=payload), patch(
            "status_watcher.sources.json_api.store_cached_response"
        ):
            snapshot = JsonSourceAdapter().load(spec)

        self.assertEqual(len(snapshot.entries), 1)
        self.assertEqual(snapshot.entries[0].title, "Investigating")
        self.assertIn("elevated errors", snapshot.entries[0].summary)
        self.assertEqual(snapshot.entries[0].link, "https://status.example.com/incidents/1")
        self.assertEqual(len(snapshot.components), 1)
        self.assertEqual(snapshot.components[0].name, "API")
        self.assertEqual(snapshot.components[0].status, "issue")
        self.assertEqual(snapshot.components[0].label, "Major outage")


if __name__ == "__main__":
    unittest.main()
