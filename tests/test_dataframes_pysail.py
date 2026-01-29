"""Tests adicionales de dataframes usando PySail."""
import pytest

from src.dataframes import suma_columnas

pytestmark = pytest.mark.pysail


def test_suma_columnas_grandes_numeros(spark):
    df = spark.createDataFrame([
        (1000000, 2000000),
        (999999, 1),
    ], ["a", "b"])

    resultado = suma_columnas(df, "a", "b", "suma")

    filas = resultado.collect()
    assert filas[0]["suma"] == 3000000
    assert filas[1]["suma"] == 1000000


def test_suma_columnas_decimales(spark):
    df = spark.createDataFrame([
        (1.5, 2.5),
        (0.1, 0.2),
    ], ["a", "b"])

    resultado = suma_columnas(df, "a", "b", "suma")

    filas = resultado.collect()
    assert filas[0]["suma"] == 4.0
    assert abs(filas[1]["suma"] - 0.3) < 0.0001


def test_suma_columnas_ceros(spark):
    df = spark.createDataFrame([
        (0, 0),
        (0, 5),
        (5, 0),
    ], ["a", "b"])

    resultado = suma_columnas(df, "a", "b", "suma")

    filas = resultado.collect()
    assert filas[0]["suma"] == 0
    assert filas[1]["suma"] == 5
    assert filas[2]["suma"] == 5
