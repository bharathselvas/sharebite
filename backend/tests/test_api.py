from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend import app as api
from backend.domain import DonationCreate


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "DATABASE_PATH", tmp_path / "test.db")
    monkeypatch.setenv("APP_MODE", "local-demo")
    monkeypatch.setenv("DONATION_STORE", "sqlite")
    with TestClient(api.app) as test_client:
        yield test_client


def donation_payload(**overrides):
    payload = {
        "donor_id": "donor-demo",
        "food_name": "Vegetable boxes",
        "quantity": 12,
        "unit": "boxes",
        "pickup_deadline": (
            datetime.now(timezone.utc) + timedelta(days=1)
        ).isoformat(),
    }
    payload.update(overrides)
    return payload


def test_create_and_list_donation(client):
    response = client.post("/api/donations", json=donation_payload())
    assert response.status_code == 201
    created = response.json()
    assert created["status"] == "available"
    assert created["donor_id"] == "donor-demo"
    assert client.get("/api/donations?status=available").json() == [created]


def test_role_dashboard_uses_owned_records_and_unit_separated_quantities(client):
    available = client.post(
        "/api/donations", json=donation_payload(quantity=6, unit="kg")
    ).json()
    completed = client.post(
        "/api/donations", json=donation_payload(quantity=3, unit="portions")
    ).json()
    claimed = client.post(
        f"/api/donations/{completed['id']}/claim", json={"ngo_id": "ngo-demo"}
    ).json()
    assert claimed["status"] == "claimed"
    assert client.patch(
        f"/api/donations/{completed['id']}/status",
        json={"actor_id": "ngo-demo", "status": "picked_up"},
    ).status_code == 200
    cancelled = client.post(
        "/api/donations", json=donation_payload(quantity=5, unit="boxes")
    ).json()
    assert client.patch(
        f"/api/donations/{cancelled['id']}/status",
        json={"actor_id": "donor-demo", "status": "cancelled"},
    ).status_code == 200
    client.post(
        "/api/donations",
        json=donation_payload(donor_id="donor-demo-2", food_name="Private record"),
    )

    donor_dashboard = client.get(
        "/api/me/dashboard?actor_id=donor-demo"
    ).json()
    assert donor_dashboard["total_donations"] == 3
    assert donor_dashboard["available_donations"] == 1
    assert donor_dashboard["completed_pickups"] == 1
    assert donor_dashboard["cancelled_donations"] == 1
    assert donor_dashboard["completed_quantity_by_unit"] == {"portions": 3.0}
    assert all(
        item["donor_id"] == "donor-demo"
        for item in donor_dashboard["recent_donations"]
    )
    assert "Private record" not in str(donor_dashboard)

    recipient_dashboard = client.get(
        "/api/me/dashboard?actor_id=ngo-demo"
    ).json()
    assert recipient_dashboard["total_donations"] == 1
    assert recipient_dashboard["completed_pickups"] == 1
    assert recipient_dashboard["completed_quantity_by_unit"] == {"portions": 3.0}
    assert all(
        item["claimed_by"] == "ngo-demo"
        for item in recipient_dashboard["recent_donations"]
    )
    assert client.get("/api/me/dashboard?actor_id=ngo-demo-2").json()[
        "total_donations"
    ] == 0
    assert client.get("/api/me/dashboard?actor_id=admin-demo").status_code == 403


@pytest.mark.parametrize(
    "overrides",
    [
        {"quantity": 0},
        {"quantity": -2},
        {"food_name": " "},
        {"donor_id": "real-person"},
        {"pickup_deadline": "2020-01-01T00:00:00Z"},
        {"pickup_deadline": "2030-01-01T00:00:00"},
    ],
)
def test_rejects_invalid_donation(client, overrides):
    assert client.post("/api/donations", json=donation_payload(**overrides)).status_code in {
        403,
        422,
    }


def test_prevents_duplicate_claim_and_enforces_pickup_actor(client):
    donation_id = client.post("/api/donations", json=donation_payload()).json()["id"]
    claim = client.post(
        f"/api/donations/{donation_id}/claim", json={"ngo_id": "ngo-demo"}
    )
    assert claim.status_code == 200
    assert claim.json()["claimed_by"] == "ngo-demo"
    assert client.post(
        f"/api/donations/{donation_id}/claim", json={"ngo_id": "ngo-demo-2"}
    ).status_code == 409
    assert client.patch(
        f"/api/donations/{donation_id}/status",
        json={"actor_id": "ngo-demo-2", "status": "picked_up"},
    ).status_code == 403
    picked_up = client.patch(
        f"/api/donations/{donation_id}/status",
        json={"actor_id": "ngo-demo", "status": "picked_up"},
    )
    assert picked_up.status_code == 200
    assert picked_up.json()["status"] == "picked_up"


def test_cancellation_and_admin_analytics(client):
    donation = client.post("/api/donations", json=donation_payload()).json()
    assert client.patch(
        f"/api/donations/{donation['id']}/status",
        json={"actor_id": "donor-demo", "status": "cancelled"},
    ).json()["status"] == "cancelled"
    assert client.get("/api/admin/analytics?actor_id=not-admin").status_code == 403
    metrics = client.get("/api/admin/analytics?actor_id=admin-demo").json()
    assert metrics["total_donations"] == 1
    assert metrics["cancelled_donations"] == 1
    assert metrics["claim_success_rate"] == 0
    assert metrics["completion_rate"] == 0
    assert metrics["expiry_rate"] == 0


def test_analytics_groups_units_and_status_filter_does_not_change_rate_cohort(
    client,
):
    fixed_day = "2026-10-20"
    available = client.post(
        "/api/donations",
        json=donation_payload(
            quantity=6,
            unit="kg",
            category="produce",
        ),
    ).json()
    completed = client.post(
        "/api/donations",
        json=donation_payload(
            quantity=3,
            unit="portions",
            category="prepared meals",
        ),
    ).json()
    assert client.post(
        f"/api/donations/{completed['id']}/claim", json={"ngo_id": "ngo-demo"}
    ).status_code == 200
    assert client.patch(
        f"/api/donations/{completed['id']}/status",
        json={"actor_id": "ngo-demo", "status": "picked_up"},
    ).status_code == 200
    cancelled = client.post(
        "/api/donations",
        json=donation_payload(quantity=2, unit="boxes", category="bakery"),
    ).json()
    assert client.patch(
        f"/api/donations/{cancelled['id']}/status",
        json={"actor_id": "donor-demo", "status": "cancelled"},
    ).status_code == 200

    import sqlite3

    connection = sqlite3.connect(api.DATABASE_PATH)
    connection.execute(
        "UPDATE donations SET created_at = ?",
        (f"{fixed_day}T08:00:00Z",),
    )
    connection.execute(
        "UPDATE donations SET claimed_at = ? WHERE id = ?",
        (f"{fixed_day}T08:30:00Z", completed["id"]),
    )
    connection.execute(
        "UPDATE donations SET completed_at = ? WHERE id = ?",
        (f"{fixed_day}T09:00:00Z", completed["id"]),
    )
    connection.commit()
    connection.close()

    query = (
        f"/api/admin/analytics?actor_id=admin-demo"
        f"&start_date={fixed_day}&end_date={fixed_day}"
    )
    metrics = client.get(query).json()
    assert metrics["claim_success_rate"] == pytest.approx(1 / 3)
    assert metrics["completion_rate"] == pytest.approx(1 / 3)
    assert metrics["completed_quantity_by_unit"] == {"portions": 3.0}
    assert metrics["daily_completed_quantity_by_unit"] == {
        fixed_day: {"portions": 3.0}
    }
    assert metrics["daily_completed_pickups"] == {fixed_day: 1}
    assert metrics["daily_status_counts"][fixed_day] == {
        "available": 1,
        "picked_up": 1,
        "cancelled": 1,
    }
    assert metrics["category_counts"] == {
        "bakery": 1,
        "prepared meals": 1,
        "produce": 1,
    }
    available_metrics = client.get(f"{query}&status=available").json()
    assert available_metrics["total_donations"] == 1
    assert available_metrics["claim_success_rate"] == pytest.approx(1 / 3)


def test_admin_can_export_json_for_etl(client):
    donation = client.post("/api/donations", json=donation_payload()).json()
    assert client.get("/api/admin/export?actor_id=not-admin").status_code == 403
    response = client.get("/api/admin/export?actor_id=admin-demo")
    assert response.status_code == 200
    assert response.json() == [donation]


def test_donor_cannot_cancel_another_donors_listing(client):
    donation = client.post("/api/donations", json=donation_payload()).json()
    response = client.patch(
        f"/api/donations/{donation['id']}/status",
        json={"actor_id": "donor-demo-2", "status": "cancelled"},
    )
    assert response.status_code == 403


def test_unknown_donation_returns_not_found(client):
    assert client.post(
        "/api/donations/missing/claim", json={"ngo_id": "ngo-demo"}
    ).status_code == 404


def test_paginated_listing_and_invalid_cursor(client):
    for index in range(3):
        response = client.post(
            "/api/donations",
            json=donation_payload(food_name=f"Donation {index}"),
        )
        assert response.status_code == 201
    first_page = client.get("/api/donations/page?status=available&limit=2")
    assert first_page.status_code == 200
    assert len(first_page.json()["items"]) == 2
    cursor = first_page.json()["next_cursor"]
    assert cursor
    second_page = client.get(
        f"/api/donations/page?status=available&limit=2&cursor={cursor}"
    )
    assert len(second_page.json()["items"]) == 1
    assert second_page.json()["next_cursor"] is None
    assert client.get("/api/donations/page?status=available&cursor=invalid").status_code == 422


def test_donation_timeline_records_successful_changes_only(client):
    donation_id = client.post("/api/donations", json=donation_payload()).json()["id"]
    claim_path = f"/api/donations/{donation_id}/claim"
    assert client.post(claim_path, json={"ngo_id": "ngo-demo"}).status_code == 200
    assert client.post(claim_path, json={"ngo_id": "ngo-demo-2"}).status_code == 409
    assert client.patch(
        f"/api/donations/{donation_id}/status",
        json={"actor_id": "ngo-demo", "status": "picked_up"},
    ).status_code == 200
    timeline = client.get(
        f"/api/donations/{donation_id}/events?actor_id=ngo-demo"
    )
    assert timeline.status_code == 200
    events = timeline.json()["items"]
    assert [event["event_type"] for event in reversed(events)] == [
        "donation_created",
        "donation_claimed",
        "donation_completed",
    ]
    assert events[0]["before_status"] == "claimed"
    assert events[0]["after_status"] == "picked_up"
    assert all(event["actor_id"] for event in events)
    assert events[0]["request_id"]
    assert client.get(
        f"/api/donations/{donation_id}/events?actor_id=ngo-demo-2"
    ).status_code == 403


def test_donor_can_edit_only_owned_available_donations(client):
    donation = client.post("/api/donations", json=donation_payload()).json()
    update = {
        "actor_id": "donor-demo",
        "food_name": "Updated vegetable boxes",
        "description": "Unopened produce",
        "category": "produce",
        "quantity": 8,
        "unit": "boxes",
        "available_at": None,
        "pickup_deadline": (
            datetime.now(timezone.utc) + timedelta(days=2)
        ).isoformat(),
        "pickup_location": "Community centre",
    }
    path = f"/api/donations/{donation['id']}"
    assert client.patch(path, json={**update, "actor_id": "donor-demo-2"}).status_code == 403
    response = client.patch(path, json=update)
    assert response.status_code == 200
    assert response.json()["food_name"] == "Updated vegetable boxes"
    assert client.post(
        f"{path}/claim", json={"ngo_id": "ngo-demo"}
    ).status_code == 200
    assert client.patch(path, json=update).status_code == 409
    events, _ = api.get_repository().list_events("donation", donation["id"])
    assert [event["event_type"] for event in events].count("donation_updated") == 1


def test_user_list_suspension_and_audit_are_admin_only(client):
    response = client.get("/api/admin/users?actor_id=admin-demo&search=ngo")
    assert response.status_code == 200
    assert {user["user_id"] for user in response.json()["items"]} == {
        "ngo-demo",
        "ngo-demo-2",
    }
    assert client.get("/api/admin/users?actor_id=donor-demo").status_code == 403
    assert client.patch(
        "/api/admin/users/donor-demo/status",
        json={"actor_id": "admin-demo", "status": "suspended"},
    ).json()["status"] == "suspended"
    assert client.post("/api/donations", json=donation_payload()).status_code == 403
    assert client.get(
        "/api/admin/users/donor-demo/events?actor_id=admin-demo"
    ).json()["items"][0]["event_type"] == "account_suspended"
    assert client.patch(
        "/api/admin/users/admin-demo/status",
        json={"actor_id": "admin-demo", "status": "suspended"},
    ).status_code == 409
    events, cursor = api.get_repository().list_events("user", "donor-demo")
    assert cursor is None
    assert events[0]["event_type"] == "account_suspended"
    assert events[0]["actor_id"] == "admin-demo"


def test_donation_visibility_is_limited_to_public_and_participant_records(client):
    payload = donation_payload()
    payload["donor_id"] = "donor-demo-2"
    donation = client.post("/api/donations", json=payload).json()
    assert client.get("/api/donations").json() == [donation]
    assert client.get(
        "/api/donations?status=claimed"
    ).status_code == 403
    donor_view = client.get("/api/donations?actor_id=donor-demo&role=donor")
    assert donor_view.status_code == 200
    assert all(item["donor_id"] == "donor-demo" or item["status"] == "available" for item in donor_view.json())
    assert client.get(
        "/api/donations?actor_id=admin-demo&role=donor"
    ).status_code == 403


def test_expiration_is_idempotent_and_prevents_claim(client):
    repository = api.get_repository()
    deadline = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    expired_candidate = repository.create(
        {
            "donor_id": "donor-demo",
            "food_name": "Expired vegetables",
            "description": "",
            "category": "produce",
            "quantity": 4,
            "unit": "boxes",
            "available_at": None,
            "pickup_deadline": deadline,
            "pickup_location": "",
            "status": "available",
            "claimed_by": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "claimed_at": None,
            "completed_at": None,
        }
    )
    claim = client.post(
        f"/api/donations/{expired_candidate['id']}/claim",
        json={"ngo_id": "ngo-demo"},
    )
    assert claim.status_code == 409
    assert repository.get(expired_candidate["id"])["status"] == "expired"
    assert repository.expire_due() == 0
    events, _ = repository.list_events("donation", expired_candidate["id"])
    assert [event["event_type"] for event in events].count("donation_expired") == 1


def test_admin_expiry_job_is_bounded_and_authorized(client):
    assert client.post("/api/admin/expire?actor_id=donor-demo").status_code == 403
    response = client.post("/api/admin/expire?actor_id=admin-demo")
    assert response.status_code == 200
    assert response.json() == {"expired_count": 0}


def test_admin_audit_activity_filters_and_paginates(client):
    donation_id = client.post("/api/donations", json=donation_payload()).json()["id"]
    client.post(
        f"/api/donations/{donation_id}/claim", json={"ngo_id": "ngo-demo"}
    )
    unauthorized = client.get("/api/admin/activity?actor_id=donor-demo")
    assert unauthorized.status_code == 403
    page = client.get("/api/admin/activity?actor_id=admin-demo&limit=1")
    assert page.status_code == 200
    assert len(page.json()["items"]) == 1
    assert page.json()["next_cursor"]
    filtered = client.get(
        "/api/admin/activity?actor_id=admin-demo&event_type=donation_claimed"
    )
    assert [event["event_type"] for event in filtered.json()["items"]] == [
        "donation_claimed"
    ]


def test_admin_etl_executes_pipeline_and_downloads_reports(client, monkeypatch, tmp_path):
    from backend import app as api

    monkeypatch.setattr(api, "ETL_RUN_ROOT", tmp_path / "etl-runs")
    api.ETL_RUNS.clear()
    api.ETL_REPORT_DIRS.clear()
    client.post("/api/donations", json=donation_payload())
    assert client.post("/api/admin/etl/runs?actor_id=donor-demo").status_code == 403

    response = client.post("/api/admin/etl/runs?actor_id=admin-demo")
    assert response.status_code == 201
    run = response.json()
    assert run["status"] == "succeeded"
    assert run["mode"] == "local"
    assert run["input_records"] == 1
    assert run["total_clean_donations"] == 1
    assert "clean_donations.csv" in run["reports"]
    assert "output_dir" not in run

    report = client.get(
        f"/api/admin/etl/runs/{run['run_id']}/reports/clean_donations.csv"
        "?actor_id=admin-demo"
    )
    assert report.status_code == 200
    assert "Vegetable boxes" in report.text
    assert client.get(
        f"/api/admin/etl/runs/{run['run_id']}/reports/../../app.py"
        "?actor_id=admin-demo"
    ).status_code in {404, 422}
    history = client.get("/api/admin/etl/runs?actor_id=admin-demo")
    assert history.json()["items"][0]["run_id"] == run["run_id"]


def test_concurrent_recipients_cannot_claim_the_same_donation(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from backend.repositories import DonationConflict, SQLiteDonationRepository

    repository = SQLiteDonationRepository(tmp_path / "concurrent.db")
    repository.initialize()
    created = repository.create(
        api._record(request=DonationCreate.model_validate(donation_payload()))
    )
    barrier = Barrier(2)

    def try_claim(recipient):
        barrier.wait()
        try:
            repository.claim(created["id"], recipient)
            return "claimed"
        except DonationConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(try_claim, ("ngo-demo", "ngo-demo-2")))
    assert sorted(results) == ["claimed", "conflict"]


def test_fastapi_cloud_mode_fails_closed_instead_of_using_sqlite(tmp_path, monkeypatch):
    database_path = tmp_path / "must-not-be-created.db"
    monkeypatch.setattr(api, "DATABASE_PATH", database_path)
    monkeypatch.setenv("APP_MODE", "aws")
    monkeypatch.setenv("DONATION_STORE", "dynamodb")

    with pytest.raises(RuntimeError, match="FastAPI adapter accepts demo identities only"):
        with TestClient(api.app):
            pass

    assert not database_path.exists()


def test_fastapi_requires_explicit_local_demo_mode(tmp_path, monkeypatch):
    database_path = tmp_path / "must-not-be-created.db"
    monkeypatch.setattr(api, "DATABASE_PATH", database_path)
    monkeypatch.delenv("APP_MODE", raising=False)
    monkeypatch.setenv("DONATION_STORE", "sqlite")
    with pytest.raises(RuntimeError, match="FastAPI adapter accepts demo identities only"):
        with TestClient(api.app):
            pass
    assert not database_path.exists()


def test_backward_compatible_sqlite_migration_preserves_existing_rows(tmp_path):
    import sqlite3

    from backend.repositories import SQLiteDonationRepository

    database = tmp_path / "existing.db"
    connection = sqlite3.connect(database)
    connection.execute(
        """
        CREATE TABLE donations (
            id TEXT PRIMARY KEY, donor_id TEXT NOT NULL, food_name TEXT NOT NULL,
            quantity REAL NOT NULL, unit TEXT NOT NULL, pickup_deadline TEXT NOT NULL,
            status TEXT NOT NULL, claimed_by TEXT, created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        INSERT INTO donations VALUES
        ('preserve-me', 'donor-demo', 'Existing synthetic row', 4, 'boxes',
         '2026-10-30T00:00:00Z', 'available', NULL, '2026-10-28T00:00:00Z')
        """
    )
    connection.commit()
    connection.close()

    repository = SQLiteDonationRepository(database)
    repository.initialize()
    row = repository.get("preserve-me")
    assert row["food_name"] == "Existing synthetic row"
    assert row["category"] == "other"
    assert row["description"] == ""


def test_dynamodb_configuration_does_not_fall_back_to_sqlite(monkeypatch):
    monkeypatch.setenv("DONATION_STORE", "dynamodb")
    monkeypatch.delenv("DONATIONS_TABLE", raising=False)
    with pytest.raises(RuntimeError, match="DONATIONS_TABLE must be configured"):
        api.get_repository()
