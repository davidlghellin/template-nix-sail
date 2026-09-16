"""Tests de la CLI: argumentos y codigos de salida."""

import csv
import glob
import os
from dataclasses import replace
from typing import cast

import pytest
from pyspark.sql import SparkSession

from etl_kedro.core.config import Config
from etl_kedro.main import (
    EXIT_BACKEND,
    EXIT_CONFIG,
    EXIT_DRY_RUN,
    EXIT_ERROR,
    EXIT_INPUT,
    EXIT_OK,
    EXIT_QUALITY,
    ejecutar_job,
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
def csv_con_duplicados(escribir_ciudades):
    return escribir_ciudades(
        [
            ("madrid", 3200000, "Madrid", "Comunidad de Madrid", 604.3),
            ("madrid", 999, "Madrid", "Comunidad de Madrid", 604.3),
            ("barcelona", 1600000, "Barcelona", "Cataluna", 101.4),
        ]
    )


# --- parse_args ---


def test_parse_args_minimos():
    args = parse_args([])

    assert args.job == "ciudades"  # el job por defecto
    assert args.all is False
    assert args.input is None  # sin sobrescribir: se usa la ruta del dataset
    assert args.output is None
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
            "--key-col",
            "id",
            "--log-level",
            "DEBUG",
        ]
    )

    assert args.key_col == "id"
    assert args.log_level == "DEBUG"


def test_parse_args_rutas_sobrescriben_el_catalogo():
    args = parse_args(["--input", "in.csv", "--output", "out"])

    assert args.input == "in.csv"
    assert args.output == "out"


def test_parse_args_log_level_invalido():
    with pytest.raises(SystemExit):
        parse_args(["--input", "in.csv", "--output", "out", "--log-level", "TRACE"])


# --- codigos de salida ---


def test_main_happy_path_devuelve_exit_ok(cli, csv_con_duplicados, tmp_path):
    salida = str(tmp_path / "salida")

    codigo = main(["--input", csv_con_duplicados, "--output", salida])

    assert codigo == EXIT_OK
    assert len(leer_csv_escrito(salida)) == 2


def test_main_lanza_la_cadena_entera(cli, reapuntar_cadena, escribir_ciudades):
    """`--all` encadena los jobs: el segundo lee lo que escribio el primero."""
    entrada = escribir_ciudades(
        [
            ("madrid", 3000000, "Madrid", "Comunidad de Madrid", 604.3),
            ("alcobendas", 100000, "Madrid", "Comunidad de Madrid", 45.0),
            ("barcelona", 1600000, "Barcelona", "Cataluna", 101.4),
        ]
    )
    _, final = reapuntar_cadena(entrada)

    codigo = main(["--all"])

    assert codigo == EXIT_OK
    # El segundo job ha leido lo que escribio el primero.
    agregado = {f["comunidad_autonoma"]: int(f["habitantes"]) for f in leer_csv_escrito(final)}
    assert agregado == {"Comunidad de Madrid": 3100000, "Cataluna": 1600000}


def test_main_puede_lanzar_un_job_concreto(cli, tmp_path, escribir_ciudades):
    entrada = escribir_ciudades(
        [("madrid", 3000000, "Madrid", "Comunidad de Madrid", 604.3)], nombre="dedup.csv"
    )
    salida = str(tmp_path / "salida")

    codigo = main(["--job", "por_ccaa", "--input", entrada, "--output", salida])

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


def test_main_columna_clave_inexistente_se_rechaza_antes_de_spark(
    monkeypatch, csv_con_duplicados, tmp_path
):
    # Es un argumento invalido, no un dato roto: sale como los demas (codigo 5).
    monkeypatch.setattr(
        "etl_kedro.main.spark_session", lambda *_: pytest.fail("no deberia arrancar Spark")
    )

    codigo = main(
        ["--input", csv_con_duplicados, "--output", str(tmp_path / "out"), "--key-col", "id"]
    )

    assert codigo == EXIT_CONFIG
    assert not (tmp_path / "out").exists()  # no escribe nada si falla el check


# --- ejecutar_job: solo se pasa lo que el usuario pidio ---


# `ejecutar_job` solo pasa la sesion al job, y el espia no la usa: estos tests
# son de cableado y no levantan Spark.
SIN_SESION = cast(SparkSession, None)


@pytest.fixture
def job_espia(monkeypatch):
    """Sustituye `load_job` por un job que anota con que opciones lo llaman."""
    recibido: dict[str, object] = {}

    def run_falso(spark, **opciones):
        recibido.update(opciones)

    modulo = type("modulo", (), {"run": staticmethod(run_falso)})
    monkeypatch.setattr(
        "etl_kedro.main.load_job",
        lambda nombre: type("Job", (), {"modulo": modulo}),
    )
    return recibido


def test_ejecutar_job_no_pasa_lo_que_no_se_ha_pedido(job_espia):
    """Sin --input/--output/--key-col no se pasan esas claves, ni como None.

    Asi cada job aplica su propio valor por defecto (su clave, sus rutas) en vez
    de recibir un centinela que tenga que interpretar.
    """
    ejecutar_job(SIN_SESION, "ciudades", parse_args([]), Config())

    assert "input_path" not in job_espia
    assert "output_path" not in job_espia
    assert "key_col" not in job_espia


def test_ejecutar_job_pasa_lo_que_si_se_ha_pedido(job_espia):
    args = parse_args(["--input", "in.csv", "--output", "out", "--key-col", "ciudad"])

    ejecutar_job(SIN_SESION, "ciudades", args, Config())

    assert job_espia["input_path"] == "in.csv"
    assert job_espia["output_path"] == "out"
    assert job_espia["key_col"] == "ciudad"


def test_parse_args_all_no_admite_key_col():
    # La clave es de cada job: una sola para toda la cadena rompe al menos uno.
    with pytest.raises(SystemExit):
        parse_args(["--all", "--key-col", "ciudad"])


def test_main_comprueba_las_entradas_del_catalogo_antes_de_arrancar_spark(monkeypatch, tmp_path):
    """Sin --input, la entrada del catalogo tambien se comprueba antes de la sesion."""

    def sesion_prohibida(*_args, **_kwargs):
        raise AssertionError("no deberia arrancar Spark para una entrada que no existe")

    monkeypatch.setattr("etl_kedro.main.spark_session", sesion_prohibida)
    monkeypatch.setenv("ETL_DATA_ROOT", str(tmp_path))  # una raiz vacia

    codigo = main(["--job", "por_ccaa"])

    assert codigo == EXIT_INPUT


def test_main_dry_run_de_un_job_revisa_la_ruta_de_input(tmp_path, capsys):
    codigo = main(["--dry-run", "--input", str(tmp_path / "no-existe.csv")])

    salida = capsys.readouterr().out
    assert codigo == EXIT_DRY_RUN
    assert "no-existe.csv" in salida


def test_main_no_escribe_encima_de_su_entrada(tmp_path, monkeypatch, escribir_ciudades):
    """Misma ruta de entrada y salida: se rechaza antes de tocar nada.

    Sin esto, en Sail la entrada se borraba antes de leerla y en PySpark se
    sustituia en silencio por la salida.
    """
    entrada = escribir_ciudades([("madrid", 1, "Madrid", "Comunidad de Madrid", 1.0)])
    directorio = os.path.dirname(entrada)
    monkeypatch.setattr(
        "etl_kedro.main.spark_session",
        lambda *_: pytest.fail("no deberia arrancar Spark"),
    )

    codigo = main(["--input", directorio, "--output", directorio])

    assert codigo == EXIT_CONFIG
    assert os.path.exists(entrada)


@pytest.fixture
def grafo_con_ciclo(monkeypatch):
    from etl_kedro.graph import discover_jobs

    grafo = discover_jobs()
    ciudades, por_ccaa = grafo.jobs["ciudades"], grafo.jobs["por_ccaa"]
    grafo.jobs["ciudades"] = replace(ciudades, consume=por_ccaa.produce)
    monkeypatch.setattr("etl_kedro.main.discover_jobs", lambda: grafo)


def test_main_dry_run_informa_de_un_ciclo_en_vez_de_romper(grafo_con_ciclo, capsys):
    codigo = main(["--all", "--dry-run"])

    assert codigo == EXIT_DRY_RUN
    assert "ciclo" in capsys.readouterr().out


def test_main_un_grafo_invalido_es_error_de_configuracion(grafo_con_ciclo):
    assert main(["--all"]) == EXIT_CONFIG


def test_un_argumento_invalido_no_sale_con_el_codigo_de_calidad():
    # argparse sale con 2, que aqui es un fallo de dato: un comando mal escrito
    # tiene que distinguirse en el orquestador.
    with pytest.raises(SystemExit) as salida:
        parse_args(["--all", "--input", "x"])

    assert salida.value.code == EXIT_CONFIG
    assert EXIT_CONFIG != EXIT_QUALITY


def test_un_fichero_que_falta_en_el_motor_no_es_una_entrada_no_encontrada(
    monkeypatch, escribir_ciudades, tmp_path
):
    """Solo las entradas de la ETL salen con codigo 4.

    Un `SPARK_HOME` roto tambien lanza `FileNotFoundError`, y presentarlo como
    "entrada no encontrada" mandaria a buscar un CSV que si esta.
    """
    entrada = escribir_ciudades([("madrid", 1, "Madrid", "Comunidad de Madrid", 1.0)])

    def motor_roto(*_args, **_kwargs):
        raise FileNotFoundError("/no/existe/bin/spark-submit")

    monkeypatch.setattr("etl_kedro.main.spark_session", motor_roto)

    codigo = main(["--input", entrada, "--output", str(tmp_path / "out")])

    assert codigo == EXIT_ERROR


def test_parse_args_all_no_admite_job():
    # Antes se ignoraba `--job` y se lanzaba la cadena entera.
    with pytest.raises(SystemExit):
        parse_args(["--all", "--job", "por_ccaa"])


def test_main_dry_run_avisa_de_una_clave_que_no_existe(capsys):
    codigo = main(["--job", "ciudades", "--key-col", "no_existe", "--dry-run"])

    assert codigo == EXIT_DRY_RUN
    assert "no_existe" in capsys.readouterr().out


def test_main_un_comodin_sin_coincidencias_no_toca_la_salida(tmp_path, monkeypatch):
    salida = tmp_path / "salida"
    salida.mkdir()
    (salida / "previa.csv").write_text("dato,previo\n", encoding="utf-8")
    monkeypatch.setattr(
        "etl_kedro.main.spark_session", lambda *_: pytest.fail("no deberia arrancar Spark")
    )

    codigo = main(["--input", str(tmp_path / "no_casa*.csv"), "--output", str(salida)])

    assert codigo == EXIT_INPUT
    assert (salida / "previa.csv").exists()


def test_main_dry_run_avisa_de_un_comodin_sin_coincidencias(tmp_path, capsys):
    codigo = main(["--dry-run", "--input", str(tmp_path / "no_casa*.csv")])

    assert codigo == EXIT_DRY_RUN
    assert "no existe la entrada" in capsys.readouterr().out
