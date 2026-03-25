from __future__ import annotations

import hashlib
import time
import urllib.error
import urllib.request

from pathlib import Path
from typing import Protocol

from status_watcher.config import (
    DEFAULT_CACHE_DIR,
    HTTP_RETRY_ATTEMPTS,
    HTTP_RETRY_BACKOFF_SECONDS,
    HTTP_TIMEOUT_SECONDS,
    USER_AGENT,
)
from status_watcher.models import FeedEntry, SourceSpec


DEFAULT_ACCEPT_HEADER = "application/atom+xml, application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.1"
TRANSIENT_HTTP_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}


class SourceAdapter(Protocol):
    def load(self, spec: SourceSpec) -> list[FeedEntry]:
        ...


def cache_path_for_url(url: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return Path(DEFAULT_CACHE_DIR) / f"{digest}.cache"


def load_cached_response(url: str) -> bytes | None:
    path = cache_path_for_url(url)
    if not path.exists():
        return None
    try:
        return path.read_bytes()
    except Exception:
        return None


def store_cached_response(url: str, payload: bytes) -> None:
    path = cache_path_for_url(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def fetch_url(url: str, accept: str = DEFAULT_ACCEPT_HEADER) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": accept,
        },
    )

    last_error: Exception | None = None
    for attempt in range(HTTP_RETRY_ATTEMPTS):
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code in TRANSIENT_HTTP_STATUS_CODES and attempt < HTTP_RETRY_ATTEMPTS - 1:
                time.sleep(HTTP_RETRY_BACKOFF_SECONDS * (2**attempt))
                continue
            if exc.code in TRANSIENT_HTTP_STATUS_CODES:
                cached = load_cached_response(url)
                if cached is not None:
                    return cached
            raise
        except urllib.error.URLError as exc:
            last_error = exc
            if attempt < HTTP_RETRY_ATTEMPTS - 1:
                time.sleep(HTTP_RETRY_BACKOFF_SECONDS * (2**attempt))
                continue
            cached = load_cached_response(url)
            if cached is not None:
                return cached
            raise

    if last_error is not None:
        raise last_error
    raise RuntimeError(f"Failed to fetch {url}")
