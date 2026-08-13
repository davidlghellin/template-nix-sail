"""Tests de la CLI: argumentos y codigos de salida."""

import csv
import glob
import os
from contextlib import contextmanager
from dataclasses import replace

import pytest

from etl_kedro.jobs.ciudades import job as ciudades_job
from etl_kedro.jobs.ciudades.datasets import CIUDADES_DEDUP, CIUDADES_RAW
from etl_kedro.jobs.por_ccaa import job as por_ccaa_job
from etl_kedro.jobs.por_ccaa.datasets import POBLACION_POR_CCAA
from etl_kedro.main import (
    EXIT_BACKEND,
    EXIT_INPUT,
    EXIT_OK,
    EXIT_QUALITY,
    main,
    parse_args,
)


def leer_csv_escrito(directorio) -> list[dict[str, str]]:
    filas: list[dict[str, str]] = []
    for part in sorted(glob.glob(os.path.join(directorio, "*.csv"))):
        with open(part, newline="", encoding="utf-8") as handle:
            filas.extend(csv.DictReader(handle))
    return filas


@pytest.fixture
def cli(spark, monkeypatch):
    """Hace que `main()` use la sesion de la suite y no la pare al terminar.

    Sin esto, en PySpark `getOrCreate` devuelve la sesion compartida y el
    `spark.stop()` del context manager destruye su contexto: cada test que
    llama a `main()` obliga a reconstruir la JVM para el siguiente. Pasaba en
    verde solo porque `getOrCreate` la resucita, y costaba ~1 s por test.
    """

    @contextmanager
    def sesion_de_test(app_name: str = "test"):
        yield spark

    monkeypatch.setattr("etl_kedro.main.spark_session", sesion_de_test)


@pytest.fixture
def csv_con_duplicados(tmp_path):
    path = tmp_path / "ciudades.csv"
    path.write_text(
        "ciudad,habitantes\nmadrid,3200000\nmadrid,999\nbarcelona,1600000\n",
        encoding="utf-8",
    )
    return str(path)


# --- parse_args ---


def test_parse_args_minimos():
    args = parse_args([])

    assert args.job == "ciudades"  # el job por defecto
    assert args.all is False
    assert args.input is None  # sin sobrescribir: se usa la ruta del dataset
    assert args.output is None
    assert args.mode == "overwrite"
    assert args.key_col is None  # sin fijar: cada job aplica la suya
    assert args.log_level == "INFO"


def test_parse_args_acepta_un_job_por_nombre():
    assert parse_args(["--job", "por_ccaa"]).job == "por_ccaa"


def test_parse_args_rechaza_un_job_que_no_existe():
    with pytest.raises(SystemExit):
        parse_args(["--job", "inventado"])


def test_parse_args_all():
    assert parse_args(["--all"]).all is True


def test_parse_args_all_no_admite_rutas():
    # Con --all mandan las rutas declaradas: una sola sobrescritura seria ambigua.
    with pytest.raises(SystemExit):
        parse_args(["--all", "--input", "in.csv"])

    with pytest.raises(SystemExit):
        parse_args(["--all", "--output", "out"])


def test_parse_args_completos():
    args = parse_args(
        [
            "--input",
            "in.csv",
            "--output",
            "out",
            "--mode",
            "append",
            "--key-col",
            "id",
            "--log-level",
            "DEBUG",
        ]
    )

    assert args.mode == "append"
    assert args.key_col == "id"
    assert args.log_level == "DEBUG"


def test_parse_args_rutas_sobrescriben_el_catalogo():
    args = parse_args(["--input", "in.csv", "--output", "out"])

    assert args.input == "in.csv"
    assert args.output == "out"


@pytest.mark.parametrize("valor", ["merge", "OVERWRITE", ""])
def test_parse_args_mode_invalido(valor):
    with pytest.raises(SystemExit):
        parse_args(["--input", "in.csv", "--output", "out", "--mode", valor])


def test_parse_args_log_level_invalido():
    with pytest.raises(SystemExit):
        parse_args(["--input", "in.csv", "--output", "out", "--log-level", "TRACE"])


# --- codigos de salida ---


def test_main_happy_path_devuelve_exit_ok(cli, csv_con_duplicados, tmp_path):
    salida = str(tmp_path / "salida")

    codigo = main(["--input", csv_con_duplicados, "--output", salida])

    assert codigo == EXIT_OK
    assert len(leer_csv_escrito(salida)) == 2


def test_main_lanza_la_cadena_entera(cli, monkeypatch, tmp_path):
    """`--all` encadena los jobs: el segundo lee lo que escribio el primero.

    Los datasets se reapuntan a `tmp_path` con rutas absolutas en vez de hacer
    `chdir`: PySpark resuelve las rutas relativas contra el directorio de la
    JVM, que se fija al arrancarla, asi que un `chdir` posterior no le afecta
    (Sail, en proceso, si lo respeta). Con rutas absolutas da igual el motor.
    """
    entrada = tmp_path / "ciudades.csv"
    entrada.write_text(
        "ciudad,habitantes,comunidad_autonoma\n"
        "madrid,3000000,Comunidad de Madrid\n"
        "alcobendas,100000,Comunidad de Madrid\n"
        "barcelona,1600000,Cataluna\n",
        encoding="utf-8",
    )
    dedup = tmp_path / "dedup"
    final = tmp_path / "por_ccaa"

    monkeypatch.setattr(ciudades_job, "CIUDADES_RAW", replace(CIUDADES_RAW, ruta=str(entrada)))
    monkeypatch.setattr(ciudades_job, "CIUDADES_DEDUP", replace(CIUDADES_DEDUP, ruta=str(dedup)))
    monkeypatch.setattr(por_ccaa_job, "CIUDADES_DEDUP", replace(CIUDADES_DEDUP, ruta=str(dedup)))
    monkeypatch.setattr(
        por_ccaa_job, "POBLACION_POR_CCAA", replace(POBLACION_POR_CCAA, ruta=str(final))
    )

    codigo = main(["--all"])

    assert codigo == EXIT_OK
    # El segundo job ha leido lo que escribio el primero.
    agregado = {f["comunidad_autonoma"]: int(f["habitantes"]) for f in leer_csv_escrito(final)}
    assert agregado == {"Comunidad de Madrid": 3100000, "Cataluna": 1600000}


def test_main_puede_lanzar_un_job_concreto(cli, tmp_path):
    entrada = tmp_path / "dedup.csv"
    entrada.write_text(
        "ciudad,habitantes,comunidad_autonoma\nmadrid,3000000,Comunidad de Madrid\n",
        encoding="utf-8",
    )
    salida = str(tmp_path / "salida")

    codigo = main(["--job", "por_ccaa", "--input", str(entrada), "--output", salida])

    assert codigo == EXIT_OK
    assert leer_csv_escrito(salida) == [
        {"comunidad_autonoma": "Comunidad de Madrid", "habitantes": "3000000"}
    ]


def test_main_backend_invalido_devuelve_exit_backend(monkeypatch, csv_con_duplicados, tmp_path):
    # Con una entrada valida, para que el fallo sea del backend y no de la ruta.
    monkeypatch.setenv("SPARK_BACKEND", "pysprak")

    codigo = main(["--input", csv_con_duplicados, "--output", str(tmp_path / "out")])

    assert codigo == EXIT_BACKEND


def test_main_entrada_inexistente_devuelve_exit_input(tmp_path):
    codigo = main(["--input", str(tmp_path / "no-existe.csv"), "--output", str(tmp_path / "out")])

    assert codigo == EXIT_INPUT


def test_main_columna_clave_inexistente_devuelve_exit_quality(cli, csv_con_duplicados, tmp_path):
    codigo = main(
        ["--input", csv_con_duplicados, "--output", str(tmp_path / "out"), "--key-col", "id"]
    )

    assert codigo == EXIT_QUALITY
    assert not (tmp_path / "out").exists()  # no escribe nada si falla el check
