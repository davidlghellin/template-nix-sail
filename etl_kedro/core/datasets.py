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

import csv
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


def cabecera_csv(ruta: str) -> list[str] | None:
    """Columnas de la cabecera de un CSV, leidas con Python y sin motor.

    Devuelve `None` cuando no se puede mirar en seco: un URI, un patron con
    comodines, una ruta que no existe o un directorio sin ningun `.csv`. En
    esos casos la comprobacion se delega al motor al leer.

    Una salida de Spark es un directorio de `part-*.csv`, todos con la misma
    cabecera: basta con el primero.
    """
    if URI_SEPARATOR in ruta or any(char in ruta for char in GLOB_CHARS):
        return None
    fichero = Path(ruta)
    if fichero.is_dir():
        partes = sorted(fichero.glob("*.csv"))
        if not partes:
            return None
        fichero = partes[0]
    if not fichero.is_file():
        return None
    with fichero.open(newline="", encoding="utf-8") as handle:
        return next(csv.reader(handle), [])


def problema_de_cabecera(esquema: StructType, cabecera: list[str]) -> str | None:
    """Mensaje si la cabecera no cumple el esquema declarado; `None` si cuadra.

    Se comprueban dos cosas, y el orden importa tanto como los nombres: un
    esquema explicito se aplica **por posicion**. PySpark avisa del desorden si
    se lee con `enforceSchema=False`, pero Sail ignora esa opcion y devolveria
    las columnas cruzadas sin un solo error, asi que se comprueba aqui para que
    el comportamiento sea el mismo en los dos backends.
    """
    declaradas = esquema.fieldNames()
    faltan = [columna for columna in declaradas if columna not in cabecera]
    if faltan:
        return f"al fichero le faltan columnas declaradas {faltan}; tiene {cabecera}"
    if cabecera[: len(declaradas)] != declaradas:
        return (
            f"las columnas estan en otro orden: el esquema dice {declaradas} y el "
            f"fichero {cabecera}. Un esquema explicito se aplica por posicion, "
            "asi que los datos saldrian cruzados"
        )
    return None
