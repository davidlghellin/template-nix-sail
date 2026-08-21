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
def csv_ciudades(escribir_ciudades):
    """Dos ciudades de Madrid y una de Cataluna, para ver el agregado."""
    return escribir_ciudades(
        [
            ("madrid", 3000000, "Madrid", "Comunidad de Madrid", 604.3),
            ("alcobendas", 100000, "Madrid", "Comunidad de Madrid", 45.0),
            ("barcelona", 1600000, "Barcelona", "Cataluna", 101.4),
        ]
    )


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
    """Un fichero que no cumple el esquema declarado corta como fallo de dato.

    El corte ocurre al leer, comparando la cabecera con el esquema, y no al
    aplicar el check de calidad: asi el mensaje dice que columna falta en vez
    de dejar que el motor lance un error de parseo, que saldria como bug.
    """
    entrada = tmp_path / "sin_habitantes.csv"
    entrada.write_text("ciudad,comunidad_autonoma\nmadrid,Comunidad de Madrid\n", encoding="utf-8")

    with pytest.raises(QualityCheckError, match="habitantes"):
        job.run(spark, str(entrada), str(tmp_path / "salida"))
