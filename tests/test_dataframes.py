"""Tests de dataframes con Spark."""
from src.dataframes import suma_columnas


def test_suma_columnas_basico(spark):
    df = spark.createDataFrame([
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


def test_suma_columnas_con_negativos(spark):
    df = spark.createDataFrame([
        (-1, 5),
        (10, -3),
    ], ["x", "y"])

    resultado = suma_columnas(df, "x", "y", "total")

    filas = resultado.collect()
    assert filas[0]["total"] == 4
    assert filas[1]["total"] == 7


def test_suma_columnas_mantiene_originales(spark):
    df = spark.createDataFrame([
        (1, 2, "extra"),
    ], ["a", "b", "c"])

    resultado = suma_columnas(df, "a", "b", "suma")

    assert resultado.columns == ["a", "b", "c", "suma"]


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
