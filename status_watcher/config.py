from __future__ import annotations

import json
import os

from typing import Any, Dict, List, Optional, Sequence

from status_watcher.models import SourceSpec


DEFAULT_SOURCE_SPECS = [
    SourceSpec(
        name="Claude",
        type="statuspage",
        url="https://status.claude.com",
    ),
]

REFRESH_SECONDS = 120
HTTP_TIMEOUT_SECONDS = 15
HTTP_RETRY_ATTEMPTS = 3
HTTP_RETRY_BACKOFF_SECONDS = 1.0
USER_AGENT = "status-dashboard/2.0 (+rich terminal monitor)"
MAX_ENTRIES_PER_FEED = 30
MAX_HISTORY_EVENTS_PER_SERVICE = 20
DEFAULT_FEEDS_PATH = "feeds.json"
DEFAULT_STATE_PATH = os.environ.get(
    "STATUS_WATCHER_STATE_PATH",
    os.path.join(os.path.expanduser("~"), ".status-watcher", "state.json"),
)
DEFAULT_CACHE_DIR = os.environ.get(
    "STATUS_WATCHER_CACHE_DIR",
    os.path.join(os.path.dirname(DEFAULT_STATE_PATH), "cache"),
)


def load_source_specs_from_file(path: str) -> List[SourceSpec]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError("Feed config must be a JSON array")

    specs: List[SourceSpec] = []
    for item in data:
        if not isinstance(item, dict) or "name" not in item or "url" not in item:
            raise ValueError("Each feed must contain 'name' and 'url'")

        source_type = str(item.get("type", "feed"))
        options: Dict[str, Any] = {}
        for key, value in item.items():
            if key not in {"name", "type", "url"}:
                options[key] = value

        specs.append(
            SourceSpec(
                name=str(item["name"]),
                type=source_type,
                url=str(item["url"]),
                options=options,
            )
        )
    return specs


def resolve_source_specs(argv: Optional[Sequence[str]] = None) -> List[SourceSpec]:
    args = list(argv if argv is not None else [])
    if args:
        return load_source_specs_from_file(args[0])

    if os.path.exists(DEFAULT_FEEDS_PATH):
        return load_source_specs_from_file(DEFAULT_FEEDS_PATH)

    return list(DEFAULT_SOURCE_SPECS)
