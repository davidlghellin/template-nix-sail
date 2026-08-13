"""Que es un dataset: nombre, donde vive y con que forma.

El tipo esta aqui; las instancias concretas viven en cada job
(`etl_kedro/jobs/<dominio>/datasets.py`), junto al codigo que las produce. Asi el
catalogo no es un fichero global que crece sin limite, y la dependencia entre
jobs se declara con un import normal:

    from etl_kedro.jobs.ciudades.datasets import CIUDADES_DEDUP

    CONSUME = (CIUDADES_DEDUP,)

Ese import es el enlace: el IDE lo navega, mypy lo verifica y "buscar usos" te
da los consumidores de un dataset al instante, tengas 3 jobs o 300.
"""

from dataclasses import dataclass
from pathlib import Path

from pyspark.sql.types import StructType

from etl_kedro.core.config import Config

# Rutas que no se comprueban en local: las resuelve el motor, no el sistema de
# ficheros.
URI_SEPARATOR = "://"
GLOB_CHARS = ("*", "?", "[")


@dataclass(frozen=True)
class Dataset:
    """Un conjunto de datos con nombre, ubicacion y (opcionalmente) esquema.

    `ruta` es **relativa al entorno**: `Config.resolver` le antepone la raiz que
    toque (`.` en local, `s3://...` en produccion). Una ruta absoluta o un URI
    se deja intacta.

    `esquema` es el contrato: pasarlo al leer evita depender de `inferSchema`,
    que hace doble pasada y no infiere igual en Sail que en PySpark.
    """

    nombre: str
    ruta: str
    esquema: StructType | None = None
    formato: str = "csv"

    def resolver(self, config: Config | None = None) -> str:
        """Ruta concreta de este dataset en el entorno dado."""
        return (config or Config()).resolver(self.ruta)

    def check_exists(self, config: Config | None = None) -> None:
        """Atajo de `check_input_exists` para la ruta resuelta."""
        check_input_exists(self.resolver(config))


def check_input_exists(path: str) -> None:
    """Comprueba que la entrada existe antes de arrancar Spark.

    Sin esto una ruta mal escrita se lee como un DataFrame vacio sin columnas y
    el error que sale es "faltan columnas requeridas", que manda a depurar el
    esquema cuando el problema es la ruta.

    Solo se comprueban rutas locales concretas: un URI (`s3://...`) o un patron
    con comodines los resuelve el motor, y `Path.exists()` diria que no existen.
    """
    if URI_SEPARATOR in path or any(char in path for char in GLOB_CHARS):
        return
    if not Path(path).exists():
        raise FileNotFoundError(f"No existe la ruta de entrada: {path}")
