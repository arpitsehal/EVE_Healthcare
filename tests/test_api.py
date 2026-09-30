import os
from collections.abc import Generator
from datetime import datetime, timedelta, timezone

os.environ.setdefault("DATABASE_URL", "sqlite://")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    test_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)

    def override_get_db() -> Generator[Session, None, None]:
        db = test_session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def signup(client: TestClient, email: str, name: str = "Test Patient") -> dict:
    response = client.post(
        "/auth/signup", json={"name": name, "email": email, "password": "test-password-123"}
    )
    assert response.status_code == 201, response.text
    return response.json()


def login(client: TestClient, email: str) -> dict[str, str]:
    response = client.post(
        "/auth/login", json={"email": email, "password": "test-password-123"}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def create_centre_and_test(client: TestClient, headers: dict[str, str]) -> tuple[int, int]:
    centre_response = client.post(
        "/centres", headers=headers, json={"name": "North Lab", "location": "Seattle"}
    )
    assert centre_response.status_code == 201, centre_response.text
    centre_id = centre_response.json()["id"]
    test_response = client.post(
        f"/centres/{centre_id}/tests",
        headers=headers,
        json={"name": "Complete Blood Count", "description": "CBC", "price": "42.50"},
    )
    assert test_response.status_code == 201, test_response.text
    return centre_id, test_response.json()["id"]


def create_booking(
    client: TestClient, headers: dict[str, str], centre_id: int, test_id: int
) -> dict:
    appointment = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    response = client.post(
        "/bookings",
        headers=headers,
        json={"centre_id": centre_id, "test_id": test_id, "appointment_at": appointment},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_authentication_validation_and_catalog_ownership(client: TestClient) -> None:
    signup(client, "owner@example.com", "Centre Owner")
    owner = login(client, "owner@example.com")
    signup(client, "other@example.com", "Other User")
    other_user = login(client, "other@example.com")

    assert client.post(
        "/auth/signup",
        json={"name": "Duplicate", "email": "OWNER@example.com", "password": "test-password-123"},
    ).status_code == 409
    assert client.post("/auth/login", json={"email": "owner@example.com", "password": "incorrect-password"}).status_code == 401
    assert client.post("/centres", json={"name": "No auth", "location": "Nowhere"}).status_code == 401

    centre_id, test_id = create_centre_and_test(client, owner)
    assert client.patch(
        f"/centres/{centre_id}", headers=other_user, json={"name": "Hijack"}
    ).status_code == 403
    catalogue = client.get("/centres").json()
    assert catalogue[0]["tests"][0]["id"] == test_id
    assert client.get(f"/centres/{centre_id}/tests").status_code == 200


def test_booking_validation_ownership_and_payment_idempotency(client: TestClient) -> None:
    signup(client, "patient@example.com")
    patient = login(client, "patient@example.com")
    signup(client, "stranger@example.com", "Stranger")
    stranger = login(client, "stranger@example.com")
    centre_id, test_id = create_centre_and_test(client, patient)
    booking = create_booking(client, patient, centre_id, test_id)
    booking_id = booking["id"]

    assert booking["amount"] == "42.50"
    assert datetime.fromisoformat(booking["appointment_at"]).utcoffset() == timedelta(0)
    assert booking["status"] == "PENDING"
    assert client.get(f"/bookings/{booking_id}", headers=stranger).status_code == 404
    assert client.get("/bookings/999999", headers=patient).status_code == 404
    assert client.post(
        "/bookings",
        headers=patient,
        json={
            "centre_id": centre_id,
            "test_id": test_id,
            "appointment_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
        },
    ).status_code == 422
    assert client.post(
        "/bookings",
        headers=patient,
        json={
            "centre_id": centre_id + 500,
            "test_id": test_id,
            "appointment_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        },
    ).status_code == 404

    payment_body = {
        "booking_id": booking_id,
        "idempotency_key": "payment-patient-001",
        "simulate_status": "SUCCESS",
    }
    first = client.post("/payments/", headers=patient, json=payment_body)
    repeated = client.post("/payments/", headers=patient, json=payment_body)
    assert first.status_code == 201, first.text
    assert repeated.status_code == 201, repeated.text
    assert repeated.json()["id"] == first.json()["id"]
    assert client.get(f"/bookings/{booking_id}", headers=patient).json()["status"] == "CONFIRMED"
    assert client.post(
        "/payments/",
        headers=patient,
        json={**payment_body, "booking_id": booking_id + 1},
    ).status_code == 409
    assert client.post("/payments/", headers=stranger, json=payment_body).status_code == 404


def test_failed_payment_webhook_replay_and_booking_cancellation(client: TestClient) -> None:
    signup(client, "webhook-patient@example.com")
    patient = login(client, "webhook-patient@example.com")
    centre_id, test_id = create_centre_and_test(client, patient)
    booking = create_booking(client, patient, centre_id, test_id)
    payment = client.post(
        "/payments/",
        headers=patient,
        json={
            "booking_id": booking["id"],
            "idempotency_key": "payment-failure-001",
            "simulate_status": "FAILED",
        },
    )
    assert payment.status_code == 201, payment.text
    assert payment.json()["status"] == "FAILED"
    assert client.get(f"/bookings/{booking['id']}", headers=patient).json()["status"] == "FAILED"

    webhook_body = {"event_id": "provider-event-001", "payment_id": payment.json()["id"], "status": "FAILED"}
    assert client.post("/payments/webhook/", json=webhook_body).status_code == 401
    first_event = client.post(
        "/payments/webhook/", headers={"X-Webhook-Secret": "local-development-webhook-secret"}, json=webhook_body
    )
    duplicate_event = client.post(
        "/payments/webhook/", headers={"X-Webhook-Secret": "local-development-webhook-secret"}, json=webhook_body
    )
    assert first_event.status_code == 200, first_event.text
    assert first_event.json()["duplicate"] is False
    assert duplicate_event.status_code == 200, duplicate_event.text
    assert duplicate_event.json()["duplicate"] is True
    reconciled_event = client.post(
        "/payments/webhook/",
        headers={"X-Webhook-Secret": "local-development-webhook-secret"},
        json={**webhook_body, "event_id": "provider-event-002", "status": "SUCCESS"},
    )
    assert reconciled_event.status_code == 200, reconciled_event.text
    assert reconciled_event.json()["status"] == "SUCCESS"
    assert client.get(f"/bookings/{booking['id']}", headers=patient).json()["status"] == "CONFIRMED"
    assert client.post(
        "/payments/webhook/",
        headers={"X-Webhook-Secret": "local-development-webhook-secret"},
        json={**webhook_body, "status": "SUCCESS"},
    ).status_code == 409

    another_booking = create_booking(client, patient, centre_id, test_id)
    cancelled = client.post(f"/bookings/{another_booking['id']}/cancel", headers=patient)
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"
    assert client.post(
        "/payments/",
        headers=patient,
        json={
            "booking_id": another_booking["id"],
            "idempotency_key": "payment-cancelled-001",
            "simulate_status": "SUCCESS",
        },
    ).status_code == 409


def test_catalog_deactivation_preserves_booking_history(client: TestClient) -> None:
    signup(client, "catalog-owner@example.com")
    owner = login(client, "catalog-owner@example.com")
    centre_id, test_id = create_centre_and_test(client, owner)
    booking = create_booking(client, owner, centre_id, test_id)

    assert client.delete(f"/centres/{centre_id}", headers=owner).status_code == 204
    assert client.get(f"/centres/{centre_id}").status_code == 404
    assert client.get(f"/bookings/{booking['id']}", headers=owner).status_code == 200