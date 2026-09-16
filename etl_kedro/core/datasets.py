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
import os
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


def se_comprueba_en_local(path: str) -> bool:
    """True si `path` es una ruta local concreta que Python puede mirar.

    Un URI (`s3://...`) o un patron con comodines los resuelve el motor, y
    `Path.exists()` diria que no existen. Es la unica regla para decidirlo:
    la ejecucion, la lectura de cabeceras y el dry-run la comparten, para que
    el dry-run no rechace lo que una ejecucion real acepta.
    """
    return URI_SEPARATOR not in path and not any(char in path for char in GLOB_CHARS)


def formato_efectivo(dataset: Dataset, config: Config | None, sobrescrita: bool) -> str:
    """Formato con el que se lee o escribe `dataset` en esta ejecucion.

    `ETL_OUTPUT_FORMAT` cambia el formato de los datasets **en su ruta del
    catalogo**, que es donde otro job de la cadena los dejo en ese formato. Una
    ruta dada a mano (`--input`/`--output`) es un fichero concreto que no ha
    escrito la cadena, y se trata con el formato declarado: forzarlo leeria un
    CSV como parquet.
    """
    if sobrescrita:
        return dataset.formato
    return (config or Config()).formato_de(dataset.nombre, dataset.formato)


def rutas_solapadas(a: str, b: str) -> bool:
    """True si `a` y `b` son la misma ruta o una esta dentro de la otra."""

    def normalizar(ruta: str) -> str:
        # Todo lo local se hace absoluto, comodines incluidos (`realpath` deja
        # el `*` tal cual). Si no, `data/in/*.csv` relativo nunca se compararia
        # con un `--output data/in` ya resuelto, y el solape pasaria sin verse.
        if URI_SEPARATOR in ruta:
            return ruta.rstrip("/")
        return os.path.realpath(os.path.expanduser(ruta))

    x, y = normalizar(a), normalizar(b)
    separadores = ("/", os.sep)
    if (
        x == y
        or any(x.startswith(y + sep) for sep in separadores)
        or any(y.startswith(x + sep) for sep in separadores)
    ):
        return True
    # Comparar texto no basta en un sistema de ficheros que no distingue
    # mayusculas (el de macOS por defecto): `Solape` y `solape` son la misma
    # carpeta y `realpath` no lo corrige. Donde las rutas existen, se compara la
    # identidad del fichero, subiendo por los padres de cada una.
    if URI_SEPARATOR in x or URI_SEPARATOR in y:
        return False
    return _dentro_por_identidad(x, y) or _dentro_por_identidad(y, x)


def _dentro_por_identidad(ruta: str, contenedor: str) -> bool:
    """True si `ruta`, o alguno de sus padres, es el mismo fichero que `contenedor`."""
    if not os.path.exists(contenedor):
        return False
    camino = Path(ruta)
    for candidato in (camino, *camino.parents):
        if candidato.exists() and os.path.samefile(candidato, contenedor):
            return True
    return False


class EntradaNoEncontradaError(FileNotFoundError):
    """Una entrada de la ETL no existe.

    Subclase propia y no `FileNotFoundError` a secas: la CLI traduce esta a
    "entrada no encontrada" (codigo 4) sin traceback, y cualquier otro fichero
    que falte, como el `spark-submit` de un `SPARK_HOME` roto, sigue saliendo
    como lo que es.
    """


def problema_de_formato(ruta: str, formato: str) -> str | None:
    """Mensaje si un directorio contiene datos en el otro formato; `None` si no.

    Pasa al dejar un dataset en parquet con `ETL_OUTPUT_FORMAT=parquet` y
    lanzar despues sin la variable: se leerian partes parquet como CSV, el
    motor fallaria con un error de parseo y, con `overwrite`, despues de haber
    vaciado la salida anterior. Solo se avisa del caso claro (hay partes del
    otro formato y ninguna del esperado), para no dar falsos positivos con
    compresiones u otros nombres de fichero.
    """
    if not se_comprueba_en_local(ruta) or not os.path.isdir(ruta):
        return None
    datos = [f for f in os.listdir(ruta) if not f.startswith((".", "_"))]
    csvs = [f for f in datos if f.endswith(".csv")]
    parquets = [f for f in datos if f.endswith(".parquet")]
    if formato == "csv" and parquets and not csvs:
        encontrado = "parquet"
    elif formato == "parquet" and csvs and not parquets:
        encontrado = "CSV"
    else:
        return None
    return (
        f"se lee como {formato} y el directorio tiene {encontrado}: {ruta}. "
        "Revisa ETL_OUTPUT_FORMAT, que tiene que ser el mismo con el que se escribio"
    )


def check_input_exists(path: str) -> None:
    """Comprueba que la entrada existe antes de arrancar Spark.

    Sin esto una ruta mal escrita se lee como un DataFrame vacio sin columnas y
    el error que sale es "faltan columnas requeridas", que manda a depurar el
    esquema cuando el problema es la ruta.

    Solo se comprueban rutas locales concretas (`se_comprueba_en_local`).
    """
    if not se_comprueba_en_local(path):
        return
    if not Path(path).exists():
        raise EntradaNoEncontradaError(f"No existe la ruta de entrada: {path}")


def cabecera_csv(ruta: str) -> list[str] | None:
    """Columnas de la cabecera de un CSV, leidas con Python y sin motor.

    Devuelve `None` cuando no se puede mirar en seco: un URI, un patron con
    comodines, una ruta que no existe o un directorio sin ningun `.csv`. En
    esos casos la comprobacion se delega al motor al leer.

    Una salida de Spark es un directorio de `part-*.csv`, todos con la misma
    cabecera: basta con el primero.
    """
    if not se_comprueba_en_local(ruta):
        return None
    fichero = Path(ruta)
    if fichero.is_dir():
        partes = sorted(fichero.glob("*.csv"))
        if not partes:
            return None
        fichero = partes[0]
    if not fichero.is_file():
        return None
    # `utf-8-sig` y no `utf-8`: un CSV exportado desde Excel empieza con BOM, y
    # la primera columna llegaria como '\ufeffciudad'. Los dos motores lo quitan
    # al leer, asi que la comprobacion tiene que hacer lo mismo.
    #
    # `errors="replace"` porque Python decodifica un bloque entero y no solo la
    # primera linea: un fichero en Latin-1 con una "n" en la segunda fila
    # reventaria aqui con traceback, aunque el motor lo lee. Una cabecera que
    # no cuadre se sigue detectando al comparar.
    with fichero.open(newline="", encoding="utf-8-sig", errors="replace") as handle:
        return next(csv.reader(handle), [])


def problema_de_cabecera(esquema: StructType, cabecera: list[str]) -> str | None:
    """Mensaje si la cabecera no cumple el esquema declarado; `None` si cuadra.

    Se comprueban los nombres, que no sobre ninguno y el orden, que importa
    tanto como los nombres: un esquema explicito se aplica **por posicion**.
    PySpark avisa del desorden si se lee con `enforceSchema=False`, pero Sail
    ignora esa opcion y devolveria las columnas cruzadas sin un solo error, asi
    que se comprueba aqui para que el comportamiento sea el mismo en los dos
    backends.

    Una columna de mas no la ignora ninguno de los dos: ambos fallan al leer,
    pero cada uno con su error interno (`SparkRuntimeException` en Sail,
    `Py4JJavaError` en PySpark), que sale como bug y no como fallo de dato.
    """
    declaradas = esquema.fieldNames()
    faltan = [columna for columna in declaradas if columna not in cabecera]
    if faltan:
        return f"al fichero le faltan columnas declaradas {faltan}; tiene {cabecera}"
    sobran = [columna for columna in cabecera if columna not in declaradas]
    if sobran:
        return (
            f"el fichero trae columnas que el esquema no declara {sobran}; "
            f"el esquema dice {declaradas}"
        )
    if cabecera != declaradas:
        return (
            f"las columnas estan en otro orden: el esquema dice {declaradas} y el "
            f"fichero {cabecera}. Un esquema explicito se aplica por posicion, "
            "asi que los datos saldrian cruzados"
        )
    return None
