"""Transformaciones del dominio de poblacion por comunidad autonoma."""

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from etl_kedro.core.quality import check_required_columns

COLUMNA_HABITANTES = "habitantes"


def agregar_por_ccaa(df: DataFrame, key_col: str) -> DataFrame:
    """Suma los habitantes de cada comunidad autonoma."""
    check_required_columns(df, [key_col, COLUMNA_HABITANTES])
    return (
        df.groupBy(key_col)
        .agg(F.sum(COLUMNA_HABITANTES).alias(COLUMNA_HABITANTES))
        .orderBy(F.col(COLUMNA_HABITANTES).desc())
    )
