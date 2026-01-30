import os

import pytest
from pyspark.sql import SparkSession


def get_spark_backend():
    """Determine which backend to use based on environment variable."""
    return os.environ.get("SPARK_BACKEND", "pysail")


def pytest_report_header():
    """Show Spark backend in pytest header."""
    backend = get_spark_backend()
    return f"spark backend: {backend}"


@pytest.fixture(scope="session")
def spark(request):
    """Spark session. Use SPARK_BACKEND=pyspark|pysail to choose."""
    backend = get_spark_backend()

    if backend == "pyspark":
        # Pure PySpark (requires Java)
        spark = SparkSession.builder.master("local[1]").appName("test-sail").getOrCreate()
        yield spark
        spark.stop()
    else:
        # PySail (no Java)
        from pysail.spark import SparkConnectServer

        server = SparkConnectServer()
        server.start(background=True)
        ip, port = server.listening_address

        spark = SparkSession.builder.remote(f"sc://{ip}:{port}").getOrCreate()
        yield spark
        spark.stop()
        server.stop()
