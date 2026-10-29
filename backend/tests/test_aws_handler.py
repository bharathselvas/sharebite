import json
from decimal import Decimal

from botocore.exceptions import ClientError

from backend import aws_handler
from backend.repositories import DynamoDBDonationRepository
from backend.tests.test_dynamodb_repository import FakeDynamoTable, donation, service_failure


def event(method, path, body=None, groups=None, subject="user-sub-1", query=""):
    request_context = {"http": {"method": method}}
    if groups is not None:
        request_context["authorizer"] = {
            "jwt": {
                "claims": {
                    "sub": subject,
                    "cognito:groups": groups,
                }
            }
        }
    return {
        "requestContext": request_context,
        "rawPath": path,
        "rawQueryString": query,
        "body": json.dumps(body) if body is not None else "",
    }


def invoke(repository, method, path, body=None, groups=None, subject="user-sub-1", query=""):
    response = aws_handler.handle(
        event(method, path, body, groups, subject, query), repository
    )
    return response["statusCode"], json.loads(response["body"])


def test_api_gateway_cognito_claims_are_required_for_protected_routes():
    table = FakeDynamoTable()
    repository = DynamoDBDonationRepository(table)
    assert invoke(repository, "GET", "/api/donations")[0] == 401
    assert invoke(repository, "GET", "/api/donations", groups=[])[0] == 401
    assert invoke(repository, "GET", "/api/health")[0] == 200
    assert invoke(
        repository,
        "GET",
        "/api/donations",
        groups=["food-donors", "food-admins"],
    )[0] == 401


def test_dashboard_uses_verified_principal_and_rejects_admins():
    repository = DynamoDBDonationRepository(FakeDynamoTable())
    owned = repository.create(donation())
    status, dashboard = invoke(
        repository,
        "GET",
        "/api/me/dashboard",
        groups=["food-donors"],
        subject="donor-sub-1",
        query="actor_id=attacker-selected-id",
    )
    assert status == 200
    assert dashboard["total_donations"] == 1
    assert dashboard["recent_donations"][0]["id"] == owned["id"]
    assert dashboard["data_source"] == "cloud_live"
    assert invoke(
        repository,
        "GET",
        "/api/me/dashboard",
        groups=["food-admins"],
    )[0] == 403
    assert invoke(repository, "GET", "/api/me/dashboard")[0] == 401


def test_dashboard_reports_bound_exhaustion_as_unavailable():
    repository = DynamoDBDonationRepository(FakeDynamoTable(), max_admin_items=1)
    repository.create(donation())
    repository.create(donation(food_name="Second donation"))

    status, result = invoke(
        repository,
        "GET",
        "/api/me/dashboard",
        groups=["food-donors"],
        subject="donor-sub-1",
    )
    assert status == 503
    assert result == {"detail": "Dashboard data is temporarily unavailable"}


def test_create_derives_donor_from_verified_claims_not_body():
    repository = DynamoDBDonationRepository(FakeDynamoTable())
    payload = {
        "food_name": "Rice bags",
        "quantity": 3,
        "unit": "bags",
        "pickup_deadline": "2026-10-30T12:00:00Z",
    }
    status, created = invoke(
        repository, "POST", "/api/donations", payload, ["food-donors"], "donor-sub"
    )
    assert status == 201
    assert created["donor_id"] == "donor-sub"
    assert isinstance(repository.table.items[created["id"]]["quantity"], Decimal)
    payload["donor_id"] = "attacker-selected-id"
    assert invoke(
        repository, "POST", "/api/donations", payload, ["food-donors"], "donor-sub"
    )[0] == 422


def test_ngo_claim_and_pickup_use_verified_subject_and_prevent_duplicate_claims():
    repository = DynamoDBDonationRepository(FakeDynamoTable())
    item = repository.create(donation())
    path = f"/api/donations/{item['id']}/claim"
    assert invoke(repository, "POST", path, {}, ["food-ngos"], "ngo-sub")[0] == 200
    assert invoke(repository, "POST", path, {}, ["food-ngos"], "other-ngo")[0] == 409
    status, body = invoke(
        repository,
        "PATCH",
        f"/api/donations/{item['id']}/status",
        {"status": "picked_up"},
        ["food-ngos"],
        "ngo-sub",
    )
    assert status == 200
    assert body["status"] == "picked_up"
    assert body["claimed_by"] == "ngo-sub"
    assert invoke(
        repository,
        "PATCH",
        f"/api/donations/{item['id']}/status",
        {"actor_id": "attacker", "status": "picked_up"},
        ["food-ngos"],
        "ngo-sub",
    )[0] == 422


def test_donor_cannot_cancel_other_users_donation_and_admin_routes_are_restricted():
    repository = DynamoDBDonationRepository(FakeDynamoTable())
    item = repository.create(donation())
    path = f"/api/donations/{item['id']}/status"
    assert invoke(
        repository, "PATCH", path, {"status": "cancelled"}, ["food-donors"], "other-donor"
    )[0] == 403
    assert invoke(
        repository, "GET", "/api/admin/analytics", groups=["food-ngos"]
    )[0] == 403
    assert invoke(
        repository, "GET", "/api/admin/export", groups=["food-donors"]
    )[0] == 403
    assert invoke(
        repository, "GET", "/api/admin/analytics", groups=["food-admins"]
    )[0] == 200
    assert invoke(
        repository, "GET", "/api/admin/export", groups=["food-admins"]
    )[0] == 200


def test_admin_analytics_filters_are_validated_and_applied():
    repository = DynamoDBDonationRepository(FakeDynamoTable())
    repository.create(
        donation(
            category="produce",
            pickup_location="North kitchen",
            created_at="2026-10-20T12:00:00Z",
        )
    )
    repository.create(
        donation(
            category="bakery",
            pickup_location="South kitchen",
            created_at="2026-10-21T12:00:00Z",
        )
    )
    status, metrics = invoke(
        repository,
        "GET",
        "/api/admin/analytics",
        groups=["food-admins"],
        query="start_date=2026-10-20&end_date=2026-10-20&category=produce&location=North",
    )
    assert status == 200
    assert metrics["total_donations"] == 1
    assert invoke(
        repository,
        "GET",
        "/api/admin/analytics",
        groups=["food-admins"],
        query="start_date=2026-99-99",
    )[0] == 422


def test_dynamo_service_errors_return_safe_unavailable_response():
    table = FakeDynamoTable()
    repository = DynamoDBDonationRepository(table)
    table.fail_with = service_failure()
    status, result = invoke(
        repository,
        "POST",
        "/api/donations",
        {
            "food_name": "Rice",
            "quantity": 3,
            "unit": "bags",
            "pickup_deadline": "2026-10-30T12:00:00Z",
        },
        ["food-donors"],
    )
    assert status == 503
    assert result == {"detail": "Donation storage is temporarily unavailable"}


def test_handler_maps_missing_table_configuration_without_falling_back(monkeypatch):
    monkeypatch.delenv("DONATIONS_TABLE", raising=False)
    response = aws_handler.handler(event("GET", "/api/donations", groups=["food-donors"]), None)
    assert response["statusCode"] == 503
    assert json.loads(response["body"]) == {
        "detail": "Donation storage is not configured"
    }
