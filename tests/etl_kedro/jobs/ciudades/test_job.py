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
def csv_con_duplicados(escribir_ciudades):
    """CSV con la clave `madrid` repetida: 4 filas, 3 claves distintas."""
    return escribir_ciudades(
        [
            ("madrid", 3200000, "Madrid", "Comunidad de Madrid", 604.3),
            ("madrid", 999, "Madrid", "Comunidad de Madrid", 604.3),
            ("barcelona", 1600000, "Barcelona", "Cataluna", 101.4),
            ("valencia", 800000, "Valencia", "Comunidad Valenciana", 134.6),
        ]
    )


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


@pytest.mark.parametrize("mayor_primero", [True, False], ids=["mayor-primero", "mayor-despues"])
def test_run_conserva_la_fila_con_mas_habitantes(spark, escribir_ciudades, tmp_path, mayor_primero):
    """La regla no depende del orden del fichero, que Spark no garantiza.

    Con un CSV grande, "la primera aparicion" era la primera fila en PySpark y
    la ultima en Sail. Se prueban los dos ordenes: los dos dan lo mismo.
    """
    filas = [
        ("madrid", 3200000, "Madrid", "Comunidad de Madrid", 604.3),
        ("madrid", 999, "Madrid", "Comunidad de Madrid", 604.3),
    ]
    entrada = escribir_ciudades(filas if mayor_primero else filas[::-1])

    job.run(spark, entrada, str(tmp_path / "salida"))

    escritas = {f["ciudad"]: f["habitantes"] for f in leer_csv_escrito(tmp_path / "salida")}
    assert escritas["madrid"] == "3200000"


def test_run_desempata_sin_depender_del_orden(spark, escribir_ciudades, tmp_path):
    # Mismos habitantes y distinto dato: decide el resto de columnas, no el azar.
    a = ("madrid", 100, "A", "Comunidad de Madrid", 1.0)
    b = ("madrid", 100, "B", "Comunidad de Madrid", 1.0)
    resultados = set()
    for orden in ([a, b], [b, a]):
        entrada = escribir_ciudades(orden, nombre=f"desempate-{orden[0][2]}.csv")
        salida = tmp_path / f"salida-{orden[0][2]}"
        job.run(spark, entrada, str(salida))
        resultados.add(leer_csv_escrito(salida)[0]["provincia"])

    assert resultados == {"B"}


def test_run_usa_la_clave_del_dominio_por_defecto(spark, csv_con_duplicados, tmp_path):
    # Sin pasar key_col: deduplica por `ciudad`, la clave declarada.
    pipeline = job.run(spark, csv_con_duplicados, str(tmp_path / "salida"))

    assert pipeline.count() == 3


def test_run_acepta_otra_clave(spark, csv_con_duplicados, tmp_path):
    # `habitantes` no tiene repetidos: no elimina nada.
    pipeline = job.run(spark, csv_con_duplicados, str(tmp_path / "salida"), key_col="habitantes")

    assert pipeline.count() == 4
