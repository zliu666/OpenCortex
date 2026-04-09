"""Tests for the OpenCortex HTTP API server."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create a test client with mocked build_runtime."""
    with patch("opencortex.api_server.app.build_runtime") as mock_build, \
         patch("opencortex.api_server.app.start_runtime", new_callable=AsyncMock) as mock_start, \
         patch("opencortex.api_server.app.close_runtime", new_callable=AsyncMock) as mock_close:

        # Create mock bundle
        mock_bundle = MagicMock()
        mock_engine = MagicMock()
        mock_engine.total_usage = None
        mock_engine.submit_message = AsyncMock()
        mock_bundle.engine = mock_engine
        mock_build.return_value = mock_bundle

        from opencortex.api_server.app import app
        with TestClient(app) as c:
            yield c, mock_build, mock_bundle


def test_status(client):
    c, _, _ = client
    resp = c.get("/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "version" in data
    assert "model" in data


def test_query_empty_prompt(client):
    c, _, _ = client
    resp = c.post("/query", json={"prompt": ""})
    assert resp.status_code == 400


def test_query_missing_prompt(client):
    c, _, _ = client
    resp = c.post("/query", json={})
    assert resp.status_code == 422  # Pydantic validation error


def test_session_not_found(client):
    c, _, _ = client
    resp = c.post("/session/nonexistent/message", json={"prompt": "hello"})
    assert resp.status_code == 404


def test_delete_session_not_found(client):
    c, _, _ = client
    resp = c.delete("/session/nonexistent")
    assert resp.status_code == 404
