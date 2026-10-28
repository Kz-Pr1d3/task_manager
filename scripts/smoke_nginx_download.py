#!/usr/bin/env python3
"""CLI-обёртка: ``python scripts/smoke_nginx_download.py [--keep]``."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.smoke.nginx_download_flow import main

if __name__ == "__main__":
    raise SystemExit(main())
