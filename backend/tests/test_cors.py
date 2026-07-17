"""
Tests for CORS configuration (S3).

Verifies that the credentialed CORS policy in app/main.py allows the real
frontend origin (https://127.0.0.1:3000) and rejects everything else — including
the port-less https://127.0.0.1 that the original buggy config allowed.

Preflight OPTIONS requests are used so CORSMiddleware answers before routing,
which means no endpoint auth or mocking is needed. The default origin
(https://127.0.0.1:3000) applies because conftest does not set
CORS_ALLOWED_ORIGINS. See agents/s3-cors-origin-fix-plan.md.
"""

PREFLIGHT = {"Access-Control-Request-Method": "GET"}


class TestCORS:
    def test_allowed_origin_is_echoed_with_credentials(self, client):
        resp = client.options(
            "/api/v1/auth/me",
            headers={"Origin": "https://127.0.0.1:3000", **PREFLIGHT},
        )
        assert resp.headers.get("access-control-allow-origin") == "https://127.0.0.1:3000"
        assert resp.headers.get("access-control-allow-credentials") == "true"

    def test_disallowed_origin_is_rejected(self, client):
        resp = client.options(
            "/api/v1/auth/me",
            headers={"Origin": "https://evil.example.com", **PREFLIGHT},
        )
        assert "access-control-allow-origin" not in resp.headers

    def test_portless_localhost_origin_is_rejected(self, client):
        """Regression: the old config allowed https://127.0.0.1 (no port)."""
        resp = client.options(
            "/api/v1/auth/me",
            headers={"Origin": "https://127.0.0.1", **PREFLIGHT},
        )
        assert "access-control-allow-origin" not in resp.headers
