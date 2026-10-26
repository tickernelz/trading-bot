from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

EXAMPLE = Path(__file__).resolve().parent.parent / "config" / "config.example.yaml"


@pytest.fixture
def example_raw() -> dict:
    return copy.deepcopy(yaml.safe_load(EXAMPLE.read_text(encoding="utf-8")))


@pytest.fixture
def write_config(tmp_path):
    def write(raw: dict) -> Path:
        path = tmp_path / "config.yaml"
        path.write_text(yaml.safe_dump(raw), encoding="utf-8")
        return path

    return write
