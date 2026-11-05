import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import create_app

pytestmark = pytest.mark.security


def test_not_found_uses_error_envelope():
    with TestClient(create_app()) as client:
        response = client.get("/not-found")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "HTTP_404"
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]


def test_validation_does_not_echo_sensitive_input():
    app: FastAPI = create_app()

    @app.get("/validate")
    def endpoint(count: int):
        return count

    with TestClient(app) as client:
        response = client.get("/validate?count=secret-input")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "secret-input" not in response.text


def test_internal_error_is_sanitized(caplog):
    app = create_app()

    @app.get("/broken")
    def endpoint():
        raise RuntimeError("secret-password")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/broken")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "secret-password" not in response.text + caplog.text
