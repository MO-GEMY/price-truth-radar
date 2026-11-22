"""Unit tests for deadlock-safe Neon upserts in `data_platform.ingestion.scrapers.base`."""

from __future__ import annotations

import unittest
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

import psycopg2
from psycopg2 import errors as pg_errors

from data_platform.ingestion.scrapers import base


def _make_snapshot(store: str, ext_id: str, snap_date: date) -> base.RawProductSnapshot:
    return base.RawProductSnapshot(
        store_name=store,
        external_id=ext_id,
        category="electronics",
        sub_category="laptops",
        brand="Lenovo",
        product_title=f"Sample Product {ext_id}",
        product_url=f"https://example.com/{store}/{ext_id}",
        image_url=f"https://example.com/{store}/{ext_id}.jpg",
        attributes_json={},
        current_price=Decimal("10000.00"),
        claimed_original_price=None,
        in_stock=True,
        snapshot_date=snap_date,
        scraped_at=datetime(2026, 11, 22, 3, 0, 0),
    )


class TestUpsertSnapshotsToNeon(unittest.TestCase):
    def _build_mock_conn(self) -> tuple[MagicMock, MagicMock]:
        conn = MagicMock()
        cur = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cur
        return conn, cur

    @patch.dict("os.environ", {"DATABASE_URL_ADMIN": "postgresql://mock/db"})
    @patch.object(base, "time")
    @patch.object(base, "execute_values")
    @patch.object(base.psycopg2, "connect")
    def test_deterministic_sorting_and_advisory_lock_before_upsert(
        self,
        mock_connect: MagicMock,
        mock_execute_values: MagicMock,
        mock_time: MagicMock,
    ) -> None:
        conn, cur = self._build_mock_conn()
        mock_connect.return_value = conn

        # Intentionally unsorted across store_name, external_id, snapshot_date
        snapshots = [
            _make_snapshot("sigma", "SKU-200", date(2026, 11, 22)),
            _make_snapshot("btech", "SKU-010", date(2026, 11, 22)),
            _make_snapshot("sigma", "SKU-100", date(2026, 11, 21)),
            _make_snapshot("sigma", "SKU-100", date(2026, 11, 20)),
        ]

        count = base.upsert_snapshots_to_neon(snapshots)

        self.assertEqual(count, 4)
        self.assertEqual(
            cur.execute.call_args_list[0].args[0],
            "SELECT pg_advisory_xact_lock(hashtext('raw_product_snapshots_upsert'))",
        )
        self.assertEqual(cur.execute.call_args_list[1].args[0], base.DDL_SQL)

        passed_rows = mock_execute_values.call_args.args[2]
        passed_keys = [(r[0], r[1], r[13]) for r in passed_rows]
        self.assertEqual(
            passed_keys,
            [
                ("btech", "SKU-010", date(2026, 11, 22)),
                ("sigma", "SKU-100", date(2026, 11, 20)),
                ("sigma", "SKU-100", date(2026, 11, 21)),
                ("sigma", "SKU-200", date(2026, 11, 22)),
            ],
        )
        conn.commit.assert_called_once()
        conn.rollback.assert_not_called()
        conn.close.assert_called_once()
        mock_time.sleep.assert_not_called()

    @patch.dict("os.environ", {"DATABASE_URL_ADMIN": "postgresql://mock/db"})
    @patch.object(base, "time")
    @patch.object(base, "execute_values")
    @patch.object(base.psycopg2, "connect")
    def test_retries_transient_deadlock_and_succeeds_on_attempt_2(
        self,
        mock_connect: MagicMock,
        mock_execute_values: MagicMock,
        mock_time: MagicMock,
    ) -> None:
        conn, cur = self._build_mock_conn()
        mock_connect.return_value = conn

        # Fail attempt 1 with DeadlockDetected, succeed on attempt 2
        mock_execute_values.side_effect = [
            pg_errors.DeadlockDetected("deadlock detected"),
            None,
        ]

        snapshots = [_make_snapshot("rayashop", "SKU-1", date(2026, 11, 22))]
        with self.assertLogs(base.logger, level="WARNING") as logs:
            count = base.upsert_snapshots_to_neon(snapshots)

        self.assertEqual(count, 1)
        self.assertEqual(mock_execute_values.call_count, 2)
        conn.rollback.assert_called_once()
        conn.commit.assert_called_once()
        conn.close.assert_called_once()

        # Verify advisory lock was acquired on BOTH attempts
        lock_calls = [
            c.args[0]
            for c in cur.execute.call_args_list
            if "pg_advisory_xact_lock" in c.args[0]
        ]
        self.assertEqual(len(lock_calls), 2)

        # Backoff on attempt 1: 0.5 * (2 ** 1) + uniform(0.1, 0.6) => [1.1, 1.6]
        mock_time.sleep.assert_called_once()
        slept = mock_time.sleep.call_args.args[0]
        self.assertGreaterEqual(slept, 1.1)
        self.assertLessEqual(slept, 1.6)
        self.assertTrue(any("DeadlockDetected" in msg for msg in logs.output))

    @patch.dict("os.environ", {"DATABASE_URL_ADMIN": "postgresql://mock/db"})
    @patch.object(base, "time")
    @patch.object(base, "execute_values")
    @patch.object(base.psycopg2, "connect")
    def test_retries_serialization_failure_and_exhausts_after_5_attempts(
        self,
        mock_connect: MagicMock,
        mock_execute_values: MagicMock,
        mock_time: MagicMock,
    ) -> None:
        conn, _ = self._build_mock_conn()
        mock_connect.return_value = conn
        mock_execute_values.side_effect = pg_errors.SerializationFailure("could not serialize")

        snapshots = [_make_snapshot("seoudi", "SKU-9", date(2026, 11, 22))]
        with self.assertRaises(pg_errors.SerializationFailure):
            base.upsert_snapshots_to_neon(snapshots)

        self.assertEqual(mock_execute_values.call_count, 5)
        self.assertEqual(conn.rollback.call_count, 5)
        self.assertEqual(mock_time.sleep.call_count, 4)
        conn.commit.assert_not_called()
        conn.close.assert_called_once()

    @patch.dict("os.environ", {"DATABASE_URL_ADMIN": "postgresql://mock/db"})
    @patch.object(base, "time")
    @patch.object(base, "execute_values")
    @patch.object(base.psycopg2, "connect")
    def test_non_retryable_db_error_fails_immediately(
        self,
        mock_connect: MagicMock,
        mock_execute_values: MagicMock,
        mock_time: MagicMock,
    ) -> None:
        conn, _ = self._build_mock_conn()
        mock_connect.return_value = conn
        mock_execute_values.side_effect = psycopg2.DataError("invalid input syntax")

        snapshots = [_make_snapshot("raneen", "SKU-5", date(2026, 11, 22))]
        with self.assertRaises(psycopg2.DataError):
            base.upsert_snapshots_to_neon(snapshots)

        self.assertEqual(mock_execute_values.call_count, 1)
        conn.rollback.assert_called_once()
        mock_time.sleep.assert_not_called()
        conn.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
