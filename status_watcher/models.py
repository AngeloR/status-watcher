from __future__ import annotations

import datetime as dt

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class SourceSpec:
    name: str
    type: str
    url: str
    options: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FeedEntry:
    title: str
    summary: str
    updated: Optional[dt.datetime]
    link: str = ""


@dataclass
class IncidentSnapshot:
    title: str
    summary: str
    updated: Optional[dt.datetime]
    state: str


@dataclass
class ServiceStatus:
    name: str
    url: str
    ok: bool
    severity: str  # operational | degraded | issue | error | unknown
    headline: str
    details: str
    updated: Optional[dt.datetime]
    error: Optional[str] = None
    entries: List[FeedEntry] = field(default_factory=list)
    current_incidents: List[IncidentSnapshot] = field(default_factory=list)
