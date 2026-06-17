"""Standardizer env config.

All secrets via environment / secret manager. No plaintext credentials here.
"""
import os

from dotenv import load_dotenv

load_dotenv()

KAFKA_BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP", "localhost:9092")
KAFKA_GROUP_ID = os.environ.get("KAFKA_GROUP_ID", "argus-standardizer")
# Regex pattern — subscribe to all Debezium source topics
KAFKA_TOPIC_REGEX = os.environ.get("KAFKA_TOPIC_REGEX", r"^argus\.src\..+")

# Audit store DSN — argus_writer role; password injected at runtime by secret manager
AUDIT_DB_DSN = os.environ.get(
    "AUDIT_DB_DSN", "postgresql://argus_writer:@localhost:5432/argus_audit_db"
)

# topic-prefix → managed_node.node_key mapping
# Format: "argus.src.pg01=prod-pg-01,argus.src.mssql01=prod-mssql-01"
_raw_map = os.environ.get(
    "TOPIC_PREFIX_NODE_MAP",
    "argus.src.pg01=prod-pg-01,argus.src.mssql01=prod-mssql-01",
)
TOPIC_PREFIX_NODE_MAP: dict[str, str] = {}
for _pair in _raw_map.split(","):
    if "=" in _pair:
        _prefix, _node_key = _pair.strip().split("=", 1)
        TOPIC_PREFIX_NODE_MAP[_prefix.strip()] = _node_key.strip()
