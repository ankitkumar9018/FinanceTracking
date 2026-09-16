"""The Windows desktop shell's requests must survive Chromium's checks.

On Windows the bundled UI runs on https://tauri.localhost (WebView2/Chromium)
and calls the sidecar on 127.0.0.1. Chromium's Private Network Access sends a
preflight with `Access-Control-Request-Private-Network: true` before any fetch
to a loopback address and DROPS the request unless the reply grants it. The
desktop.log from a real Windows launch showed the backend healthy for four
minutes with zero requests from the webview — every fetch was blocked before
it left the browser.
"""

import pytest
from httpx import AsyncClient

PNA_PREFLIGHT = {
    "Origin": "https://tauri.localhost",
    "Access-Control-Request-Method": "POST",
    "Access-Control-Request-Headers": "content-type",
    "Access-Control-Request-Private-Network": "true",
}


@pytest.mark.asyncio
async def test_pna_preflight_from_windows_desktop_origin_is_granted(client: AsyncClient):
    r = await client.options("/api/v1/auth/login", headers=PNA_PREFLIGHT)
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") in ("https://tauri.localhost", "*")
    assert r.headers.get("access-control-allow-private-network") == "true"


@pytest.mark.asyncio
async def test_pna_header_absent_when_not_requested(client: AsyncClient):
    """Only granted when asked for — never sprayed onto every response."""
    r = await client.get("/health")
    assert r.status_code == 200
    assert "access-control-allow-private-network" not in r.headers
