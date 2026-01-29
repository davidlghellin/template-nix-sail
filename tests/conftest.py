import pytest
from pyspark.sql import SparkSession


# === PySpark puro (requiere Java) ===
@pytest.fixture(scope="session")
def spark():
    """Sesión de Spark local (requiere Java instalado)."""
    spark = (
        SparkSession.builder
        .master("local[1]")
        .appName("test-sail")
        .getOrCreate()
    )
    yield spark
    spark.stop()


# === PySail (no requiere Java) ===
@pytest.fixture(scope="session")
def sail_server():
    """Servidor de Spark Connect con Sail como backend."""
    from pysail.spark import SparkConnectServer
    server = SparkConnectServer()
    server.start(background=True)
    yield server
    server.stop()


@pytest.fixture(scope="session")
def spark_sail(sail_server):
    """Sesión de Spark conectada al servidor de Sail."""
    ip, port = sail_server.listening_address
    spark = (
        SparkSession.builder
        .remote(f"sc://{ip}:{port}")
        .getOrCreate()
    )
    yield spark
    spark.stop()
