from __future__ import annotations

import json

from dataclasses import replace
from pathlib import Path
from typing import Dict, List, Optional

from status_watcher.config import DEFAULT_STATE_PATH, MAX_HISTORY_EVENTS_PER_SERVICE
from status_watcher.domain import now_utc, parse_date
from status_watcher.models import ComponentSnapshot, HistoryEvent, IncidentSnapshot, ServiceStatus


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

            stored_incidents = status.current_incidents
            stored_components = status.components
            if status.severity == "error" and previous:
                stored_incidents = self._deserialize_incidents(previous.get("current_incidents", []))
                stored_components = self._deserialize_components(previous.get("components", []))

            services[service_key] = {
                "name": status.name,
                "url": status.url,
                "severity": status.severity,
                "headline": status.headline,
                "updated": self._serialize_datetime(status.updated),
                "current_incidents": [self._serialize_incident(incident) for incident in stored_incidents],
                "components": [self._serialize_component(component) for component in stored_components],
                "history": [self._serialize_event(event) for event in history[:MAX_HISTORY_EVENTS_PER_SERVICE]],
            }
            enriched.append(replace(status, recent_changes=history[:5]))

        self._save()
        return enriched

    def _detect_changes(self, previous: Optional[Dict[str, object]], status: ServiceStatus) -> List[HistoryEvent]:
        if not previous:
            return []

        if status.severity == "error":
            previous_severity = str(previous.get("severity") or "")
            previous_headline = str(previous.get("headline") or "")
            if previous_severity != status.severity or previous_headline != status.headline:
                return [
                    HistoryEvent(
                        timestamp=status.updated or now_utc(),
                        kind="updated",
                        message=f"Status change: {status.headline}",
                        severity=status.severity,
                    )
                ]
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

        events.extend(self._detect_component_changes(previous, status.components))
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

    def _detect_component_changes(self, previous: Dict[str, object], components: List[ComponentSnapshot]) -> List[HistoryEvent]:
        previous_components = {
            str(item.get("name") or ""): item
            for item in previous.get("components", [])
            if isinstance(item, dict) and item.get("name")
        }
        current_components = {component.name: component for component in components if component.name}

        events: List[HistoryEvent] = []
        for name, component in current_components.items():
            previous_component = previous_components.get(name)
            if previous_component is None:
                if component.status != "operational":
                    events.append(
                        HistoryEvent(
                            timestamp=component.updated or now_utc(),
                            kind="opened",
                            message=f"Component issue: {name} is {component.label}",
                            severity=component.status,
                        )
                    )
                continue

            previous_status = str(previous_component.get("status") or "unknown")
            previous_label = str(previous_component.get("label") or previous_status.title())
            if previous_status == component.status and previous_label == component.label:
                continue

            if previous_status != "operational" and component.status == "operational":
                kind = "resolved"
                message = f"Component recovered: {name}"
                severity = "operational"
            elif previous_status == "operational" and component.status != "operational":
                kind = "opened"
                message = f"Component issue: {name} is {component.label}"
                severity = component.status
            else:
                kind = "updated"
                message = f"Component update: {name} is {component.label}"
                severity = component.status

            events.append(
                HistoryEvent(
                    timestamp=component.updated or now_utc(),
                    kind=kind,
                    message=message,
                    severity=severity,
                )
            )

        for name, previous_component in previous_components.items():
            if name in current_components:
                continue
            previous_status = str(previous_component.get("status") or "unknown")
            if previous_status == "operational":
                continue
            events.append(
                HistoryEvent(
                    timestamp=parse_date(str(previous_component.get("updated") or "")) or now_utc(),
                    kind="resolved",
                    message=f"Component recovered: {name}",
                    severity="operational",
                )
            )

        return events

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

    def _serialize_component(self, component: ComponentSnapshot) -> Dict[str, object]:
        return {
            "name": component.name,
            "status": component.status,
            "label": component.label,
            "updated": self._serialize_datetime(component.updated),
            "details": component.details,
            "link": component.link,
        }

    def _serialize_event(self, event: HistoryEvent) -> Dict[str, object]:
        return {
            "timestamp": self._serialize_datetime(event.timestamp),
            "kind": event.kind,
            "message": event.message,
            "severity": event.severity,
        }

    def _deserialize_incidents(self, items: List[object]) -> List[IncidentSnapshot]:
        incidents: List[IncidentSnapshot] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            incidents.append(
                IncidentSnapshot(
                    title=str(item.get("title") or ""),
                    summary="",
                    updated=parse_date(str(item.get("updated") or "")),
                    state=str(item.get("state") or "unknown"),
                    key=str(item.get("key") or ""),
                )
            )
        return incidents

    def _deserialize_components(self, items: List[object]) -> List[ComponentSnapshot]:
        components: List[ComponentSnapshot] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            components.append(
                ComponentSnapshot(
                    name=str(item.get("name") or ""),
                    status=str(item.get("status") or "unknown"),
                    label=str(item.get("label") or "Unknown"),
                    updated=parse_date(str(item.get("updated") or "")),
                    details=str(item.get("details") or ""),
                    link=str(item.get("link") or ""),
                )
            )
        return components

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
