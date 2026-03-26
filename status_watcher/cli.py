from __future__ import annotations

import argparse
import json
import sys

from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from status_watcher.config import DEFAULT_FEEDS_PATH, load_source_specs_from_file, resolve_source_specs
from status_watcher.discovery import DiscoveryResult, discover_source, upsert_config_entry
from status_watcher.domain import infer_service_status
from status_watcher.models import ComponentSnapshot, FeedEntry, IncidentSnapshot, ServiceStatus, SourceSpec
from status_watcher.presets import list_presets, source_spec_from_preset
from status_watcher.sources import load_source_snapshot


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if args and args[0] == "inspect":
        return inspect_main(args[1:])
    if args and args[0] == "presets":
        return presets_main()
    if args and args[0] == "discover":
        return discover_main(args[1:])
    if args and args[0] == "add":
        return add_main(args[1:])
    from status_watcher.app import run_dashboard

    return run_dashboard(args)


def build_inspect_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="status-watcher inspect")
    parser.add_argument("source_name", nargs="?")
    parser.add_argument("config_path", nargs="?")
    parser.add_argument("--config", dest="config_override")
    parser.add_argument("--preset")
    parser.add_argument("--name")
    parser.add_argument("--url")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def build_discover_parser(prog: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog)
    parser.add_argument("name")
    parser.add_argument("url")
    parser.add_argument("config_path", nargs="?")
    parser.add_argument("--config", dest="config_override")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def inspect_main(argv: Sequence[str]) -> int:
    parser = build_inspect_parser()
    args = parser.parse_args(list(argv))

    try:
        spec = resolve_inspect_spec(args)
        snapshot = load_source_snapshot(spec)
        status = infer_service_status(spec.name, spec.url, snapshot.entries, snapshot.components)
    except Exception as exc:
        print(f"inspect failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    if args.as_json:
        print(json.dumps(serialize_inspection(spec, status), indent=2))
        return 0

    print(render_inspection(spec, status))
    return 0


def discover_main(argv: Sequence[str]) -> int:
    parser = build_discover_parser("status-watcher discover")
    args = parser.parse_args(list(argv))

    try:
        result = discover_source(args.name, args.url)
    except Exception as exc:
        print(f"discover failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    if args.as_json:
        print(json.dumps(serialize_discovery(result), indent=2))
        return 0

    print(render_discovery(result))
    return 0


def add_main(argv: Sequence[str]) -> int:
    parser = build_discover_parser("status-watcher add")
    args = parser.parse_args(list(argv))

    try:
        result = discover_source(args.name, args.url)
        config_path = args.config_override or args.config_path or DEFAULT_FEEDS_PATH
        entries, updated = upsert_config_entry(config_path, result)
        target = Path(config_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:
        print(f"add failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    payload = {
        "path": str(Path(config_path)),
        "updated": updated,
        "discovery": serialize_discovery(result),
    }

    if args.as_json:
        print(json.dumps(payload, indent=2))
        return 0

    action = "Updated" if updated else "Added"
    print(f"{action} {result.spec.name} in {config_path}")
    print(render_discovery(result))
    return 0


def presets_main() -> int:
    for preset in list_presets():
        print(f"{preset.key:<12} {preset.type:<10} {preset.url or '-'}")
        print(f"  {preset.description}")
    return 0


def resolve_inspect_spec(args: argparse.Namespace) -> SourceSpec:
    if args.preset:
        return source_spec_from_preset(args.preset, name=args.name, url=args.url)

    config_path = args.config_override or args.config_path
    specs = load_source_specs_from_file(config_path) if config_path else resolve_source_specs()
    if args.source_name:
        matches = [spec for spec in specs if spec.name.lower() == args.source_name.lower()]
        if not matches:
            raise ValueError(f"No source named '{args.source_name}' found")
        return matches[0]
    if len(specs) == 1:
        return specs[0]
    raise ValueError("Multiple sources configured. Pass a source name to inspect one.")


def format_timestamp(value: Optional[datetime]) -> str:
    if value is None:
        return "-"
    return value.isoformat()


def render_inspection(spec: SourceSpec, status: ServiceStatus) -> str:
    lines = [
        f"Source: {spec.name}",
        f"Type: {spec.type}",
        f"URL: {spec.url}",
        f"Severity: {status.severity}",
        f"Headline: {status.headline}",
        f"Updated: {format_timestamp(status.updated)}",
        f"Entries: {len(status.entries)}",
        f"Components: {len(status.components)}",
    ]
    if status.details:
        lines.append(f"Details: {status.details}")

    lines.append("")
    lines.append("Current incidents:")
    if status.current_incidents:
        lines.extend(render_incidents(status.current_incidents))
    else:
        lines.append("- none")

    lines.append("")
    lines.append("Entries:")
    if status.entries:
        lines.extend(render_entries(status.entries))
    else:
        lines.append("- none")

    lines.append("")
    lines.append("Components:")
    if status.components:
        lines.extend(render_components(status.components))
    else:
        lines.append("- none")

    return "\n".join(lines)


def render_discovery(result: DiscoveryResult) -> str:
    lines = [
        f"Detected: {result.spec.type}",
        f"Name: {result.spec.name}",
        f"URL: {result.spec.url}",
        f"Method: {result.detection}",
    ]
    if result.preset is not None:
        lines.append(f"Preset: {result.preset}")
    lines.append("Config:")
    lines.append(json.dumps(result.config_entry, indent=2))
    return "\n".join(lines)


def render_entries(entries: Iterable[FeedEntry]) -> list[str]:
    lines: list[str] = []
    for entry in entries:
        line = f"- {entry.title}"
        if entry.updated is not None:
            line += f" [{entry.updated.isoformat()}]"
        lines.append(line)
        if entry.summary:
            lines.append(f"  {entry.summary}")
        if entry.link:
            lines.append(f"  {entry.link}")
    return lines


def render_components(components: Iterable[ComponentSnapshot]) -> list[str]:
    lines: list[str] = []
    for component in components:
        line = f"- {component.name}: {component.label} ({component.status})"
        if component.updated is not None:
            line += f" [{component.updated.isoformat()}]"
        lines.append(line)
        if component.details:
            lines.append(f"  {component.details}")
        if component.link:
            lines.append(f"  {component.link}")
    return lines


def render_incidents(incidents: Iterable[IncidentSnapshot]) -> list[str]:
    lines: list[str] = []
    for incident in incidents:
        line = f"- {incident.title} ({incident.state})"
        if incident.updated is not None:
            line += f" [{incident.updated.isoformat()}]"
        lines.append(line)
        if incident.summary:
            lines.append(f"  {incident.summary}")
    return lines


def serialize_inspection(spec: SourceSpec, status: ServiceStatus) -> dict[str, Any]:
    data = asdict(status)
    data["spec"] = asdict(spec)
    return normalize_json(data)


def serialize_discovery(result: DiscoveryResult) -> dict[str, Any]:
    return normalize_json(
        {
            "spec": asdict(result.spec),
            "config_entry": result.config_entry,
            "detection": result.detection,
            "preset": result.preset,
        }
    )


def normalize_json(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, list):
        return [normalize_json(item) for item in value]
    if isinstance(value, dict):
        return {key: normalize_json(item) for key, item in value.items()}
    return value
