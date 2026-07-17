"""
S6 regression: baseline security response headers.

The app adds these via a `@app.middleware("http")` in app/main.py. HSTS is gated
on the ENABLE_HSTS flag (off by default; on only behind real TLS termination).
See agents/s6-security-headers-fix-plan.md.

House style mirrors test_cors.py: class-based, case-insensitive header lookups
via resp.headers.get(...), using the shared `client` fixture.
"""

from unittest.mock import patch

import app.main as main

PREFIX = "/api/v1/auth"

# `/auth/me` with no cookie returns 401, but the middleware wraps the auth
# dependency, so the headers are still applied — a no-setup endpoint to assert on.
BASELINE = {
    "x-content-type-options": "nosniff",
    "referrer-policy": "strict-origin-when-cross-origin",
    "x-frame-options": "DENY",
    "content-security-policy": "default-src 'none'; frame-ancestors 'none'",
}


class TestSecurityHeaders:
    def test_baseline_headers_present(self, client):
        resp = client.get(f"{PREFIX}/me")
        for name, value in BASELINE.items():
            assert resp.headers.get(name) == value

    def test_headers_present_on_error_response(self, client):
        resp = client.get(f"{PREFIX}/me")
        assert resp.status_code == 401
        assert resp.headers.get("x-frame-options") == "DENY"

    def test_hsts_absent_by_default(self, client):
        resp = client.get(f"{PREFIX}/me")
        assert "strict-transport-security" not in resp.headers

    def test_hsts_present_when_enabled(self, client):
        with patch.object(main, "ENABLE_HSTS", True):
            resp = client.get(f"{PREFIX}/me")
        assert resp.headers.get("strict-transport-security") == (
            "max-age=31536000; includeSubDomains"
        )
