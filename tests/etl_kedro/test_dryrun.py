"""Tests del dry-run: plan, esquemas y entradas, todo sin arrancar Spark."""

from dataclasses import replace

import pytest
from pyspark.sql.types import StringType, StructField, StructType

from etl_kedro.core.config import Config
from etl_kedro.core.datasets import Dataset
from etl_kedro.dryrun import render_plan, revisar, revisar_entradas, revisar_esquemas
from etl_kedro.graph import Grafo, Job, discover_jobs

ESQUEMA = StructType(
    [StructField("ciudad", StringType(), True), StructField("habitantes", StringType(), True)]
)
OTRO_ESQUEMA = StructType([StructField("otra", StringType(), True)])


def job_falso(nombre, consume=(), produce=()):
    return Job(nombre=nombre, modulo=None, consume=consume, produce=produce)  # type: ignore[arg-type]


@pytest.fixture
def csv_correcto(tmp_path):
    path = tmp_path / "entrada.csv"
    path.write_text("ciudad,habitantes\nmadrid,3200000\n", encoding="utf-8")
    return path


# --- el proyecto de verdad ---


def test_el_grafo_real_no_tiene_problemas():
    # La cadena que hay en el repo tiene que pasar el dry-run en dev.
    assert revisar(discover_jobs(), Config()) == []


def test_el_plan_lista_los_jobs_en_orden():
    grafo = discover_jobs()

    plan = render_plan(grafo, Config(), grafo.orden, [])

    assert "1. ciudades" in plan
    assert "2. por_ccaa" in plan
    assert "Sin problemas" in plan


def test_el_plan_muestra_las_rutas_del_entorno():
    grafo = discover_jobs()
    config = Config(entorno="pro", raiz="s3://bucket/oro")

    plan = render_plan(grafo, config, grafo.orden, [])

    assert "entorno=pro" in plan
    assert "s3://bucket/oro/data/ciudades_dedup" in plan


# --- esquemas ---


def test_esquemas_coherentes_cuando_se_importa_el_dataset(csv_correcto):
    # El consumidor usa el mismo objeto que el productor: no hay nada que casar.
    compartido = Dataset("intermedio", "data/intermedio", ESQUEMA)
    grafo = Grafo(
        jobs={
            "a": job_falso("a", produce=(compartido,)),
            "b": job_falso("b", consume=(compartido,)),
        }
    )

    assert revisar_esquemas(grafo) == []


def test_detecta_el_mismo_dataset_con_dos_esquemas():
    # El fallo clasico: redeclararlo en vez de importarlo.
    productor = Dataset("intermedio", "data/intermedio", ESQUEMA)
    copia = Dataset("intermedio", "data/intermedio", OTRO_ESQUEMA)
    grafo = Grafo(
        jobs={"a": job_falso("a", produce=(productor,)), "b": job_falso("b", consume=(copia,))}
    )

    problemas = revisar_esquemas(grafo)

    assert len(problemas) == 1
    assert "esquemas distintos" in problemas[0].mensaje


def test_detecta_el_mismo_dataset_con_dos_rutas():
    productor = Dataset("intermedio", "data/aqui", ESQUEMA)
    copia = Dataset("intermedio", "data/alli", ESQUEMA)
    grafo = Grafo(
        jobs={"a": job_falso("a", produce=(productor,)), "b": job_falso("b", consume=(copia,))}
    )

    problemas = revisar_esquemas(grafo)

    assert len(problemas) == 1
    assert "rutas distintas" in problemas[0].mensaje


# --- entradas ---


def test_entrada_externa_correcta(csv_correcto):
    entrada = Dataset("entrada", str(csv_correcto), ESQUEMA)
    grafo = Grafo(jobs={"a": job_falso("a", consume=(entrada,))})

    assert revisar_entradas(grafo, Config()) == []


def test_detecta_que_falta_la_entrada(tmp_path):
    entrada = Dataset("entrada", str(tmp_path / "no-existe.csv"), ESQUEMA)
    grafo = Grafo(jobs={"a": job_falso("a", consume=(entrada,))})

    problemas = revisar_entradas(grafo, Config())

    assert len(problemas) == 1
    assert "no existe la entrada" in problemas[0].mensaje


def test_detecta_columnas_que_faltan_en_el_fichero(tmp_path):
    # El caso real: el CSV de origen ha cambiado de columnas.
    path = tmp_path / "entrada.csv"
    path.write_text("ciudad,poblacion\nmadrid,1\n", encoding="utf-8")
    entrada = Dataset("entrada", str(path), ESQUEMA)
    grafo = Grafo(jobs={"a": job_falso("a", consume=(entrada,))})

    problemas = revisar_entradas(grafo, Config())

    assert len(problemas) == 1
    assert "habitantes" in problemas[0].mensaje


def test_no_comprueba_las_entradas_remotas():
    # Un s3:// no se puede mirar en seco: se deja pasar en vez de dar un falso error.
    entrada = Dataset("entrada", "s3://bucket/datos.csv", ESQUEMA)
    grafo = Grafo(jobs={"a": job_falso("a", consume=(entrada,))})

    assert revisar_entradas(grafo, Config()) == []


def test_un_dataset_sin_esquema_no_se_comprueba(csv_correcto):
    entrada = Dataset("entrada", str(csv_correcto), esquema=None)
    grafo = Grafo(jobs={"a": job_falso("a", consume=(entrada,))})

    assert revisar_entradas(grafo, Config()) == []


def test_lee_la_cabecera_de_un_directorio_de_partes(tmp_path):
    # Salida de Spark: un directorio con part-*.csv, no un fichero suelto.
    directorio = tmp_path / "salida"
    directorio.mkdir()
    (directorio / "part-00000.csv").write_text("ciudad,habitantes\nmadrid,1\n", encoding="utf-8")
    entrada = Dataset("entrada", str(directorio), ESQUEMA)
    grafo = Grafo(jobs={"a": job_falso("a", consume=(entrada,))})

    assert revisar_entradas(grafo, Config()) == []


def test_el_plan_lista_los_problemas(tmp_path):
    entrada = Dataset("entrada", str(tmp_path / "no-existe.csv"), ESQUEMA)
    grafo = Grafo(jobs={"a": job_falso("a", consume=(entrada,), produce=())})
    problemas = revisar(grafo, Config())

    plan = render_plan(grafo, Config(), ["a"], problemas)

    assert "1 problema(s):" in plan
    assert "[entrada]" in plan


def test_un_ciclo_se_reporta_como_problema():
    a_out = Dataset("de_a", "data/a", ESQUEMA)
    b_out = Dataset("de_b", "data/b", ESQUEMA)
    grafo = Grafo(
        jobs={
            "a": job_falso("a", consume=(b_out,), produce=(a_out,)),
            "b": job_falso("b", consume=(a_out,), produce=(b_out,)),
        }
    )

    problemas = revisar(grafo, Config())

    assert len(problemas) == 1
    assert "ciclo" in problemas[0].mensaje


def test_dataset_resolver_usa_la_config():
    dataset = Dataset("x", "data/x", ESQUEMA)

    assert dataset.resolver(Config(entorno="pro", raiz="/lago")) == "/lago/data/x"
    assert replace(dataset, ruta="/fijo/x").resolver(Config(raiz="/lago")) == "/fijo/x"
