from __future__ import annotations

from status_watcher.models import FeedEntry, SourceSpec
from status_watcher.sources.feed import FeedSourceAdapter
from status_watcher.sources.html_page import HtmlSourceAdapter


ADAPTERS = {
    "feed": FeedSourceAdapter(),
    "html": HtmlSourceAdapter(),
}


def load_entries(spec: SourceSpec) -> list[FeedEntry]:
    adapter = ADAPTERS.get(spec.type)
    if adapter is None:
        raise ValueError(f"Unknown source type: {spec.type}")
    return adapter.load(spec)
