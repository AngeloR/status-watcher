from __future__ import annotations

import json

from pathlib import Path
from typing import Any


FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def fixture_path(*parts: str) -> Path:
    return FIXTURES_DIR.joinpath(*parts)


def load_fixture_bytes(*parts: str) -> bytes:
    return fixture_path(*parts).read_bytes()


def load_fixture_text(*parts: str) -> str:
    return fixture_path(*parts).read_text(encoding="utf-8")


def load_fixture_json(*parts: str) -> Any:
    return json.loads(load_fixture_text(*parts))
