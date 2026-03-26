from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Iterable, List, Optional, Sequence
from urllib.parse import urljoin

from status_watcher.domain import normalize_component_status, parse_date
from status_watcher.models import ComponentSnapshot, FeedEntry, SourceSnapshot, SourceSpec
from status_watcher.sources.base import fetch_url


VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "strong", "b"}
ENTRY_CONTAINER_TAGS = {"article", "section", "div", "li", "tr", "main", "aside"}
SIGNAL_KEYWORDS = ("incident", "outage", "degraded", "maintenance", "status", "component", "disruption", "unavailable")


@dataclass
class HtmlNode:
    tag: str
    attrs: dict[str, str]
    parent: Optional["HtmlNode"] = None
    children: List["HtmlNode"] = field(default_factory=list)
    text_chunks: List[str] = field(default_factory=list)


class _HtmlTreeParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = HtmlNode(tag="document", attrs={})
        self._stack = [self.root]

    def handle_starttag(self, tag: str, attrs) -> None:
        node = HtmlNode(
            tag=tag.lower(),
            attrs={str(key).lower(): str(value or "") for key, value in attrs},
            parent=self._stack[-1],
        )
        self._stack[-1].children.append(node)
        if node.tag not in VOID_TAGS:
            self._stack.append(node)

    def handle_startendtag(self, tag: str, attrs) -> None:
        node = HtmlNode(
            tag=tag.lower(),
            attrs={str(key).lower(): str(value or "") for key, value in attrs},
            parent=self._stack[-1],
        )
        self._stack[-1].children.append(node)

    def handle_endtag(self, tag: str) -> None:
        lower = tag.lower()
        while len(self._stack) > 1 and self._stack[-1].tag != lower:
            self._stack.pop()
        if len(self._stack) > 1:
            self._stack.pop()

    def handle_data(self, data: str) -> None:
        if data and data.strip():
            self._stack[-1].text_chunks.append(data)


def parse_html_tree(raw: bytes) -> HtmlNode:
    parser = _HtmlTreeParser()
    parser.feed(raw.decode("utf-8", errors="replace"))
    return parser.root


def normalize_space(text: str) -> str:
    return " ".join(text.split())


def iter_nodes(node: HtmlNode) -> Iterable[HtmlNode]:
    for child in node.children:
        yield child
        yield from iter_nodes(child)


def node_text(node: HtmlNode) -> str:
    parts = list(node.text_chunks)
    for child in node.children:
        parts.append(node_text(child))
    return normalize_space(" ".join(part for part in parts if part))


def ancestor_of(ancestor: HtmlNode, node: HtmlNode) -> bool:
    current = node.parent
    while current is not None:
        if current is ancestor:
            return True
        current = current.parent
    return False


def selector_list(value: object, fallback: Optional[List[str]] = None) -> List[str]:
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if isinstance(value, list):
        selectors = [str(item).strip() for item in value if str(item).strip()]
        if selectors:
            return selectors
    return list(fallback or [])


def matches_selector(node: HtmlNode, selector: str) -> bool:
    selector = selector.strip()
    if not selector:
        return False
    if " " in selector:
        return False

    attrs: List[tuple[str, Optional[str]]] = []
    while "[" in selector and "]" in selector:
        start = selector.index("[")
        end = selector.index("]", start)
        body = selector[start + 1 : end]
        selector = selector[:start] + selector[end + 1 :]
        if "=" in body:
            key, value = body.split("=", 1)
            attrs.append((key.strip().lower(), value.strip().strip('"\'')))
        else:
            attrs.append((body.strip().lower(), None))

    tag = ""
    node_id = ""
    classes: List[str] = []
    buffer = selector
    while buffer:
        if buffer.startswith("#"):
            buffer = buffer[1:]
            split = len(buffer)
            for idx, char in enumerate(buffer):
                if char in ".#":
                    split = idx
                    break
            node_id = buffer[:split]
            buffer = buffer[split:]
            continue
        if buffer.startswith("."):
            buffer = buffer[1:]
            split = len(buffer)
            for idx, char in enumerate(buffer):
                if char in ".#":
                    split = idx
                    break
            classes.append(buffer[:split])
            buffer = buffer[split:]
            continue
        split = len(buffer)
        for idx, char in enumerate(buffer):
            if char in ".#":
                split = idx
                break
        tag = buffer[:split].lower()
        buffer = buffer[split:]

    if tag and node.tag != tag:
        return False
    if node_id and node.attrs.get("id", "") != node_id:
        return False
    class_names = set(node.attrs.get("class", "").split())
    if any(class_name not in class_names for class_name in classes):
        return False
    for key, value in attrs:
        if key not in node.attrs:
            return False
        if value is not None and node.attrs.get(key) != value:
            return False
    return True


def find_nodes(root: HtmlNode, selectors: List[str]) -> List[HtmlNode]:
    if not selectors:
        return []
    matches: List[HtmlNode] = []
    for node in iter_nodes(root):
        if any(matches_selector(node, selector) for selector in selectors):
            matches.append(node)
    return matches


def heuristic_entry_nodes(root: HtmlNode) -> List[HtmlNode]:
    scored: List[tuple[int, int, HtmlNode]] = []
    for node in iter_nodes(root):
        if node.tag not in ENTRY_CONTAINER_TAGS:
            continue
        text = node_text(node)
        if len(text) < 24:
            continue
        attr_blob = " ".join(node.attrs.values()).lower()
        score = sum(2 for keyword in SIGNAL_KEYWORDS if keyword in attr_blob)
        score += sum(1 for keyword in SIGNAL_KEYWORDS if keyword in text.lower())
        if score < 2:
            continue
        scored.append((score, len(text), node))

    scored.sort(key=lambda item: (-item[0], item[1]))
    selected: List[HtmlNode] = []
    for _, _, node in scored:
        if any(ancestor_of(existing, node) or ancestor_of(node, existing) for existing in selected):
            continue
        selected.append(node)
        if len(selected) >= 5:
            break
    return selected


def first_descendant(node: HtmlNode, tags: set[str]) -> Optional[HtmlNode]:
    for candidate in iter_nodes(node):
        if candidate.tag in tags:
            text = node_text(candidate)
            if text:
                return candidate
    return None


def first_descendant_with_class(node: HtmlNode, class_names: Sequence[str]) -> Optional[HtmlNode]:
    candidates = list(iter_nodes(node))
    for class_name in class_names:
        for candidate in candidates:
            candidate_classes = set(candidate.attrs.get("class", "").split())
            if class_name in candidate_classes:
                text = node_text(candidate)
                if text:
                    return candidate
    return None


def first_time(node: HtmlNode) -> Optional[str]:
    for candidate in iter_nodes(node):
        if candidate.tag == "time":
            value = candidate.attrs.get("datetime") or node_text(candidate)
            if value:
                return value
    return None


def first_link(node: HtmlNode, base_url: str) -> str:
    for candidate in iter_nodes(node):
        if candidate.tag == "a" and candidate.attrs.get("href"):
            return urljoin(base_url, candidate.attrs["href"])
    return ""


def document_title(root: HtmlNode) -> str:
    for node in iter_nodes(root):
        if node.tag == "title":
            text = node_text(node)
            if text:
                return text
    return ""


def meta_content(root: HtmlNode, keys: set[str]) -> str:
    for node in iter_nodes(root):
        if node.tag != "meta":
            continue
        name = node.attrs.get("name", "").lower()
        prop = node.attrs.get("property", "").lower()
        if name in keys or prop in keys:
            content = node.attrs.get("content", "")
            if content:
                return normalize_space(content)
    return ""


def canonical_link(root: HtmlNode, base_url: str) -> str:
    for node in iter_nodes(root):
        if node.tag == "link" and node.attrs.get("rel", "").lower() == "canonical" and node.attrs.get("href"):
            return urljoin(base_url, node.attrs["href"])
    return base_url


def entry_from_node(node: HtmlNode, base_url: str) -> Optional[FeedEntry]:
    text = node_text(node)
    if not text:
        return None
    title_node = first_descendant_with_class(node, ["actual-title", "update-title", "incident-title"])
    if title_node is None:
        title_node = first_descendant(node, HEADING_TAGS)
    title = node_text(title_node) if title_node is not None else ""
    if not title:
        title = text.split(".", 1)[0][:96].strip() or "Status update"

    summary = text
    if title and summary.lower().startswith(title.lower()):
        summary = summary[len(title) :].lstrip(" :-|")
    if not summary:
        summary = text
    if len(summary) > 320:
        summary = summary[:317] + "..."

    updated = parse_date(first_time(node) or "")
    return FeedEntry(title=title, summary=summary, updated=updated, link=first_link(node, base_url))


def component_from_node(node: HtmlNode, base_url: str) -> Optional[ComponentSnapshot]:
    text = node_text(node)
    if not text:
        return None
    name_node = first_descendant_with_class(node, ["name"])
    if name_node is None:
        name_node = first_descendant(node, HEADING_TAGS)
    name = node_text(name_node) if name_node is not None else text.split("-", 1)[0][:80].strip()
    raw_status = (
        node.attrs.get("data-component-status")
        or node.attrs.get("data-status")
        or node.attrs.get("aria-label")
        or text
    )
    status, label = normalize_component_status(raw_status)
    if not name or status == "unknown":
        return None
    details = text
    if len(details) > 220:
        details = details[:217] + "..."
    return ComponentSnapshot(
        name=name,
        status=status,
        label=label,
        updated=parse_date(first_time(node) or ""),
        details=details,
        link=first_link(node, base_url),
    )


def fallback_entry(root: HtmlNode, spec: SourceSpec) -> FeedEntry:
    title = document_title(root) or meta_content(root, {"og:title"}) or spec.name
    summary = meta_content(root, {"description", "og:description"})
    if not summary:
        candidates = heuristic_entry_nodes(root)
        if candidates:
            summary = node_text(candidates[0])
        else:
            summary = node_text(root)
    if len(summary) > 320:
        summary = summary[:317] + "..."
    return FeedEntry(
        title=title,
        summary=summary or f"Fetched HTML status page from {spec.url}",
        updated=parse_date(first_time(root) or ""),
        link=canonical_link(root, spec.url),
    )


class HtmlSourceAdapter:
    def load(self, spec: SourceSpec) -> SourceSnapshot:
        raw = fetch_url(spec.url)
        root = parse_html_tree(raw)

        entry_nodes = find_nodes(root, selector_list(spec.options.get("selectors") or spec.options.get("entry_selectors")))
        if not entry_nodes:
            entry_nodes = heuristic_entry_nodes(root)

        seen_summaries: set[str] = set()
        entries: List[FeedEntry] = []
        for node in entry_nodes:
            entry = entry_from_node(node, spec.url)
            if entry is None:
                continue
            key = f"{entry.title}|{entry.summary}"
            if key in seen_summaries:
                continue
            seen_summaries.add(key)
            entries.append(entry)

        if not entries:
            entries.append(fallback_entry(root, spec))

        components: List[ComponentSnapshot] = []
        component_nodes = find_nodes(root, selector_list(spec.options.get("component_selectors")))
        for node in component_nodes:
            component = component_from_node(node, spec.url)
            if component is not None:
                components.append(component)

        entries.sort(key=lambda entry: entry.updated or parse_date("1970-01-01T00:00:00+00:00"), reverse=True)
        return SourceSnapshot(entries=entries, components=components)
