from __future__ import annotations

import json

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional
from urllib.parse import urlparse

from status_watcher.models import SourceSpec
from status_watcher.presets import matching_preset_name, source_spec_from_preset
from status_watcher.sources.base import fetch_url
from status_watcher.sources.feed import parse_feed
from status_watcher.sources.html_page import find_nodes, parse_html_tree
from status_watcher.sources.json_api import decode_json
from status_watcher.sources.statuspage import fetch_statuspage_json, normalize_statuspage_base


JSON_DISCOVERY_TEMPLATES = [
    {
        "match": lambda payload: isinstance(payload, dict)
        and isinstance(payload.get("status"), dict)
        and isinstance(payload.get("page"), dict)
        and "description" in payload["status"],
        "options": {
            "entries_path": "",
            "title_path": "status.description",
            "summary_path": "page.name",
            "updated_path": "page.updated_at",
        },
    },
    {
        "match": lambda payload: isinstance(payload, dict)
        and isinstance(payload.get("data"), dict)
        and isinstance(payload["data"].get("events"), list),
        "options": {
            "entries_path": "data.events[]",
            "components_path": "data.components[]",
            "summary_path": "details.text",
        },
    },
]

ENTRY_SELECTOR_CANDIDATES = [
    ".unresolved-incident",
    "[data-incident-id]",
    ".incident",
    "article.incident",
    "section.incident",
]

COMPONENT_SELECTOR_CANDIDATES = [
    "[data-component-id]",
    ".component",
]


@dataclass(frozen=True)
class DiscoveryResult:
    spec: SourceSpec
    config_entry: Dict[str, Any]
    detection: str
    preset: Optional[str] = None


def discover_source(name: str, url: str) -> DiscoveryResult:
    normalized_name = name.strip()
    normalized_url = normalize_input_url(url)

    statuspage = discover_statuspage(normalized_name, normalized_url)
    if statuspage is not None:
        return build_result(statuspage, "statuspage probe")

    raw = fetch_url(
        normalized_url,
        accept="application/json, application/atom+xml, application/rss+xml, application/xml, text/html;q=0.9, */*;q=0.1",
    )

    feed_spec = discover_feed(normalized_name, normalized_url, raw)
    if feed_spec is not None:
        return build_result(feed_spec, "feed probe")

    json_spec = discover_json(normalized_name, normalized_url, raw)
    if json_spec is not None:
        return build_result(json_spec, "json probe")

    return build_result(discover_html(normalized_name, normalized_url, raw), "html probe")


def normalize_input_url(url: str) -> str:
    value = url.strip()
    if "://" not in value:
        return f"https://{value}"
    return value


def discover_statuspage(name: str, url: str) -> SourceSpec | None:
    candidate = statuspage_base_candidate(url)
    if candidate is None:
        return None

    try:
        summary = fetch_statuspage_json(candidate, "summary.json")
        fetch_statuspage_json(candidate, "incidents.json")
    except Exception:
        return None

    if not looks_like_statuspage_summary(summary):
        return None
    return SourceSpec(name=name, type="statuspage", url=normalize_statuspage_base(candidate))


def statuspage_base_candidate(url: str) -> str | None:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return None

    path = parsed.path.rstrip("/")
    if not path or path == "/":
        return f"{parsed.scheme}://{parsed.netloc}"
    if path.startswith("/api/v2/"):
        return normalize_statuspage_base(url)
    if path.endswith(".atom") or path.endswith(".xml") or path.endswith(".rss") or path.endswith(".json"):
        return None
    return None


def looks_like_statuspage_summary(payload: Any) -> bool:
    return isinstance(payload, dict) and isinstance(payload.get("page"), dict) and "status" in payload


def discover_feed(name: str, url: str, raw: bytes) -> SourceSpec | None:
    try:
        parse_feed(raw)
    except Exception:
        return None
    return SourceSpec(name=name, type="feed", url=url)


def discover_json(name: str, url: str, raw: bytes) -> SourceSpec | None:
    try:
        payload = decode_json(raw, url)
    except Exception:
        return None

    if looks_like_statuspage_summary(payload):
        return SourceSpec(name=name, type="statuspage", url=normalize_statuspage_base(url))

    for template in JSON_DISCOVERY_TEMPLATES:
        if template["match"](payload):
            return SourceSpec(name=name, type="json", url=url, options=dict(template["options"]))

    return SourceSpec(name=name, type="json", url=url)


def discover_html(name: str, url: str, raw: bytes) -> SourceSpec:
    root = parse_html_tree(raw)
    options: Dict[str, Any] = {}

    entry_selector = first_selector_with_matches(root, ENTRY_SELECTOR_CANDIDATES)
    if entry_selector is not None:
        options["selectors"] = [entry_selector]

    component_selector = first_selector_with_matches(root, COMPONENT_SELECTOR_CANDIDATES)
    if component_selector is not None:
        options["component_selectors"] = [component_selector]

    return SourceSpec(name=name, type="html", url=url, options=options)


def first_selector_with_matches(root, selectors: Iterable[str]) -> str | None:
    for selector in selectors:
        if find_nodes(root, [selector]):
            return selector
    return None


def build_result(spec: SourceSpec, detection: str) -> DiscoveryResult:
    preset = matching_preset_name(spec)
    config_entry = serialize_config_entry(spec, preset)
    return DiscoveryResult(spec=spec, config_entry=config_entry, detection=detection, preset=preset)


def serialize_config_entry(spec: SourceSpec, preset: Optional[str]) -> Dict[str, Any]:
    if preset is not None:
        preset_spec = source_spec_from_preset(preset)
        entry: Dict[str, Any] = {"preset": preset}
        if spec.name != preset_spec.name:
            entry["name"] = spec.name
        if spec.url != preset_spec.url:
            entry["url"] = spec.url
        if spec.type != preset_spec.type:
            entry["type"] = spec.type
        for key, value in spec.options.items():
            if preset_spec.options.get(key) != value:
                entry[key] = value
        return entry

    entry = {"name": spec.name, "url": spec.url}
    if spec.type != "feed":
        entry["type"] = spec.type
    entry.update(spec.options)
    return entry


def load_config_entries(path: str) -> list[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = handle.read()
    except FileNotFoundError:
        return []
    if not raw.strip():
        return []
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("Feed config must be a JSON array")
    if not all(isinstance(item, dict) for item in data):
        raise ValueError("Each feed must be a JSON object")
    return [dict(item) for item in data]


def upsert_config_entry(path: str, result: DiscoveryResult) -> tuple[list[Dict[str, Any]], bool]:
    from status_watcher.presets import source_spec_from_definition

    entries = load_config_entries(path)
    updated = False
    for index, item in enumerate(entries):
        try:
            existing = source_spec_from_definition(item)
        except Exception:
            continue
        if existing.name == result.spec.name or existing.url == result.spec.url:
            entries[index] = dict(result.config_entry)
            updated = True
            break

    if not updated:
        entries.append(dict(result.config_entry))
    return entries, updated
