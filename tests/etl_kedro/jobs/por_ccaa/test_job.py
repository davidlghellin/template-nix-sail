"""Tests del job que agrega poblacion por comunidad autonoma."""

import csv
import glob
import os

import pytest

from etl_kedro.core.quality import QualityCheckError
from etl_kedro.jobs.ciudades.datasets import CIUDADES_DEDUP
from etl_kedro.jobs.por_ccaa import job
from etl_kedro.jobs.por_ccaa.datasets import POBLACION_POR_CCAA


def leer_csv_escrito(directorio) -> list[dict[str, str]]:
    filas: list[dict[str, str]] = []
    for part in sorted(glob.glob(os.path.join(directorio, "*.csv"))):
        with open(part, newline="", encoding="utf-8") as handle:
            filas.extend(csv.DictReader(handle))
    return filas


@pytest.fixture
def csv_ciudades(tmp_path):
    """Dos ciudades de Madrid y una de Cataluna, para ver el agregado."""
    path = tmp_path / "ciudades.csv"
    path.write_text(
        "ciudad,habitantes,comunidad_autonoma\n"
        "madrid,3000000,Comunidad de Madrid\n"
        "alcobendas,100000,Comunidad de Madrid\n"
        "barcelona,1600000,Cataluna\n",
        encoding="utf-8",
    )
    return str(path)


def test_declara_que_consume_la_salida_de_ciudades():
    assert job.CONSUME == (CIUDADES_DEDUP,)
    assert job.PRODUCE == (POBLACION_POR_CCAA,)


def test_suma_los_habitantes_por_comunidad(spark, csv_ciudades, tmp_path):
    salida = str(tmp_path / "salida")

    job.run(spark, csv_ciudades, salida)

    filas = {f["comunidad_autonoma"]: int(f["habitantes"]) for f in leer_csv_escrito(salida)}
    assert filas == {"Comunidad de Madrid": 3100000, "Cataluna": 1600000}


def test_deja_una_fila_por_comunidad(spark, csv_ciudades, tmp_path):
    pipeline = job.run(spark, csv_ciudades, str(tmp_path / "salida"))

    assert pipeline.count() == 2


def test_falla_si_falta_la_columna_de_habitantes(spark, tmp_path):
    entrada = tmp_path / "sin_habitantes.csv"
    entrada.write_text("ciudad,comunidad_autonoma\nmadrid,Comunidad de Madrid\n", encoding="utf-8")

    with pytest.raises(QualityCheckError, match="habitantes"):
        job.run(spark, str(entrada), str(tmp_path / "salida"))
