from __future__ import annotations

from status_watcher.models import FeedEntry, SourceSnapshot, SourceSpec
from status_watcher.sources.feed import FeedSourceAdapter
from status_watcher.sources.html_page import HtmlSourceAdapter
from status_watcher.sources.json_api import JsonSourceAdapter
from status_watcher.sources.statuspage import StatuspageSourceAdapter


ADAPTERS = {
    "feed": FeedSourceAdapter(),
    "html": HtmlSourceAdapter(),
    "json": JsonSourceAdapter(),
    "statuspage": StatuspageSourceAdapter(),
}


def load_source_snapshot(spec: SourceSpec) -> SourceSnapshot:
    adapter = ADAPTERS.get(spec.type)
    if adapter is None:
        raise ValueError(f"Unknown source type: {spec.type}")
    return adapter.load(spec)


def load_entries(spec: SourceSpec) -> list[FeedEntry]:
    return load_source_snapshot(spec).entries
