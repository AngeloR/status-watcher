# Contributing

## Local setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Running tests

```bash
python3 -m unittest discover -s tests
```

## Project expectations

- Keep changes focused and easy to review.
- Preserve backward compatibility for existing `feeds.json` entries unless there is a strong reason not to.
- Treat the adapter contract as the main extension point for new source types.
- Keep source-specific parsing in `status_watcher.sources` and shared status inference in `status_watcher.domain`.

## Adding a new source adapter

1. Add an adapter under `status_watcher/sources/`.
2. Return normalized `FeedEntry` values from the adapter.
3. Register the adapter in `status_watcher/sources/__init__.py`.
4. Add tests for config loading or domain behavior when relevant.
5. Update the README if the new source type is user-facing.

## Pull requests

- Include a short description of the user-facing impact.
- Mention any config or compatibility implications.
- Include tests or explain why tests were not added.
