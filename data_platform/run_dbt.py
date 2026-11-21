"""Convenience runner that loads .env and executes dbt commands against data_platform/warehouse_dbt."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
DBT_DIR = REPO_ROOT / "data_platform" / "warehouse_dbt"


def main() -> int:
    load_dotenv(REPO_ROOT / ".env")
    dbt_exe = Path(sys.executable).parent / ("dbt.exe" if sys.platform == "win32" else "dbt")
    cmd = [
        str(dbt_exe),
        *sys.argv[1:],
        "--project-dir",
        str(DBT_DIR),
        "--profiles-dir",
        str(DBT_DIR),
    ]
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
