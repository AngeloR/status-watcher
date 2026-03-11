from __future__ import annotations

import urllib.request

from typing import Protocol

from status_watcher.config import HTTP_TIMEOUT_SECONDS, USER_AGENT
from status_watcher.models import FeedEntry, SourceSpec


class SourceAdapter(Protocol):
    def load(self, spec: SourceSpec) -> list[FeedEntry]:
        ...


def fetch_url(url: str) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/atom+xml, application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.1",
        },
    )
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
        return resp.read()
