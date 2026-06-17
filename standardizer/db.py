"""asyncpg audit-store writer.

Connects as argus_writer role (no plaintext creds — DSN from env/secret manager).
All writes are idempotent: duplicate LSN/table/pk rows are silently skipped via
the unique index on audit_event.
"""
import asyncpg

_INSERT = """
INSERT INTO argus_audit.audit_event (
    event_id, node_id, source_database, source_schema, source_table,
    operation, row_pk, old_values, new_values, changed_columns,
    db_user, app_user, client_host, application_name,
    tx_id, source_lsn, source_ts_utc, committed_at,
    capture_method, source_offset, raw_payload
) VALUES (
    $1::uuid, $2, $3, $4, $5,
    $6, $7::jsonb, $8::jsonb, $9::jsonb, $10,
    $11, $12, $13, $14,
    $15, $16, $17, $18,
    $19, $20::jsonb, $21::jsonb
)
ON CONFLICT DO NOTHING
"""


async def create_pool(dsn: str) -> asyncpg.Pool:
    return await asyncpg.create_pool(dsn, min_size=1, max_size=4)


async def resolve_node_id(pool: asyncpg.Pool, node_key: str) -> int | None:
    row = await pool.fetchrow(
        "SELECT id FROM argus_audit.managed_node WHERE node_key = $1", node_key
    )
    return row["id"] if row else None


async def insert_event(pool: asyncpg.Pool, evt: dict) -> bool:
    """Insert an audit event. Returns True if inserted, False if duplicate."""
    result = await pool.execute(
        _INSERT,
        evt["event_id"], evt["node_id"],
        evt["source_database"], evt["source_schema"], evt["source_table"],
        evt["operation"],
        evt["row_pk"], evt["old_values"], evt["new_values"], evt["changed_columns"],
        evt["db_user"], evt["app_user"], evt["client_host"], evt["application_name"],
        evt["tx_id"], evt["source_lsn"], evt["source_ts_utc"], evt["committed_at"],
        evt["capture_method"], evt["source_offset"], evt["raw_payload"],
    )
    return result == "INSERT 0 1"
