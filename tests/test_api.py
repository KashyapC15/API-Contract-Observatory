from fastapi.testclient import TestClient

from api import main
from api.main import app
from api.models import RiskReport

client = TestClient(app)


def test_health_check_returns_ok() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_analyze_rejects_invalid_yaml() -> None:
    response = client.post(
        "/analyze",
        json={"api_v1": "not: [valid", "api_v2": "openapi: 3.0.3\npaths: {}"},
    )

    assert response.status_code == 400
    assert "Invalid YAML" in response.json()["detail"]


def test_analyze_returns_detected_changes_and_validated_report(monkeypatch) -> None:
    monkeypatch.setattr(
        main,
        "analyze_changes",
        lambda changes: RiskReport(
            risk="HIGH",
            breaking=True,
            confidence=0.94,
            reason="Clients may rely on the removed field.",
            affected_consumers=["Web clients"],
            recommended_action="Keep the field or release a new API version.",
            human_review_required=False,
        ),
    )
    response = client.post(
        "/analyze",
        json={
            "api_v1": "openapi: 3.0.3\npaths: {}\ncomponents:\n  schemas:\n    User:\n      properties:\n        name:\n          type: string\n",
            "api_v2": "openapi: 3.0.3\npaths: {}\ncomponents:\n  schemas:\n    User:\n      properties: {}\n",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["changes"] == [
        {"type": "FIELD_REMOVED", "location": "User.name"}
    ]
    assert body["risk_report"]["risk"] == "HIGH"
