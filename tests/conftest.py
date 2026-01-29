import pytest
from pysail.spark import SparkConnectServer
from pyspark.sql import SparkSession


@pytest.fixture(scope="session")
def sail_server():
    """Inicia el servidor de Spark Connect con Sail como backend."""
    server = SparkConnectServer()
    server.start(background=True)
    yield server
    server.stop()


@pytest.fixture(scope="session")
def spark(sail_server):
    """Crea una sesión de Spark conectada al servidor de Sail."""
    ip, port = sail_server.listening_address
    spark = (
        SparkSession.builder
        .remote(f"sc://{ip}:{port}")
        .getOrCreate()
    )
    yield spark
    spark.stop()
