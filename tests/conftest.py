"""Point the app at a throwaway DB/cache dir before any app module is
imported, so tests never touch the real data/ directory.
"""
import os
import shutil
import tempfile
from pathlib import Path

import pytest

_tmp_dir = tempfile.mkdtemp(prefix="dashboard-tests-")
os.environ["DB_PATH"] = str(Path(_tmp_dir) / "test.db")
os.environ["CACHE_DIR"] = str(Path(_tmp_dir) / "cache")


@pytest.fixture(autouse=True)
def _clear_disk_cache():
    """The disk cache in app/cache.py persists for the whole test session
    (same CACHE_DIR throughout). Without this, two tests that happen to
    query the same term (e.g. "mascotas" in both a pagination test and a
    scoring test) can read back a stale cached response from an earlier
    test's mocked network call instead of hitting their own mock.
    """
    cache_dir = Path(os.environ["CACHE_DIR"])
    if cache_dir.exists():
        shutil.rmtree(cache_dir)
    yield


@pytest.fixture(autouse=True)
def _clear_shared_db():
    """The default DB_PATH (set above) is shared for the whole test
    session too. Tests that exercise the app through TestClient without
    overriding db.settings.db_path (most of tests/test_pipeline.py and
    tests/test_batch.py) all write to that same file — without clearing
    it, a niche created in one test (e.g. "cocina") can be seen as a
    *previous run* by a later, unrelated test using the same niche name.
    Tests that explicitly monkeypatch db.settings.db_path to their own
    tmp_path file are unaffected, since they never touch this path.
    """
    db_path = Path(os.environ["DB_PATH"])
    if db_path.exists():
        db_path.unlink()
    yield
