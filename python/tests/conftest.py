from __future__ import annotations

import sys
from pathlib import Path

import pytest

# The distribution installs ``aab_*`` from python/src; the two services live in the repo and
# are imported from the source tree, exactly as the worker and API run them.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from aab_core import Settings  # noqa: E402
from aab_db import init_db, make_engine  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def settings(tmp_path, monkeypatch) -> Settings:
    monkeypatch.setenv("AAB_HOME", str(tmp_path))
    monkeypatch.setenv("AAB_MEDIA_DIR", str(tmp_path / "media"))
    monkeypatch.setenv("AAB_MODELS_DIR", str(tmp_path / "models"))
    monkeypatch.setenv("AAB_DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("AAB_TTS_PROVIDER", "fake")
    return Settings.load()


@pytest.fixture()
def engine(settings):
    engine = make_engine(settings.database_url)
    init_db(engine)
    return engine


@pytest.fixture()
def sample_path() -> Path:
    return FIXTURES / "sample.txt"
