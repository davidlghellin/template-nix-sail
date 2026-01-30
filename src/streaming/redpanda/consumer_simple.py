"""Simple consumer: Read and sum numbers without Spark (pure Python)."""

import json
import logging
import sys

import colorlog
from kafka import KafkaConsumer
from kafka.errors import NoBrokersAvailable

# Logging setup
handler = colorlog.StreamHandler()
handler.setFormatter(
    colorlog.ColoredFormatter(
        "%(log_color)s%(asctime)s - %(levelname)s - %(message)s",
        log_colors={"DEBUG": "cyan", "INFO": "green", "WARNING": "yellow", "ERROR": "red"},
    )
)
logger = logging.getLogger(__name__)
logger.addHandler(handler)
logger.setLevel(logging.INFO)

TOPIC = "numbers"
BOOTSTRAP_SERVERS = "localhost:9092"


def main():
    """Read and sum numbers from Redpanda (simple version without Spark)."""
    logger.info("Connecting to Redpanda at %s...", BOOTSTRAP_SERVERS)

    try:
        consumer = KafkaConsumer(
            TOPIC,
            bootstrap_servers=BOOTSTRAP_SERVERS,
            value_deserializer=lambda m: json.loads(m.decode("utf-8")),
            auto_offset_reset="earliest",
            group_id="simple-consumer",
        )
    except NoBrokersAvailable:
        logger.error("Cannot connect to Redpanda. Start it first with: rpk container start")
        sys.exit(1)

    logger.info("Connected! Listening to topic: %s", TOPIC)
    logger.info("Waiting for numbers... (Press Ctrl+C to stop)")
    logger.info("-" * 50)

    total_sum = 0.0
    count = 0

    try:
        for message in consumer:
            value = message.value.get("value", 0)
            total_sum += value
            count += 1
            logger.info(
                "Received: %s | Running sum: %s | Count: %d",
                value,
                total_sum,
                count,
            )

    except KeyboardInterrupt:
        logger.info("Interrupted")

    consumer.close()
    logger.info("Final sum: %s (from %d numbers)", total_sum, count)


if __name__ == "__main__":
    main()
