"""Consumer: Read numbers from Redpanda and sum them with PySail."""

import json
import logging
import socket
import sys
import time

import colorlog
from kafka import KafkaConsumer
from kafka.errors import NoBrokersAvailable
from pyspark.sql import SparkSession

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
BATCH_INTERVAL = 2  # seconds
SAIL_HOST = "localhost"
SAIL_PORT = 50051


def is_port_open(host: str, port: int) -> bool:
    """Check if a port is open."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            s.connect((host, port))
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


def get_sail_session():
    """Get SparkSession: connect to external server or start internal one."""
    if is_port_open(SAIL_HOST, SAIL_PORT):
        logger.info("Connecting to external Sail server at %s:%s...", SAIL_HOST, SAIL_PORT)
        spark = SparkSession.builder.remote(f"sc://{SAIL_HOST}:{SAIL_PORT}").getOrCreate()
        return spark, None

    logger.info("Starting internal PySail server...")
    from pysail.spark import SparkConnectServer

    server = SparkConnectServer()
    server.start(background=True)
    ip, port = server.listening_address
    spark = SparkSession.builder.remote(f"sc://{ip}:{port}").getOrCreate()
    return spark, server


def main():
    """Read numbers from Redpanda and process with PySail."""
    spark, server = get_sail_session()
    logger.info("PySail ready!")

    logger.info("Connecting to Redpanda at %s...", BOOTSTRAP_SERVERS)
    try:
        consumer = KafkaConsumer(
            TOPIC,
            bootstrap_servers=BOOTSTRAP_SERVERS,
            value_deserializer=lambda m: json.loads(m.decode("utf-8")),
            auto_offset_reset="earliest",
            group_id="pysail-consumer",
            consumer_timeout_ms=1000,  # Non-blocking
        )
    except NoBrokersAvailable:
        logger.error("Cannot connect to Redpanda. Start it first with: rpk container start")
        spark.stop()
        if server:
            server.stop()
        sys.exit(1)

    logger.info("Connected! Listening to topic: %s", TOPIC)
    logger.info("Processing with PySail every %d seconds...", BATCH_INTERVAL)
    logger.info("Press Ctrl+C to stop")
    logger.info("-" * 50)

    all_numbers = []

    try:
        while True:
            # Collect messages for BATCH_INTERVAL seconds
            batch = []
            for message in consumer:
                value = message.value.get("value", 0)
                batch.append(value)
                all_numbers.append(value)

            if batch:
                # Process batch with PySail
                df = spark.createDataFrame([(n,) for n in all_numbers], ["value"])
                result = df.agg({"value": "sum"}).collect()[0][0]
                logger.info(
                    "Batch: %s new | Total: %d numbers | Sum: %s",
                    len(batch),
                    len(all_numbers),
                    result,
                )

            time.sleep(BATCH_INTERVAL)

    except KeyboardInterrupt:
        logger.info("Stopping...")

    consumer.close()
    spark.stop()
    if server:
        server.stop()

    if all_numbers:
        logger.info("Final sum: %s (from %d numbers)", sum(all_numbers), len(all_numbers))
    logger.info("Done!")


if __name__ == "__main__":
    main()
