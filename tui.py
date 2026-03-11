#!/usr/bin/env python3
"""
status_dashboard.py

A Rich-based terminal dashboard for monitoring status Atom/RSS feeds.

Features:
- Multiple feeds
- Graphical dashboard in terminal
- Auto-refresh
- Keyboard navigation
- Attempts to infer whether a service currently has an issue
- Single-file script

Usage:
    python3 status_dashboard.py
    python3 status_dashboard.py feeds.json

Keys:
    q         quit
    j / down  move down
    k / up    move up
    r         refresh now
"""

from __future__ import annotations

import datetime as dt
import html
import json
import os
import queue
import re
import select
import sys
import termios
import textwrap
import threading
import time
import traceback
import tty
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional, Tuple

from rich import box
from rich.align import Align
from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text


DEFAULT_FEEDS = [
    {
        "name": "Claude",
        "url": "https://status.claude.com/history.atom",
    },
]

REFRESH_SECONDS = 120
HTTP_TIMEOUT_SECONDS = 15
USER_AGENT = "status-dashboard/2.0 (+rich terminal monitor)"
MAX_ENTRIES_PER_FEED = 30

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


ACTIVE_TERMS = [
    "investigating",
    "identified",
    "monitoring",
    "degraded performance",
    "partial outage",
    "major outage",
    "outage",
    "service disruption",
    "elevated errors",
    "elevated error",
    "incident",
    "connection timeout",
    "timeouts",
    "unresponsive",
    "failing",
    "login issues",
    "performance issues",
    "disruption",
]

RESOLVED_TERMS = [
    "resolved",
    "completed",
    "operational",
    "recovered",
    "restored",
    "monitoring complete",
]

DEGRADED_TERMS = [
    "degraded",
    "partial outage",
    "elevated",
    "issue",
    "issues",
    "timeouts",
    "latency",
]

TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")
STATE_PREFIX_RE = re.compile(
    r"^(investigating|identified|monitoring|resolved|update|completed|in progress|scheduled)\s*-\s*",
    re.IGNORECASE,
)


@dataclass
class FeedEntry:
    title: str
    summary: str
    updated: Optional[dt.datetime]
    link: str = ""


@dataclass
class ServiceStatus:
    name: str
    url: str
    ok: bool
    severity: str  # operational | degraded | issue | error | unknown
    headline: str
    details: str
    updated: Optional[dt.datetime]
    error: Optional[str] = None
    entries: List[FeedEntry] = field(default_factory=list)


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def strip_html(text: str) -> str:
    if not text:
        return ""
    text = html.unescape(text)
    text = TAG_RE.sub(" ", text)
    text = SPACE_RE.sub(" ", text).strip()
    return text


def parse_date(value: str) -> Optional[dt.datetime]:
    if not value:
        return None

    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone.utc)
    except Exception:
        pass

    try:
        value = value.replace("Z", "+00:00")
        parsed = dt.datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone.utc)
    except Exception:
        return None


def fmt_age(ts: Optional[dt.datetime]) -> str:
    if not ts:
        return "unknown"
    delta = now_utc() - ts
    s = int(delta.total_seconds())
    if s < 60:
        return f"{s}s ago"
    m = s // 60
    if m < 60:
        return f"{m}m ago"
    h = m // 60
    if h < 48:
        return f"{h}h ago"
    d = h // 24
    return f"{d}d ago"


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


def contains_any(text: str, terms: List[str]) -> bool:
    lower = text.lower()
    return any(term in lower for term in terms)


def normalize_incident_key(title: str, summary: str) -> str:
    source = strip_html(title or summary or "")
    source = STATE_PREFIX_RE.sub("", source)
    source = source.lower()
    source = re.sub(r"[^a-z0-9\s]+", " ", source)
    source = SPACE_RE.sub(" ", source).strip()
    return source


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


def parse_feed(xml_bytes: bytes) -> List[FeedEntry]:
    root = ET.fromstring(xml_bytes)
    tag = root.tag.lower()

    if tag.endswith("feed"):
        return parse_atom(root)
    if tag.endswith("rss") or tag.endswith("rdf"):
        return parse_rss(root)

    raise ValueError(f"Unsupported feed format: {root.tag}")


def parse_atom(root: ET.Element) -> List[FeedEntry]:
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}")[0] + "}"

    entries: List[FeedEntry] = []
    for item in root.findall(f"{ns}entry"):
        title = (item.findtext(f"{ns}title") or "").strip()
        summary = (
            item.findtext(f"{ns}summary")
            or item.findtext(f"{ns}content")
            or ""
        ).strip()
        updated = parse_date(
            (item.findtext(f"{ns}updated") or item.findtext(f"{ns}published") or "").strip()
        )

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


def parse_rss(root: ET.Element) -> List[FeedEntry]:
    channel = root.find("channel")
    items = channel.findall("item") if channel is not None else root.findall(".//item")

    entries: List[FeedEntry] = []
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


def classify_entry(entry: FeedEntry) -> Dict[str, Any]:
    title = strip_html(entry.title)
    summary = strip_html(entry.summary)
    combined = f"{title} {summary}".lower()

    resolved = contains_any(combined, RESOLVED_TERMS)
    active = contains_any(combined, ACTIVE_TERMS)
    degraded = contains_any(combined, DEGRADED_TERMS)

    if resolved and not active:
        state = "resolved"
    elif active:
        state = "issue"
    elif degraded:
        state = "degraded"
    else:
        state = "unknown"

    return {
        "state": state,
        "key": normalize_incident_key(title, summary),
        "title": title,
        "summary": summary,
        "updated": entry.updated,
    }


def infer_service_status(name: str, url: str, entries: List[FeedEntry]) -> ServiceStatus:
    if not entries:
        return ServiceStatus(
            name=name,
            url=url,
            ok=False,
            severity="unknown",
            headline="No entries found",
            details="The feed loaded but did not contain any entries.",
            updated=None,
            entries=[],
        )

    classified = [classify_entry(e) for e in entries[:MAX_ENTRIES_PER_FEED]]

    latest_by_key: Dict[str, Dict[str, Any]] = {}
    for item in classified:
        key = item["key"] or item["title"]
        if key not in latest_by_key:
            latest_by_key[key] = item

    active = []
    degraded = []

    for item in latest_by_key.values():
        if item["state"] == "issue":
            active.append(item)
        elif item["state"] == "degraded":
            degraded.append(item)

    if active:
        active.sort(key=lambda x: x["updated"] or dt.datetime.min.replace(tzinfo=dt.timezone.utc), reverse=True)
        top = active[0]
        return ServiceStatus(
            name=name,
            url=url,
            ok=False,
            severity="issue",
            headline=top["title"] or "Active issue",
            details=top["summary"] or top["title"] or "Issue inferred from recent feed entries.",
            updated=top["updated"],
            entries=entries,
        )

    if degraded:
        degraded.sort(key=lambda x: x["updated"] or dt.datetime.min.replace(tzinfo=dt.timezone.utc), reverse=True)
        top = degraded[0]
        return ServiceStatus(
            name=name,
            url=url,
            ok=False,
            severity="degraded",
            headline=top["title"] or "Degraded",
            details=top["summary"] or top["title"] or "Degraded state inferred from recent feed entries.",
            updated=top["updated"],
            entries=entries,
        )

    latest = entries[0]
    latest_title = strip_html(latest.title) or "Operational"
    latest_summary = strip_html(latest.summary) or "No active issues inferred from recent entries."

    return ServiceStatus(
        name=name,
        url=url,
        ok=True,
        severity="operational",
        headline="Operational",
        details=f"Latest update: {latest_title}. {latest_summary}",
        updated=latest.updated,
        entries=entries,
    )


def load_service(name: str, url: str) -> ServiceStatus:
    try:
        raw = fetch_url(url)
        entries = parse_feed(raw)
        return infer_service_status(name, url, entries)
    except urllib.error.HTTPError as e:
        return ServiceStatus(
            name=name,
            url=url,
            ok=False,
            severity="error",
            headline=f"HTTP {e.code}",
            details=str(e),
            updated=None,
            error=str(e),
        )
    except urllib.error.URLError as e:
        return ServiceStatus(
            name=name,
            url=url,
            ok=False,
            severity="error",
            headline="Network error",
            details=str(e.reason),
            updated=None,
            error=str(e),
        )
    except Exception as e:
        return ServiceStatus(
            name=name,
            url=url,
            ok=False,
            severity="error",
            headline="Parse error",
            details=f"{type(e).__name__}: {e}",
            updated=None,
            error=traceback.format_exc(limit=1),
        )


def load_all(feeds: List[Dict[str, str]]) -> List[ServiceStatus]:
    results: List[ServiceStatus] = []
    for feed in feeds:
        results.append(load_service(feed["name"], feed["url"]))
    return results


def load_feeds_from_file(path: str) -> List[Dict[str, str]]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError("Feed config must be a JSON array")

    feeds: List[Dict[str, str]] = []
    for item in data:
        if not isinstance(item, dict) or "name" not in item or "url" not in item:
            raise ValueError("Each feed must contain 'name' and 'url'")
        feeds.append({"name": str(item["name"]), "url": str(item["url"])})
    return feeds


class KeyboardReader:
    def __init__(self) -> None:
        self.queue: "queue.Queue[str]" = queue.Queue()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._enabled = sys.stdin.isatty()
        self._old_settings = None

    def start(self) -> None:
        if not self._enabled:
            return
        self._old_settings = termios.tcgetattr(sys.stdin.fileno())
        tty.setcbreak(sys.stdin.fileno())
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._enabled and self._old_settings is not None:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, self._old_settings)

    def _run(self) -> None:
        while not self._stop.is_set():
            rlist, _, _ = select.select([sys.stdin], [], [], 0.1)
            if not rlist:
                continue

            ch = sys.stdin.read(1)
            if ch == "\x1b":
                seq = ch
                rlist, _, _ = select.select([sys.stdin], [], [], 0.01)
                while rlist:
                    seq += sys.stdin.read(1)
                    rlist, _, _ = select.select([sys.stdin], [], [], 0.01)
                self.queue.put(seq)
            else:
                self.queue.put(ch)

    def get_key(self) -> Optional[str]:
        try:
            return self.queue.get_nowait()
        except queue.Empty:
            return None


def normalize_key(key: Optional[str]) -> Optional[str]:
    if key is None:
        return None

    keymap = {
        "\x1b[A": "up",
        "\x1bOA": "up",
        "\x1b[B": "down",
        "\x1bOB": "down",
        "k": "up",
        "K": "up",
        "j": "down",
        "J": "down",
        "r": "refresh",
        "R": "refresh",
        "q": "quit",
        "Q": "quit",
    }
    return keymap.get(key, key)


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
    table.add_column("AGE", width=10)
    table.add_column("LIVE SIGNAL", ratio=1)

    for idx, s in enumerate(statuses):
        pointer = ">" if idx == selected else " "
        glyph = Text(severity_glyph(s.severity), style=severity_style(s.severity))
        label = Text.assemble(
            (severity_label(s.severity), severity_style(s.severity)),
            ("", ""),
        )
        headline = strip_html(s.headline)
        updated = fmt_age(s.updated)
        row_style = f"bold {PALETTE['white']} on #0A1418" if idx == selected else PALETTE["white"]
        service = Text.assemble(
            (pointer, f"bold {PALETTE['cyan']}"),
            (" ", ""),
            (s.name.upper(), row_style),
        )
        signal = Text(headline, style=row_style)
        age_style = f"bold {PALETTE['dim']}" if s.severity == "operational" else severity_style(s.severity)

        table.add_row(glyph, service, label, Text(updated, style=age_style), signal, style=row_style)

    return table


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
    body.append(Rule(style=PALETTE["grid"]))

    body.append(Text("INCIDENT TRACE", style=f"bold {PALETTE['cyan']}"))
    body.append(Text(strip_html(status.details) or "No details available.", style=PALETTE["white"]))

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


def build_header(statuses: List[ServiceStatus], last_refresh: float) -> Panel:
    operational = sum(1 for s in statuses if s.severity == "operational")
    issues = sum(1 for s in statuses if s.severity == "issue")
    degraded = sum(1 for s in statuses if s.severity == "degraded")
    errors = sum(1 for s in statuses if s.severity == "error")

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
    )
    ops = Text.assemble(
        ("ALERT ", f"bold {PALETTE['dim']}"), (alert_state, alert_style),
        ("   AUTO-SCAN ", f"bold {PALETTE['dim']}"), (f"{REFRESH_SECONDS}s", f"bold {PALETTE['cyan']}"),
        ("   LAST SYNC ", f"bold {PALETTE['dim']}"), (f"{age}s ago", f"bold {PALETTE['white']}"),
    )
    controls = Text(
        "NAV j/k or arrows   REFRESH r   EXIT q",
        style=f"bold {PALETTE['dim']}",
    )

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


def build_layout(statuses: List[ServiceStatus], selected: int, last_refresh: float) -> Layout:
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

    layout["header"].update(build_header(statuses, last_refresh))
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


def main() -> int:
    feeds = DEFAULT_FEEDS
    if len(sys.argv) > 1:
        feeds = load_feeds_from_file(sys.argv[1])

    console = Console()
    keyboard = KeyboardReader()

    statuses = load_all(feeds)
    selected = 0
    last_refresh = time.time()

    keyboard.start()
    try:
        with Live(
            build_layout(statuses, selected, last_refresh),
            console=console,
            refresh_per_second=8,
            screen=True,
        ) as live:
            while True:
                key = normalize_key(keyboard.get_key())
                needs_render = key is not None

                if key == "quit":
                    break
                elif key == "refresh":
                    statuses = load_all(feeds)
                    if selected >= len(statuses):
                        selected = max(0, len(statuses) - 1)
                    last_refresh = time.time()
                elif key == "down":
                    if statuses:
                        selected = min(len(statuses) - 1, selected + 1)
                elif key == "up":
                    if statuses:
                        selected = max(0, selected - 1)

                if time.time() - last_refresh >= REFRESH_SECONDS:
                    statuses = load_all(feeds)
                    if selected >= len(statuses):
                        selected = max(0, len(statuses) - 1)
                    last_refresh = time.time()
                    needs_render = True

                if needs_render:
                    live.update(build_layout(statuses, selected, last_refresh), refresh=True)

                time.sleep(0.05)
    finally:
        keyboard.stop()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
