from __future__ import annotations

import json
import re

from typing import Any, Iterable, List, Sequence
from urllib.parse import urljoin

from status_watcher.domain import normalize_component_status, parse_date, strip_html
from status_watcher.models import ComponentSnapshot, FeedEntry, SourceSnapshot, SourceSpec
from status_watcher.sources.base import fetch_url, load_cached_response, store_cached_response


DEFAULT_JSON_ACCEPT = "application/json, text/plain;q=0.9, */*;q=0.1"
DEFAULT_ENTRY_COLLECTION_PATHS = ["entries[]", "incidents[]", "items[]", "results[]", "events[]", "data[]", ""]
DEFAULT_COMPONENT_COLLECTION_PATHS = ["components[]", "services[]", "data.components[]"]
SEGMENT_RE = re.compile(r"(?P<name>[^\[\]]+)?(?:\[(?P<index>\*|\d*)\])?$")


def decode_json(raw: bytes, url: str) -> Any:
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, (dict, list)):
        raise ValueError(f"Unexpected JSON payload from {url}")
    return data


def request_headers(spec: SourceSpec) -> dict[str, str]:
    headers = spec.options.get("headers")
    if not isinstance(headers, dict):
        return {}
    return {str(key): str(value) for key, value in headers.items()}


def fetch_json_payload(spec: SourceSpec) -> Any:
    raw = fetch_url(spec.url, accept=str(spec.options.get("accept") or DEFAULT_JSON_ACCEPT), headers=request_headers(spec))
    try:
        payload = decode_json(raw, spec.url)
    except Exception:
        cached = load_cached_response(spec.url)
        if cached is None or cached == raw:
            raise
        payload = decode_json(cached, spec.url)
        store_cached_response(spec.url, cached)
        return payload

    store_cached_response(spec.url, raw)
    return payload


def normalize_paths(value: Any, defaults: Sequence[str]) -> List[str]:
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if isinstance(value, list):
        paths = [str(item).strip() for item in value if str(item).strip()]
        if paths:
            return paths
    return list(defaults)


def apply_segment(value: Any, segment: str) -> List[Any]:
    match = SEGMENT_RE.fullmatch(segment)
    if match is None:
        return []

    name = match.group("name")
    index = match.group("index")
    targets = [value]
    if name:
        if isinstance(value, dict) and name in value:
            targets = [value[name]]
        else:
            return []

    if index is None:
        return targets

    expanded: List[Any] = []
    for target in targets:
        if not isinstance(target, list):
            continue
        if index in {"", "*"}:
            expanded.extend(target)
            continue
        try:
            expanded.append(target[int(index)])
        except (IndexError, ValueError):
            continue
    return expanded


def extract_path_values(data: Any, path: str) -> List[Any]:
    if not path:
        return [data]

    values = [data]
    for segment in [segment for segment in path.split(".") if segment]:
        next_values: List[Any] = []
        for value in values:
            next_values.extend(apply_segment(value, segment))
        values = next_values
        if not values:
            break
    return values


def flatten_collection(values: Iterable[Any]) -> List[Any]:
    flattened: List[Any] = []
    for value in values:
        if isinstance(value, list):
            flattened.extend(value)
        else:
            flattened.append(value)
    return flattened


def extract_collection(data: Any, paths: Sequence[str]) -> List[Any]:
    for path in paths:
        values = flatten_collection(extract_path_values(data, path))
        if values:
            return values
    return []


def first_value(data: Any, paths: Sequence[str]) -> Any:
    for path in paths:
        values = extract_path_values(data, path)
        for value in values:
            if value is not None and value != "":
                return value
    return None


def first_text(data: Any, paths: Sequence[str]) -> str:
    value = first_value(data, paths)
    if value is None:
        return ""
    return strip_html(str(value)).strip()


def build_entry(item: Any, spec: SourceSpec) -> FeedEntry | None:
    if isinstance(item, dict):
        title = first_text(item, normalize_paths(spec.options.get("title_path"), ["title", "name", "headline", "status.title"]))
        summary = first_text(
            item,
            normalize_paths(
                spec.options.get("summary_path"),
                ["summary", "description", "body", "details", "message", "status.description"],
            ),
        )
        updated = parse_date(
            first_text(
                item,
                normalize_paths(
                    spec.options.get("updated_path"),
                    ["updated_at", "updated", "updatedAt", "published_at", "created_at", "timestamp", "date"],
                ),
            )
        )
        link = first_text(item, normalize_paths(spec.options.get("link_path"), ["shortlink", "link", "url", "html_url"]))
    else:
        title = strip_html(str(item))
        summary = title
        updated = None
        link = ""

    if not title and not summary:
        return None
    if not title:
        title = summary[:80] or "Status update"
    if not summary:
        summary = title
    return FeedEntry(title=title, summary=summary, updated=updated, link=urljoin(spec.url, link) if link else "")


def build_component(item: Any, spec: SourceSpec) -> ComponentSnapshot | None:
    if not isinstance(item, dict):
        return None

    name = first_text(item, normalize_paths(spec.options.get("component_name_path"), ["name", "component", "display_name", "title"]))
    if not name:
        return None

    raw_status = first_text(item, normalize_paths(spec.options.get("component_status_path"), ["status", "state", "indicator", "severity"]))
    status, label = normalize_component_status(raw_status)
    label_override = first_text(item, normalize_paths(spec.options.get("component_label_path"), []))
    details = first_text(
        item,
        normalize_paths(spec.options.get("component_details_path"), ["description", "details", "body", "message"]),
    )
    updated = parse_date(
        first_text(
            item,
            normalize_paths(spec.options.get("component_updated_path"), ["updated_at", "updated", "updatedAt", "timestamp", "date"]),
        )
    )
    link = first_text(item, normalize_paths(spec.options.get("component_link_path"), ["link", "url", "html_url"]))

    return ComponentSnapshot(
        name=name,
        status=status,
        label=label_override or label,
        updated=updated,
        details=details,
        link=urljoin(spec.url, link) if link else "",
    )


class JsonSourceAdapter:
    def load(self, spec: SourceSpec) -> SourceSnapshot:
        payload = fetch_json_payload(spec)
        entry_items = extract_collection(payload, normalize_paths(spec.options.get("entries_path"), DEFAULT_ENTRY_COLLECTION_PATHS))
        component_items = extract_collection(
            payload,
            normalize_paths(spec.options.get("components_path"), DEFAULT_COMPONENT_COLLECTION_PATHS),
        )

        entries = [entry for entry in (build_entry(item, spec) for item in entry_items) if entry is not None]
        entries.sort(key=lambda entry: entry.updated or parse_date("1970-01-01T00:00:00+00:00"), reverse=True)

        components = [component for component in (build_component(item, spec) for item in component_items) if component is not None]
        seen_names: set[str] = set()
        deduped_components: List[ComponentSnapshot] = []
        for component in components:
            key = component.name.lower()
            if key in seen_names:
                continue
            seen_names.add(key)
            deduped_components.append(component)

        return SourceSnapshot(entries=entries, components=deduped_components)
