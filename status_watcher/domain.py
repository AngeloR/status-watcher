from __future__ import annotations

import datetime as dt
import html
import re

from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional

from status_watcher.config import MAX_ENTRIES_PER_FEED
from status_watcher.models import FeedEntry, ServiceStatus


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


def normalize_incident_key(title: str, summary: str) -> str:
    source = strip_html(" ".join(part for part in [title, summary] if part))
    source = STATE_PREFIX_RE.sub("", source)
    for pattern in INCIDENT_NOISE_PATTERNS:
        source = pattern.sub(" ", source)
    source = source.lower()
    source = re.sub(r"[^a-z0-9\s]+", " ", source)
    return SPACE_RE.sub(" ", source).strip()


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

    active = [item for item in latest_by_key.values() if item["state"] == "issue"]
    degraded = [item for item in latest_by_key.values() if item["state"] == "degraded"]

    if active:
        active.sort(
            key=lambda item: item["updated"] or dt.datetime.min.replace(tzinfo=dt.timezone.utc),
            reverse=True,
        )
        top = active[0]
        return ServiceStatus(
            name=name,
            url=url,
            ok=False,
            severity="issue",
            headline=top["title"] or "Active issue",
            details=top["summary"] or top["title"] or "Issue inferred from recent feed entries.",
            updated=top["updated"],
            entries=entries,
        )

    if degraded:
        degraded.sort(
            key=lambda item: item["updated"] or dt.datetime.min.replace(tzinfo=dt.timezone.utc),
            reverse=True,
        )
        top = degraded[0]
        return ServiceStatus(
            name=name,
            url=url,
            ok=False,
            severity="degraded",
            headline=top["title"] or "Degraded",
            details=top["summary"] or top["title"] or "Degraded state inferred from recent feed entries.",
            updated=top["updated"],
            entries=entries,
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
