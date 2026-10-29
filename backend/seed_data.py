import argparse
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.repositories import SQLiteDonationRepository

DEFAULT_DATABASE = Path(__file__).parent / "data" / "sharebite-synthetic.db"

SEED_RECORDS = (
    {
        "id": "sharebite-seed-001",
        "donor_id": "donor-demo",
        "food_name": "Seasonal vegetable boxes",
        "description": "Fresh mixed vegetables packed for community kitchens.",
        "category": "produce",
        "quantity": 18,
        "unit": "boxes",
        "location": "Adyar, Chennai",
        "status": "available",
        "created_days_ago": 1,
        "pickup_hours_from_now": 8,
    },
    {
        "id": "sharebite-seed-002",
        "donor_id": "donor-demo-2",
        "food_name": "Fresh bakery assortment",
        "description": "Unsold bread and buns, packed this morning.",
        "category": "bakery",
        "quantity": 12,
        "unit": "kg",
        "location": "Indiranagar, Bengaluru",
        "status": "available",
        "created_days_ago": 0,
        "pickup_hours_from_now": 5,
    },
    {
        "id": "sharebite-seed-003",
        "donor_id": "donor-demo",
        "food_name": "Prepared lunch meals",
        "description": "Vegetarian meals kept chilled for prompt collection.",
        "category": "prepared meals",
        "quantity": 24,
        "unit": "portions",
        "location": "Kakkanad, Kochi",
        "status": "claimed",
        "claimed_by": "ngo-demo",
        "created_days_ago": 2,
        "pickup_hours_from_now": 4,
    },
    {
        "id": "sharebite-seed-004",
        "donor_id": "donor-demo-2",
        "food_name": "Seasonal fruit crates",
        "description": "Ripe fruit suitable for same-day distribution.",
        "category": "produce",
        "quantity": 16,
        "unit": "kg",
        "location": "Whitefield, Bengaluru",
        "status": "picked_up",
        "claimed_by": "ngo-demo-2",
        "created_days_ago": 4,
        "pickup_hours_from_now": -48,
    },
    {
        "id": "sharebite-seed-005",
        "donor_id": "donor-demo",
        "food_name": "Packaged pantry staples",
        "description": "Sealed, shelf-stable pantry items.",
        "category": "packaged",
        "quantity": 10,
        "unit": "packs",
        "location": "Palarivattom, Kochi",
        "status": "cancelled",
        "created_days_ago": 5,
        "pickup_hours_from_now": -36,
    },
    {
        "id": "sharebite-seed-006",
        "donor_id": "donor-demo-2",
        "food_name": "Fresh dairy packs",
        "description": "Refrigerated packs; pickup window has passed.",
        "category": "dairy",
        "quantity": 8,
        "unit": "litres",
        "location": "Koramangala, Bengaluru",
        "status": "expired",
        "created_days_ago": 6,
        "pickup_hours_from_now": -72,
    },
    {
        "id": "sharebite-seed-007",
        "donor_id": "donor-demo",
        "food_name": "Cooked rice and lentils",
        "description": "Freshly prepared meal portions for prompt pickup.",
        "category": "prepared meals",
        "quantity": 30,
        "unit": "portions",
        "location": "Fort Kochi, Kochi",
        "status": "picked_up",
        "claimed_by": "ngo-demo",
        "created_days_ago": 3,
        "pickup_hours_from_now": -30,
    },
    {
        "id": "sharebite-seed-008",
        "donor_id": "donor-demo-2",
        "food_name": "Unopened breakfast cereals",
        "description": "Sealed boxes with clear ingredient labels.",
        "category": "packaged",
        "quantity": 14,
        "unit": "boxes",
        "location": "Jayanagar, Bengaluru",
        "status": "claimed",
        "claimed_by": "ngo-demo-2",
        "created_days_ago": 1,
        "pickup_hours_from_now": 3,
    },
)


def _utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _existing_seed_count(database_path: Path) -> int | None:
    if not database_path.exists() or database_path.stat().st_size == 0:
        return None
    connection = sqlite3.connect(
        f"file:{database_path.resolve().as_posix()}?mode=ro", uri=True
    )
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        if not tables:
            return None
        if "sharebite_seed_metadata" in tables:
            seeded = connection.execute(
                "SELECT record_count FROM sharebite_seed_metadata WHERE seed_key = ?",
                ("sharebite-synthetic-v1",),
            ).fetchone()
            if seeded is not None:
                return int(seeded[0])
        raise ValueError(
            "Refusing to seed a database that already contains tables. "
            "Choose a new, empty development database path."
        )
    finally:
        connection.close()


def seed_database(database_path: Path = DEFAULT_DATABASE) -> int:
    database_path = Path(database_path).expanduser().resolve()
    existing_seed_count = _existing_seed_count(database_path)
    if existing_seed_count is not None:
        return existing_seed_count

    repository = SQLiteDonationRepository(database_path)
    repository.initialize()
    now = datetime.now(timezone.utc)
    connection = sqlite3.connect(database_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            """
            CREATE TABLE sharebite_seed_metadata (
                seed_key TEXT PRIMARY KEY,
                record_count INTEGER NOT NULL,
                seeded_at TEXT NOT NULL
            )
            """
        )
        for record in SEED_RECORDS:
            created_at = now - timedelta(days=record["created_days_ago"])
            claimed_at = created_at + timedelta(minutes=45)
            completed_at = claimed_at + timedelta(minutes=35)
            deadline = now + timedelta(hours=record["pickup_hours_from_now"])
            status = record["status"]
            last_event_at = (
                completed_at if status == "picked_up"
                else claimed_at if status == "claimed"
                else deadline if status == "expired"
                else created_at + timedelta(hours=1) if status == "cancelled"
                else created_at
            )
            donation = {
                "id": record["id"],
                "donor_id": record["donor_id"],
                "food_name": record["food_name"],
                "description": record["description"],
                "category": record["category"],
                "quantity": record["quantity"],
                "unit": record["unit"],
                "available_at": _utc_iso(created_at),
                "pickup_deadline": _utc_iso(deadline),
                "pickup_location": record["location"],
                "status": status,
                "claimed_by": record.get("claimed_by"),
                "created_at": _utc_iso(created_at),
                "updated_at": _utc_iso(last_event_at),
                "claimed_at": (
                    _utc_iso(claimed_at) if record.get("claimed_by") else None
                ),
                "completed_at": (
                    _utc_iso(completed_at) if status == "picked_up" else None
                ),
            }
            connection.execute(
                """
                INSERT INTO donations (
                    id, donor_id, food_name, quantity, unit, pickup_deadline,
                    status, claimed_by, created_at, description, category,
                    available_at, pickup_location, updated_at, claimed_at,
                    completed_at
                ) VALUES (
                    :id, :donor_id, :food_name, :quantity, :unit, :pickup_deadline,
                    :status, :claimed_by, :created_at, :description, :category,
                    :available_at, :pickup_location, :updated_at, :claimed_at,
                    :completed_at
                )
                """,
                donation,
            )
            event_rows = [
                (
                    f"{record['id']}-created",
                    "donation_created",
                    record["donor_id"],
                    None,
                    "available",
                    _utc_iso(created_at),
                )
            ]
            if record.get("claimed_by"):
                event_rows.append(
                    (
                        f"{record['id']}-claimed",
                        "donation_claimed",
                        record["claimed_by"],
                        "available",
                        "claimed",
                        _utc_iso(claimed_at),
                    )
                )
            if status == "picked_up":
                event_rows.append(
                    (
                        f"{record['id']}-picked-up",
                        "donation_picked_up",
                        record["claimed_by"],
                        "claimed",
                        "picked_up",
                        _utc_iso(completed_at),
                    )
                )
            elif status in {"cancelled", "expired"}:
                event_rows.append(
                    (
                        f"{record['id']}-{status}",
                        f"donation_{status}",
                        "system:expiry" if status == "expired" else record["donor_id"],
                        "available",
                        status,
                        _utc_iso(deadline if status == "expired" else created_at + timedelta(hours=1)),
                    )
                )
            connection.executemany(
                """
                INSERT INTO donation_events (
                    id, entity_type, entity_id, event_type, actor_id,
                    occurred_at, before_status, after_status, metadata, request_id
                ) VALUES (?, 'donation', ?, ?, ?, ?, ?, ?, '{}', 'synthetic-seed')
                """,
                [
                    (
                        event_id,
                        record["id"],
                        event_type,
                        actor_id,
                        occurred_at,
                        before_status,
                        after_status,
                    )
                    for (
                        event_id,
                        event_type,
                        actor_id,
                        before_status,
                        after_status,
                        occurred_at,
                    ) in event_rows
                ],
            )
        connection.execute(
            """
            INSERT INTO sharebite_seed_metadata (seed_key, record_count, seeded_at)
            VALUES (?, ?, ?)
            """,
            ("sharebite-synthetic-v1", len(SEED_RECORDS), _utc_iso(now)),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return len(SEED_RECORDS)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create synthetic ShareBite records in an empty local SQLite database."
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=DEFAULT_DATABASE,
        help=f"Target SQLite database (default: {DEFAULT_DATABASE})",
    )
    args = parser.parse_args()
    try:
        count = seed_database(args.database)
    except (OSError, sqlite3.Error, ValueError) as error:
        parser.error(str(error))
    print(
        f"Synthetic dataset ready: {count} donations in "
        f"{Path(args.database).expanduser().resolve()}"
    )


if __name__ == "__main__":
    main()
