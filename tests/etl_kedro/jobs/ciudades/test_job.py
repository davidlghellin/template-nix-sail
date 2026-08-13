"""Tests del job de ciudades: cadena declarada y ejecucion de punta a punta."""

import csv
import glob
import os

import pytest

from etl_kedro.core.pipeline import ETLPipeline
from etl_kedro.jobs.ciudades import job
from etl_kedro.jobs.ciudades.datasets import CIUDADES_DEDUP, CIUDADES_RAW, CLAVE


def leer_csv_escrito(directorio) -> list[dict[str, str]]:
    """Lee el CSV que Spark deja en `directorio` (varios ficheros) como dicts."""
    filas: list[dict[str, str]] = []
    for part in sorted(glob.glob(os.path.join(directorio, "*.csv"))):
        with open(part, newline="", encoding="utf-8") as handle:
            filas.extend(csv.DictReader(handle))
    return filas


@pytest.fixture
def csv_con_duplicados(tmp_path):
    """CSV con la clave `madrid` repetida: 4 filas, 3 claves distintas."""
    path = tmp_path / "ciudades.csv"
    path.write_text(
        "ciudad,habitantes\nmadrid,3200000\nmadrid,999\nbarcelona,1600000\nvalencia,800000\n",
        encoding="utf-8",
    )
    return str(path)


# --- la cadena declarada ---


def test_el_job_declara_lo_que_consume_y_produce():
    assert job.CONSUME == (CIUDADES_RAW,)
    assert job.PRODUCE == (CIUDADES_DEDUP,)


def test_los_datasets_de_la_cadena_tienen_nombre_unico():
    nombres = [dataset.nombre for dataset in job.CONSUME + job.PRODUCE]

    assert len(nombres) == len(set(nombres))


def test_la_clave_esta_en_el_esquema_declarado():
    # Si alguien renombra la columna en el esquema, la clave deja de existir.
    assert CIUDADES_RAW.esquema is not None
    assert CLAVE in CIUDADES_RAW.esquema.fieldNames()


# --- ejecucion ---


def test_run_lee_deduplica_y_escribe(spark, csv_con_duplicados, tmp_path):
    salida = str(tmp_path / "salida")

    pipeline = job.run(spark, csv_con_duplicados, salida)

    assert isinstance(pipeline, ETLPipeline)
    assert pipeline.count() == 3  # 4 filas, `madrid` repetida
    filas = leer_csv_escrito(salida)
    assert sorted(fila["ciudad"] for fila in filas) == ["barcelona", "madrid", "valencia"]


def test_run_conserva_la_primera_aparicion(spark, csv_con_duplicados, tmp_path):
    job.run(spark, csv_con_duplicados, str(tmp_path / "salida"))

    filas = {f["ciudad"]: f["habitantes"] for f in leer_csv_escrito(tmp_path / "salida")}
    assert filas["madrid"] == "3200000"  # no el 999 de la fila duplicada


def test_run_mode_append_acumula(spark, csv_con_duplicados, tmp_path):
    salida = str(tmp_path / "salida")

    job.run(spark, csv_con_duplicados, salida)
    job.run(spark, csv_con_duplicados, salida, mode="append")

    assert len(leer_csv_escrito(salida)) == 6


def test_run_usa_la_clave_del_dominio_por_defecto(spark, csv_con_duplicados, tmp_path):
    # Sin pasar key_col: deduplica por `ciudad`, la clave declarada.
    pipeline = job.run(spark, csv_con_duplicados, str(tmp_path / "salida"))

    assert pipeline.count() == 3


def test_run_acepta_otra_clave(spark, csv_con_duplicados, tmp_path):
    # `habitantes` no tiene repetidos: no elimina nada.
    pipeline = job.run(spark, csv_con_duplicados, str(tmp_path / "salida"), key_col="habitantes")

    assert pipeline.count() == 4
