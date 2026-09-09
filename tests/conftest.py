"""Point the app at a throwaway DB/cache dir before any app module is
imported, so tests never touch the real data/ directory.
"""
import os
import tempfile
from pathlib import Path

_tmp_dir = tempfile.mkdtemp(prefix="dashboard-tests-")
os.environ["DB_PATH"] = str(Path(_tmp_dir) / "test.db")
os.environ["CACHE_DIR"] = str(Path(_tmp_dir) / "cache")
