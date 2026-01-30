"""DataFrame tests with Spark."""

from src.dataframes import suma_columnas


def test_suma_columnas_basic(spark):
    df = spark.createDataFrame(
        [
            (1, 2),
            (3, 4),
            (5, 6),
        ],
        ["a", "b"],
    )

    result = suma_columnas(df, "a", "b", "suma")

    assert "suma" in result.columns
    rows = result.collect()
    assert rows[0]["suma"] == 3
    assert rows[1]["suma"] == 7
    assert rows[2]["suma"] == 11


def test_suma_columnas_with_negatives(spark):
    df = spark.createDataFrame(
        [
            (-1, 5),
            (10, -3),
        ],
        ["x", "y"],
    )

    result = suma_columnas(df, "x", "y", "total")

    rows = result.collect()
    assert rows[0]["total"] == 4
    assert rows[1]["total"] == 7


def test_suma_columnas_keeps_original_columns(spark):
    df = spark.createDataFrame(
        [
            (1, 2, "extra"),
        ],
        ["a", "b", "c"],
    )

    result = suma_columnas(df, "a", "b", "suma")

    assert result.columns == ["a", "b", "c", "suma"]


def test_suma_columnas_large_numbers(spark):
    df = spark.createDataFrame(
        [
            (1000000, 2000000),
            (999999, 1),
        ],
        ["a", "b"],
    )

    result = suma_columnas(df, "a", "b", "suma")

    rows = result.collect()
    assert rows[0]["suma"] == 3000000
    assert rows[1]["suma"] == 1000000


def test_suma_columnas_decimals(spark):
    df = spark.createDataFrame(
        [
            (1.5, 2.5),
            (0.1, 0.2),
        ],
        ["a", "b"],
    )

    result = suma_columnas(df, "a", "b", "suma")

    rows = result.collect()
    assert rows[0]["suma"] == 4.0
    assert abs(rows[1]["suma"] - 0.3) < 0.0001
