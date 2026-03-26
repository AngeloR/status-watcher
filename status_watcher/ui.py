from __future__ import annotations

import time

from typing import Any, List, Optional, Tuple

from rich import box
from rich.align import Align
from rich.console import Group
from rich.layout import Layout
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from status_watcher.domain import fmt_age, impacted_components, sort_components, strip_html
from status_watcher.models import ComponentSnapshot, HistoryEvent, IncidentSnapshot, ServiceStatus


PALETTE = {
    "bg": "#05080A",
    "grid": "#12333B",
    "cyan": "#6DF2FF",
    "blue": "#1ED2FF",
    "green": "#4CFF87",
    "amber": "#FFC857",
    "red": "#FF5A7A",
    "white": "#D9FFF8",
    "dim": "#6C8A92",
}


def severity_style(severity: str) -> str:
    return {
        "operational": f"bold {PALETTE['green']}",
        "degraded": f"bold {PALETTE['amber']}",
        "issue": f"bold {PALETTE['red']}",
        "error": f"bold {PALETTE['red']}",
        "unknown": f"bold {PALETTE['white']}",
    }.get(severity, f"bold {PALETTE['white']}")


def severity_label(severity: str) -> str:
    return {
        "operational": "OPERATIONAL",
        "degraded": "DEGRADED",
        "issue": "ISSUE",
        "error": "ERROR",
        "unknown": "UNKNOWN",
    }.get(severity, "UNKNOWN")


def severity_accent(severity: str) -> str:
    return {
        "operational": PALETTE["green"],
        "degraded": PALETTE["amber"],
        "issue": PALETTE["red"],
        "error": PALETTE["red"],
        "unknown": PALETTE["white"],
    }.get(severity, PALETTE["white"])


def severity_glyph(severity: str) -> str:
    return {
        "operational": "●",
        "degraded": "▲",
        "issue": "■",
        "error": "✕",
        "unknown": "◇",
    }.get(severity, "◇")


def incident_severity(incident: IncidentSnapshot) -> str:
    return "issue" if incident.state == "issue" else "degraded"


def impacted_count(status: ServiceStatus) -> int:
    return len([component for component in status.components if component.status in {"issue", "degraded"}])


def component_counter(status: ServiceStatus) -> str:
    if not status.components:
        return "--"
    return f"{impacted_count(status)}/{len(status.components)}"


def status_signal_text(status: ServiceStatus) -> str:
    if len(status.current_incidents) > 1:
        return f"{len(status.current_incidents)} live incidents"
    if len(status.current_incidents) == 1:
        return strip_html(status.headline)

    impacted = impacted_components(status.components)
    if len(impacted) > 1:
        return f"{len(impacted)} impacted components"
    if len(impacted) == 1:
        component = impacted[0]
        return f"{component.name}: {component.label}"
    return strip_html(status.headline)


def build_summary_table(statuses: List[ServiceStatus], selected: int) -> Table:
    table = Table(
        box=box.SIMPLE_HEAVY,
        expand=True,
        header_style=f"bold {PALETTE['cyan']}",
        border_style=PALETTE["grid"],
        row_styles=[f"on {PALETTE['bg']}", ""],
        pad_edge=False,
    )
    table.add_column("", width=2, justify="center")
    table.add_column("NODE", min_width=16)
    table.add_column("STATE", width=15)
    table.add_column("COMP", width=7, justify="center")
    table.add_column("AGE", width=10)
    table.add_column("LIVE SIGNAL", ratio=1)

    for idx, status in enumerate(statuses):
        pointer = ">" if idx == selected else " "
        glyph = Text(severity_glyph(status.severity), style=severity_style(status.severity))
        label = Text(severity_label(status.severity), style=severity_style(status.severity))
        headline = status_signal_text(status)
        updated = fmt_age(status.updated)
        row_style = f"bold {PALETTE['white']} on #0A1418" if idx == selected else PALETTE["white"]
        service = Text.assemble(
            (pointer, f"bold {PALETTE['cyan']}"),
            (" ", ""),
            (status.name.upper(), row_style),
        )
        signal = Text(headline, style=row_style)
        age_style = f"bold {PALETTE['dim']}" if status.severity == "operational" else severity_style(status.severity)
        component_style = f"bold {PALETTE['dim']}" if impacted_count(status) == 0 else severity_style(status.severity)
        table.add_row(
            glyph,
            service,
            label,
            Text(component_counter(status), style=component_style),
            Text(updated, style=age_style),
            signal,
            style=row_style,
        )

    return table


def build_live_incidents(status: ServiceStatus) -> List[Any]:
    body: List[Any] = []
    if not status.current_incidents:
        body.append(Text("INCIDENT TRACE", style=f"bold {PALETTE['cyan']}"))
        body.append(Text(strip_html(status.details) or "No details available.", style=PALETTE["white"]))
        return body

    heading = "INCIDENT TRACE" if len(status.current_incidents) == 1 else f"LIVE INCIDENTS ({len(status.current_incidents)})"
    body.append(Text(heading, style=f"bold {PALETTE['cyan']}"))

    for incident in status.current_incidents[:5]:
        ts = fmt_age(incident.updated)
        title = strip_html(incident.title) or "(untitled incident)"
        summary = strip_html(incident.summary)
        if len(summary) > 220:
            summary = summary[:217] + "..."
        accent_style = severity_style(incident_severity(incident))
        body.append(
            Text.assemble(
                (severity_glyph(incident_severity(incident)), accent_style),
                (" ", ""),
                (title, f"bold {PALETTE['white']}"),
                (f"   {ts}", f"bold {PALETTE['dim']}"),
            )
        )
        if summary:
            body.append(Text(f"  {summary}", style=PALETTE["dim"]))

    if len(status.current_incidents) > 5:
        remaining = len(status.current_incidents) - 5
        body.append(Text(f"  +{remaining} more live incidents not shown", style=PALETTE["dim"]))

    return body


def component_rows(components: List[ComponentSnapshot]) -> List[ComponentSnapshot]:
    impacted = impacted_components(components)
    if impacted:
        return impacted[:6]
    return sort_components(components)[:5]


def build_component_lines(status: ServiceStatus) -> List[Any]:
    body: List[Any] = []
    if not status.components:
        return body

    impacted = impacted_components(status.components)
    heading = (
        f"COMPONENT STATUS ({len(impacted)}/{len(status.components)} impacted)"
        if impacted
        else f"COMPONENT STATUS ({len(status.components)} tracked)"
    )
    body.append(Text(""))
    body.append(Text(heading, style=f"bold {PALETTE['cyan']}"))

    visible = component_rows(status.components)
    for component in visible:
        ts = fmt_age(component.updated)
        label = component.label.upper()
        style = severity_style(component.status)
        body.append(
            Text.assemble(
                (severity_glyph(component.status), style),
                (" ", ""),
                (component.name, f"bold {PALETTE['white']}"),
                ("   ", ""),
                (label, style),
                (f"   {ts}", f"bold {PALETTE['dim']}"),
            )
        )
        details = strip_html(component.details)
        if details and details.lower() != component.name.lower():
            if len(details) > 180:
                details = details[:177] + "..."
            body.append(Text(f"  {details}", style=PALETTE["dim"]))

    if impacted:
        hidden_stable = len(status.components) - len(impacted)
        if hidden_stable > 0:
            body.append(Text(f"  {hidden_stable} stable components hidden", style=PALETTE["dim"]))
    elif len(status.components) > len(visible):
        body.append(Text(f"  +{len(status.components) - len(visible)} more components not shown", style=PALETTE["dim"]))

    return body


def build_recent_changes(events: List[HistoryEvent]) -> List[Any]:
    body: List[Any] = []
    if not events:
        return body

    body.append(Text(""))
    body.append(Text("RECENT CHANGES", style=f"bold {PALETTE['cyan']}"))
    for event in events[:5]:
        ts = fmt_age(event.timestamp)
        body.append(
            Text.assemble(
                ("> ", severity_style(event.severity)),
                (event.message, f"bold {PALETTE['white']}"),
                (f"   {ts}", f"bold {PALETTE['dim']}"),
            )
        )
    return body


def build_details_panel(status: Optional[ServiceStatus]) -> Panel:
    if status is None:
        return Panel(
            "No services configured.",
            title="TACTICAL VIEW",
            border_style=PALETTE["grid"],
            box=box.DOUBLE,
        )

    body: List[Any] = []
    accent = severity_accent(status.severity)
    body.append(
        Text.assemble(
            ("[", f"bold {PALETTE['cyan']}"),
            (status.name.upper(), f"bold {PALETTE['white']}"),
            ("] ", f"bold {PALETTE['cyan']}"),
            (severity_label(status.severity), severity_style(status.severity)),
        )
    )
    body.append(Text(f"LINK  {status.url}", style=PALETTE["dim"]))
    body.append(Text(f"SYNC  {fmt_age(status.updated)}", style=PALETTE["dim"]))
    if status.components:
        body.append(Text(f"COMP  {component_counter(status)} impacted", style=PALETTE["dim"]))
    body.append(Rule(style=PALETTE["grid"]))
    body.extend(build_live_incidents(status))
    body.extend(build_component_lines(status))
    body.extend(build_recent_changes(status.recent_changes))

    recent_entries = status.entries[:5]
    if recent_entries:
        body.append(Text(""))
        body.append(Text("RECENT TRANSMISSIONS", style=f"bold {PALETTE['cyan']}"))
        for entry in recent_entries:
            ts = fmt_age(entry.updated)
            title = strip_html(entry.title) or "(untitled)"
            summary = strip_html(entry.summary)
            if len(summary) > 180:
                summary = summary[:177] + "..."
            body.append(
                Text.assemble(
                    ("> ", f"bold {accent}"),
                    (title, f"bold {PALETTE['white']}"),
                    (f"   {ts}", f"bold {PALETTE['dim']}"),
                )
            )
            if summary:
                body.append(Text(f"  {summary}", style=PALETTE["dim"]))

    return Panel(
        Group(*body),
        title=f"TACTICAL VIEW // {status.name.upper()}",
        subtitle=f"{severity_glyph(status.severity)} LIVE FEED",
        border_style=accent,
        box=box.DOUBLE,
        padding=(1, 2),
        style=f"on {PALETTE['bg']}",
    )


def build_header(statuses: List[ServiceStatus], last_refresh: float, refresh_seconds: int) -> Panel:
    operational = sum(1 for status in statuses if status.severity == "operational")
    issues = sum(1 for status in statuses if status.severity == "issue")
    degraded = sum(1 for status in statuses if status.severity == "degraded")
    errors = sum(1 for status in statuses if status.severity == "error")
    impacted = sum(impacted_count(status) for status in statuses)

    age = int(time.time() - last_refresh)
    alert_state = "GREEN" if issues == 0 and degraded == 0 and errors == 0 else "ALERT"
    alert_style = severity_style("operational" if alert_state == "GREEN" else "issue")

    title = Text.assemble(
        ("STATUS WATCHER ", f"bold {PALETTE['cyan']}"),
        ("// ", f"bold {PALETTE['blue']}"),
        ("CYBER OPS CONSOLE", f"bold {PALETTE['green']}"),
    )
    stats = Text.assemble(
        ("NODES ", f"bold {PALETTE['dim']}"), (str(len(statuses)), f"bold {PALETTE['white']}"),
        ("   STABLE ", f"bold {PALETTE['dim']}"), (str(operational), f"bold {PALETTE['green']}"),
        ("   DEGRADED ", f"bold {PALETTE['dim']}"), (str(degraded), f"bold {PALETTE['amber']}"),
        ("   FAILURES ", f"bold {PALETTE['dim']}"), (str(issues + errors), f"bold {PALETTE['red']}"),
        ("   COMPONENTS ", f"bold {PALETTE['dim']}"), (str(impacted), f"bold {PALETTE['amber'] if impacted else PALETTE['green']}"),
    )
    ops = Text.assemble(
        ("ALERT ", f"bold {PALETTE['dim']}"), (alert_state, alert_style),
        ("   AUTO-SCAN ", f"bold {PALETTE['dim']}"), (f"{refresh_seconds}s", f"bold {PALETTE['cyan']}"),
        ("   LAST SYNC ", f"bold {PALETTE['dim']}"), (f"{age}s ago", f"bold {PALETTE['white']}"),
    )
    controls = Text("NAV j/k or arrows   REFRESH r   EXIT q", style=f"bold {PALETTE['dim']}")

    return Panel(
        Group(Align.left(title), stats, ops, controls),
        border_style=PALETTE["cyan"],
        box=box.DOUBLE,
        padding=(0, 2),
        style=f"on {PALETTE['bg']}",
    )


def build_status_strip(statuses: List[ServiceStatus], selected: int, last_refresh: float) -> Panel:
    if not statuses:
        text = Text("NO ACTIVE FEEDS", style=f"bold {PALETTE['dim']}")
        return Panel(text, border_style=PALETTE["grid"], box=box.SQUARE, padding=(0, 1))

    parts: List[Tuple[str, str]] = []
    for idx, status in enumerate(statuses):
        accent = severity_accent(status.severity)
        style = f"bold {PALETTE['bg']} on {accent}" if idx == selected else f"bold {accent}"
        parts.append((f" {status.name.upper()} ", style))
        if idx != len(statuses) - 1:
            parts.append((" ", ""))

    parts.append(("   ", ""))
    parts.append(("SCAN", f"bold {PALETTE['dim']}"))
    parts.append((f" {int(time.time() - last_refresh):03d}s", f"bold {PALETTE['white']}"))

    return Panel(
        Text.assemble(*parts),
        border_style=PALETTE["grid"],
        box=box.SQUARE,
        padding=(0, 1),
        style=f"on {PALETTE['bg']}",
    )


def build_layout(statuses: List[ServiceStatus], selected: int, last_refresh: float, refresh_seconds: int) -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=6),
        Layout(name="strip", size=3),
        Layout(name="body"),
    )
    layout["body"].split_row(
        Layout(name="table", ratio=2),
        Layout(name="details", ratio=3),
    )

    current = statuses[selected] if statuses else None
    layout["header"].update(build_header(statuses, last_refresh, refresh_seconds))
    layout["strip"].update(build_status_strip(statuses, selected, last_refresh))
    layout["table"].update(
        Panel(
            build_summary_table(statuses, selected),
            title="NETWORK MAP",
            subtitle="RETROFEED BUS",
            border_style=PALETTE["cyan"],
            box=box.DOUBLE,
            padding=(1, 1),
            style=f"on {PALETTE['bg']}",
        )
    )
    layout["details"].update(build_details_panel(current))
    return layout
