import base64
import json
import logging
import os
import re
from datetime import datetime, timezone
from decimal import Decimal
from urllib.parse import parse_qs

from botocore.exceptions import ClientError
from pydantic import ValidationError

try:
    from .domain import ClaimCommand, DonationFields, Principal, STATUSES, StatusCommand
    from .repositories import (
        MAX_PAGE_SIZE,
        DonationConflict,
        DonationForbidden,
        DonationNotFound,
        get_dynamodb_repository,
    )
    from .request_context import request_id_context
except ImportError:
    from domain import ClaimCommand, DonationFields, Principal, STATUSES, StatusCommand
    from repositories import (
        MAX_PAGE_SIZE,
        DonationConflict,
        DonationForbidden,
        DonationNotFound,
        get_dynamodb_repository,
    )
    from request_context import request_id_context

logger = logging.getLogger(__name__)


def _json_default(value):
    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def respond(status_code: int, payload) -> dict:
    return {
        "statusCode": status_code,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(payload, default=_json_default),
    }


def _request_body(event: dict) -> dict:
    body = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        body = base64.b64decode(body, validate=True).decode("utf-8")
    parsed = json.loads(body)
    if not isinstance(parsed, dict):
        raise ValueError("Request body must be a JSON object")
    return parsed


def _principal(event: dict) -> Principal | None:
    claims = (
        event.get("requestContext", {})
        .get("authorizer", {})
        .get("jwt", {})
        .get("claims", {})
    )
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject:
        return None
    raw_groups = claims.get("cognito:groups", [])
    if isinstance(raw_groups, str):
        try:
            decoded_groups = json.loads(raw_groups)
            groups = decoded_groups if isinstance(decoded_groups, list) else [raw_groups]
        except json.JSONDecodeError:
            groups = [raw_groups]
    elif isinstance(raw_groups, list):
        groups = raw_groups
    else:
        groups = []
    principal = Principal(subject=subject, groups=frozenset(map(str, groups)))
    return principal if principal.role else None


def _repository_error(error: Exception) -> dict:
    if isinstance(error, DonationNotFound):
        return respond(404, {"detail": "Donation not found"})
    if isinstance(error, DonationForbidden):
        return respond(403, {"detail": "Actor is not authorized for this donation"})
    if isinstance(error, DonationConflict):
        return respond(409, {"detail": "Donation state changed; refresh and retry"})
    raise error


def handle(event: dict, repository) -> dict:
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    path = event.get("rawPath", "")
    query = parse_qs(event.get("rawQueryString", ""))
    if method == "GET" and path == "/api/health":
        return respond(200, {"status": "ok", "mode": "aws"})

    principal = _principal(event)
    if principal is None:
        return respond(401, {"detail": "A valid Cognito JWT with an application group is required"})

    if method == "GET" and path in {"/api/donations", "/api/donations/page"}:
        if principal.role not in {"donor", "ngo", "admin"}:
            return respond(403, {"detail": "Donation-list permission required"})
        status = query.get("status", ["available"])[0]
        if status not in STATUSES:
            return respond(422, {"detail": "Unsupported donation status"})
        if principal.role != "admin" and status != "available":
            return respond(403, {"detail": "Only administrators can list non-available donations"})
        try:
            limit = int(query.get("limit", ["25"])[0])
        except ValueError:
            return respond(422, {"detail": "limit must be an integer"})
        if not 1 <= limit <= MAX_PAGE_SIZE:
            return respond(422, {"detail": f"limit must be between 1 and {MAX_PAGE_SIZE}"})
        cursor = query.get("cursor", [None])[0]
        try:
            items, next_cursor = repository.list_status(status, limit, cursor)
        except ValueError as error:
            return respond(422, {"detail": str(error)})
        if path == "/api/donations/page":
            return respond(200, {"items": items, "next_cursor": next_cursor})
        return respond(200, items)

    if method == "GET" and path == "/api/donations/mine":
        if principal.role not in {"donor", "ngo"}:
            return respond(403, {"detail": "Donor or recipient permission required"})
        try:
            limit = int(query.get("limit", ["25"])[0])
        except ValueError:
            return respond(422, {"detail": "limit must be an integer"})
        if not 1 <= limit <= MAX_PAGE_SIZE:
            return respond(422, {"detail": f"limit must be between 1 and {MAX_PAGE_SIZE}"})
        try:
            if principal.role == "donor":
                items, next_cursor = repository.list_by_donor(
                    principal.subject, limit, query.get("cursor", [None])[0]
                )
            else:
                items, next_cursor = repository.list_by_claimant(
                    principal.subject, limit, query.get("cursor", [None])[0]
                )
        except ValueError as error:
            return respond(422, {"detail": str(error)})
        return respond(200, {"items": items, "next_cursor": next_cursor})

    if method == "GET" and path == "/api/admin/donations":
        if principal.role != "admin":
            return respond(403, {"detail": "Administrator permission required"})
        try:
            return respond(200, repository.list_all())
        except (RuntimeError, ClientError) as error:
            code = (
                error.response.get("Error", {}).get("Code", "Unknown")
                if isinstance(error, ClientError)
                else "configured bound exceeded"
            )
            logger.error("DynamoDB donation list failed (%s)", code)
            return respond(503, {"detail": "Donation list is temporarily unavailable"})

    if method == "POST" and path == "/api/donations":
        if principal.role != "donor":
            return respond(403, {"detail": "Donor permission required"})
        try:
            request = DonationFields.model_validate(_request_body(event))
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError, ValidationError) as error:
            return respond(422, {"detail": str(error)})
        now = datetime.now(timezone.utc)
        created_at = now.isoformat().replace("+00:00", "Z")
        donation = {
            "donor_id": principal.subject,
            "food_name": request.food_name,
            "description": request.description,
            "category": request.category,
            "quantity": Decimal(str(request.quantity)),
            "unit": request.unit,
            "available_at": (
                request.available_at.isoformat().replace("+00:00", "Z")
                if request.available_at
                else None
            ),
            "pickup_deadline": request.pickup_deadline.isoformat().replace("+00:00", "Z"),
            "pickup_location": request.pickup_location,
            "status": "available",
            "claimed_by": None,
            "created_at": created_at,
            "updated_at": created_at,
            "claimed_at": None,
            "completed_at": None,
        }
        try:
            return respond(201, repository.create(donation))
        except ClientError as error:
            code = error.response.get("Error", {}).get("Code", "Unknown")
            logger.error("DynamoDB create failed (%s)", code)
            return respond(503, {"detail": "Donation storage is temporarily unavailable"})

    segments = path.strip("/").split("/")
    if method == "GET" and len(segments) == 4 and segments[:2] == ["api", "donations"] and segments[3] == "events":
        donation = repository.get(segments[2])
        if donation is None:
            return respond(404, {"detail": "Donation not found"})
        if principal.role != "admin" and principal.subject not in {
            donation.get("donor_id"),
            donation.get("claimed_by"),
        }:
            return respond(403, {"detail": "Donation history is restricted to its participants"})
        try:
            limit = int(query.get("limit", ["25"])[0])
        except ValueError:
            return respond(422, {"detail": "limit must be an integer"})
        if not 1 <= limit <= MAX_PAGE_SIZE:
            return respond(422, {"detail": f"limit must be between 1 and {MAX_PAGE_SIZE}"})
        try:
            events, next_cursor = repository.list_events(
                "donation", segments[2], limit, query.get("cursor", [None])[0]
            )
        except ValueError as error:
            return respond(422, {"detail": str(error)})
        return respond(200, {"items": events, "next_cursor": next_cursor})

    if (
        method == "PATCH"
        and len(segments) == 3
        and segments[:2] == ["api", "donations"]
    ):
        if principal.role != "donor":
            return respond(403, {"detail": "Donor permission required"})
        try:
            request = DonationFields.model_validate(_request_body(event))
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError, ValidationError) as error:
            return respond(422, {"detail": str(error)})
        fields = request.model_dump()
        fields["quantity"] = Decimal(str(fields["quantity"]))
        for key in ("available_at", "pickup_deadline"):
            value = fields[key]
            fields[key] = value.isoformat().replace("+00:00", "Z") if value else None
        try:
            return respond(
                200,
                repository.update_donation(
                    segments[2], fields, principal.subject, principal.role
                ),
            )
        except (DonationNotFound, DonationConflict, DonationForbidden) as error:
            return _repository_error(error)
        except ClientError as error:
            code = error.response.get("Error", {}).get("Code", "Unknown")
            logger.error("DynamoDB donation edit failed (%s)", code)
            return respond(503, {"detail": "Donation storage is temporarily unavailable"})

    if len(segments) == 4 and segments[:2] == ["api", "donations"]:
        donation_id, action = segments[2], segments[3]
        if method == "POST" and action == "claim":
            if principal.role != "ngo":
                return respond(403, {"detail": "NGO permission required"})
            try:
                ClaimCommand.model_validate(_request_body(event))
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError, ValidationError) as error:
                return respond(422, {"detail": str(error)})
            try:
                return respond(200, repository.claim(donation_id, principal.subject))
            except (DonationNotFound, DonationConflict, DonationForbidden) as error:
                return _repository_error(error)
            except ClientError as error:
                code = error.response.get("Error", {}).get("Code", "Unknown")
                logger.error("DynamoDB claim failed (%s)", code)
                return respond(503, {"detail": "Donation storage is temporarily unavailable"})

        if method == "PATCH" and action == "status":
            try:
                request = StatusCommand.model_validate(_request_body(event))
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError, ValidationError) as error:
                return respond(422, {"detail": str(error)})
            if (request.status == "cancelled" and principal.role != "donor") or (
                request.status == "picked_up" and principal.role != "ngo"
            ):
                return respond(403, {"detail": "Role cannot perform this status transition"})
            try:
                return respond(
                    200,
                    repository.transition(
                        donation_id,
                        request.status,
                        principal.subject,
                        principal.role,
                    ),
                )
            except (DonationNotFound, DonationConflict, DonationForbidden) as error:
                return _repository_error(error)
            except ClientError as error:
                code = error.response.get("Error", {}).get("Code", "Unknown")
                logger.error("DynamoDB status update failed (%s)", code)
                return respond(503, {"detail": "Donation storage is temporarily unavailable"})

    if method == "GET" and path == "/api/admin/analytics":
        if principal.role != "admin":
            return respond(403, {"detail": "Administrator permission required"})
        try:
            filters = {
                key: query[key][0]
                for key in ("start_date", "end_date", "status", "category", "location")
                if key in query
            }
            if any(
                not re.fullmatch(r"\d{4}-\d{2}-\d{2}", filters[key])
                for key in ("start_date", "end_date")
                if key in filters
            ):
                return respond(422, {"detail": "Dates must use YYYY-MM-DD"})
            try:
                for date_key in ("start_date", "end_date"):
                    if date_key in filters:
                        datetime.strptime(filters[date_key], "%Y-%m-%d")
            except ValueError:
                return respond(422, {"detail": "Dates must be valid YYYY-MM-DD values"})
            if "status" in filters and filters["status"] not in STATUSES:
                return respond(422, {"detail": "Unsupported donation status"})
            if (
                "start_date" in filters
                and "end_date" in filters
                and filters["start_date"] > filters["end_date"]
            ):
                return respond(422, {"detail": "start_date must be on or before end_date"})
            return respond(200, repository.analytics(filters))
        except (RuntimeError, ClientError) as error:
            code = (
                error.response.get("Error", {}).get("Code", "Unknown")
                if isinstance(error, ClientError)
                else "configured bound exceeded"
            )
            logger.error("DynamoDB analytics failed (%s)", code)
            return respond(503, {"detail": "Analytics are temporarily unavailable"})

    if method == "POST" and path == "/api/admin/expire":
        if principal.role != "admin":
            return respond(403, {"detail": "Administrator permission required"})
        try:
            return respond(200, {"expired_count": repository.expire_due()})
        except (RuntimeError, ClientError) as error:
            code = (
                error.response.get("Error", {}).get("Code", "Unknown")
                if isinstance(error, ClientError)
                else "configured processing bound exceeded"
            )
            logger.error("Donation expiry processing failed (%s)", code)
            return respond(503, {"detail": "Expiry processing is temporarily unavailable"})

    if method == "GET" and path == "/api/admin/export":
        if principal.role != "admin":
            return respond(403, {"detail": "Administrator permission required"})
        try:
            return respond(200, repository.list_all())
        except (RuntimeError, ClientError) as error:
            code = (
                error.response.get("Error", {}).get("Code", "Unknown")
                if isinstance(error, ClientError)
                else "configured bound exceeded"
            )
            logger.error("DynamoDB export failed (%s)", code)
            return respond(503, {"detail": "Export is temporarily unavailable"})

    return respond(404, {"detail": "Route not found"})


def handler(event, context):
    request_context = event.get("requestContext", {})
    request_id = request_context.get("requestId") or getattr(context, "aws_request_id", None)
    token = request_id_context.set(request_id)
    try:
        try:
            repository = get_dynamodb_repository()
        except RuntimeError as error:
            logger.error("DynamoDB configuration error: %s", error)
            return respond(503, {"detail": "Donation storage is not configured"})
        try:
            return handle(event, repository)
        except ClientError as error:
            code = error.response.get("Error", {}).get("Code", "Unknown")
            logger.error("DynamoDB request failed (%s)", code)
            return respond(503, {"detail": "Donation storage is temporarily unavailable"})
    finally:
        request_id_context.reset(token)
