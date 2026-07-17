"""
1.1: liveness/readiness probes for compose healthchecks, the nginx upstream
check, and the deploy health gate.

The endpoints live at the root (/health, /health/ready) — not under /api/v1 —
and are unauthenticated and not rate-limited (they're infra probes). House
style mirrors test_security_headers.py: class-based, using the shared `client`
fixture, whose mock_db makes db.execute() a no-op MagicMock by default.
"""


class TestHealth:
    def test_liveness_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_liveness_unauthenticated(self, client):
        # No session cookie set on the client fixture — probe must still pass.
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_readiness_ok(self, client, mock_db):
        resp = client.get("/health/ready")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ready"}
        mock_db.execute.assert_called_once()

    def test_readiness_reports_db_failure(self, client, mock_db):
        mock_db.execute.side_effect = Exception("connection refused")
        resp = client.get("/health/ready")
        assert resp.status_code == 503
        assert resp.json()["detail"] == {"status": "unavailable"}
