import sqlite3

import pytest

from backend.seed_data import seed_database


def test_seed_database_is_synthetic_consistent_and_idempotent(tmp_path):
    database = tmp_path / "synthetic.db"

    assert seed_database(database) == 8
    assert seed_database(database) == 8

    connection = sqlite3.connect(database)
    try:
        donations = connection.execute(
            "SELECT id, status, donor_id, claimed_by, claimed_at, completed_at FROM donations"
        ).fetchall()
        assert len(donations) == 8
        assert {row[1] for row in donations} == {
            "available",
            "claimed",
            "picked_up",
            "cancelled",
            "expired",
        }
        for _, status, _, claimed_by, claimed_at, completed_at in donations:
            if status in {"claimed", "picked_up"}:
                assert claimed_by
                assert claimed_at
            if status == "picked_up":
                assert completed_at
            else:
                assert completed_at is None
        event_count = connection.execute(
            "SELECT COUNT(*) FROM donation_events"
        ).fetchone()[0]
        assert event_count > len(donations)
        assert connection.execute(
            "SELECT record_count FROM sharebite_seed_metadata"
        ).fetchone()[0] == 8
    finally:
        connection.close()


def test_seed_database_refuses_existing_non_seed_data_without_modifying_it(tmp_path):
    database = tmp_path / "existing.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE donations (id TEXT PRIMARY KEY)")
    connection.execute("INSERT INTO donations (id) VALUES ('preserve-me')")
    connection.commit()
    connection.close()

    with pytest.raises(ValueError, match="Refusing to seed"):
        seed_database(database)

    connection = sqlite3.connect(database)
    try:
        assert connection.execute("SELECT id FROM donations").fetchall() == [
            ("preserve-me",)
        ]
    finally:
        connection.close()
