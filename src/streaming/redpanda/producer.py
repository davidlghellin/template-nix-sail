"""Producer: Send numbers to Redpanda topic."""

import json
import logging
import sys

import colorlog
from kafka import KafkaProducer
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
    """Send numbers to Redpanda."""
    logger.info("Connecting to Redpanda at %s...", BOOTSTRAP_SERVERS)

    try:
        producer = KafkaProducer(
            bootstrap_servers=BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )
    except NoBrokersAvailable:
        logger.error("Cannot connect to Redpanda. Start it first with: rpk container start")
        sys.exit(1)

    logger.info("Connected! Topic: %s", TOPIC)
    logger.info("Type numbers and press Enter to send. Type 'quit' to exit.")
    logger.info("-" * 50)

    total_sent = 0
    try:
        while True:
            user_input = input("Enter number: ").strip()

            if user_input.lower() == "quit":
                break

            try:
                number = float(user_input)
                message = {"value": number}
                producer.send(TOPIC, message)
                producer.flush()
                total_sent += 1
                logger.info("Sent: %s (total: %d messages)", number, total_sent)
            except ValueError:
                logger.warning("Invalid number: %s", user_input)

    except KeyboardInterrupt:
        logger.info("Interrupted")

    producer.close()
    logger.info("Done! Sent %d messages total.", total_sent)


if __name__ == "__main__":
    main()
