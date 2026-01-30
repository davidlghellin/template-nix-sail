"""Test Sail demo with PySpark and PySail."""

import logging
import os
import socket

import colorlog
from pyspark.sql import SparkSession

handler = colorlog.StreamHandler()
handler.setFormatter(
    colorlog.ColoredFormatter(
        "%(log_color)s%(asctime)s - %(levelname)s - %(message)s",
        log_colors={
            "DEBUG": "cyan",
            "INFO": "green",
            "WARNING": "yellow",
            "ERROR": "red",
            "CRITICAL": "red,bg_white",
        },
    )
)
logger = logging.getLogger(__name__)
logger.addHandler(handler)
logger.setLevel(logging.INFO)


def get_spark_backend():
    """Get configured backend (pysail by default)."""
    return os.environ.get("SPARK_BACKEND", "pysail")


def is_port_open(host: str, port: int) -> bool:
    """Check if a port is open."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            s.connect((host, port))
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


def get_spark_session():
    """Get SparkSession based on configured backend."""
    backend = get_spark_backend()

    # Traditional PySpark (requires Java)
    if backend == "pyspark":
        logger.info("Starting local PySpark (requires Java)...")
        spark = SparkSession.builder.master("local[*]").appName("test-sail").getOrCreate()
        return spark, None

    # PySail: connect to external server or start internal one
    external_host = "localhost"
    external_port = 50051

    if is_port_open(external_host, external_port):
        logger.info("Connecting to external server at %s:%s...", external_host, external_port)
        spark = SparkSession.builder.remote(f"sc://{external_host}:{external_port}").getOrCreate()
        return spark, None

    logger.info("External server unavailable, starting internal server...")
    from pysail.spark import SparkConnectServer

    server = SparkConnectServer()
    server.start(background=True)
    ip, port = server.listening_address
    spark = SparkSession.builder.remote(f"sc://{ip}:{port}").getOrCreate()
    return spark, server


def main():
    spark, server = get_spark_session()

    # Read Spanish cities CSV
    logger.info("Reading Spanish cities CSV...")
    df = spark.read.option("header", "true").option("inferSchema", "true").csv(
        "resources/ciudades_espana.csv"
    )

    logger.info("Total cities: %s", df.count())
    logger.info("DataFrame schema:")
    df.printSchema()

    logger.info("First 10 cities:")
    df.show(10)

    # Top 10 most populated cities
    logger.info("Top 10 most populated cities:")
    df.orderBy(df.habitantes.desc()).select("ciudad", "habitantes", "comunidad_autonoma").show(10)

    # Population by autonomous community
    logger.info("Population by autonomous community:")
    df_ccaa = df.groupBy("comunidad_autonoma").sum("habitantes")
    df_ccaa.orderBy("sum(habitantes)", ascending=False).show()

    # Population density example (inhabitants / area)
    logger.info("Population density (inhabitants/km2):")
    from pyspark.sql import functions as F

    df_densidad = df.select(
        "ciudad",
        "habitantes",
        "superficie_km2",
        (F.col("habitantes") / F.col("superficie_km2")).alias("densidad"),
    ).orderBy("densidad", ascending=False)
    df_densidad.show(10)

    # Cleanup
    spark.stop()
    if server:
        server.stop()

    logger.info("Done!")


if __name__ == "__main__":
    main()
