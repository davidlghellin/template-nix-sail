"""Caso base end to end: catalogo, tablas parquet e insertInto posicional."""

from datetime import date
from decimal import Decimal

import pytest

from devel0pez.caso_base import (
    AUDIT,
    CORTE,
    FILAS_1,
    FILAS_2,
    TABLE_1,
    TABLE_2,
    TABLE_OUT,
    etl,
)

BD = "caso_base_e2e"


def ddl(schema):
    return ", ".join(f"{f.name} {f.dataType.simpleString()}" for f in schema.fields)


@pytest.fixture
def catalogo(spark):
    """Base de datos limpia antes y despues.

    El DROP inicial no es cortesia: con el backend pyspark, un `spark-warehouse/`
    de una corrida anterior hace fallar el CREATE TABLE con LOCATION_ALREADY_EXISTS.
    """
    spark.sql(f"DROP DATABASE IF EXISTS {BD} CASCADE")
    spark.sql(f"CREATE DATABASE {BD}")
    yield spark
    spark.sql(f"DROP DATABASE IF EXISTS {BD} CASCADE")


@pytest.fixture
def origenes(catalogo):
    spark = catalogo
    spark.sql(f"CREATE TABLE {BD}.t1 ({ddl(TABLE_1)}) USING parquet")
    spark.sql(f"CREATE TABLE {BD}.t2 ({ddl(TABLE_2)}) USING parquet")
    spark.createDataFrame(FILAS_1, TABLE_1).write.insertInto(f"{BD}.t1")
    spark.createDataFrame(FILAS_2, TABLE_2).write.insertInto(f"{BD}.t2")
    return spark


def test_insert_into_y_read_table(origenes):
    spark = origenes

    assert spark.read.table(f"{BD}.t1").count() == len(FILAS_1)
    assert spark.read.table(f"{BD}.t2").count() == len(FILAS_2)
    assert spark.read.table(f"{BD}.t1").columns == [f.name for f in TABLE_1.fields]


def test_etl_completa_sobre_tabla_particionada(origenes):
    spark = origenes
    spark.sql(
        f"CREATE TABLE {BD}.salida ({ddl(TABLE_OUT)}) USING parquet PARTITIONED BY (OUT_COL_7)"
    )

    salida = etl(spark.read.table(f"{BD}.t1"), spark.read.table(f"{BD}.t2"), CORTE, AUDIT)
    salida.write.insertInto(f"{BD}.salida")

    leida = spark.read.table(f"{BD}.salida")
    assert leida.columns == [f.name for f in TABLE_OUT.fields]

    filas = {r["OUT_COL_3"]: r for r in leida.collect()}
    assert set(filas) == {"C1", "C2"}
    assert filas["C1"]["OUT_COL_4"] == "P1"
    assert filas["C1"]["OUT_COL_5"] == Decimal("300.75")
    assert filas["C2"]["OUT_COL_4"] == "SIN_MATCH"
    assert filas["C2"]["OUT_COL_5"] == Decimal("10.00")
    # La columna de particion sobrevive al viaje de ida y vuelta por parquet.
    assert filas["C1"]["OUT_COL_7"] == date(2024, 12, 31)
