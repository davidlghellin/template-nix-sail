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


def deduplicar(df: DataFrame, key_col: str) -> DataFrame:
    """Deja una fila por clave, conservando la primera aparicion."""
    return deduplicate_by_key(df, key_col, keep="first")
