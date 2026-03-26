from __future__ import annotations

import io
import json
import tempfile
import unittest

from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from status_watcher.cli import main
from status_watcher.models import ComponentSnapshot, FeedEntry, SourceSnapshot


class CliTests(unittest.TestCase):
    def test_presets_command_lists_known_presets(self) -> None:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            exit_code = main(["presets"])

        self.assertEqual(exit_code, 0)
        output = stdout.getvalue()
        self.assertIn("claude", output)
        self.assertIn("github-json", output)

    def test_inspect_supports_preset_json_output(self) -> None:
        snapshot = SourceSnapshot(
            entries=[FeedEntry(title="All Systems Operational", summary="GitHub", updated=None)],
            components=[
                ComponentSnapshot(
                    name="API Requests",
                    status="operational",
                    label="Operational",
                    updated=None,
                )
            ],
        )

        stdout = io.StringIO()
        with patch("status_watcher.cli.load_source_snapshot", return_value=snapshot), redirect_stdout(stdout):
            exit_code = main(["inspect", "--preset", "github-json", "--json"])

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["spec"]["type"], "json")
        self.assertEqual(payload["spec"]["url"], "https://www.githubstatus.com/api/v2/status.json")
        self.assertEqual(payload["headline"], "Operational")
        self.assertEqual(payload["components"][0]["name"], "API Requests")

    def test_inspect_selects_named_source_from_config(self) -> None:
        snapshot = SourceSnapshot(
            entries=[FeedEntry(title="Operational", summary="No active issues", updated=None)],
            components=[],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "feeds.json"
            path.write_text(
                json.dumps(
                    [
                        {"preset": "claude"},
                        {"preset": "openai", "recent_incidents": 3},
                    ]
                ),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with patch("status_watcher.cli.load_source_snapshot", return_value=snapshot), redirect_stdout(stdout):
                exit_code = main(["inspect", "OpenAI", str(path)])

        self.assertEqual(exit_code, 0)
        output = stdout.getvalue()
        self.assertIn("Source: OpenAI", output)
        self.assertIn("Type: statuspage", output)
        self.assertIn("Entries: 1", output)


if __name__ == "__main__":
    unittest.main()
