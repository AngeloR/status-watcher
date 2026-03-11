from __future__ import annotations

import datetime as dt
import xml.etree.ElementTree as ET

from status_watcher.domain import parse_date
from status_watcher.models import FeedEntry, SourceSpec
from status_watcher.sources.base import fetch_url


def parse_feed(xml_bytes: bytes) -> list[FeedEntry]:
    root = ET.fromstring(xml_bytes)
    tag = root.tag.lower()

    if tag.endswith("feed"):
        return parse_atom(root)
    if tag.endswith("rss") or tag.endswith("rdf"):
        return parse_rss(root)

    raise ValueError(f"Unsupported feed format: {root.tag}")


def parse_atom(root: ET.Element) -> list[FeedEntry]:
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}")[0] + "}"

    entries: list[FeedEntry] = []
    for item in root.findall(f"{ns}entry"):
        title = (item.findtext(f"{ns}title") or "").strip()
        summary = (item.findtext(f"{ns}summary") or item.findtext(f"{ns}content") or "").strip()
        updated = parse_date((item.findtext(f"{ns}updated") or item.findtext(f"{ns}published") or "").strip())

        link = ""
        for link_el in item.findall(f"{ns}link"):
            href = link_el.attrib.get("href")
            rel = link_el.attrib.get("rel", "alternate")
            if href and rel in ("alternate", "", None):
                link = href
                break
            if href and not link:
                link = href

        entries.append(FeedEntry(title=title, summary=summary, updated=updated, link=link))

    entries.sort(key=lambda e: e.updated or dt.datetime.min.replace(tzinfo=dt.timezone.utc), reverse=True)
    return entries


def parse_rss(root: ET.Element) -> list[FeedEntry]:
    channel = root.find("channel")
    items = channel.findall("item") if channel is not None else root.findall(".//item")

    entries: list[FeedEntry] = []
    for item in items:
        title = (item.findtext("title") or "").strip()
        summary = (
            item.findtext("description")
            or item.findtext("{http://purl.org/rss/1.0/modules/content/}encoded")
            or ""
        ).strip()
        updated = parse_date((item.findtext("pubDate") or item.findtext("date") or "").strip())
        link = (item.findtext("link") or "").strip()
        entries.append(FeedEntry(title=title, summary=summary, updated=updated, link=link))

    entries.sort(key=lambda e: e.updated or dt.datetime.min.replace(tzinfo=dt.timezone.utc), reverse=True)
    return entries


class FeedSourceAdapter:
    def load(self, spec: SourceSpec) -> list[FeedEntry]:
        return parse_feed(fetch_url(spec.url))
