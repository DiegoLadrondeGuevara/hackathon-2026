import sys
import unittest
from pathlib import Path

from azure.core.exceptions import ResourceExistsError, ResourceModifiedError, ResourceNotFoundError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
from status_store import STATUSES, list_zones, save_newer, validate_update  # noqa: E402


class Entity(dict):
    def __init__(self, values, etag):
        super().__init__(values)
        self.metadata = {"etag": etag}


class FakeTable:
    def __init__(self):
        self.rows = {}
        self.version = 0

    def get_entity(self, partition_key, row_key):
        key = (partition_key, row_key)
        if key not in self.rows:
            raise ResourceNotFoundError("not found")
        return self.rows[key]

    def create_entity(self, entity):
        key = (entity["PartitionKey"], entity["RowKey"])
        if key in self.rows:
            raise ResourceExistsError("exists")
        self.version += 1
        self.rows[key] = Entity(entity, str(self.version))

    def update_entity(self, entity, mode, etag, match_condition):
        key = (entity["PartitionKey"], entity["RowKey"])
        if self.rows[key].metadata["etag"] != etag:
            raise ResourceModifiedError("etag mismatch")
        self.version += 1
        self.rows[key] = Entity(entity, str(self.version))

    def query_entities(self, query_filter):
        return list(self.rows.values())


def update(zone, status, timestamp, priority="P2"):
    return {
        "zone_id": zone,
        "status": status,
        "priority": None if status == "SIN_INCIDENTE" else priority,
        "updated_at": timestamp,
        "public_message": STATUSES[status],
    }


class StoreTests(unittest.TestCase):
    def test_newer_wins_and_repeated_event_is_idempotent(self):
        table = FakeTable()
        first = update("Z01", "EVALUACION", "2026-11-14T10:00:00Z")
        newer = update("Z01", "CONFIRMADO", "2026-11-14T10:05:00Z")
        self.assertTrue(save_newer(table, "Z01", first)[0])
        self.assertFalse(save_newer(table, "Z01", first)[0])
        self.assertTrue(save_newer(table, "Z01", newer)[0])
        self.assertFalse(save_newer(table, "Z01", first)[0])
        self.assertEqual(list_zones(table)[0]["status"], "CONFIRMADO")

    def test_closed_incident_becomes_no_incident(self):
        table = FakeTable()
        save_newer(table, "Z01", update("Z01", "CONFIRMADO", "2026-11-14T10:00:00Z"))
        save_newer(table, "Z01", update("Z01", "SIN_INCIDENTE", "2026-11-14T11:00:00Z"))
        self.assertEqual(list_zones(table)[0]["priority"], None)
        self.assertEqual(list_zones(table)[0]["status"], "SIN_INCIDENTE")

    def test_public_message_is_whitelisted(self):
        body = update("Z01", "CONFIRMADO", "2026-11-14T10:00:00Z")
        body["public_message"] = "Falla del cliente Juan Pérez"
        with self.assertRaisesRegex(ValueError, "public_message"):
            validate_update("Z01", body)

    def test_zone_id_and_timestamp_are_validated(self):
        body = update("Z01", "EVALUACION", "2026-11-14T10:00:00")
        with self.assertRaisesRegex(ValueError, "zona horaria"):
            validate_update("Z01", body)
        body["updated_at"] = "2026-11-14T10:00:00Z"
        with self.assertRaisesRegex(ValueError, "zone_id"):
            validate_update("Z02", body)

    def test_public_list_is_sorted_and_has_no_internal_keys(self):
        table = FakeTable()
        save_newer(table, "Z02", update("Z02", "EVALUACION", "2026-11-14T10:00:00Z"))
        save_newer(table, "Z01", update("Z01", "CONFIRMADO", "2026-11-14T10:00:00Z"))
        rows = list_zones(table)
        self.assertEqual([r["zone_id"] for r in rows], ["Z01", "Z02"])
        self.assertNotIn("PartitionKey", rows[0])
        self.assertNotIn("RowKey", rows[0])

    def test_concurrent_newer_write_is_not_overwritten(self):
        class RacingTable(FakeTable):
            race_pending = True

            def update_entity(self, entity, mode, etag, match_condition):
                if self.race_pending:
                    self.race_pending = False
                    # Another writer commits a newer event before this update.
                    self.version += 1
                    key = (entity["PartitionKey"], entity["RowKey"])
                    other = validate_update(
                        "Z01", update("Z01", "RESTABLECIDO", "2026-11-14T10:20:00Z")
                    )
                    self.rows[key] = Entity({**other, "last_synced_at": "2026-11-14T10:20:00Z"}, str(self.version))
                super().update_entity(entity, mode, etag, match_condition)

        table = RacingTable()
        save_newer(table, "Z01", update("Z01", "EVALUACION", "2026-11-14T10:00:00Z"))
        applied, _ = save_newer(table, "Z01", update("Z01", "CONFIRMADO", "2026-11-14T10:10:00Z"))
        self.assertFalse(applied)
        self.assertEqual(list_zones(table)[0]["status"], "RESTABLECIDO")


if __name__ == "__main__":
    unittest.main()
