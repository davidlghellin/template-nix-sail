"""Tests de dataframes con PySail (no requiere Java)."""
import pytest

from src.dataframes import suma_columnas

pytestmark = pytest.mark.pysail


def test_suma_columnas_basico(spark_sail):
    df = spark_sail.createDataFrame([
        (1, 2),
        (3, 4),
        (5, 6),
    ], ["a", "b"])

    resultado = suma_columnas(df, "a", "b", "suma")

    assert "suma" in resultado.columns
    filas = resultado.collect()
    assert filas[0]["suma"] == 3
    assert filas[1]["suma"] == 7
    assert filas[2]["suma"] == 11


def test_suma_columnas_grandes_numeros(spark_sail):
    df = spark_sail.createDataFrame([
        (1000000, 2000000),
        (999999, 1),
    ], ["a", "b"])

    resultado = suma_columnas(df, "a", "b", "suma")

    filas = resultado.collect()
    assert filas[0]["suma"] == 3000000
    assert filas[1]["suma"] == 1000000


def test_suma_columnas_decimales(spark_sail):
    df = spark_sail.createDataFrame([
        (1.5, 2.5),
        (0.1, 0.2),
    ], ["a", "b"])

    resultado = suma_columnas(df, "a", "b", "suma")

    filas = resultado.collect()
    assert filas[0]["suma"] == 4.0
    assert abs(filas[1]["suma"] - 0.3) < 0.0001
