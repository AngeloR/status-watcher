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

## Pull request titles

This repository uses conventional PR titles and prefers squash merges on `main`.

Valid examples:

- `feat(sources): add statuspage api adapter`
- `fix(domain): resolve resolved incidents correctly`
- `docs: clarify config examples`
- `refactor!: simplify source registry`

Use `!` for breaking changes in PR titles, since PR titles are single-line and do not support full commit bodies.

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
- Use a conventional PR title so the squash-merge commit is release-ready.

## Releases

- Release Please manages version bumps, changelog updates, tags, and GitHub releases.
- Do not manually edit version numbers in `pyproject.toml` or `status_watcher/__init__.py` for normal releases.
- Merge the Release Please PR to cut the next release.
