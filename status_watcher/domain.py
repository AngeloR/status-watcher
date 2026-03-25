from __future__ import annotations

import datetime as dt
import html
import re

from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional

from status_watcher.config import MAX_ENTRIES_PER_FEED
from status_watcher.models import FeedEntry, IncidentSnapshot, ServiceStatus


ACTIVE_TERMS = [
    "investigating",
    "identified",
    "monitoring",
    "degraded performance",
    "partial outage",
    "major outage",
    "outage",
    "service disruption",
    "elevated errors",
    "elevated error",
    "incident",
    "connection timeout",
    "timeouts",
    "unresponsive",
    "failing",
    "login issues",
    "performance issues",
    "disruption",
]

RESOLVED_TERMS = [
    "resolved",
    "completed",
    "operational",
    "recovered",
    "restored",
    "monitoring complete",
]

DEGRADED_TERMS = [
    "degraded",
    "partial outage",
    "elevated",
    "issue",
    "issues",
    "timeouts",
    "latency",
]

TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")
STATE_PREFIX_RE = re.compile(
    r"^(investigating|identified|monitoring|resolved|update|completed|in progress|scheduled)\s*-\s*",
    re.IGNORECASE,
)
STATE_SUFFIX_RE = re.compile(r"\b(resolved|completed|restored|recovered|operational)\b$", re.IGNORECASE)
INCIDENT_NOISE_PATTERNS = [
    re.compile(r"\bwe are experiencing (?:an )?issue with\b", re.IGNORECASE),
    re.compile(r"\bwe are aware of (?:an )?issue with\b", re.IGNORECASE),
    re.compile(r"\bwe have identified (?:an )?issue with\b", re.IGNORECASE),
    re.compile(r"\bthe issue with\b", re.IGNORECASE),
    re.compile(r"\bthis issue with\b", re.IGNORECASE),
    re.compile(r"\bhas been resolved\b", re.IGNORECASE),
    re.compile(r"\bhas now been resolved\b", re.IGNORECASE),
    re.compile(r"\bis resolved\b", re.IGNORECASE),
    re.compile(r"\bhas been restored\b", re.IGNORECASE),
    re.compile(r"\bhas recovered\b", re.IGNORECASE),
    re.compile(r"\b(investigating|identified|monitoring|resolved|completed|update)\b", re.IGNORECASE),
]
GENERIC_INCIDENT_KEYS = {
    "incident",
    "issue",
    "service issue",
    "degraded performance",
    "partial outage",
    "major outage",
    "outage",
}


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def strip_html(text: str) -> str:
    if not text:
        return ""
    text = html.unescape(text)
    text = TAG_RE.sub(" ", text)
    return SPACE_RE.sub(" ", text).strip()


def parse_date(value: str) -> Optional[dt.datetime]:
    if not value:
        return None

    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone.utc)
    except Exception:
        pass

    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone.utc)
    except Exception:
        return None


def fmt_age(ts: Optional[dt.datetime]) -> str:
    if not ts:
        return "unknown"

    delta = now_utc() - ts
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return f"{seconds}s ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 48:
        return f"{hours}h ago"
    return f"{hours // 24}d ago"


def contains_any(text: str, terms: List[str]) -> bool:
    lower = text.lower()
    return any(term in lower for term in terms)


def normalize_incident_text(text: str) -> str:
    source = strip_html(text)
    source = STATE_PREFIX_RE.sub("", source)
    source = STATE_SUFFIX_RE.sub("", source)
    for pattern in INCIDENT_NOISE_PATTERNS:
        source = pattern.sub(" ", source)
    source = source.lower()
    source = re.sub(r"[^a-z0-9\s]+", " ", source)
    return SPACE_RE.sub(" ", source).strip()


def normalize_incident_key(title: str, summary: str) -> str:
    title_key = normalize_incident_text(title)
    if title_key and title_key not in GENERIC_INCIDENT_KEYS:
        return title_key
    return normalize_incident_text(" ".join(part for part in [title, summary] if part))


def classify_entry(entry: FeedEntry) -> Dict[str, Any]:
    title = strip_html(entry.title)
    summary = strip_html(entry.summary)
    combined = f"{title} {summary}".lower()

    resolved = contains_any(combined, RESOLVED_TERMS)
    active = contains_any(combined, ACTIVE_TERMS)
    degraded = contains_any(combined, DEGRADED_TERMS)

    if resolved:
        state = "resolved"
    elif active:
        state = "issue"
    elif degraded:
        state = "degraded"
    else:
        state = "unknown"

    return {
        "state": state,
        "key": normalize_incident_key(title, summary),
        "title": title,
        "summary": summary,
        "updated": entry.updated,
    }


def sort_incidents(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        items,
        key=lambda item: item["updated"] or dt.datetime.min.replace(tzinfo=dt.timezone.utc),
        reverse=True,
    )


def snapshot_incidents(items: List[Dict[str, Any]]) -> List[IncidentSnapshot]:
    return [
        IncidentSnapshot(
            title=item["title"],
            summary=item["summary"],
            updated=item["updated"],
            state=item["state"],
        )
        for item in items
    ]


def infer_service_status(name: str, url: str, entries: List[FeedEntry]) -> ServiceStatus:
    if not entries:
        return ServiceStatus(
            name=name,
            url=url,
            ok=False,
            severity="unknown",
            headline="No entries found",
            details="The feed loaded but did not contain any entries.",
            updated=None,
            entries=[],
        )

    classified = [classify_entry(entry) for entry in entries[:MAX_ENTRIES_PER_FEED]]
    latest_by_key: Dict[str, Dict[str, Any]] = {}
    for item in classified:
        key = item["key"] or item["title"]
        if key not in latest_by_key:
            latest_by_key[key] = item

    active = sort_incidents([item for item in latest_by_key.values() if item["state"] == "issue"])
    degraded = sort_incidents([item for item in latest_by_key.values() if item["state"] == "degraded"])
    current_incidents = snapshot_incidents(sort_incidents(active + degraded))

    if active:
        top = active[0]
        headline = top["title"] or "Active issue"
        details = top["summary"] or top["title"] or "Issue inferred from recent feed entries."
        if len(current_incidents) > 1:
            headline = f"{len(current_incidents)} live incidents"
            details = "Multiple ongoing incidents detected. See live incidents below."
        return ServiceStatus(
            name=name,
            url=url,
            ok=False,
            severity="issue",
            headline=headline,
            details=details,
            updated=top["updated"],
            entries=entries,
            current_incidents=current_incidents,
        )

    if degraded:
        top = degraded[0]
        headline = top["title"] or "Degraded"
        details = top["summary"] or top["title"] or "Degraded state inferred from recent feed entries."
        if len(current_incidents) > 1:
            headline = f"{len(current_incidents)} live incidents"
            details = "Multiple ongoing degraded incidents detected. See live incidents below."
        return ServiceStatus(
            name=name,
            url=url,
            ok=False,
            severity="degraded",
            headline=headline,
            details=details,
            updated=top["updated"],
            entries=entries,
            current_incidents=current_incidents,
        )

    latest = entries[0]
    latest_title = strip_html(latest.title) or "Operational"
    latest_summary = strip_html(latest.summary) or "No active issues inferred from recent entries."

    return ServiceStatus(
        name=name,
        url=url,
        ok=True,
        severity="operational",
        headline="Operational",
        details=f"Latest update: {latest_title}. {latest_summary}",
        updated=latest.updated,
        entries=entries,
    )
