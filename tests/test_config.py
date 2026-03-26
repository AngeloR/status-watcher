from __future__ import annotations

import json
import tempfile
import unittest

from pathlib import Path

from status_watcher.config import load_source_specs_from_file


class ConfigTests(unittest.TestCase):
    def test_back_compat_feed_config_defaults_to_feed_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "feeds.json"
            path.write_text(
                json.dumps([{"name": "Claude", "url": "https://status.claude.com/history.atom"}]),
                encoding="utf-8",
            )

            specs = load_source_specs_from_file(str(path))

        self.assertEqual(len(specs), 1)
        self.assertEqual(specs[0].type, "feed")
        self.assertEqual(specs[0].options, {})

    def test_extra_fields_are_stored_in_options(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "feeds.json"
            path.write_text(
                json.dumps(
                    [
                        {
                            "name": "Example",
                            "type": "html",
                            "url": "https://example.com/status",
                            "selector": ".incident",
                        }
                    ]
                ),
                encoding="utf-8",
            )

            specs = load_source_specs_from_file(str(path))

        self.assertEqual(specs[0].type, "html")
        self.assertEqual(specs[0].options, {"selector": ".incident"})

    def test_json_source_config_preserves_nested_path_options(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "feeds.json"
            path.write_text(
                json.dumps(
                    [
                        {
                            "name": "Example API",
                            "type": "json",
                            "url": "https://status.example.com/api.json",
                            "entries_path": "data.events[]",
                            "components_path": "data.components[]",
                        }
                    ]
                ),
                encoding="utf-8",
            )

            specs = load_source_specs_from_file(str(path))

        self.assertEqual(specs[0].type, "json")
        self.assertEqual(specs[0].options["entries_path"], "data.events[]")
        self.assertEqual(specs[0].options["components_path"], "data.components[]")


if __name__ == "__main__":
    unittest.main()
