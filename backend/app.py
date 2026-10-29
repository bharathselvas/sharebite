import json
import logging
import os
import re
import tempfile
import threading
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from .domain import (
    AccountStatusRequest,
    ClaimRequest,
    DonationCreate,
    DonationUpdateRequest,
    StatusRequest,
)
from .repositories import (
    MAX_PAGE_SIZE,
    DonationConflict,
    DonationForbidden,
    DonationNotFound,
    SQLiteDonationRepository,
    get_dynamodb_repository,
)
from .request_context import request_id_context
from etl.pipeline import MAX_RECORDS, run_pipeline

DATABASE_PATH = Path(
    os.environ.get("FOOD_REDISTRIBUTION_DB", Path(__file__).parent / "data" / "app.db")
)
logger = logging.getLogger(__name__)
ETL_RUN_LOCK = threading.Lock()
ETL_RUNS: dict[str, dict] = {}
ETL_REPORT_DIRS: dict[str, Path] = {}
ETL_RUN_ROOT = Path(tempfile.gettempdir()) / "smart-food-redistribution-etl"
ETL_REPORTS = {
    "clean_donations.csv": "text/csv",
    "cleaned_donations.csv": "text/csv",
    "rejected_records.csv": "text/csv",
    "rejected_donations.csv": "text/csv",
    "donation_daily_summary.csv": "text/csv",
    "donation_status_summary.csv": "text/csv",
    "summary.json": "application/json",
    "etl_run_summary.json": "application/json",
}


def get_repository():
    store = os.environ.get("DONATION_STORE", "sqlite").strip().lower()
    if store == "sqlite":
        return SQLiteDonationRepository(DATABASE_PATH)
    if store == "dynamodb":
        return get_dynamodb_repository()
    raise RuntimeError(f"Unsupported DONATION_STORE value: {store}")


@asynccontextmanager
async def lifespan(_: FastAPI):
    app_mode = os.environ.get("APP_MODE", "").strip().lower()
    store = os.environ.get("DONATION_STORE", "sqlite").strip().lower()
    if app_mode != "local-demo" or store != "sqlite":
        raise RuntimeError(
            "The FastAPI adapter accepts demo identities only in APP_MODE=local-demo "
            "with DONATION_STORE=sqlite. Use the authenticated Lambda adapter for AWS."
        )
    get_repository().initialize()
    yield


app = FastAPI(
    title="ShareBite API",
    description="Local-only API with synthetic demo identities.",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Content-Type", "Authorization"],
)


@app.middleware("http")
async def correlation_id_middleware(request, call_next):
    supplied = request.headers.get("x-request-id", "")
    request_id = supplied if re.fullmatch(r"[A-Za-z0-9._-]{1,64}", supplied) else str(uuid.uuid4())
    token = request_id_context.set(request_id)
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        request_id_context.reset(token)


def _record(donation_id: str | None = None, request: DonationCreate | None = None):
    if request is None:
        raise ValueError("A validated donation request is required")
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "id": donation_id or str(uuid.uuid4()),
        "donor_id": request.donor_id,
        "food_name": request.food_name,
        "description": request.description,
        "category": request.category,
        "quantity": request.quantity,
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
        "created_at": now,
        "updated_at": now,
        "claimed_at": None,
        "completed_at": None,
    }


def _local_role(repository, actor_id: str) -> str:
    user = repository.get_user(actor_id)
    if user is None:
        raise HTTPException(status_code=403, detail="Unknown local demo identity")
    if user["status"] != "active":
        raise HTTPException(status_code=403, detail="Account is suspended")
    return user["role"]


def _raise_repository_error(error: Exception) -> None:
    if isinstance(error, DonationNotFound):
        raise HTTPException(status_code=404, detail="Donation not found") from error
    if isinstance(error, DonationForbidden):
        raise HTTPException(status_code=403, detail="Actor is not authorized for this donation") from error
    if isinstance(error, DonationConflict):
        raise HTTPException(
            status_code=409, detail="Donation state changed; refresh and retry"
        ) from error
    raise error


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "mode": "local-demo"}


@app.get("/api/donations")
def list_donations(
    status: str | None = Query(
        default=None, pattern="^(available|claimed|picked_up|cancelled|expired)$"
    ),
    actor_id: str | None = None,
    role: str | None = Query(default=None, pattern="^(donor|ngo|admin)$"),
) -> list[dict]:
    repository = get_repository()
    if actor_id:
        actual_role = _local_role(repository, actor_id)
        if role and role != actual_role:
            raise HTTPException(status_code=403, detail="Role does not match local demo profile")
        if actual_role == "admin":
            return repository.list_status(status, MAX_PAGE_SIZE)[0] if status else repository.list_all()
    elif status not in {None, "available"}:
        raise HTTPException(status_code=403, detail="Only available donations are public")
    return repository.list_status("available", MAX_PAGE_SIZE)[0]


@app.get("/api/donations/page")
def list_donations_page(
    status: Annotated[str, Query(pattern="^(available|claimed|picked_up|cancelled|expired)$")] = "available",
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 25,
    cursor: str | None = None,
    actor_id: str | None = None,
) -> dict:
    if status != "available":
        if not actor_id or _local_role(get_repository(), actor_id) != "admin":
            raise HTTPException(status_code=403, detail="Only administrators can list non-available donations")
    try:
        items, next_cursor = get_repository().list_status(status, limit, cursor)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {"items": items, "next_cursor": next_cursor}


@app.get("/api/donations/mine")
def list_my_donations(
    actor_id: str = Query(...),
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 25,
    cursor: str | None = None,
) -> dict:
    repository = get_repository()
    role = _local_role(repository, actor_id)
    if role == "donor":
        items, next_cursor = repository.list_by_donor(actor_id, limit, cursor)
    elif role == "ngo":
        items, next_cursor = repository.list_by_claimant(actor_id, limit, cursor)
    else:
        raise HTTPException(status_code=403, detail="Personal donation history is for donors and recipients")
    return {"items": items, "next_cursor": next_cursor}


@app.post("/api/donations", status_code=201)
def create_donation(request: DonationCreate) -> dict:
    repository = get_repository()
    if _local_role(repository, request.donor_id) != "donor":
        raise HTTPException(status_code=403, detail="Use a configured local demo donor identity")
    return repository.create(_record(request=request))


@app.post("/api/donations/{donation_id}/claim")
def claim_donation(donation_id: str, request: ClaimRequest) -> dict:
    repository = get_repository()
    if _local_role(repository, request.ngo_id) != "ngo":
        raise HTTPException(status_code=403, detail="Use a configured local demo NGO identity")
    try:
        return repository.claim(donation_id, request.ngo_id)
    except (DonationNotFound, DonationConflict, DonationForbidden) as error:
        _raise_repository_error(error)


@app.patch("/api/donations/{donation_id}")
def edit_donation(donation_id: str, request: DonationUpdateRequest) -> dict:
    repository = get_repository()
    role = _local_role(repository, request.actor_id)
    if role != "donor":
        raise HTTPException(status_code=403, detail="Only the owning donor can edit a listing")
    fields = request.model_dump(exclude={"actor_id"})
    for key in ("available_at", "pickup_deadline"):
        value = fields[key]
        fields[key] = value.isoformat().replace("+00:00", "Z") if value else None
    try:
        return repository.update_donation(donation_id, fields, request.actor_id, role)
    except (DonationNotFound, DonationConflict, DonationForbidden) as error:
        _raise_repository_error(error)


@app.patch("/api/donations/{donation_id}/status")
def update_status(donation_id: str, request: StatusRequest) -> dict:
    repository = get_repository()
    actual_role = _local_role(repository, request.actor_id)
    if request.status == "cancelled":
        if actual_role not in {"donor", "admin"}:
            raise HTTPException(status_code=403, detail="Only a donor or admin can cancel")
    else:
        if actual_role not in {"ngo", "admin"}:
            raise HTTPException(status_code=403, detail="Only an NGO or admin can confirm pickup")
    try:
        return repository.transition(
            donation_id, request.status, request.actor_id, actual_role
        )
    except (DonationNotFound, DonationConflict, DonationForbidden) as error:
        _raise_repository_error(error)


@app.get("/api/admin/analytics")
def analytics(
    actor_id: str = Query(...),
    start_date: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end_date: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    status: str | None = Query(default=None, pattern="^(available|claimed|picked_up|cancelled|expired)$"),
    category: str | None = Query(default=None, max_length=40),
    location: str | None = Query(default=None, max_length=160),
) -> dict:
    repository = get_repository()
    if _local_role(repository, actor_id) != "admin":
        raise HTTPException(status_code=403, detail="Admin demo identity required")
    filters = {
        "start_date": start_date,
        "end_date": end_date,
        "status": status,
        "category": category,
        "location": location,
    }
    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=422, detail="start_date must be on or before end_date")
    try:
        for value in (start_date, end_date):
            if value:
                datetime.strptime(value, "%Y-%m-%d")
    except ValueError as error:
        raise HTTPException(status_code=422, detail="Dates must use a valid YYYY-MM-DD value") from error
    return repository.analytics(filters)


@app.get("/api/admin/donations")
def admin_donations(actor_id: str = Query(...)) -> list[dict]:
    repository = get_repository()
    if _local_role(repository, actor_id) != "admin":
        raise HTTPException(status_code=403, detail="Admin demo identity required")
    return repository.list_all()


@app.get("/api/admin/export")
def export_donations(actor_id: str = Query(...)) -> list[dict]:
    repository = get_repository()
    if _local_role(repository, actor_id) != "admin":
        raise HTTPException(status_code=403, detail="Admin demo identity required")
    return repository.list_all()


@app.get("/api/me")
def get_my_profile(actor_id: str = Query(...)) -> dict:
    profile = get_repository().get_user(actor_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    if profile["status"] != "active":
        raise HTTPException(status_code=403, detail="Account is suspended")
    return profile


@app.get("/api/me/dashboard")
def user_dashboard(actor_id: str = Query(...)) -> dict:
    repository = get_repository()
    role = _local_role(repository, actor_id)
    if role == "admin":
        raise HTTPException(
            status_code=403,
            detail="Use the administrator analytics endpoint for platform metrics",
        )
    if os.environ.get("DONATION_STORE", "sqlite").strip().lower() != "sqlite":
        raise HTTPException(
            status_code=501,
            detail="Role-specific dashboard summaries are not available in the cloud adapter",
        )
    return repository.dashboard_for_user(actor_id, role)


@app.get("/api/admin/users")
def list_users(
    actor_id: str = Query(...),
    search: str = "",
    status: str | None = Query(default=None, pattern="^(active|suspended)$"),
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 25,
    cursor: str | None = None,
) -> dict:
    repository = get_repository()
    if _local_role(repository, actor_id) != "admin":
        raise HTTPException(status_code=403, detail="Admin demo identity required")
    users, next_cursor = repository.list_users(search, status, limit, cursor)
    return {"items": users, "next_cursor": next_cursor}


@app.patch("/api/admin/users/{user_id}/status")
def set_user_status(user_id: str, request: AccountStatusRequest) -> dict:
    repository = get_repository()
    if _local_role(repository, request.actor_id) != "admin":
        raise HTTPException(status_code=403, detail="Admin demo identity required")
    if user_id == request.actor_id:
        raise HTTPException(status_code=409, detail="Administrators cannot change their own account status")
    try:
        return repository.set_user_status(user_id, request.status, request.actor_id)
    except (DonationNotFound, DonationConflict) as error:
        _raise_repository_error(error)


@app.get("/api/admin/users/{user_id}/events")
def user_events(
    user_id: str,
    actor_id: str = Query(...),
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 25,
    cursor: str | None = None,
) -> dict:
    repository = get_repository()
    if _local_role(repository, actor_id) != "admin":
        raise HTTPException(status_code=403, detail="Admin demo identity required")
    if repository.get_user(user_id) is None:
        raise HTTPException(status_code=404, detail="User profile not found")
    events, next_cursor = repository.list_events("user", user_id, limit, cursor)
    return {"items": events, "next_cursor": next_cursor}


@app.get("/api/donations/{donation_id}/events")
def donation_events(
    donation_id: str,
    actor_id: str = Query(...),
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 25,
    cursor: str | None = None,
) -> dict:
    repository = get_repository()
    role = _local_role(repository, actor_id)
    donation = repository.get(donation_id)
    if donation is None:
        raise HTTPException(status_code=404, detail="Donation not found")
    if role != "admin" and actor_id not in {
        donation["donor_id"],
        donation.get("claimed_by"),
    }:
        raise HTTPException(status_code=403, detail="Donation history is restricted to its participants")
    events, next_cursor = repository.list_events("donation", donation_id, limit, cursor)
    return {"items": events, "next_cursor": next_cursor}


@app.post("/api/admin/expire")
def expire_donations(actor_id: str = Query(...)) -> dict:
    repository = get_repository()
    if _local_role(repository, actor_id) != "admin":
        raise HTTPException(status_code=403, detail="Admin demo identity required")
    return {"expired_count": repository.expire_due()}


@app.get("/api/admin/activity")
def admin_activity(
    actor_id: str = Query(...),
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 25,
    cursor: str | None = None,
    event_type: str | None = Query(default=None, max_length=50),
    start_date: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end_date: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> dict:
    repository = get_repository()
    if _local_role(repository, actor_id) != "admin":
        raise HTTPException(status_code=403, detail="Admin demo identity required")
    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=422, detail="start_date must be on or before end_date")
    try:
        for value in (start_date, end_date):
            if value:
                datetime.strptime(value, "%Y-%m-%d")
        items, next_cursor = repository.list_recent_events(
            limit, cursor, event_type, start_date, end_date
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {"items": items, "next_cursor": next_cursor}


def _require_local_admin(repository, actor_id: str) -> None:
    if os.environ.get("DONATION_STORE", "sqlite").strip().lower() != "sqlite":
        raise HTTPException(
            status_code=501,
            detail="This operational feature is available only in the local SQLite demo.",
        )
    if _local_role(repository, actor_id) != "admin":
        raise HTTPException(status_code=403, detail="Admin demo identity required")


def _public_etl_run(run: dict) -> dict:
    return {
        key: value
        for key, value in run.items()
        if key != "output_dir"
    }


@app.get("/api/admin/etl/runs")
def list_etl_runs(actor_id: str = Query(...)) -> dict:
    _require_local_admin(get_repository(), actor_id)
    with ETL_RUN_LOCK:
        runs = sorted(
            (_public_etl_run(run) for run in ETL_RUNS.values()),
            key=lambda run: run["started_at"],
            reverse=True,
        )[:20]
    return {"items": runs, "mode": "local"}


@app.post("/api/admin/etl/runs", status_code=201)
def run_local_etl(actor_id: str = Query(...)) -> dict:
    repository = get_repository()
    _require_local_admin(repository, actor_id)
    if not ETL_RUN_LOCK.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="An ETL run is already in progress")

    run_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    run = {
        "run_id": run_id,
        "status": "running",
        "mode": "local",
        "started_at": started_at,
        "completed_at": None,
        "processing_duration_seconds": None,
        "input_records": 0,
        "total_clean_donations": 0,
        "rejected_records": 0,
        "duplicate_records": 0,
        "completed_pickups": 0,
        "error": None,
        "reports": [],
        "output_dir": None,
    }
    ETL_RUNS[run_id] = run
    try:
        ETL_RUN_ROOT.mkdir(parents=True, exist_ok=True)
        output_dir = Path(
            tempfile.mkdtemp(prefix=f"food-etl-{run_id}-", dir=ETL_RUN_ROOT)
        )
        run["output_dir"] = str(output_dir)
        ETL_REPORT_DIRS[run_id] = output_dir
        records = repository.list_all()
        if len(records) > MAX_RECORDS:
            raise ValueError(f"Local ETL is limited to {MAX_RECORDS} donation records")
        input_path = output_dir / "application-export.json"
        input_path.write_text(json.dumps(records), encoding="utf-8")
        summary = run_pipeline(input_path, output_dir)
        run.update(
            {
                "status": "succeeded",
                "completed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "processing_duration_seconds": summary["processing_duration_seconds"],
                "input_records": summary["input_records"],
                "total_clean_donations": summary["total_clean_donations"],
                "rejected_records": summary["rejected_records"],
                "duplicate_records": summary["duplicate_records"],
                "completed_pickups": summary["completed_pickups"],
                "reports": [
                    name
                    for name in ETL_REPORTS
                    if (output_dir / name).is_file()
                ],
            }
        )
        return _public_etl_run(run)
    except (OSError, TypeError, ValueError) as error:
        run.update(
            {
                "status": "failed",
                "completed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "error": str(error),
            }
        )
        logger.exception("Local ETL run %s failed", run_id)
        raise HTTPException(
            status_code=500, detail="ETL run failed; review the local server error log."
        ) from error
    finally:
        ETL_RUN_LOCK.release()


@app.get("/api/admin/etl/runs/{run_id}/reports/{report_name}")
def download_etl_report(run_id: str, report_name: str, actor_id: str = Query(...)):
    _require_local_admin(get_repository(), actor_id)
    if run_id not in ETL_RUNS or report_name not in ETL_REPORTS:
        raise HTTPException(status_code=404, detail="ETL report not found")
    run = ETL_RUNS[run_id]
    report_path = ETL_REPORT_DIRS[run_id] / report_name
    if run["status"] != "succeeded" or not report_path.is_file():
        raise HTTPException(status_code=404, detail="ETL report not found")
    return FileResponse(
        report_path,
        media_type=ETL_REPORTS[report_name],
        filename=report_name,
    )


@app.get("/api/admin/system/health")
def system_health(actor_id: str = Query(...)) -> dict:
    repository = get_repository()
    _require_local_admin(repository, actor_id)
    try:
        donation_count = len(repository.list_all())
        database_status = "healthy"
        database_error = None
    except (OSError, RuntimeError) as error:
        donation_count = None
        database_status = "unavailable"
        database_error = type(error).__name__
        logger.exception("Local SQLite health query failed")
    latest_run = max(
        ETL_RUNS.values(),
        key=lambda run: run["started_at"],
        default=None,
    )
    return {
        "checked_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "api": "reachable",
        "application_mode": "local-demo",
        "database": {
            "adapter": "sqlite",
            "status": database_status,
            "donation_count": donation_count,
            "error_type": database_error,
        },
        "etl": _public_etl_run(latest_run) if latest_run else None,
        "ci": "unknown (no GitHub Actions integration configured)",
        "deployment": "not_deployed",
    }
