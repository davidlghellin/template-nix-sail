import os
import pytest
from pyspark.sql import SparkSession


def get_spark_backend():
    """Determina qué backend usar según variable de entorno."""
    return os.environ.get("SPARK_BACKEND", "pysail")


def pytest_report_header():
    """Muestra el backend de Spark en el header de pytest."""
    backend = get_spark_backend()
    return f"spark backend: {backend}"


@pytest.fixture(scope="session")
def spark(request):
    """Sesión de Spark. Usa SPARK_BACKEND=pyspark|pysail para elegir."""
    backend = get_spark_backend()

    if backend == "pyspark":
        # PySpark puro (requiere Java)
        spark = (
            SparkSession.builder
            .master("local[1]")
            .appName("test-sail")
            .getOrCreate()
        )
        yield spark
        spark.stop()
    else:
        # PySail (sin Java)
        from pysail.spark import SparkConnectServer
        server = SparkConnectServer()
        server.start(background=True)
        ip, port = server.listening_address

        spark = (
            SparkSession.builder
            .remote(f"sc://{ip}:{port}")
            .getOrCreate()
        )
        yield spark
        spark.stop()
        server.stop()
