"""Transformaciones del dominio de ciudades.

Dominio puro: entra un `DataFrame`, sale un `DataFrame`. No se crea sesion, no
se lee ni se escribe nada. Por eso se puede probar contra cualquier backend y
componer dentro de un `ETLPipeline.transform`.
"""

import logging

from pyspark.sql import DataFrame

from etl_kedro.core.quality import (
    check_non_null_key,
    check_required_columns,
    deduplicate_by_key,
)

logger = logging.getLogger(__name__)


def validar(df: DataFrame, key_col: str) -> DataFrame:
    """Exige que la clave exista y no tenga nulos."""
    check_required_columns(df, [key_col])
    return check_non_null_key(df, key_col)


COLUMNA_HABITANTES = "habitantes"


def deduplicar(df: DataFrame, key_col: str) -> DataFrame:
    """Deja una fila por clave: la de mas habitantes.

    Es una regla de negocio y no "la primera del fichero" a proposito: Spark no
    garantiza el orden de lectura, y con un CSV grande PySpark se quedaba con la
    primera fila repetida y Sail con la ultima. A igualdad de habitantes
    desempatan el resto de columnas, para que ninguna eleccion quede al azar.
    """
    resto = sorted(c for c in df.columns if c not in (key_col, COLUMNA_HABITANTES))
    orden = [COLUMNA_HABITANTES, *resto] if COLUMNA_HABITANTES in df.columns else resto
    return deduplicate_by_key(df, key_col, keep="last", order_col=orden)
