"""Smoke: полный download через nginx (opt-in, ``pytest -m smoke``)."""

import os

import pytest

from tests.smoke.nginx_download_flow import (
    DEFAULT_BASE,
    SmokeUnavailable,
    run_smoke,
)


@pytest.mark.smoke
def test__download__via_nginx_bytes():
    base = os.getenv("SMOKE_BASE", DEFAULT_BASE)
    try:
        result = run_smoke(base_url=base, keep=False)
    except SmokeUnavailable as exc:
        pytest.skip(str(exc))

    assert result.download_url.startswith(base.rstrip("/"))
    assert result.token
    assert result.server is not None
    assert result.server.lower().startswith("nginx")
    assert result.body.startswith(b"%PDF-1.4")
