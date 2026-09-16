"""Checks de calidad sobre DataFrames: columnas requeridas, clave y duplicados.

Todas las funciones reciben y devuelven `DataFrame` (no crean sesion), para
poder ejecutarlas contra cualquier backend (`SPARK_BACKEND=pysail|pyspark`) y
encadenarlas dentro de un `ETLPipeline.transform`.
"""

import logging
from collections.abc import Sequence
from typing import Literal

from pyspark.sql import DataFrame, Window
from pyspark.sql import functions as F

logger = logging.getLogger(__name__)

KeepStrategy = Literal["first", "last"]

_ROW_ID_COL = "__etl_row_id__"
_ROW_NUMBER_COL = "__etl_row_number__"


class QualityCheckError(Exception):
    """Un check de calidad ha fallado; el dato no cumple el contrato esperado."""


def check_required_columns(df: DataFrame, required_cols: Sequence[str]) -> DataFrame:
    """Verifica que `df` contiene todas las columnas de `required_cols`.

    Devuelve el mismo DataFrame para poder encadenar. Lanza `QualityCheckError`
    si falta alguna, indicando cuales.
    """
    present = set(df.columns)
    missing = [col for col in required_cols if col not in present]
    if missing:
        raise QualityCheckError(
            f"Faltan columnas requeridas: {sorted(missing)}. Presentes: {df.columns}"
        )
    logger.debug("Columnas requeridas presentes: %s", list(required_cols))
    return df


def check_non_null_key(df: DataFrame, key_col: str) -> DataFrame:
    """Verifica que la columna clave existe y no tiene nulos.

    Devuelve el mismo DataFrame. Lanza `QualityCheckError` si la columna no
    existe o si hay al menos un nulo, indicando cuantos.
    """
    check_required_columns(df, [key_col])

    null_count = df.filter(F.col(key_col).isNull()).count()
    if null_count:
        raise QualityCheckError(f"La clave {key_col!r} tiene {null_count} valores nulos")
    logger.debug("Clave %r sin nulos", key_col)
    return df


def deduplicate_by_key(df: DataFrame, key_col: str, keep: KeepStrategy = "first") -> DataFrame:
    """Deja una sola fila por valor de `key_col`.

    `keep="first"` conserva la primera aparicion segun el orden de lectura y
    `keep="last"` la ultima. El orden se materializa con
    `monotonically_increasing_id`, que es creciente dentro de cada particion:
    con ficheros leidos en una sola pasada reproduce el orden del origen, pero
    no es un orden total garantizado si el origen esta reparticionado. Cuando el
    criterio importe, ordena antes por una columna de negocio.
    """
    if keep not in ("first", "last"):
        raise ValueError(f"keep invalido: {keep!r}. Validos: 'first', 'last'")
    check_required_columns(df, [key_col])

    original_cols = df.columns
    row_id = _nombre_libre(_ROW_ID_COL, original_cols)
    row_number = _nombre_libre(_ROW_NUMBER_COL, original_cols)
    ordered = df.withColumn(row_id, F.monotonically_increasing_id())
    order_by = F.col(row_id).asc() if keep == "first" else F.col(row_id).desc()
    window = Window.partitionBy(key_col).orderBy(order_by)

    return (
        ordered.withColumn(row_number, F.row_number().over(window))
        .filter(F.col(row_number) == 1)
        .select(*original_cols)
    )


def _nombre_libre(base: str, columnas: Sequence[str]) -> str:
    """Un nombre auxiliar que no coincida con ninguna columna de la entrada.

    `withColumn` sobre un nombre existente lo sustituye, asi que una entrada
    que ya trajera `__etl_row_id__` saldria con el id en vez de su dato.
    """
    nombre = base
    while nombre in columnas:
        nombre = f"_{nombre}"
    return nombre
