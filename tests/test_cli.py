from __future__ import annotations

import io
import json
import tempfile
import unittest

from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from status_watcher.cli import main
from status_watcher.discovery import DiscoveryResult
from status_watcher.models import ComponentSnapshot, FeedEntry, SourceSnapshot, SourceSpec


class CliTests(unittest.TestCase):
    def test_presets_command_lists_known_presets(self) -> None:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            exit_code = main(["presets"])

        self.assertEqual(exit_code, 0)
        output = stdout.getvalue()
        self.assertIn("azure", output)
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

    def test_discover_command_renders_detected_config(self) -> None:
        result = DiscoveryResult(
            spec=SourceSpec(name="Claude", type="statuspage", url="https://status.claude.com"),
            config_entry={"preset": "claude"},
            detection="statuspage probe",
            preset="claude",
        )

        stdout = io.StringIO()
        with patch("status_watcher.cli.discover_source", return_value=result), redirect_stdout(stdout):
            exit_code = main(["discover", "Claude", "https://status.claude.com"])

        self.assertEqual(exit_code, 0)
        output = stdout.getvalue()
        self.assertIn("Detected: statuspage", output)
        self.assertIn('"preset": "claude"', output)

    def test_add_command_writes_discovered_entry_to_config(self) -> None:
        result = DiscoveryResult(
            spec=SourceSpec(name="Claude", type="statuspage", url="https://status.claude.com"),
            config_entry={"preset": "claude"},
            detection="statuspage probe",
            preset="claude",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "feeds.json"

            stdout = io.StringIO()
            with patch("status_watcher.cli.discover_source", return_value=result), redirect_stdout(stdout):
                exit_code = main(["add", "Claude", "https://status.claude.com", str(path)])

            self.assertEqual(exit_code, 0)
            written = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(written, [{"preset": "claude"}])

            with patch("status_watcher.cli.discover_source", return_value=result), redirect_stdout(io.StringIO()):
                second_exit_code = main(["add", "Claude", "https://status.claude.com", str(path)])

            self.assertEqual(second_exit_code, 0)
            rewritten = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(rewritten, [{"preset": "claude"}])

    def test_add_command_accepts_empty_existing_config_file(self) -> None:
        result = DiscoveryResult(
            spec=SourceSpec(name="OpenAI", type="statuspage", url="https://status.openai.com"),
            config_entry={"preset": "openai"},
            detection="statuspage probe",
            preset="openai",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "feeds.json"
            path.write_text("", encoding="utf-8")

            with patch("status_watcher.cli.discover_source", return_value=result), redirect_stdout(io.StringIO()):
                exit_code = main(["add", "OpenAI", "https://status.openai.com", str(path)])

            self.assertEqual(exit_code, 0)
            written = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(written, [{"preset": "openai"}])


if __name__ == "__main__":
    unittest.main()
