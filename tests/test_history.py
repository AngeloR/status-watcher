from __future__ import annotations

import datetime as dt
import tempfile
import unittest

from pathlib import Path

from status_watcher.history import HistoryStore
from status_watcher.models import ComponentSnapshot, IncidentSnapshot, ServiceStatus


class HistoryTests(unittest.TestCase):
    def test_history_store_tracks_open_and_resolved_incidents(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = HistoryStore(path=str(Path(tmpdir) / "state.json"))
            now = dt.datetime(2026, 3, 25, 17, 0, tzinfo=dt.timezone.utc)

            operational = ServiceStatus(
                name="Claude",
                url="https://status.claude.com",
                ok=True,
                severity="operational",
                headline="Operational",
                details="All clear.",
                updated=now,
            )
            issue = ServiceStatus(
                name="Claude",
                url="https://status.claude.com",
                ok=False,
                severity="issue",
                headline="Investigating - Elevated errors on claude.ai",
                details="Investigating.",
                updated=now + dt.timedelta(minutes=5),
                current_incidents=[
                    IncidentSnapshot(
                        title="Investigating - Elevated errors on claude.ai",
                        summary="Investigating.",
                        updated=now + dt.timedelta(minutes=5),
                        state="issue",
                        key="elevated errors on claude ai",
                    )
                ],
            )

            first = store.apply([operational])[0]
            second = store.apply([issue])[0]
            third = store.apply([operational])[0]

            self.assertEqual(first.recent_changes, [])
            self.assertEqual(second.recent_changes[0].kind, "opened")
            self.assertIn("New incident", second.recent_changes[0].message)
            self.assertEqual(third.recent_changes[0].kind, "resolved")
            self.assertIn("Resolved", third.recent_changes[0].message)

    def test_history_store_tracks_component_degradation_and_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = HistoryStore(path=str(Path(tmpdir) / "state.json"))
            now = dt.datetime(2026, 3, 25, 17, 0, tzinfo=dt.timezone.utc)

            operational = ServiceStatus(
                name="Example",
                url="https://status.example.com",
                ok=True,
                severity="operational",
                headline="Operational",
                details="All clear.",
                updated=now,
                components=[
                    ComponentSnapshot(
                        name="API",
                        status="operational",
                        label="Operational",
                        updated=now,
                    )
                ],
            )
            degraded = ServiceStatus(
                name="Example",
                url="https://status.example.com",
                ok=False,
                severity="issue",
                headline="API major outage",
                details="API is unavailable.",
                updated=now + dt.timedelta(minutes=5),
                components=[
                    ComponentSnapshot(
                        name="API",
                        status="issue",
                        label="Major outage",
                        updated=now + dt.timedelta(minutes=5),
                        details="API is unavailable.",
                    )
                ],
            )

            store.apply([operational])
            second = store.apply([degraded])[0]
            third = store.apply([operational])[0]

            self.assertIn("Component issue: API is Major outage", second.recent_changes[0].message)
            self.assertEqual(third.recent_changes[0].kind, "resolved")
            self.assertIn("Component recovered: API", third.recent_changes[0].message)

    def test_history_store_persists_changes_across_reloads(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "state.json")
            now = dt.datetime(2026, 3, 25, 17, 0, tzinfo=dt.timezone.utc)
            issue = ServiceStatus(
                name="Claude",
                url="https://status.claude.com",
                ok=False,
                severity="issue",
                headline="Investigating - Elevated errors on claude.ai",
                details="Investigating.",
                updated=now,
                current_incidents=[
                    IncidentSnapshot(
                        title="Investigating - Elevated errors on claude.ai",
                        summary="Investigating.",
                        updated=now,
                        state="issue",
                        key="elevated errors on claude ai",
                    )
                ],
            )
            operational = ServiceStatus(
                name="Claude",
                url="https://status.claude.com",
                ok=True,
                severity="operational",
                headline="Operational",
                details="Recovered.",
                updated=now + dt.timedelta(minutes=10),
            )

            store = HistoryStore(path=path)
            store.apply([issue])
            store.apply([operational])

            reloaded = HistoryStore(path=path)
            status = reloaded.apply([operational])[0]

            self.assertGreaterEqual(len(status.recent_changes), 1)
            self.assertEqual(status.recent_changes[0].kind, "resolved")


if __name__ == "__main__":
    unittest.main()
