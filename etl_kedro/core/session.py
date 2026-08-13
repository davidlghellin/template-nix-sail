"""Creacion de la sesion de Spark y validacion del entorno que la ejecuta.

Aqui no hay nada de ningun dato concreto: solo que motor se usa y si la maquina
puede levantarlo.
"""

import logging
import os
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from pyspark.sql import SparkSession

logger = logging.getLogger(__name__)

APP_NAME = "etl-csv"

VALID_BACKENDS = ("pysail", "pyspark")
DEFAULT_BACKEND = "pysail"


class BackendError(RuntimeError):
    """El backend pedido no existe o el entorno no puede ejecutarlo."""


def resolve_backend(backend: str | None = None) -> str:
    """Devuelve el backend a usar, validado.

    Sin argumento lee `SPARK_BACKEND`. Un valor desconocido es un error y no un
    silencioso "pues pysail": si te equivocas al escribir `pyspark` quieres
    enterarte, no creer que has probado la JVM cuando has corrido en Sail.
    """
    value = backend if backend is not None else os.environ.get("SPARK_BACKEND", DEFAULT_BACKEND)
    if value not in VALID_BACKENDS:
        raise BackendError(
            f"SPARK_BACKEND invalido: {value!r}. Validos: {', '.join(VALID_BACKENDS)}"
        )
    return value


def check_java_available() -> None:
    """Comprueba que hay una JVM para el backend `pyspark`.

    PySpark mira `JAVA_HOME` antes que el `PATH`, asi que se comprueban en ese
    mismo orden. Sin esto el fallo llega mas tarde como `JAVA_GATEWAY_EXITED`,
    que no dice que lo que falta es Java.
    """
    java_home = os.environ.get("JAVA_HOME")
    if java_home and (Path(java_home) / "bin" / "java").is_file():
        return
    if shutil.which("java"):
        return
    raise BackendError(
        "El backend 'pyspark' necesita Java y no se ha encontrado ninguno "
        "(ni JAVA_HOME ni 'java' en el PATH). Usa el shell por defecto "
        "(`nix develop`, que trae JDK 17) o cambia a SPARK_BACKEND=pysail."
    )


@contextmanager
def spark_session(app_name: str = APP_NAME) -> Iterator[SparkSession]:
    """Sesion de Spark segun `SPARK_BACKEND` (pysail por defecto, como los tests).

    Con `pyspark` se levanta una sesion local (requiere Java); con `pysail` se
    arranca un servidor Spark Connect en background y se conecta por `sc://`.
    """
    backend = resolve_backend()
    logger.info("Iniciando sesion de Spark (backend=%s)", backend)

    if backend == "pyspark":
        check_java_available()
        spark = SparkSession.builder.master("local[*]").appName(app_name).getOrCreate()
        try:
            yield spark
        finally:
            spark.stop()
        return

    from pysail.spark import SparkConnectServer

    server = SparkConnectServer()
    server.start(background=True)
    ip, port = server.listening_address
    spark = SparkSession.builder.remote(f"sc://{ip}:{port}").getOrCreate()
    try:
        yield spark
    finally:
        spark.stop()
        server.stop()
