"""Tests de `ETLPipeline`: estado, lectura, transformacion y escritura.

La sesion de Spark local viene de la fixture `spark` de `conftest.py`, que la
levanta con el backend de `SPARK_BACKEND` (pysail por defecto, pyspark si se
pide). Los ficheros temporales se crean con `tmp_path`.
"""

import csv
import glob
import os

import pytest
from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from etl_kedro.core.pipeline import ETLPipeline, PipelineStateError

FILAS = [
    ("1", "madrid", "3200000"),
    ("2", "barcelona", "1600000"),
    ("3", "valencia", "800000"),
]
CABECERA = ["id", "ciudad", "poblacion"]


@pytest.fixture
def csv_entrada(tmp_path):
    """CSV de entrada con cabecera y tres filas."""
    path = tmp_path / "entrada.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(CABECERA)
        writer.writerows(FILAS)
    return str(path)


@pytest.fixture
def pipeline(spark):
    """Pipeline vacio sobre la sesion de test."""
    return ETLPipeline(spark, name="test-etl")


def leer_csv_escrito(directorio: str) -> list[dict[str, str]]:
    """Lee el CSV que Spark deja en `directorio` (part-*.csv) como lista de dicts."""
    filas: list[dict[str, str]] = []
    for part in sorted(glob.glob(os.path.join(directorio, "*.csv"))):
        with open(part, newline="", encoding="utf-8") as handle:
            filas.extend(csv.DictReader(handle))
    return filas


def test_init_no_tiene_dataframe(spark):
    pipeline = ETLPipeline(spark, name="mi-etl")

    assert pipeline.spark is spark
    assert pipeline.name == "mi-etl"
    assert pipeline.has_data is False


def test_init_nombre_por_defecto(spark):
    assert ETLPipeline(spark).name == "etl"


def test_df_sin_leer_lanza_pipeline_state_error(pipeline):
    with pytest.raises(PipelineStateError, match="no tiene DataFrame"):
        _ = pipeline.df


def test_transform_sin_dataframe_lanza_error(pipeline):
    with pytest.raises(PipelineStateError):
        pipeline.transform(lambda df: df)


def test_write_csv_sin_dataframe_lanza_error(pipeline, tmp_path):
    with pytest.raises(PipelineStateError):
        pipeline.write_csv(str(tmp_path / "salida"))

    assert not (tmp_path / "salida").exists()


def test_count_sin_dataframe_lanza_error(pipeline):
    with pytest.raises(PipelineStateError):
        pipeline.count()


def test_read_csv_carga_datos(pipeline, csv_entrada):
    resultado = pipeline.read_csv(csv_entrada)

    assert resultado is pipeline  # encadenable
    assert pipeline.has_data is True
    assert pipeline.df.columns == CABECERA
    assert pipeline.count() == 3


def test_read_csv_infiere_tipos(pipeline, csv_entrada):
    pipeline.read_csv(csv_entrada)

    # PySpark infiere `int` y Sail `bigint`: basta con que no sea texto.
    assert dict(pipeline.df.dtypes)["poblacion"] in ("int", "bigint")


def test_read_csv_permite_sobrescribir_opciones(pipeline, csv_entrada):
    pipeline.read_csv(csv_entrada, inferSchema=False)

    assert dict(pipeline.df.dtypes)["poblacion"] == "string"


def test_read_csv_sin_cabecera(pipeline, csv_entrada):
    pipeline.read_csv(csv_entrada, header=False, inferSchema=False)

    # Sin cabecera, la primera fila es un dato mas y las columnas son _c0.._c2.
    assert pipeline.df.columns == ["_c0", "_c1", "_c2"]
    assert pipeline.count() == 4


def test_transform_aplica_la_funcion(pipeline, csv_entrada):
    def anadir_pais(df: DataFrame) -> DataFrame:
        return df.withColumn("pais", F.lit("ES"))

    resultado = pipeline.read_csv(csv_entrada).transform(anadir_pais)

    assert resultado is pipeline
    assert "pais" in pipeline.df.columns
    assert {fila["pais"] for fila in pipeline.df.collect()} == {"ES"}


def test_transform_encadena_varias_funciones(pipeline, csv_entrada):
    pipeline.read_csv(csv_entrada)
    pipeline.transform(lambda df: df.filter(F.col("poblacion") > 900000))
    pipeline.transform(lambda df: df.select("ciudad"))

    assert pipeline.df.columns == ["ciudad"]
    assert sorted(fila["ciudad"] for fila in pipeline.df.collect()) == [
        "barcelona",
        "madrid",
    ]


def test_transform_propaga_la_excepcion_de_la_funcion(pipeline, csv_entrada):
    def explota(df: DataFrame) -> DataFrame:
        raise ValueError("boom")

    pipeline.read_csv(csv_entrada)

    with pytest.raises(ValueError, match="boom"):
        pipeline.transform(explota)


def test_write_csv_escribe_los_datos(pipeline, csv_entrada, tmp_path):
    salida = str(tmp_path / "salida")

    resultado = pipeline.read_csv(csv_entrada).write_csv(salida)

    assert resultado is pipeline
    filas = leer_csv_escrito(salida)
    assert len(filas) == 3
    assert {fila["ciudad"] for fila in filas} == {"madrid", "barcelona", "valencia"}


def test_write_csv_overwrite_reemplaza(pipeline, csv_entrada, tmp_path):
    salida = str(tmp_path / "salida")

    pipeline.read_csv(csv_entrada).write_csv(salida)
    pipeline.transform(lambda df: df.filter(F.col("id") == 1)).write_csv(salida, mode="overwrite")

    assert len(leer_csv_escrito(salida)) == 1


def test_write_csv_append_acumula(pipeline, csv_entrada, tmp_path):
    salida = str(tmp_path / "salida")

    pipeline.read_csv(csv_entrada).write_csv(salida)
    pipeline.write_csv(salida, mode="append")

    assert len(leer_csv_escrito(salida)) == 6


def test_pipeline_end_to_end_encadenado(pipeline, csv_entrada, tmp_path):
    salida = str(tmp_path / "salida")

    (
        pipeline.read_csv(csv_entrada)
        .transform(lambda df: df.filter(F.col("poblacion") > 900000))
        .transform(lambda df: df.withColumn("pais", F.lit("ES")))
        .write_csv(salida)
    )

    filas = leer_csv_escrito(salida)
    assert len(filas) == 2
    assert all(fila["pais"] == "ES" for fila in filas)
