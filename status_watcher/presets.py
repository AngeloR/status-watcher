from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from status_watcher.models import SourceSpec


@dataclass(frozen=True)
class SourcePreset:
    key: str
    description: str
    type: str
    url: str = ""
    name: str = ""
    options: Dict[str, Any] = field(default_factory=dict)


PRESETS: dict[str, SourcePreset] = {
    "claude": SourcePreset(
        key="claude",
        description="Anthropic Claude public Statuspage feed with components and incidents.",
        type="statuspage",
        url="https://status.claude.com",
        name="Claude",
    ),
    "openai": SourcePreset(
        key="openai",
        description="OpenAI public Statuspage feed with components and incidents.",
        type="statuspage",
        url="https://status.openai.com",
        name="OpenAI",
    ),
    "github": SourcePreset(
        key="github",
        description="GitHub public Statuspage feed with components and incidents.",
        type="statuspage",
        url="https://www.githubstatus.com",
        name="GitHub",
    ),
    "cloudflare": SourcePreset(
        key="cloudflare",
        description="Cloudflare public Statuspage feed with components and incidents.",
        type="statuspage",
        url="https://www.cloudflarestatus.com",
        name="Cloudflare",
    ),
    "azure": SourcePreset(
        key="azure",
        description="Azure public regional status RSS feed.",
        type="feed",
        url="https://status.azure.com/en-us/status/feed/",
        name="Azure",
    ),
    "vercel": SourcePreset(
        key="vercel",
        description="Vercel public Statuspage feed with components and incidents.",
        type="statuspage",
        url="https://www.vercel-status.com",
        name="Vercel",
    ),
    "linear": SourcePreset(
        key="linear",
        description="Linear public Statuspage feed with components and incidents.",
        type="statuspage",
        url="https://linearstatus.com",
        name="Linear",
    ),
    "github-json": SourcePreset(
        key="github-json",
        description="GitHub status summary JSON via the generic JSON adapter.",
        type="json",
        url="https://www.githubstatus.com/api/v2/status.json",
        name="GitHub",
        options={
            "entries_path": "",
            "title_path": "status.description",
            "summary_path": "page.name",
            "updated_path": "page.updated_at",
        },
    ),
    "claude-html": SourcePreset(
        key="claude-html",
        description="Claude status site via the generic HTML adapter with incident and component selectors.",
        type="html",
        url="https://status.claude.com",
        name="Claude",
        options={
            "selectors": [".unresolved-incident"],
            "component_selectors": ["[data-component-id]"],
        },
    ),
}


def get_preset(name: str) -> SourcePreset:
    key = name.strip().lower()
    preset = PRESETS.get(key)
    if preset is None:
        raise ValueError(f"Unknown preset: {name}")
    return preset


def list_presets() -> List[SourcePreset]:
    return [PRESETS[key] for key in sorted(PRESETS)]


def source_spec_from_definition(item: Dict[str, Any]) -> SourceSpec:
    preset_name = str(item.get("preset") or "").strip()
    preset = get_preset(preset_name) if preset_name else None

    name = str(item.get("name") or (preset.name if preset else "")).strip()
    source_type = str(item.get("type") or (preset.type if preset else "feed")).strip() or "feed"
    url = str(item.get("url") or (preset.url if preset else "")).strip()

    options: Dict[str, Any] = dict(preset.options) if preset is not None else {}
    for key, value in item.items():
        if key not in {"name", "type", "url", "preset"}:
            options[key] = value

    if not name or not url:
        raise ValueError("Each feed must contain 'name' and 'url'")

    return SourceSpec(name=name, type=source_type, url=url, options=options)


def source_spec_from_preset(
    preset_name: str,
    *,
    name: Optional[str] = None,
    url: Optional[str] = None,
    options: Optional[Dict[str, Any]] = None,
) -> SourceSpec:
    item: Dict[str, Any] = {"preset": preset_name}
    if name is not None:
        item["name"] = name
    if url is not None:
        item["url"] = url
    item.update(options or {})
    return source_spec_from_definition(item)


def matching_preset_name(spec: SourceSpec) -> Optional[str]:
    for preset in list_presets():
        preset_spec = source_spec_from_preset(preset.key)
        if preset_spec.type != spec.type:
            continue
        if preset_spec.url != spec.url:
            continue
        if preset_spec.options != spec.options:
            continue
        return preset.key
    return None
