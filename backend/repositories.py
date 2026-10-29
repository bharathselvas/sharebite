import base64
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol

from boto3.dynamodb.conditions import Key
from boto3.dynamodb.types import TypeSerializer
from botocore.exceptions import ClientError

from .domain import DEMO_ADMIN, DEMO_DONORS, DEMO_NGOS, STATUSES
from .request_context import current_request_id

MAX_PAGE_SIZE = 100
MAX_ADMIN_EXPORT = 500


class DonationNotFound(Exception):
    pass


class DonationConflict(Exception):
    pass


class DonationForbidden(Exception):
    pass


class DonationRepository(Protocol):
    def initialize(self) -> None: ...

    def create(self, donation: dict) -> dict: ...

    def update_donation(
        self, donation_id: str, fields: dict, actor_id: str, role: str
    ) -> dict: ...

    def get(self, donation_id: str) -> dict | None: ...

    def list_status(
        self, status: str, limit: int, cursor: str | None = None
    ) -> tuple[list[dict], str | None]: ...

    def list_by_donor(
        self, donor_id: str, limit: int, cursor: str | None = None
    ) -> tuple[list[dict], str | None]: ...

    def list_by_claimant(
        self, claimant_id: str, limit: int, cursor: str | None = None
    ) -> tuple[list[dict], str | None]: ...

    def list_all(self) -> list[dict]: ...

    def claim(self, donation_id: str, ngo_id: str) -> dict: ...

    def transition(
        self, donation_id: str, status: str, actor_id: str, role: str
    ) -> dict: ...

    def analytics(self) -> dict: ...


def _encode_cursor(value: dict | None) -> str | None:
    if value is None:
        return None
    payload = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(value: str | None) -> dict | None:
    if value is None:
        return None
    try:
        padded = value + "=" * (-len(value) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, json.JSONDecodeError) as error:
        raise ValueError("Invalid pagination cursor") from error
    if not isinstance(decoded, dict):
        raise ValueError("Invalid pagination cursor")
    return decoded


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class SQLiteDonationRepository:
    def __init__(self, database_path: Path):
        self.database_path = Path(database_path)

    @contextmanager
    def _connect(self):
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS donations (
                    id TEXT PRIMARY KEY,
                    donor_id TEXT NOT NULL,
                    food_name TEXT NOT NULL,
                    quantity REAL NOT NULL CHECK(quantity > 0),
                    unit TEXT NOT NULL,
                    pickup_deadline TEXT NOT NULL,
                    status TEXT NOT NULL,
                    claimed_by TEXT,
                    created_at TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    category TEXT NOT NULL DEFAULT 'other',
                    available_at TEXT,
                    pickup_location TEXT NOT NULL DEFAULT '',
                    updated_at TEXT,
                    claimed_at TEXT,
                    completed_at TEXT
                )
                """
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(donations)")
            }
            additions = {
                "description": "TEXT NOT NULL DEFAULT ''",
                "category": "TEXT NOT NULL DEFAULT 'other'",
                "available_at": "TEXT",
                "pickup_location": "TEXT NOT NULL DEFAULT ''",
                "updated_at": "TEXT",
                "claimed_at": "TEXT",
                "completed_at": "TEXT",
            }
            for name, declaration in additions.items():
                if name not in columns:
                    connection.execute(
                        f"ALTER TABLE donations ADD COLUMN {name} {declaration}"
                    )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS donation_events (
                    id TEXT PRIMARY KEY,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    before_status TEXT,
                    after_status TEXT,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    request_id TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS donation_events_entity_time
                ON donation_events(entity_type, entity_id, occurred_at DESC, id DESC)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS donation_events_time
                ON donation_events(occurred_at DESC, id DESC)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS donations_expiry
                ON donations(status, pickup_deadline, id)
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS user_profiles (
                    user_id TEXT PRIMARY KEY,
                    role TEXT NOT NULL CHECK(role IN ('donor', 'ngo', 'admin')),
                    status TEXT NOT NULL CHECK(status IN ('active', 'suspended')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            now = _utc_now()
            demo_users = [
                (user_id, "donor") for user_id in sorted(DEMO_DONORS)
            ] + [
                (user_id, "ngo") for user_id in sorted(DEMO_NGOS)
            ] + [(DEMO_ADMIN, "admin")]
            connection.executemany(
                """
                INSERT OR IGNORE INTO user_profiles
                    (user_id, role, status, created_at, updated_at)
                VALUES (?, ?, 'active', ?, ?)
                """,
                [(user_id, role, now, now) for user_id, role in demo_users],
            )

    def create(self, donation: dict) -> dict:
        record = {"id": str(uuid.uuid4()), **donation}
        record.setdefault("description", "")
        record.setdefault("category", "other")
        record.setdefault("available_at", None)
        record.setdefault("pickup_location", "")
        record.setdefault("updated_at", record["created_at"])
        record.setdefault("claimed_at", None)
        record.setdefault("completed_at", None)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO donations
                    (id, donor_id, food_name, quantity, unit, pickup_deadline,
                     status, claimed_by, created_at, description, category,
                     available_at, pickup_location, updated_at)
                VALUES
                    (:id, :donor_id, :food_name, :quantity, :unit, :pickup_deadline,
                     :status, :claimed_by, :created_at, :description, :category,
                     :available_at, :pickup_location, :updated_at)
                """,
                record,
            )
            self._insert_event(
                connection,
                "donation",
                record["id"],
                "donation_created",
                record["donor_id"],
                None,
                record["status"],
                {},
            )
        return record

    def get(self, donation_id: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM donations WHERE id = ?", (donation_id,)
            ).fetchone()
        return dict(row) if row else None

    def update_donation(
        self, donation_id: str, fields: dict, actor_id: str, role: str
    ) -> dict:
        now = _utc_now()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM donations WHERE id = ?", (donation_id,)
            ).fetchone()
            if not row:
                raise DonationNotFound
            if role != "donor" or row["donor_id"] != actor_id:
                raise DonationForbidden
            if row["status"] != "available":
                raise DonationConflict
            cursor = connection.execute(
                """
                UPDATE donations SET
                    food_name = ?, description = ?, category = ?, quantity = ?,
                    unit = ?, available_at = ?, pickup_deadline = ?,
                    pickup_location = ?, updated_at = ?
                WHERE id = ? AND donor_id = ? AND status = 'available'
                """,
                (
                    fields["food_name"],
                    fields["description"],
                    fields["category"],
                    fields["quantity"],
                    fields["unit"],
                    fields["available_at"],
                    fields["pickup_deadline"],
                    fields["pickup_location"],
                    now,
                    donation_id,
                    actor_id,
                ),
            )
            if cursor.rowcount == 0:
                raise DonationConflict
            self._insert_event(
                connection,
                "donation",
                donation_id,
                "donation_updated",
                actor_id,
                "available",
                "available",
                {"changed_fields": sorted(fields)},
            )
            updated = connection.execute(
                "SELECT * FROM donations WHERE id = ?", (donation_id,)
            ).fetchone()
        return dict(updated)

    def list_status(
        self, status: str, limit: int, cursor: str | None = None
    ) -> tuple[list[dict], str | None]:
        offset = _decode_cursor(cursor)
        if offset is not None and (
            set(offset) != {"offset"}
            or not isinstance(offset["offset"], int)
            or offset["offset"] < 0
        ):
            raise ValueError("Invalid pagination cursor")
        start = offset["offset"] if offset else 0
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM donations
                WHERE status = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                (status, limit + 1, start),
            ).fetchall()
        next_cursor = _encode_cursor({"offset": start + limit}) if len(rows) > limit else None
        return [dict(row) for row in rows[:limit]], next_cursor

    def list_by_donor(
        self, donor_id: str, limit: int, cursor: str | None = None
    ) -> tuple[list[dict], str | None]:
        offset = _decode_cursor(cursor)
        if offset is not None and (
            set(offset) != {"offset"}
            or not isinstance(offset["offset"], int)
            or offset["offset"] < 0
        ):
            raise ValueError("Invalid pagination cursor")
        start = offset["offset"] if offset else 0
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM donations
                WHERE donor_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                (donor_id, limit + 1, start),
            ).fetchall()
        next_cursor = _encode_cursor({"offset": start + limit}) if len(rows) > limit else None
        return [dict(row) for row in rows[:limit]], next_cursor

    def list_by_claimant(
        self, claimant_id: str, limit: int, cursor: str | None = None
    ) -> tuple[list[dict], str | None]:
        decoded = _decode_cursor(cursor)
        if decoded is not None and (
            set(decoded) != {"offset"}
            or not isinstance(decoded["offset"], int)
            or decoded["offset"] < 0
        ):
            raise ValueError("Invalid pagination cursor")
        offset = decoded["offset"] if decoded else 0
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM donations
                WHERE claimed_by = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                (claimant_id, limit + 1, offset),
            ).fetchall()
        next_cursor = _encode_cursor({"offset": offset + limit}) if len(rows) > limit else None
        return [dict(row) for row in rows[:limit]], next_cursor

    def list_all(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM donations ORDER BY created_at DESC, id DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def claim(self, donation_id: str, ngo_id: str) -> dict:
        now = _utc_now()
        conflict = False
        claimed = None
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE donations
                SET status = 'claimed', claimed_by = ?, claimed_at = ?, updated_at = ?
                WHERE id = ? AND status = 'available' AND pickup_deadline > ?
                """,
                (ngo_id, now, now, donation_id, now),
            )
            if cursor.rowcount == 0:
                row = connection.execute(
                    "SELECT * FROM donations WHERE id = ?", (donation_id,)
                ).fetchone()
                if not row:
                    raise DonationNotFound
                if row["status"] == "available" and row["pickup_deadline"] <= now:
                    expired = connection.execute(
                        """
                        UPDATE donations SET status = 'expired', updated_at = ?
                        WHERE id = ? AND status = 'available'
                        """,
                        (now, donation_id),
                    )
                    if expired.rowcount:
                        self._insert_event(
                            connection,
                            "donation",
                            donation_id,
                            "donation_expired",
                            "system:expiry",
                            "available",
                            "expired",
                            {"reason": "pickup_deadline_passed"},
                        )
                conflict = True
            else:
                claimed = connection.execute(
                    "SELECT * FROM donations WHERE id = ?", (donation_id,)
                ).fetchone()
                self._insert_event(
                    connection,
                    "donation",
                    donation_id,
                    "donation_claimed",
                    ngo_id,
                    "available",
                    "claimed",
                    {},
                )
        if conflict:
            raise DonationConflict
        return dict(claimed)

    def transition(
        self, donation_id: str, status: str, actor_id: str, role: str
    ) -> dict:
        expected_status = "available" if status == "cancelled" else "claimed"
        now = _utc_now()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM donations WHERE id = ?", (donation_id,)
            ).fetchone()
            if not row:
                raise DonationNotFound
            if role == "donor" and status == "cancelled":
                owner_column = "donor_id"
            elif role == "ngo" and status == "picked_up":
                owner_column = "claimed_by"
            elif role == "admin":
                owner_column = None
            else:
                raise DonationForbidden
            if owner_column and row[owner_column] != actor_id:
                raise DonationForbidden
            if row["status"] != expected_status:
                raise DonationConflict
            if owner_column:
                cursor = connection.execute(
                    f"UPDATE donations SET status = ?, updated_at = ?, completed_at = ? WHERE id = ? AND status = ? AND {owner_column} = ?",
                    (
                        status,
                        now,
                        now if status == "picked_up" else None,
                        donation_id,
                        expected_status,
                        actor_id,
                    ),
                )
            else:
                cursor = connection.execute(
                    """
                    UPDATE donations SET status = ?, updated_at = ?, completed_at = ?
                    WHERE id = ? AND status = ?
                    """,
                    (
                        status,
                        now,
                        now if status == "picked_up" else None,
                        donation_id,
                        expected_status,
                    ),
                )
            if cursor.rowcount == 0:
                raise DonationConflict
            updated = connection.execute(
                "SELECT * FROM donations WHERE id = ?", (donation_id,)
            ).fetchone()
            self._insert_event(
                connection,
                "donation",
                donation_id,
                "donation_completed" if status == "picked_up" else "donation_cancelled",
                actor_id,
                expected_status,
                status,
                {},
            )
        return dict(updated)

    @staticmethod
    def _insert_event(
        connection,
        entity_type: str,
        entity_id: str,
        event_type: str,
        actor_id: str,
        before_status: str | None,
        after_status: str | None,
        metadata: dict,
        request_id: str | None = None,
    ) -> None:
        connection.execute(
            """
            INSERT INTO donation_events
                (id, entity_type, entity_id, event_type, actor_id, occurred_at,
                 before_status, after_status, metadata, request_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                entity_type,
                entity_id,
                event_type,
                actor_id,
                _utc_now(),
                before_status,
                after_status,
                json.dumps(metadata, sort_keys=True),
                request_id or current_request_id(),
            ),
        )

    def list_events(
        self, entity_type: str, entity_id: str, limit: int = 50, cursor: str | None = None
    ) -> tuple[list[dict], str | None]:
        decoded = _decode_cursor(cursor)
        if decoded is not None and (
            set(decoded) != {"offset"}
            or not isinstance(decoded["offset"], int)
            or decoded["offset"] < 0
        ):
            raise ValueError("Invalid pagination cursor")
        offset = decoded["offset"] if decoded else 0
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM donation_events
                WHERE entity_type = ? AND entity_id = ?
                ORDER BY occurred_at DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                (entity_type, entity_id, limit + 1, offset),
            ).fetchall()
        events = []
        for row in rows[:limit]:
            event = dict(row)
            event["metadata"] = json.loads(event["metadata"])
            events.append(event)
        next_cursor = _encode_cursor({"offset": offset + limit}) if len(rows) > limit else None
        return events, next_cursor

    def get_user(self, user_id: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT user_id, role, status, created_at, updated_at FROM user_profiles WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_users(
        self, search: str = "", status: str | None = None, limit: int = 25,
        cursor: str | None = None,
    ) -> tuple[list[dict], str | None]:
        decoded = _decode_cursor(cursor)
        if decoded is not None and (
            set(decoded) != {"offset"}
            or not isinstance(decoded["offset"], int)
            or decoded["offset"] < 0
        ):
            raise ValueError("Invalid pagination cursor")
        offset = decoded["offset"] if decoded else 0
        clauses = []
        parameters: list = []
        if search.strip():
            clauses.append("user_id LIKE ?")
            parameters.append(f"%{search.strip()}%")
        if status:
            clauses.append("status = ?")
            parameters.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT user_id, role, status, created_at, updated_at
                FROM user_profiles {where}
                ORDER BY role, user_id
                LIMIT ? OFFSET ?
                """,
                (*parameters, limit + 1, offset),
            ).fetchall()
        next_cursor = _encode_cursor({"offset": offset + limit}) if len(rows) > limit else None
        return [dict(row) for row in rows[:limit]], next_cursor

    def list_recent_events(
        self,
        limit: int = 50,
        cursor: str | None = None,
        event_type: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> tuple[list[dict], str | None]:
        decoded = _decode_cursor(cursor)
        if decoded is not None and (
            set(decoded) != {"offset"}
            or not isinstance(decoded["offset"], int)
            or decoded["offset"] < 0
        ):
            raise ValueError("Invalid pagination cursor")
        offset = decoded["offset"] if decoded else 0
        clauses = []
        values: list[object] = []
        if event_type:
            clauses.append("event_type = ?")
            values.append(event_type)
        if start_date:
            clauses.append("occurred_at >= ?")
            values.append(f"{start_date}T00:00:00")
        if end_date:
            end_exclusive = (
                datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
            ).strftime("%Y-%m-%d")
            clauses.append("occurred_at < ?")
            values.append(f"{end_exclusive}T00:00:00Z~")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM donation_events {where}
                ORDER BY occurred_at DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                (*values, limit + 1, offset),
            ).fetchall()
        next_cursor = _encode_cursor({"offset": offset + limit}) if len(rows) > limit else None
        return [dict(row) for row in rows[:limit]], next_cursor

    def dashboard_for_user(self, user_id: str, role: str) -> dict:
        if role not in {"donor", "ngo"}:
            raise ValueError("A donor or NGO role is required")
        owner_column = "donor_id" if role == "donor" else "claimed_by"
        now = _utc_now()
        with self._connect() as connection:
            counts = connection.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(status = 'available' AND pickup_deadline > ?) AS available,
                    SUM(status = 'claimed') AS claimed,
                    SUM(status = 'picked_up') AS picked_up,
                    SUM(status = 'cancelled') AS cancelled,
                    SUM(status = 'expired') AS expired
                FROM donations WHERE %s = ?
                """ % owner_column,
                (now, user_id),
            ).fetchone()
            marketplace_available = connection.execute(
                """
                SELECT COUNT(*) FROM donations
                WHERE status = 'available' AND pickup_deadline > ?
                """,
                (now,),
            ).fetchone()[0]
            quantity_rows = connection.execute(
                f"""
                SELECT unit, SUM(quantity) AS quantity
                FROM donations
                WHERE {owner_column} = ? AND status = 'picked_up'
                GROUP BY unit
                ORDER BY unit
                """,
                (user_id,),
            ).fetchall()
            recent_rows = connection.execute(
                f"""
                SELECT * FROM donations WHERE {owner_column} = ?
                ORDER BY created_at DESC, id DESC LIMIT 5
                """,
                (user_id,),
            ).fetchall()
            upcoming_rows = (
                connection.execute(
                    """
                    SELECT * FROM donations
                    WHERE claimed_by = ? AND status = 'claimed' AND pickup_deadline > ?
                    ORDER BY pickup_deadline, id LIMIT 5
                    """,
                    (user_id, now),
                ).fetchall()
                if role == "ngo"
                else []
            )
            event_rows = connection.execute(
                f"""
                SELECT e.* FROM donation_events AS e
                INNER JOIN donations AS d ON d.id = e.entity_id
                WHERE e.entity_type = 'donation' AND d.{owner_column} = ?
                ORDER BY e.occurred_at DESC, e.id DESC LIMIT 10
                """,
                (user_id,),
            ).fetchall()
            events = []
            for event_row in event_rows:
                event = dict(event_row)
                event["metadata"] = json.loads(event["metadata"])
                events.append(event)

        return {
            "role": role,
            "total_donations": counts["total"],
            "available_donations": counts["available"] or 0,
            "marketplace_available_donations": marketplace_available,
            "claimed_donations": counts["claimed"] or 0,
            "completed_pickups": counts["picked_up"] or 0,
            "cancelled_donations": counts["cancelled"] or 0,
            "expired_donations": counts["expired"] or 0,
            "completed_quantity_by_unit": {
                row["unit"]: row["quantity"] for row in quantity_rows
            },
            "upcoming_pickups": [dict(row) for row in upcoming_rows],
            "recent_donations": [dict(row) for row in recent_rows],
            "recent_activity": events,
            "last_updated": now,
            "data_source": "local_live",
        }

    def set_user_status(self, user_id: str, status: str, actor_id: str) -> dict:
        now = _utc_now()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM user_profiles WHERE user_id = ?", (user_id,)
            ).fetchone()
            if not row:
                raise DonationNotFound
            if row["status"] == status:
                raise DonationConflict
            connection.execute(
                "UPDATE user_profiles SET status = ?, updated_at = ? WHERE user_id = ?",
                (status, now, user_id),
            )
            self._insert_event(
                connection,
                "user",
                user_id,
                f"account_{status}",
                actor_id,
                row["status"],
                status,
                {},
            )
            updated = connection.execute(
                """
                SELECT user_id, role, status, created_at, updated_at
                FROM user_profiles WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
        return dict(updated)

    def expire_due(self, now: datetime | None = None, limit: int = 100) -> int:
        cutoff = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id FROM donations
                WHERE status = 'available' AND pickup_deadline <= ?
                ORDER BY pickup_deadline, id
                LIMIT ?
                """,
                (cutoff, limit),
            ).fetchall()
            for row in rows:
                result = connection.execute(
                    """
                    UPDATE donations SET status = 'expired', updated_at = ?
                    WHERE id = ? AND status = 'available'
                    """,
                    (cutoff, row["id"]),
                )
                if result.rowcount:
                    self._insert_event(
                        connection,
                        "donation",
                        row["id"],
                        "donation_expired",
                        "system:expiry",
                        "available",
                        "expired",
                        {"reason": "pickup_deadline_passed"},
                    )
        return len(rows)

    def analytics(self, filters: dict | None = None) -> dict:
        rows = self.list_all()
        filters = filters or {}
        start = filters.get("start_date")
        end = filters.get("end_date")
        status_filter = filters.get("status")
        category_filter = filters.get("category")
        location_filter = filters.get("location")
        if start:
            rows = [row for row in rows if row["created_at"][:10] >= start]
        if end:
            rows = [row for row in rows if row["created_at"][:10] <= end]
        if category_filter:
            rows = [row for row in rows if row["category"] == category_filter]
        if location_filter:
            rows = [
                row for row in rows
                if location_filter.casefold() in row["pickup_location"].casefold()
            ]
        rate_records = rows
        if status_filter:
            rows = [row for row in rows if row["status"] == status_filter]
        counts = {status: 0 for status in STATUSES}
        for row in rows:
            if row["status"] in counts:
                counts[row["status"]] += 1
        with self._connect() as connection:
            user_counts = {"donor": 0, "ngo": 0, "admin": 0}
            user_counts.update(
                {
                    row["role"]: row["count"]
                    for row in connection.execute(
                        """
                        SELECT role, COUNT(*) AS count FROM user_profiles
                        WHERE status = 'active' GROUP BY role
                        """
                    ).fetchall()
                }
            )
        return _analytics_payload(
            counts, rows, user_counts, rate_records
        )


class DynamoDBDonationRepository:
    def __init__(self, table, max_admin_items: int = MAX_ADMIN_EXPORT):
        self.table = table
        self.max_admin_items = max_admin_items
        self._serializer = TypeSerializer()

    def initialize(self) -> None:
        return None

    @staticmethod
    def _public_item(item: dict) -> dict:
        return {
            key: value
            for key, value in item.items()
            if key not in {
                "status_pk",
                "status_sk",
                "donor_pk",
                "donor_sk",
                "recipient_pk",
                "recipient_sk",
                "entity_pk",
                "entity_sk",
                "deadline_sk",
            }
        }

    def _ddb_item(self, item: dict) -> dict:
        return {
            key: self._serializer.serialize(value)
            for key, value in item.items()
        }

    def _ddb_values(self, values: dict) -> dict:
        return {
            key: self._serializer.serialize(value)
            for key, value in values.items()
        }

    def _transact_write(self, transactions: list[dict]) -> None:
        self.table.meta.client.transact_write_items(
            TransactItems=transactions,
            ReturnConsumedCapacity="NONE",
        )

    @staticmethod
    def _conditional_transaction_failure(error: ClientError) -> bool:
        code = error.response.get("Error", {}).get("Code")
        if code == "ConditionalCheckFailedException":
            return True
        if code != "TransactionCanceledException":
            return False
        cancellation_reasons = error.response.get("CancellationReasons", [])
        return any(reason.get("Code") == "ConditionalCheckFailed" for reason in cancellation_reasons)

    def _event_item(
        self,
        entity_type: str,
        entity_id: str,
        event_type: str,
        actor_id: str,
        before_status: str | None,
        after_status: str | None,
        metadata: dict,
    ) -> dict:
        event_id = str(uuid.uuid4())
        occurred_at = _utc_now()
        return {
            "id": f"event#{event_id}",
            "entity_type": entity_type,
            "entity_id": entity_id,
            "event_type": event_type,
            "actor_id": actor_id,
            "occurred_at": occurred_at,
            "before_status": before_status,
            "after_status": after_status,
            "metadata": metadata,
            "request_id": current_request_id(),
            "entity_pk": entity_id,
            "entity_sk": f"{occurred_at}#{event_id}",
        }

    def create(self, donation: dict) -> dict:
        donation_id = str(uuid.uuid4())
        now = _utc_now()
        record = {
            "id": donation_id,
            **donation,
            "description": donation.get("description", ""),
            "category": donation.get("category", "other"),
            "available_at": donation.get("available_at"),
            "pickup_location": donation.get("pickup_location", ""),
            "updated_at": donation.get("updated_at", donation["created_at"]),
            "claimed_at": donation.get("claimed_at"),
            "completed_at": donation.get("completed_at"),
            "status_pk": donation["status"],
            "status_sk": f"{donation['created_at']}#{donation_id}",
            "deadline_sk": f"{donation['pickup_deadline']}#{donation_id}",
            "donor_pk": donation["donor_id"],
            "donor_sk": f"{donation['created_at']}#{donation_id}",
        }
        if donation.get("claimed_by"):
            record["recipient_pk"] = donation["claimed_by"]
            record["recipient_sk"] = f"{donation['created_at']}#{donation_id}"
        try:
            event = self._event_item(
                "donation",
                donation_id,
                "donation_created",
                donation["donor_id"],
                None,
                donation["status"],
                {},
            )
            self._transact_write(
                [
                    {
                        "Put": {
                            "TableName": self.table.name,
                            "Item": self._ddb_item(record),
                            "ConditionExpression": "attribute_not_exists(id)",
                        }
                    },
                    {
                        "Put": {
                            "TableName": self.table.name,
                            "Item": self._ddb_item(event),
                        }
                    },
                ]
            )
        except ClientError:
            raise
        return self._public_item(record)

    def get(self, donation_id: str) -> dict | None:
        result = self.table.get_item(Key={"id": donation_id}, ConsistentRead=True)
        item = result.get("Item")
        return self._public_item(item) if item else None

    def update_donation(
        self, donation_id: str, fields: dict, actor_id: str, role: str
    ) -> dict:
        existing = self.get(donation_id)
        if existing is None:
            raise DonationNotFound
        if role != "donor" or existing.get("donor_id") != actor_id:
            raise DonationForbidden
        if existing.get("status") != "available":
            raise DonationConflict
        names = {
            "food_name": "#food_name",
            "description": "#description",
            "category": "#category",
            "quantity": "#quantity",
            "unit": "#unit",
            "available_at": "#available_at",
            "pickup_deadline": "#pickup_deadline",
            "pickup_location": "#pickup_location",
            "updated_at": "#updated_at",
        }
        now = _utc_now()
        values = {f":{key}": value for key, value in fields.items()}
        values[":updated_at"] = now
        values[":deadline_sort"] = f"{fields['pickup_deadline']}#{donation_id}"
        update_expression = "SET " + ", ".join(
            f"{names[key]} = :{key}" for key in fields
        ) + ", #updated_at = :updated_at, deadline_sk = :deadline_sort"
        event = self._event_item(
            "donation",
            donation_id,
            "donation_updated",
            actor_id,
            "available",
            "available",
            {"changed_fields": sorted(fields)},
        )
        try:
            self._transact_write(
                [
                    {
                        "Update": {
                            "TableName": self.table.name,
                            "Key": self._ddb_item({"id": donation_id}),
                            "UpdateExpression": update_expression,
                            "ConditionExpression": (
                                "attribute_exists(id) AND #status = :available AND donor_id = :actor"
                            ),
                            "ExpressionAttributeNames": {
                                **{value: key for key, value in names.items()},
                                "#status": "status",
                            },
                            "ExpressionAttributeValues": self._ddb_values(
                                {
                                    **values,
                                    ":available": "available",
                                    ":actor": actor_id,
                                }
                            ),
                        }
                    },
                    {
                        "Put": {
                            "TableName": self.table.name,
                            "Item": self._ddb_item(event),
                        }
                    },
                ]
            )
        except ClientError as error:
            if self._conditional_transaction_failure(error):
                raise DonationConflict from error
            raise
        updated = {**existing, **fields, "updated_at": now}
        return self._public_item(updated)

    def list_status(
        self, status: str, limit: int, cursor: str | None = None
    ) -> tuple[list[dict], str | None]:
        kwargs = {
            "IndexName": "status-index",
            "KeyConditionExpression": Key("status_pk").eq(status),
            "Limit": limit,
            "ScanIndexForward": False,
        }
        start_key = _decode_cursor(cursor)
        if start_key:
            kwargs["ExclusiveStartKey"] = start_key
        result = self.table.query(**kwargs)
        items = [self._public_item(item) for item in result.get("Items", [])]
        return items, _encode_cursor(result.get("LastEvaluatedKey"))

    def list_events(
        self, entity_type: str, entity_id: str, limit: int = 50, cursor: str | None = None
    ) -> tuple[list[dict], str | None]:
        kwargs = {
            "IndexName": "entity-index",
            "KeyConditionExpression": Key("entity_pk").eq(entity_id),
            "Limit": limit,
            "ScanIndexForward": False,
        }
        start_key = _decode_cursor(cursor)
        if start_key:
            kwargs["ExclusiveStartKey"] = start_key
        result = self.table.query(**kwargs)
        events = [
            self._public_item(item)
            for item in result.get("Items", [])
            if item.get("entity_type") == entity_type
        ]
        return events, _encode_cursor(result.get("LastEvaluatedKey"))

    def list_by_donor(
        self, donor_id: str, limit: int, cursor: str | None = None
    ) -> tuple[list[dict], str | None]:
        kwargs = {
            "IndexName": "donor-index",
            "KeyConditionExpression": Key("donor_pk").eq(donor_id),
            "Limit": limit,
            "ScanIndexForward": False,
        }
        start_key = _decode_cursor(cursor)
        if start_key:
            kwargs["ExclusiveStartKey"] = start_key
        result = self.table.query(**kwargs)
        items = [self._public_item(item) for item in result.get("Items", [])]
        return items, _encode_cursor(result.get("LastEvaluatedKey"))

    def list_by_claimant(
        self, claimant_id: str, limit: int, cursor: str | None = None
    ) -> tuple[list[dict], str | None]:
        kwargs = {
            "IndexName": "recipient-index",
            "KeyConditionExpression": Key("recipient_pk").eq(claimant_id),
            "Limit": limit,
            "ScanIndexForward": False,
        }
        start_key = _decode_cursor(cursor)
        if start_key:
            kwargs["ExclusiveStartKey"] = start_key
        result = self.table.query(**kwargs)
        items = [self._public_item(item) for item in result.get("Items", [])]
        return items, _encode_cursor(result.get("LastEvaluatedKey"))

    def _query_all_status(self, status: str) -> list[dict]:
        records = []
        cursor = None
        while len(records) < self.max_admin_items:
            page_size = min(100, self.max_admin_items - len(records))
            page, cursor = self.list_status(status, page_size, cursor)
            records.extend(page)
            if not cursor:
                return records
        if cursor:
            raise RuntimeError(
                f"Administrator query exceeded the configured {self.max_admin_items}-record bound"
            )
        return records

    def list_all(self) -> list[dict]:
        donations = []
        for status in STATUSES:
            donations.extend(self._query_all_status(status))
            if len(donations) > self.max_admin_items:
                raise RuntimeError(
                    f"Administrator query exceeded the configured {self.max_admin_items}-record bound"
                )
        return sorted(
            donations,
            key=lambda item: (item["created_at"], item["id"]),
            reverse=True,
        )

    def claim(self, donation_id: str, ngo_id: str) -> dict:
        now = _utc_now()
        event = self._event_item(
            "donation", donation_id, "donation_claimed", ngo_id, "available", "claimed", {}
        )
        try:
            self._transact_write(
                [
                    {
                        "Update": {
                            "TableName": self.table.name,
                            "Key": self._ddb_item({"id": donation_id}),
                            "UpdateExpression": (
                                "SET #status = :claimed, status_pk = :claimed, "
                                "claimed_by = :ngo, recipient_pk = :ngo, "
                                "recipient_sk = :recipient_sort, claimed_at = :now, "
                                "updated_at = :now"
                            ),
                            "ConditionExpression": (
                                "attribute_exists(id) AND #status = :available "
                                "AND pickup_deadline > :now"
                            ),
                            "ExpressionAttributeNames": {"#status": "status"},
                            "ExpressionAttributeValues": self._ddb_values(
                                {
                                    ":claimed": "claimed",
                                    ":available": "available",
                                    ":ngo": ngo_id,
                                    ":now": now,
                                    ":recipient_sort": f"{now}#{donation_id}",
                                }
                            ),
                        }
                    },
                    {
                        "Put": {
                            "TableName": self.table.name,
                            "Item": self._ddb_item(event),
                        }
                    },
                ]
            )
        except ClientError as error:
            if not self._conditional_transaction_failure(error):
                raise
            existing = self.get(donation_id)
            if existing is None:
                raise DonationNotFound from error
            if (
                existing
                and existing.get("status") == "available"
                and existing.get("pickup_deadline", "") <= now
            ):
                self._expire_one(donation_id, now)
            raise DonationConflict from error
        existing = self.get(donation_id)
        if existing is None:
            raise RuntimeError("Donation disappeared after a successful claim transaction")
        return existing

    def _list_due(
        self, cutoff: str, limit: int, cursor: str | None = None
    ) -> tuple[list[dict], str | None]:
        kwargs = {
            "IndexName": "expiry-index",
            "KeyConditionExpression": (
                Key("status_pk").eq("available")
                & Key("deadline_sk").lte(f"{cutoff}#~")
            ),
            "Limit": limit,
            "ScanIndexForward": True,
        }
        start_key = _decode_cursor(cursor)
        if start_key:
            kwargs["ExclusiveStartKey"] = start_key
        result = self.table.query(**kwargs)
        items = [self._public_item(item) for item in result.get("Items", [])]
        return items, _encode_cursor(result.get("LastEvaluatedKey"))

    def _expire_one(self, donation_id: str, cutoff: str) -> bool:
        event = self._event_item(
            "donation",
            donation_id,
            "donation_expired",
            "system:expiry",
            "available",
            "expired",
            {"reason": "pickup_deadline_passed"},
        )
        try:
            self._transact_write(
                [
                    {
                        "Update": {
                            "TableName": self.table.name,
                            "Key": self._ddb_item({"id": donation_id}),
                            "UpdateExpression": (
                                "SET #status = :expired, status_pk = :expired, updated_at = :now"
                            ),
                            "ConditionExpression": (
                                "attribute_exists(id) AND #status = :available "
                                "AND pickup_deadline <= :now"
                            ),
                            "ExpressionAttributeNames": {"#status": "status"},
                            "ExpressionAttributeValues": self._ddb_values(
                                {
                                    ":expired": "expired",
                                    ":available": "available",
                                    ":now": cutoff,
                                }
                            ),
                        }
                    },
                    {
                        "Put": {
                            "TableName": self.table.name,
                            "Item": self._ddb_item(event),
                        }
                    },
                ]
            )
        except ClientError as error:
            if self._conditional_transaction_failure(error):
                return False
            raise
        return True

    def expire_due(self, now: datetime | None = None, limit: int = 100) -> int:
        cutoff = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        expired = 0
        examined = 0
        cursor = None
        while examined < limit:
            page_limit = min(100, limit - examined)
            records, cursor = self._list_due(cutoff, page_limit, cursor)
            if not records:
                break
            for record in records:
                examined += 1
                if self._expire_one(record["id"], cutoff):
                    expired += 1
                if examined >= limit:
                    break
            if not cursor:
                break
        return expired

    def transition(
        self, donation_id: str, status: str, actor_id: str, role: str
    ) -> dict:
        existing = self.get(donation_id)
        if existing is None:
            raise DonationNotFound
        expected_status = "available" if status == "cancelled" else "claimed"
        if role == "donor" and status == "cancelled":
            owner_attribute = "donor_id"
        elif role == "ngo" and status == "picked_up":
            owner_attribute = "claimed_by"
        elif role == "admin":
            owner_attribute = None
        else:
            raise DonationForbidden
        if owner_attribute and existing.get(owner_attribute) != actor_id:
            raise DonationForbidden
        if existing["status"] != expected_status:
            raise DonationConflict
        condition = "attribute_exists(id) AND #status = :expected_status"
        now = _utc_now()
        values = {":new_status": status, ":expected_status": expected_status, ":now": now}
        if owner_attribute:
            condition += f" AND {owner_attribute} = :actor"
            values[":actor"] = actor_id
        update_expression = (
            "SET #status = :new_status, status_pk = :new_status, updated_at = :now"
            + (", completed_at = :now" if status == "picked_up" else "")
        )
        event = self._event_item(
            "donation",
            donation_id,
            "donation_completed" if status == "picked_up" else "donation_cancelled",
            actor_id,
            expected_status,
            status,
            {},
        )
        try:
            self._transact_write(
                [
                    {
                        "Update": {
                            "TableName": self.table.name,
                            "Key": self._ddb_item({"id": donation_id}),
                            "UpdateExpression": update_expression,
                            "ConditionExpression": condition,
                            "ExpressionAttributeNames": {"#status": "status"},
                            "ExpressionAttributeValues": self._ddb_values(values),
                        }
                    },
                    {
                        "Put": {
                            "TableName": self.table.name,
                            "Item": self._ddb_item(event),
                        }
                    },
                ]
            )
        except ClientError as error:
            if not self._conditional_transaction_failure(error):
                raise
            raise DonationConflict from error
        updated = {**existing, "status": status, "updated_at": now}
        if status == "picked_up":
            updated["completed_at"] = now
        return self._public_item(updated)

    def analytics(self, filters: dict | None = None) -> dict:
        records = self.list_all()
        filters = filters or {}
        start = filters.get("start_date")
        end = filters.get("end_date")
        status = filters.get("status")
        category = filters.get("category")
        location = filters.get("location")
        if start:
            records = [row for row in records if row.get("created_at", "")[:10] >= start]
        if end:
            records = [row for row in records if row.get("created_at", "")[:10] <= end]
        if category:
            records = [row for row in records if row.get("category", "other") == category]
        if location:
            records = [
                row for row in records
                if location.casefold() in row.get("pickup_location", "").casefold()
            ]
        rate_records = records
        if status:
            records = [row for row in records if row.get("status") == status]
        return _analytics_payload(
            {status: sum(row["status"] == status for row in records) for status in STATUSES},
            records,
            None,
            rate_records,
        )


def _analytics_payload(
    counts: dict[str, int],
    records: list[dict],
    user_counts: dict[str, int] | None,
    rate_records: list[dict] | None = None,
) -> dict:
    total = len(records)
    cohort = records if rate_records is None else rate_records
    rate_counts = {status: 0 for status in STATUSES}
    for row in cohort:
        if row.get("status") in rate_counts:
            rate_counts[row["status"]] += 1
    terminal_count = (
        rate_counts["picked_up"] + rate_counts["cancelled"] + rate_counts["expired"]
    )
    completed_quantity_by_unit: dict[str, float] = {}
    daily_donations: dict[str, int] = {}
    daily_completed_quantity: dict[str, dict[str, float]] = {}
    daily_completed_pickups: dict[str, int] = {}
    daily_status_counts: dict[str, dict[str, int]] = {}
    category_counts: dict[str, int] = {}
    quantities_by_status_and_unit: dict[str, dict[str, float]] = {
        status: {} for status in STATUSES
    }
    claim_durations: list[float] = []
    for row in records:
        created_at = row.get("created_at", "")[:10]
        category = row.get("category", "other")
        category_counts[category] = category_counts.get(category, 0) + 1
        status = row.get("status")
        if created_at and status in STATUSES:
            status_counts = daily_status_counts.setdefault(created_at, {})
            status_counts[status] = status_counts.get(status, 0) + 1
        unit = row.get("unit", "unknown")
        if status in STATUSES:
            status_quantities = quantities_by_status_and_unit[status]
            status_quantities[unit] = (
                status_quantities.get(unit, 0.0) + float(row.get("quantity", 0))
            )
        if created_at:
            daily_donations[created_at] = daily_donations.get(created_at, 0) + 1
        if row.get("status") == "picked_up":
            completed_quantity_by_unit[unit] = (
                completed_quantity_by_unit.get(unit, 0.0) + float(row["quantity"])
            )
            if created_at:
                daily_completed_pickups[created_at] = (
                    daily_completed_pickups.get(created_at, 0) + 1
                )
                daily_completed_quantity.setdefault(created_at, {})
                daily_completed_quantity[created_at][unit] = (
                    daily_completed_quantity[created_at].get(unit, 0.0)
                    + float(row["quantity"])
                )
        claimed_at = row.get("claimed_at")
        if claimed_at:
            try:
                created = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
                claimed = datetime.fromisoformat(claimed_at.replace("Z", "+00:00"))
                if (
                    created.tzinfo is not None
                    and claimed.tzinfo is not None
                    and claimed >= created
                ):
                    claim_durations.append((claimed - created).total_seconds())
            except (TypeError, ValueError):
                continue
    available_count = sum(
        row.get("status") == "available"
        and row.get("pickup_deadline", "") > _utc_now()
        for row in records
    )
    rates = {
        "claim_rate": (
            (rate_counts["claimed"] + rate_counts["picked_up"]) / len(cohort)
            if cohort else 0.0
        ),
        "completion_rate": (
            rate_counts["picked_up"] / len(cohort) if cohort else 0.0
        ),
        "expiry_rate": (
            rate_counts["expired"] / terminal_count if terminal_count else 0.0
        ),
    }
    return {
        "total_donations": total,
        "completed_pickups": counts["picked_up"],
        "available_donations": available_count,
        "claimed_donations": counts["claimed"],
        "cancelled_donations": counts["cancelled"],
        "expired_donations": counts["expired"],
        "donors_registered": user_counts.get("donor") if user_counts is not None else None,
        "recipients_registered": user_counts.get("ngo") if user_counts is not None else None,
        "active_users": sum(user_counts.values()) if user_counts is not None else None,
        "claim_success_rate": rates["claim_rate"],
        "completion_rate": rates["completion_rate"],
        "expiry_rate": rates["expiry_rate"],
        "average_time_to_claim_seconds": (
            sum(claim_durations) / len(claim_durations) if claim_durations else None
        ),
        "quantities_by_status_and_unit": quantities_by_status_and_unit,
        "completed_quantity_by_unit": completed_quantity_by_unit,
        "category_counts": dict(sorted(category_counts.items())),
        "daily_donations": dict(sorted(daily_donations.items())),
        "daily_completed_pickups": dict(sorted(daily_completed_pickups.items())),
        "daily_completed_quantity_by_unit": dict(sorted(daily_completed_quantity.items())),
        "daily_status_counts": dict(sorted(daily_status_counts.items())),
        "last_updated": _utc_now(),
        "data_source": "local_live" if user_counts is not None else "cloud_live",
    }


def get_dynamodb_repository(table_name: str | None = None) -> DynamoDBDonationRepository:
    import os

    from boto3 import resource

    configured_table = table_name or os.environ.get("DONATIONS_TABLE")
    if not configured_table:
        raise RuntimeError("DONATIONS_TABLE must be configured for DynamoDB storage")
    return DynamoDBDonationRepository(resource("dynamodb").Table(configured_table))
