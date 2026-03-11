from __future__ import annotations

import re

from status_watcher.domain import strip_html
from status_watcher.models import FeedEntry, SourceSpec
from status_watcher.sources.base import fetch_url


TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
META_DESC_RE = re.compile(
    r"""<meta[^>]+(?:name|property)=["'](?:description|og:description)["'][^>]+content=["'](.*?)["'][^>]*>""",
    re.IGNORECASE | re.DOTALL,
)
SCRIPT_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
BODY_RE = re.compile(r"<body[^>]*>(.*?)</body>", re.IGNORECASE | re.DOTALL)


def _extract_first(pattern: re.Pattern[str], text: str) -> str:
    match = pattern.search(text)
    if not match:
        return ""
    return strip_html(match.group(1))


class HtmlSourceAdapter:
    def load(self, spec: SourceSpec) -> list[FeedEntry]:
        raw = fetch_url(spec.url)
        text = raw.decode("utf-8", errors="replace")

        title = _extract_first(TITLE_RE, text) or spec.name
        meta_description = _extract_first(META_DESC_RE, text)
        body_html = _extract_first(BODY_RE, text) or text
        body_text = strip_html(SCRIPT_STYLE_RE.sub(" ", body_html))
        summary = meta_description or body_text[:280] or f"Fetched HTML status page from {spec.url}"

        return [
            FeedEntry(
                title=title,
                summary=summary,
                updated=None,
                link=spec.url,
            )
        ]
