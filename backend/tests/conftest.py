from __future__ import annotations

from pathlib import Path

import pytest

from labelspec.store import Store


@pytest.fixture()
def store(tmp_path: Path) -> Store:
    value = Store(tmp_path / "test.db")
    value.initialize()
    return value

