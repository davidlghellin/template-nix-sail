from pyspark.sql import DataFrame
from pyspark.sql import functions as F


def suma_columnas(df: DataFrame, col1: str, col2: str, nueva_col: str) -> DataFrame:
    """Suma dos columnas y añade el resultado como nueva columna usando select."""
    return df.select(
        "*",
        (F.col(col1) + F.col(col2)).alias(nueva_col)
    )
