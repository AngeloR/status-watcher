# Status Watcher

`status-watcher` is a terminal dashboard for monitoring public service status feeds and status pages. It turns Atom/RSS history feeds into a live retro-cyber console and includes a basic adapter model for expanding beyond feeds over time.

![Status Watcher screenshot](docs/screenshot.png)

## Features

- Rich terminal UI with keyboard navigation and auto-refresh
- Atom and RSS feed support out of the box
- Generic Atlassian Statuspage adapter for public `summary.json` and incident timelines
- Persistent per-service change history across refreshes and restarts
- Retry/backoff plus last-known-good response caching for flaky sources
- Adapter registry for future source types
- Backward-compatible `feeds.json` config
- Centralized incident normalization and status inference

## Current Status

This project is early-stage (`0.2.0`). Feed-based sources remain supported, and public Statuspage sites now have a first-class adapter. The HTML adapter still exists as a basic extension point and should be treated as experimental.

## Installation

### Local checkout

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Run

```bash
status-watcher
```

You can also run it directly from the repo:

```bash
python3 tui.py
python3 -m status_watcher
```

By default the app persists history to `~/.status-watcher/state.json`. Set `STATUS_WATCHER_STATE_PATH` to override that path.
By default the app caches last-known-good source responses under `~/.status-watcher/cache`. Set `STATUS_WATCHER_CACHE_DIR` to override that path.

## Configuration

By default the app loads `./feeds.json` when present. If that file does not exist, it falls back to built-in defaults.

You can also pass an explicit config path:

```bash
status-watcher path/to/feeds.json
```

### Config format

Minimal feed entry:

```json
[
  {
    "name": "GitHub",
    "url": "https://www.githubstatus.com/history.atom"
  }
]
```

Explicit source types:

```json
[
  {
    "name": "Claude",
    "type": "statuspage",
    "url": "https://status.claude.com"
  },
  {
    "name": "GitHub",
    "type": "feed",
    "url": "https://www.githubstatus.com/history.atom"
  },
  {
    "name": "Example HTML Status",
    "type": "html",
    "url": "https://example.com/status"
  }
]
```

`type` is optional and defaults to `feed`.

Statuspage sources also accept `recent_incidents` to control how much recent incident history is pulled from `incidents.json`.

## Architecture

The codebase is split into a few small layers:

- `status_watcher.config`: config loading, defaults, runtime constants
- `status_watcher.domain`: normalized feed parsing helpers, incident matching, status inference
- `status_watcher.history`: persisted snapshots and change detection
- `status_watcher.sources`: source adapters, fetch/cache helpers, and adapter registry
- `status_watcher.monitor`: load pipeline and service-level error mapping
- `status_watcher.ui`: Rich rendering
- `status_watcher.app`: terminal event loop and application entrypoint

Contributors adding new source types should focus on the adapter layer. Adapters should produce normalized `FeedEntry` records and leave status classification to the domain layer.

## Development

Install and run tests:

```bash
pip install -e .
python3 -m unittest discover -s tests
```

## Releases

This repository uses conventional commits via PR titles and Release Please for automated release PRs.

- Open PRs with conventional titles such as `feat(sources): add statuspage api adapter` or `fix(domain): handle resolved incidents`
- Squash merge PRs into `main`
- Let Release Please open the release PR that updates the version and `CHANGELOG.md`
- Merge the Release Please PR to create the GitHub release and tag

## Roadmap

- Better HTML/status-page extraction
- JSON/API-based source adapters
- Better screenshots/demo assets for the README

## Limitations

- Status inference is heuristic and source-dependent
- HTML support is not yet site-specific or hardened
- The dashboard is terminal-first and not intended as a library API yet

## License

MIT. See [LICENSE](LICENSE).
