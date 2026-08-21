import os
import sys
import threading
import time

import pytest
from pyspark.sql import SparkSession

VALID_BACKENDS = ("pysail", "pyspark")
DEFAULT_BACKEND = "pysail"


def get_spark_backend():
    """Determine which backend to use based on environment variable."""
    return os.environ.get("SPARK_BACKEND", DEFAULT_BACKEND)


def pytest_configure(config):
    """Reject an unknown SPARK_BACKEND before any test runs.

    Falling back to PySail on a typo is the worst outcome: the suite goes green
    and the header claims a backend that never ran.
    """
    backend = get_spark_backend()
    if backend not in VALID_BACKENDS:
        raise pytest.UsageError(
            f"SPARK_BACKEND invalido: {backend!r}. Validos: {', '.join(VALID_BACKENDS)}"
        )


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

        if sys.platform == "win32":
            # Windows: usar threading en lugar de multiprocessing
            server_thread = threading.Thread(
                target=server.start,
                kwargs={"background": False},
                daemon=True,
            )
            server_thread.start()

            # Esperar a que el servidor esté listo
            for _ in range(30):
                try:
                    ip, port = server.listening_address
                    if ip and port:
                        break
                except Exception:
                    pass
                time.sleep(0.5)
            else:
                raise RuntimeError("PySail server failed to start")
        else:
            # Linux/Mac: usar background=True normal
            server.start(background=True)

        ip, port = server.listening_address
        spark = SparkSession.builder.remote(f"sc://{ip}:{port}").getOrCreate()
        yield spark
        spark.stop()
        server.stop()
