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
import glob
import os
from dataclasses import dataclass
from pathlib import Path

from pyspark.sql.types import StructType

from etl_kedro.core.config import Config

# Rutas que no se comprueban en local: las resuelve el motor, no el sistema de
# ficheros.
URI_SEPARATOR = "://"
GLOB_CHARS = ("*", "?", "[")
EXTENSIONES_COMPRIMIDAS = (".gz", ".bz2", ".zst", ".lz4", ".snappy", ".deflate", ".xz")


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


def rutas_solapadas(a: str, b: str) -> bool:
    """True si `a` y `b` son la misma ruta o una esta dentro de la otra."""

    def normalizar(ruta: str) -> str:
        # Todo lo local se hace absoluto, comodines incluidos (`realpath` deja
        # el `*` tal cual). Si no, `data/in/*.csv` relativo nunca se compararia
        # con un `--output data/in` ya resuelto, y el solape pasaria sin verse.
        if URI_SEPARATOR in ruta:
            return ruta.rstrip("/")
        return os.path.realpath(os.path.expanduser(ruta))

    # Un comodin local se expande: `data/*/in.csv` solapa con `data/out` si
    # alguno de los ficheros que casa esta dentro. Comparar el patron como
    # texto no lo veria.
    # Si aun no casa ningun fichero, se compara la parte fija del patron, la
    # anterior al primer comodin: mas vale un aviso de sobra que perder datos.
    for ruta, otra in ((a, b), (b, a)):
        if URI_SEPARATOR not in ruta and any(char in ruta for char in GLOB_CHARS):
            encontradas = glob.glob(ruta)
            if encontradas:
                return any(rutas_solapadas(encontrada, otra) for encontrada in encontradas)
            return rutas_solapadas(_parte_fija(ruta), otra)

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


def _parte_fija(patron: str) -> str:
    """El directorio de un patron hasta el primer segmento con comodines."""
    segmentos = patron.replace("\\", "/").split("/")
    fijos = []
    for segmento in segmentos:
        if any(char in segmento for char in GLOB_CHARS):
            break
        fijos.append(segmento)
    return "/".join(fijos) or "."


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

    Pasa si se cambia el `formato` de un dataset y quedan datos escritos con el
    anterior: se leerian partes parquet como CSV, el motor fallaria con un
    error de parseo y, en un job que sobrescribe su salida, despues de haberla
    vaciado. Solo se avisa del caso claro (hay partes del otro formato y
    ninguna del esperado), para no dar falsos positivos con compresiones u
    otros nombres de fichero.
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
        "Se escribio con otro formato: vuelve a generarlo o declara el formato con el que esta"
    )


def sin_datos(ruta: str) -> bool:
    """True si `ruta` es un directorio local sin ningun fichero de datos.

    Es lo que deja Sail al escribir un resultado vacio (con el directorio que
    crea `write_dataset`). Leerlo sin esquema da un DataFrame sin columnas en
    Sail y un error en PySpark, asi que se lee con el declarado.
    """
    if not se_comprueba_en_local(ruta) or not os.path.isdir(ruta):
        return False
    return not any(not f.startswith((".", "_")) for f in os.listdir(ruta))


def check_input_exists(path: str) -> None:
    """Comprueba que la entrada existe antes de arrancar Spark.

    Sin esto una ruta mal escrita se lee como un DataFrame vacio sin columnas y
    el error que sale es "faltan columnas requeridas", que manda a depurar el
    esquema cuando el problema es la ruta.

    Un URI (`s3://...`) no se puede mirar desde aqui y se deja al motor. Un
    comodin local si: si no casa con ningun fichero es una ruta mal escrita, y
    dejarlo pasar leia "nada" y, en un job que sobrescribe, vaciaba la salida.
    """
    if URI_SEPARATOR in path:
        return
    if any(char in path for char in GLOB_CHARS):
        if not glob.glob(path):
            raise EntradaNoEncontradaError(f"Ningun fichero casa con la entrada: {path}")
        return
    if not Path(path).exists():
        raise EntradaNoEncontradaError(f"No existe la ruta de entrada: {path}")


def cabecera_csv(ruta: str) -> list[str] | None:
    """Columnas de la cabecera de un CSV, leidas con Python y sin motor.

    Devuelve `None` cuando no se puede mirar en seco: un URI, un patron con
    comodines, una ruta que no existe, un fichero comprimido o un directorio
    sin ningun `.csv`. En
    esos casos la comprobacion se delega al motor al leer.

    Una salida de Spark es un directorio de `part-*.csv`, todos con la misma
    cabecera: basta con el primero.
    """
    if not se_comprueba_en_local(ruta):
        return None
    fichero = Path(ruta)
    if fichero.is_dir():
        # Como hacen los motores, se ignoran los ocultos y los que empiezan por
        # `_`: un `._part-0.csv` que deja macOS al copiar a exFAT se leeria
        # como la cabecera.
        partes = sorted(p for p in fichero.glob("*.csv") if not p.name.startswith((".", "_")))
        if not partes:
            return None
        fichero = partes[0]
    if not fichero.is_file():
        return None
    if fichero.suffix.lower() in EXTENSIONES_COMPRIMIDAS:
        # El motor los descomprime al leer; aqui se leerian bytes de gzip como
        # si fueran la cabecera. Se deja la comprobacion al motor.
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
    """Mensaje si las columnas no cumplen el esquema declarado; `None` si cuadran.

    Se comparan **nombres**: que no se repita, falte ni sobre ninguna. El
    orden no importa, porque los datasets se leen por nombre de columna y no
    por posicion (ver `ETLPipeline.read_dataset`).
    """
    declaradas = esquema.fieldNames()
    # Una columna repetida no falta ni sobra, pero al leer por nombre es
    # ambigua: Sail falla con traceback y PySpark las renombra (`ciudad0`).
    repetidas = sorted({columna for columna in cabecera if cabecera.count(columna) > 1})
    if repetidas:
        return f"el fichero repite columnas {repetidas}; tiene {cabecera}"
    faltan = [columna for columna in declaradas if columna not in cabecera]
    if faltan:
        return f"al fichero le faltan columnas declaradas {faltan}; tiene {cabecera}"
    sobran = [columna for columna in cabecera if columna not in declaradas]
    if sobran:
        return (
            f"el fichero trae columnas que el esquema no declara {sobran}; "
            f"el esquema dice {declaradas}"
        )
    return None
