"""Caso base de compatibilidad Spark/Sail: esquemas, ETL y conformado.

Reproduce la forma de una ETL real: dos tablas con `StructType` explicito, un
filtro con `CASE` + `DISTINCT`, un `LEFT JOIN` cualificado por DataFrame (las
dos tablas traen nombres de columna que se repiten), un agregado sobre decimal
y un conformado posicional al esquema destino para poder hacer `insertInto`.

Las transformaciones no crean sesion: reciben DataFrames y devuelven DataFrames,
para poder ejecutarlas contra cualquier backend (`SPARK_BACKEND=pysail|pyspark`).
"""

from datetime import datetime
from decimal import Decimal

from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import (
    DateType,
    DecimalType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

CORTE = datetime(2024, 12, 31)
AUDIT = datetime(2025, 1, 20, 15, 4, 31)

TABLE_1 = StructType(
    [
        StructField("TABLE_1_COL_1", StringType(), True),  # clave
        StructField("TABLE_1_COL_2", StringType(), True),  # clave
        StructField("TABLE_1_COL_3", StringType(), True),  # clave
        StructField("TABLE_1_COL_4", DecimalType(18, 2), True),  # importe
        StructField("TABLE_1_COL_5", TimestampType(), True),  # fecha
    ]
)

TABLE_2 = StructType(
    [
        StructField("TABLE_2_COL_1", StringType(), True),  # clave
        StructField("TABLE_2_COL_2", StringType(), True),  # clave, se normaliza
        StructField("TABLE_2_COL_3", StringType(), True),  # clave
        StructField("TABLE_2_COL_4", StringType(), True),  # atributo a traer
        StructField("TABLE_2_COL_5", StringType(), True),  # tipo, para el filtro
        StructField("TABLE_2_COL_6", TimestampType(), True),  # fecha
    ]
)

# La columna de particion va al FINAL: insertInto es posicional.
TABLE_OUT = StructType(
    [
        StructField("OUT_COL_1", StringType(), True),
        StructField("OUT_COL_2", StringType(), True),
        StructField("OUT_COL_3", StringType(), True),
        StructField("OUT_COL_4", StringType(), True),
        StructField("OUT_COL_5", DecimalType(18, 2), True),
        StructField("OUT_COL_6", TimestampType(), True),
        StructField("OUT_COL_7", DateType(), True),
    ]
)

FILAS_1 = [
    ("ES", "0182", "C1", Decimal("100.50"), CORTE),
    ("ES", "0182", "C1", Decimal("200.25"), CORTE),  # agrega con la anterior
    ("ES", "0182", "C2", Decimal("10.00"), CORTE),  # sin match -> coalesce
]

FILAS_2 = [
    ("ES", "0227", "C1", "P1", "TIT", CORTE),  # 0227 -> 0182
    ("ES", "0182", "C1", "P1", "TIT", CORTE),  # duplicado -> distinct
    ("ES", "0182", "C9", "P9", "AUT", CORTE),  # no TIT -> se filtra
]


def filtrar_y_deduplicar(t2: DataFrame, corte: datetime) -> DataFrame:
    """Filtro por fecha y tipo + normalizacion con CASE + DISTINCT."""
    c = F.lit(corte).cast("timestamp")
    return (
        t2.filter((F.col("TABLE_2_COL_6") == c) & (F.col("TABLE_2_COL_5") == "TIT"))
        .select(
            "TABLE_2_COL_1",
            F.when(F.col("TABLE_2_COL_2").isin("0227", "0057"), F.lit("0182"))
            .otherwise(F.col("TABLE_2_COL_2"))
            .alias("TABLE_2_COL_2"),
            "TABLE_2_COL_3",
            "TABLE_2_COL_4",
        )
        .distinct()
    )


def unir_y_agregar(t1: DataFrame, t2: DataFrame, audit: datetime) -> DataFrame:
    """LEFT JOIN cualificado por DataFrame + coalesce + groupBy/sum."""
    j = t1.join(
        t2,
        (t2["TABLE_2_COL_1"] == t1["TABLE_1_COL_1"])
        & (t2["TABLE_2_COL_2"] == t1["TABLE_1_COL_2"])
        & (t2["TABLE_2_COL_3"] == t1["TABLE_1_COL_3"]),
        how="left",
    ).select(
        t1["TABLE_1_COL_1"].alias("OUT_COL_1"),
        t1["TABLE_1_COL_2"].alias("OUT_COL_2"),
        t1["TABLE_1_COL_3"].alias("OUT_COL_3"),
        F.coalesce(t2["TABLE_2_COL_4"], F.lit("SIN_MATCH")).alias("OUT_COL_4"),
        t1["TABLE_1_COL_4"].alias("OUT_COL_5"),
        t1["TABLE_1_COL_5"].alias("OUT_COL_7"),
    )
    return (
        j.groupBy("OUT_COL_1", "OUT_COL_2", "OUT_COL_3", "OUT_COL_4", "OUT_COL_7")
        .agg(F.sum("OUT_COL_5").alias("OUT_COL_5"))
        .select("*", F.lit(audit).cast("timestamp").alias("OUT_COL_6"))
    )


def conformar(df: DataFrame, schema: StructType) -> DataFrame:
    """Ordena y castea al esquema destino. Sustituye al INSERT INTO (cols)."""
    faltan = [f.name for f in schema.fields if f.name not in df.columns]
    if faltan:
        raise ValueError(f"faltan columnas: {faltan}")
    return df.select(*[F.col(f.name).cast(f.dataType).alias(f.name) for f in schema.fields])


def etl(t1: DataFrame, t2: DataFrame, corte: datetime, audit: datetime) -> DataFrame:
    """ETL completa: de las dos tablas de origen al esquema de salida."""
    return conformar(unir_y_agregar(t1, filtrar_y_deduplicar(t2, corte), audit), TABLE_OUT)
