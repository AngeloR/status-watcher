from __future__ import annotations

import json
import urllib.request

from pathlib import Path


FIXTURES = [
    {
        "url": "https://status.claude.com/api/v2/summary.json",
        "path": Path("tests/fixtures/providers/claude_statuspage_summary.json"),
        "kind": "json",
    },
    {
        "url": "https://status.claude.com/api/v2/incidents.json",
        "path": Path("tests/fixtures/providers/claude_statuspage_incidents.json"),
        "kind": "json",
        "incident_limit": 10,
    },
    {
        "url": "https://status.claude.com/",
        "path": Path("tests/fixtures/providers/claude_status.html"),
        "kind": "text",
    },
    {
        "url": "https://status.openai.com/api/v2/summary.json",
        "path": Path("tests/fixtures/providers/openai_statuspage_summary.json"),
        "kind": "json",
    },
    {
        "url": "https://status.openai.com/api/v2/incidents.json",
        "path": Path("tests/fixtures/providers/openai_statuspage_incidents.json"),
        "kind": "json",
        "incident_limit": 10,
    },
    {
        "url": "https://www.githubstatus.com/api/v2/summary.json",
        "path": Path("tests/fixtures/providers/github_statuspage_summary.json"),
        "kind": "json",
    },
    {
        "url": "https://www.githubstatus.com/api/v2/incidents.json",
        "path": Path("tests/fixtures/providers/github_statuspage_incidents.json"),
        "kind": "json",
        "incident_limit": 10,
    },
    {
        "url": "https://www.githubstatus.com/api/v2/status.json",
        "path": Path("tests/fixtures/providers/github_status.json"),
        "kind": "json",
    },
    {
        "url": "https://www.vercel-status.com/api/v2/summary.json",
        "path": Path("tests/fixtures/providers/vercel_statuspage_summary.json"),
        "kind": "json",
    },
    {
        "url": "https://www.vercel-status.com/api/v2/incidents.json",
        "path": Path("tests/fixtures/providers/vercel_statuspage_incidents.json"),
        "kind": "json",
        "incident_limit": 10,
    },
    {
        "url": "https://linearstatus.com/api/v2/summary.json",
        "path": Path("tests/fixtures/providers/linear_statuspage_summary.json"),
        "kind": "json",
    },
    {
        "url": "https://linearstatus.com/api/v2/incidents.json",
        "path": Path("tests/fixtures/providers/linear_statuspage_incidents.json"),
        "kind": "json",
        "incident_limit": 10,
    },
]


def fetch_bytes(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "status-watcher fixture refresher"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read()


def write_fixture(repo_root: Path, spec: dict[str, object]) -> None:
    raw = fetch_bytes(str(spec["url"]))
    target = repo_root / Path(spec["path"])
    target.parent.mkdir(parents=True, exist_ok=True)

    if spec["kind"] == "json":
        payload = json.loads(raw.decode("utf-8"))
        incident_limit = int(spec.get("incident_limit", 0) or 0)
        if incident_limit > 0 and isinstance(payload, dict) and isinstance(payload.get("incidents"), list):
            payload = dict(payload)
            payload["incidents"] = payload["incidents"][:incident_limit]
        formatted = json.dumps(payload, indent=2)
        target.write_text(formatted + "\n", encoding="utf-8")
        return

    target.write_bytes(raw)


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    for spec in FIXTURES:
        write_fixture(repo_root, spec)
        print(f"updated {spec['path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
