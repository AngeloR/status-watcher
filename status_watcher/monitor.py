from __future__ import annotations

import traceback
import urllib.error

from typing import List

from status_watcher.domain import infer_service_status
from status_watcher.models import ServiceStatus, SourceSpec
from status_watcher.sources import load_entries


def load_service(spec: SourceSpec) -> ServiceStatus:
    try:
        entries = load_entries(spec)
        return infer_service_status(spec.name, spec.url, entries)
    except urllib.error.HTTPError as e:
        return ServiceStatus(
            name=spec.name,
            url=spec.url,
            ok=False,
            severity="error",
            headline=f"HTTP {e.code}",
            details=str(e),
            updated=None,
            error=str(e),
        )
    except urllib.error.URLError as e:
        return ServiceStatus(
            name=spec.name,
            url=spec.url,
            ok=False,
            severity="error",
            headline="Network error",
            details=str(e.reason),
            updated=None,
            error=str(e),
        )
    except Exception as e:
        return ServiceStatus(
            name=spec.name,
            url=spec.url,
            ok=False,
            severity="error",
            headline="Parse error",
            details=f"{type(e).__name__}: {e}",
            updated=None,
            error=traceback.format_exc(limit=1),
        )


def load_all(specs: List[SourceSpec]) -> List[ServiceStatus]:
    return [load_service(spec) for spec in specs]
