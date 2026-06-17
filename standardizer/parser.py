"""Debezium envelope → argus_audit.audit_event normalized dict.

Pure functions, no I/O — testable offline without Kafka or DB.
"""
import json
import uuid
from datetime import datetime, timezone

_OP_MAP = {
    "c": "INSERT",
    "u": "UPDATE",
    "d": "DELETE",
    "r": "SNAPSHOT",
    "t": "TRUNCATE",
}


def topic_to_capture_method(topic: str) -> str:
    return "mssql_cdc" if ".mssql" in topic else "pg_logical"


def _utc_ms(ms: int | None) -> datetime | None:
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)


def _lsn(source: dict, capture_method: str) -> str | None:
    if capture_method == "pg_logical":
        lsn = source.get("lsn")
        return str(lsn) if lsn is not None else None
    # mssql_cdc: commit_lsn is the stable ordering LSN
    return source.get("commit_lsn") or source.get("change_lsn")


def _changed_columns(before: dict | None, after: dict | None) -> list[str] | None:
    if not before or not after:
        return None
    cols = [k for k in after if k in before and before[k] != after[k]]
    return cols or None


def parse_envelope(
    raw_key: bytes | None,
    raw_value: bytes | None,
    topic: str,
    node_id: int,
) -> dict | None:
    """Parse a Debezium Kafka message into an audit_event row dict.

    Returns None for tombstones or non-DML messages (schema-change topics).
    """
    if raw_value is None:
        return None  # tombstone

    try:
        value = json.loads(raw_value)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None

    payload = value.get("payload") or value
    op_raw = payload.get("op")
    operation = _OP_MAP.get(op_raw)
    if not operation:
        return None

    source = payload.get("source") or {}
    before: dict | None = payload.get("before")
    after: dict | None = payload.get("after")
    capture_method = topic_to_capture_method(topic)

    # Row PK from Kafka message key (preferred) or fallback heuristic
    row_pk: dict = {}
    if raw_key:
        try:
            key_doc = json.loads(raw_key)
            row_pk = key_doc.get("payload") or key_doc or {}
        except (json.JSONDecodeError, AttributeError):
            pass

    committed_at = _utc_ms(payload.get("ts_ms")) or datetime.now(tz=timezone.utc)

    return {
        "event_id": str(uuid.uuid4()),
        "node_id": node_id,
        "source_database": source.get("db", ""),
        "source_schema": source.get("schema", ""),
        "source_table": source.get("table", ""),
        "operation": operation,
        "row_pk": json.dumps(row_pk),
        "old_values": json.dumps(before) if before is not None else None,
        "new_values": json.dumps(after) if after is not None else None,
        "changed_columns": _changed_columns(before, after),
        "db_user": source.get("user"),
        "app_user": None,
        "client_host": None,
        "application_name": source.get("application_name"),
        "tx_id": str(source.get("txId") or source.get("transaction_id") or ""),
        "source_lsn": _lsn(source, capture_method),
        "source_ts_utc": _utc_ms(source.get("ts_ms")),
        "committed_at": committed_at,
        "capture_method": capture_method,
        "source_offset": json.dumps({"topic": topic}),
        "raw_payload": raw_value.decode("utf-8", errors="replace"),
    }
