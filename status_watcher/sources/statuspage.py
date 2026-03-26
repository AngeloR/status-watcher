from __future__ import annotations

import json

from typing import Any, Dict, List
from urllib.parse import urljoin

from status_watcher.domain import normalize_component_status, parse_date
from status_watcher.models import ComponentSnapshot, FeedEntry, SourceSnapshot, SourceSpec
from status_watcher.sources.base import fetch_url, load_cached_response, store_cached_response


COMPONENT_STATUS_LABELS = {
    "operational": "Operational",
    "degraded_performance": "Degraded performance",
    "partial_outage": "Partial outage",
    "major_outage": "Major outage",
    "under_maintenance": "Under maintenance",
}

ACTIVE_STATUSES = {"investigating", "identified", "monitoring", "in_progress", "verifying"}


def normalize_statuspage_base(url: str) -> str:
    base = url.strip().rstrip("/")
    marker = "/api/v2/"
    if marker in base:
        base = base.split(marker, 1)[0]
    return base


def statuspage_endpoint(base_url: str, path: str) -> str:
    return urljoin(base_url + "/", f"api/v2/{path}")


def decode_statuspage_json(raw: bytes, path: str) -> Dict[str, Any]:
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Unexpected Statuspage payload for {path}")
    return data


def fetch_statuspage_json(base_url: str, path: str) -> Dict[str, Any]:
    url = statuspage_endpoint(base_url, path)
    raw = fetch_url(url, accept="application/json, */*;q=0.1")
    try:
        data = decode_statuspage_json(raw, path)
    except Exception:
        cached = load_cached_response(url)
        if cached is None or cached == raw:
            raise
        data = decode_statuspage_json(cached, path)
        store_cached_response(url, cached)
        return data

    store_cached_response(url, raw)
    return data


def status_label(status: str) -> str:
    return COMPONENT_STATUS_LABELS.get(status, status.replace("_", " ").title())


def format_affected_components(update: Dict[str, Any], incident: Dict[str, Any]) -> str:
    affected = update.get("affected_components") or incident.get("components") or []
    names = [str(component.get("name", "")).strip() for component in affected if component.get("name")]
    names = [name for name in names if name]
    if not names:
        return ""
    return f"Affected: {', '.join(names)}."


def incident_update_to_entry(incident: Dict[str, Any], update: Dict[str, Any]) -> FeedEntry:
    update_status = str(update.get("status") or incident.get("status") or "update")
    title = f"{update_status.replace('_', ' ').title()} - {incident.get('name', 'Status incident')}"

    body_parts = [str(update.get("body") or "").strip(), format_affected_components(update, incident)]
    summary = " ".join(part for part in body_parts if part).strip()
    updated = parse_date(str(update.get("display_at") or update.get("updated_at") or incident.get("updated_at") or ""))
    link = str(incident.get("shortlink") or "")
    return FeedEntry(title=title, summary=summary, updated=updated, link=link)


def incident_fallback_entry(incident: Dict[str, Any]) -> FeedEntry:
    status = str(incident.get("status") or "update")
    components = format_affected_components({}, incident)
    title = f"{status.replace('_', ' ').title()} - {incident.get('name', 'Status incident')}"
    summary = components or "Statuspage incident with no updates provided."
    updated = parse_date(str(incident.get("updated_at") or incident.get("created_at") or ""))
    link = str(incident.get("shortlink") or "")
    return FeedEntry(title=title, summary=summary, updated=updated, link=link)


def maintenance_to_entries(maintenance: Dict[str, Any]) -> List[FeedEntry]:
    updates = maintenance.get("incident_updates") or []
    if updates:
        return [incident_update_to_entry(maintenance, update) for update in updates]
    return [incident_fallback_entry(maintenance)]


def incident_to_entries(incident: Dict[str, Any]) -> List[FeedEntry]:
    updates = incident.get("incident_updates") or []
    if updates:
        return [incident_update_to_entry(incident, update) for update in updates]
    return [incident_fallback_entry(incident)]


def synthesize_status_entry(summary_payload: Dict[str, Any]) -> FeedEntry:
    page = summary_payload.get("page") or {}
    status = summary_payload.get("status") or {}
    description = str(status.get("description") or "Operational")
    indicator = str(status.get("indicator") or "none")
    components = summary_payload.get("components") or []
    degraded = [str(component.get("name") or "").strip() for component in components if component.get("status") != "operational"]
    if degraded:
        details = f"Non-operational components: {', '.join(name for name in degraded if name)}."
    else:
        details = "All listed components are operational."
    title = description
    if indicator not in {"none", "operational"}:
        title = f"{description} ({indicator.replace('_', ' ')})"
    updated = parse_date(str(page.get("updated_at") or ""))
    page_url = str(page.get("url") or "")
    return FeedEntry(title=title, summary=details, updated=updated, link=page_url)


def parse_statuspage_entries(
    summary_payload: Dict[str, Any],
    incidents_payload: Dict[str, Any],
    recent_incidents: int = 10,
) -> List[FeedEntry]:
    summary_incidents = summary_payload.get("incidents") or []
    recent_incident_items = incidents_payload.get("incidents") or []
    unresolved_ids = {str(item.get("id") or "") for item in summary_incidents if item.get("id")}

    selected_incidents: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()
    for incident in list(summary_incidents) + list(recent_incident_items)[: max(0, recent_incidents)]:
        incident_id = str(incident.get("id") or "")
        if incident_id and incident_id in seen_ids:
            continue
        if incident_id:
            seen_ids.add(incident_id)
        selected_incidents.append(incident)

    entries: List[FeedEntry] = []
    for incident in selected_incidents:
        status = str(incident.get("status") or "")
        if incident.get("id") in unresolved_ids or status in ACTIVE_STATUSES or max(0, recent_incidents) > 0:
            entries.extend(incident_to_entries(incident))

    for maintenance in summary_payload.get("scheduled_maintenances") or []:
        entries.extend(maintenance_to_entries(maintenance))

    if not entries:
        entries.append(synthesize_status_entry(summary_payload))

    entries.sort(key=lambda entry: entry.updated or parse_date("1970-01-01T00:00:00+00:00"), reverse=True)
    return entries


def parse_statuspage_components(summary_payload: Dict[str, Any]) -> List[ComponentSnapshot]:
    page = summary_payload.get("page") or {}
    page_url = str(page.get("url") or "")
    components: List[ComponentSnapshot] = []
    for item in summary_payload.get("components") or []:
        if item.get("group"):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        raw_status = str(item.get("status") or "unknown")
        status, _ = normalize_component_status(raw_status)
        label = status_label(raw_status)
        details = f"Statuspage reports {name} as {label.lower()}."
        components.append(
            ComponentSnapshot(
                name=name,
                status=status,
                label=label,
                updated=parse_date(str(item.get("updated_at") or page.get("updated_at") or "")),
                details=details,
                link=page_url,
            )
        )
    return components


class StatuspageSourceAdapter:
    def load(self, spec: SourceSpec) -> SourceSnapshot:
        base_url = normalize_statuspage_base(spec.url)
        recent_incidents = int(spec.options.get("recent_incidents", 10))
        summary_payload = fetch_statuspage_json(base_url, "summary.json")
        incidents_payload = fetch_statuspage_json(base_url, "incidents.json")
        return SourceSnapshot(
            entries=parse_statuspage_entries(summary_payload, incidents_payload, recent_incidents=recent_incidents),
            components=parse_statuspage_components(summary_payload),
        )
