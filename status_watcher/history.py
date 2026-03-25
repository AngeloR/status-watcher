from __future__ import annotations

import json

from dataclasses import replace
from pathlib import Path
from typing import Dict, List, Optional

from status_watcher.config import DEFAULT_STATE_PATH, MAX_HISTORY_EVENTS_PER_SERVICE
from status_watcher.domain import now_utc, parse_date
from status_watcher.models import HistoryEvent, IncidentSnapshot, ServiceStatus


class HistoryStore:
    def __init__(self, path: Optional[str] = None) -> None:
        self.path = Path(path or DEFAULT_STATE_PATH)
        self.state = self._load()

    def apply(self, statuses: List[ServiceStatus]) -> List[ServiceStatus]:
        services = self.state.setdefault("services", {})
        enriched: List[ServiceStatus] = []

        for status in statuses:
            service_key = self._service_key(status)
            previous = services.get(service_key)
            history = self._deserialize_history(previous.get("history", [])) if previous else []
            new_events = self._detect_changes(previous, status)
            if new_events:
                history = (new_events + history)[:MAX_HISTORY_EVENTS_PER_SERVICE]

            services[service_key] = {
                "name": status.name,
                "url": status.url,
                "severity": status.severity,
                "headline": status.headline,
                "updated": self._serialize_datetime(status.updated),
                "current_incidents": [self._serialize_incident(incident) for incident in status.current_incidents],
                "history": [self._serialize_event(event) for event in history[:MAX_HISTORY_EVENTS_PER_SERVICE]],
            }
            enriched.append(replace(status, recent_changes=history[:5]))

        self._save()
        return enriched

    def _detect_changes(self, previous: Optional[Dict[str, object]], status: ServiceStatus) -> List[HistoryEvent]:
        if not previous:
            return []

        previous_incidents = {
            item.get("key") or item.get("title") or "": item.get("title") or "Incident"
            for item in previous.get("current_incidents", [])
            if isinstance(item, dict)
        }
        current_incidents = {
            (incident.key or incident.title): incident.title or "Incident"
            for incident in status.current_incidents
            if incident.key or incident.title
        }

        events: List[HistoryEvent] = []
        opened = [key for key in current_incidents if key not in previous_incidents]
        resolved = [key for key in previous_incidents if key not in current_incidents]

        for key in opened:
            incident = next((item for item in status.current_incidents if (item.key or item.title) == key), None)
            events.append(
                HistoryEvent(
                    timestamp=(incident.updated if incident else status.updated) or now_utc(),
                    kind="opened",
                    message=f"New incident: {current_incidents[key]}",
                    severity=status.severity,
                )
            )

        for key in resolved:
            events.append(
                HistoryEvent(
                    timestamp=status.updated or now_utc(),
                    kind="resolved",
                    message=f"Resolved: {previous_incidents[key]}",
                    severity="operational" if status.ok else status.severity,
                )
            )

        if events:
            return events

        previous_severity = str(previous.get("severity") or "")
        previous_headline = str(previous.get("headline") or "")
        if previous_severity != status.severity or previous_headline != status.headline:
            label = "Status update" if status.current_incidents else "Status change"
            return [
                HistoryEvent(
                    timestamp=status.updated or now_utc(),
                    kind="updated",
                    message=f"{label}: {status.headline}",
                    severity=status.severity,
                )
            ]

        return []

    def _load(self) -> Dict[str, object]:
        if not self.path.exists():
            return {"services": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {"services": {}}
        if not isinstance(data, dict):
            return {"services": {}}
        services = data.get("services")
        if not isinstance(services, dict):
            return {"services": {}}
        return {"services": services}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.state, indent=2), encoding="utf-8")

    def _service_key(self, status: ServiceStatus) -> str:
        return f"{status.name}|{status.url}"

    def _serialize_datetime(self, value):
        return value.isoformat() if value else None

    def _serialize_incident(self, incident: IncidentSnapshot) -> Dict[str, object]:
        return {
            "key": incident.key,
            "title": incident.title,
            "state": incident.state,
            "updated": self._serialize_datetime(incident.updated),
        }

    def _serialize_event(self, event: HistoryEvent) -> Dict[str, object]:
        return {
            "timestamp": self._serialize_datetime(event.timestamp),
            "kind": event.kind,
            "message": event.message,
            "severity": event.severity,
        }

    def _deserialize_history(self, items: List[object]) -> List[HistoryEvent]:
        events: List[HistoryEvent] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            events.append(
                HistoryEvent(
                    timestamp=parse_date(str(item.get("timestamp") or "")),
                    kind=str(item.get("kind") or "updated"),
                    message=str(item.get("message") or ""),
                    severity=str(item.get("severity") or "unknown"),
                )
            )
        return events
