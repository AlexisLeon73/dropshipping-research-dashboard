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
