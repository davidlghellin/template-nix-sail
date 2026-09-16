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


def deduplicate_by_key(
    df: DataFrame,
    key_col: str,
    keep: KeepStrategy = "first",
    order_col: str | Sequence[str] | None = None,
) -> DataFrame:
    """Deja una sola fila por valor de `key_col`.

    `keep="first"` conserva la fila con los menores valores de `order_col` y
    `keep="last"` la de los mayores. `order_col` admite varias columnas, que
    desempatan en orden. Si importa **cual** de los duplicados se queda, pasa
    `order_col`: es la unica forma de que el resultado sea el mismo en los dos
    motores.

    Sin `order_col` se usa `monotonically_increasing_id`, que **no** es el orden
    del fichero. Es creciente dentro de cada particion, pero el motor decide
    como numerarlas: con un CSV grande PySpark conserva la primera fila del
    fichero y Sail la ultima. Vale para quitar duplicados exactos; no para
    elegir entre filas que difieren.
    """
    if keep not in ("first", "last"):
        raise ValueError(f"keep invalido: {keep!r}. Validos: 'first', 'last'")
    columnas_orden = [order_col] if isinstance(order_col, str) else list(order_col or [])
    check_required_columns(df, [key_col, *columnas_orden])

    original_cols = df.columns
    row_number = _nombre_libre(_ROW_NUMBER_COL, original_cols)
    ordered = df
    if not columnas_orden:
        row_id = _nombre_libre(_ROW_ID_COL, original_cols)
        ordered = df.withColumn(row_id, F.monotonically_increasing_id())
        columnas_orden = [row_id]
    # Nulos al final en los dos sentidos: una fila sin valor de orden no es "la
    # primera" ni "la ultima", y `asc()` la pondria delante.
    order_by = [
        F.col(c).asc_nulls_last() if keep == "first" else F.col(c).desc_nulls_last()
        for c in columnas_orden
    ]
    window = Window.partitionBy(key_col).orderBy(*order_by)

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
