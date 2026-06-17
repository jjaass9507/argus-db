"""parser.py 純函式單元測試 (stdlib unittest，無 Kafka/DB 相依).

    cd standardizer && python -m unittest discover -s tests
"""
import json
import sys
import os
import unittest

# Ensure the standardizer package root is on the path when running from repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from parser import parse_envelope, topic_to_capture_method


def _pg_msg(op: str, before=None, after=None, source_extra: dict | None = None) -> bytes:
    source = {
        "db": "app_db", "schema": "public", "table": "orders",
        "ts_ms": 1700000000000, "lsn": 12345678, "txId": 99,
    }
    if source_extra:
        source.update(source_extra)
    return json.dumps({"payload": {"op": op, "before": before, "after": after,
                                   "source": source, "ts_ms": 1700000001000}}).encode()


def _mssql_msg(op: str, before=None, after=None) -> bytes:
    source = {
        "db": "AppDb", "schema": "dbo", "table": "users",
        "ts_ms": 1700000000000, "commit_lsn": "00000025:00000b88:000a",
    }
    return json.dumps({"payload": {"op": op, "before": before, "after": after,
                                   "source": source, "ts_ms": 1700000001000}}).encode()


_PG_TOPIC = "argus.src.pg01.public.orders"
_MS_TOPIC = "argus.src.mssql01.AppDb.dbo.users"
_KEY = json.dumps({"payload": {"id": 42}}).encode()


class TopicCaptureMethodTest(unittest.TestCase):
    def test_pg_topic(self):
        self.assertEqual(topic_to_capture_method(_PG_TOPIC), "pg_logical")

    def test_mssql_topic(self):
        self.assertEqual(topic_to_capture_method(_MS_TOPIC), "mssql_cdc")


class ParseEnvelopeInsertTest(unittest.TestCase):
    def setUp(self):
        self.evt = parse_envelope(_KEY, _pg_msg("c", after={"id": 42, "name": "Alice"}),
                                  _PG_TOPIC, node_id=1)

    def test_not_none(self):
        self.assertIsNotNone(self.evt)

    def test_operation(self):
        self.assertEqual(self.evt["operation"], "INSERT")

    def test_capture_method(self):
        self.assertEqual(self.evt["capture_method"], "pg_logical")

    def test_new_values_set(self):
        self.assertIsNotNone(self.evt["new_values"])
        self.assertEqual(json.loads(self.evt["new_values"])["name"], "Alice")

    def test_old_values_none(self):
        self.assertIsNone(self.evt["old_values"])

    def test_row_pk_from_key(self):
        self.assertEqual(json.loads(self.evt["row_pk"]), {"id": 42})

    def test_source_fields(self):
        self.assertEqual(self.evt["source_database"], "app_db")
        self.assertEqual(self.evt["source_table"], "orders")

    def test_node_id(self):
        self.assertEqual(self.evt["node_id"], 1)


class ParseEnvelopeUpdateTest(unittest.TestCase):
    def setUp(self):
        before = {"id": 1, "status": "new", "amount": 100}
        after  = {"id": 1, "status": "paid", "amount": 100}
        self.evt = parse_envelope(None, _pg_msg("u", before=before, after=after),
                                  _PG_TOPIC, node_id=1)

    def test_operation(self):
        self.assertEqual(self.evt["operation"], "UPDATE")

    def test_changed_columns(self):
        self.assertEqual(self.evt["changed_columns"], ["status"])

    def test_both_values_present(self):
        self.assertIsNotNone(self.evt["old_values"])
        self.assertIsNotNone(self.evt["new_values"])


class ParseEnvelopeDeleteTest(unittest.TestCase):
    def setUp(self):
        self.evt = parse_envelope(None,
                                  _mssql_msg("d", before={"id": 7, "name": "Bob"}),
                                  _MS_TOPIC, node_id=2)

    def test_operation(self):
        self.assertEqual(self.evt["operation"], "DELETE")

    def test_capture_method(self):
        self.assertEqual(self.evt["capture_method"], "mssql_cdc")

    def test_old_values_set(self):
        self.assertIsNotNone(self.evt["old_values"])

    def test_new_values_none(self):
        self.assertIsNone(self.evt["new_values"])

    def test_lsn_is_commit_lsn(self):
        self.assertEqual(self.evt["source_lsn"], "00000025:00000b88:000a")


class ParseEnvelopeSkipTest(unittest.TestCase):
    def test_tombstone_returns_none(self):
        self.assertIsNone(parse_envelope(None, None, _PG_TOPIC, node_id=1))

    def test_unknown_op_returns_none(self):
        msg = json.dumps({"payload": {"op": "x", "source": {}, "ts_ms": 0}}).encode()
        self.assertIsNone(parse_envelope(None, msg, _PG_TOPIC, node_id=1))

    def test_missing_op_returns_none(self):
        msg = json.dumps({"payload": {"source": {}, "ts_ms": 0}}).encode()
        self.assertIsNone(parse_envelope(None, msg, _PG_TOPIC, node_id=1))

    def test_invalid_json_returns_none(self):
        self.assertIsNone(parse_envelope(None, b"not-json", _PG_TOPIC, node_id=1))


class ParseEnvelopeSnapshotTruncateTest(unittest.TestCase):
    def test_snapshot(self):
        evt = parse_envelope(None, _pg_msg("r", after={"id": 1}), _PG_TOPIC, node_id=1)
        self.assertEqual(evt["operation"], "SNAPSHOT")

    def test_truncate(self):
        evt = parse_envelope(None, _pg_msg("t"), _PG_TOPIC, node_id=1)
        self.assertEqual(evt["operation"], "TRUNCATE")


if __name__ == "__main__":
    unittest.main()
