from __future__ import annotations

from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.config import get_settings


@pytest.fixture(autouse=True)
def reset_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Force each test to use a clean data store."""

    data_file = tmp_path / "calls.json"
    monkeypatch.setenv("DATA_PATH", str(data_file))
    for key in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER"):
        monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()  # type: ignore[attr-defined]
    yield
    get_settings.cache_clear()  # type: ignore[attr-defined]


def create_client() -> TestClient:
    app = create_app()
    return TestClient(app)


def test_health_endpoint_reports_status():
    client = create_client()
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["twilio"] is False


def test_create_call_without_twilio_records_entry():
    client = create_client()
    response = client.post(
        "/calls",
        json={"to_number": "+15555550100", "message": "Hello from tests"},
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "recorded"
    assert payload["to_number"] == "+15555550100"

    list_response = client.get("/calls")
    assert list_response.status_code == 200
    calls = list_response.json()["calls"]
    assert len(calls) == 1
    assert calls[0]["id"] == payload["id"]


def test_update_status_changes_record():
    client = create_client()
    create_response = client.post(
        "/calls",
        json={"to_number": "+15555550100", "message": "Status update"},
    )
    call_id = create_response.json()["id"]

    update_response = client.post(
        f"/calls/{call_id}/status",
        json={"status": "completed", "provider_sid": "CA123"},
    )
    assert update_response.status_code == 200
    data = update_response.json()
    assert data["status"] == "completed"
    assert data["provider_sid"] == "CA123"
