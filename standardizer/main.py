"""Argus-DB Standardizer — Debezium → audit_event consumer.

Subscribes to all Debezium source topics (pattern: KAFKA_TOPIC_REGEX) and
idempotently writes normalized events into argus_audit.audit_event.

Usage:
    cd standardizer
    python -m venv .venv && . .venv/bin/activate
    pip install -r requirements.txt
    cp .env.example .env  # fill in real values
    python main.py
"""
import asyncio
import logging
import signal

from aiokafka import AIOKafkaConsumer

import config
import db
from parser import parse_envelope

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("standardizer")

_shutdown = asyncio.Event()


def _node_key_for_topic(topic: str, prefix_map: dict[str, str]) -> str | None:
    for prefix, node_key in prefix_map.items():
        if topic.startswith(prefix):
            return node_key
    return None


async def _consume(pool, prefix_map: dict[str, str]) -> None:
    node_id_cache: dict[str, int | None] = {}

    consumer = AIOKafkaConsumer(
        bootstrap_servers=config.KAFKA_BOOTSTRAP,
        group_id=config.KAFKA_GROUP_ID,
        auto_offset_reset="earliest",
        enable_auto_commit=False,
        value_deserializer=None,
        key_deserializer=None,
    )
    consumer.subscribe(pattern=config.KAFKA_TOPIC_REGEX)
    await consumer.start()
    logger.info("Started. Subscribed to pattern: %s", config.KAFKA_TOPIC_REGEX)

    try:
        async for msg in consumer:
            if _shutdown.is_set():
                break

            node_key = _node_key_for_topic(msg.topic, prefix_map)
            if node_key is None:
                logger.debug("No node mapping for topic %s — skipping", msg.topic)
                await consumer.commit()
                continue

            if node_key not in node_id_cache:
                node_id_cache[node_key] = await db.resolve_node_id(pool, node_key)
            node_id = node_id_cache[node_key]

            if node_id is None:
                logger.warning("node_key=%r not in managed_node — skipping", node_key)
                await consumer.commit()
                continue

            evt = parse_envelope(msg.key, msg.value, msg.topic, node_id)
            if evt is None:
                await consumer.commit()
                continue

            try:
                inserted = await db.insert_event(pool, evt)
                if not inserted:
                    logger.debug(
                        "Duplicate skipped: lsn=%s table=%s",
                        evt["source_lsn"], evt["source_table"],
                    )
            except Exception:
                # Do not commit offset — message will be redelivered
                logger.exception(
                    "DB write failed for topic=%s lsn=%s; offset not committed",
                    msg.topic, evt.get("source_lsn"),
                )
                continue

            await consumer.commit()
    finally:
        await consumer.stop()


async def main() -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _shutdown.set)

    pool = await db.create_pool(config.AUDIT_DB_DSN)
    logger.info("Connected to audit store")
    try:
        await _consume(pool, config.TOPIC_PREFIX_NODE_MAP)
    finally:
        await pool.close()
    logger.info("Standardizer stopped cleanly")


if __name__ == "__main__":
    asyncio.run(main())
