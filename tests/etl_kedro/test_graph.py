"""Tests del grafo de jobs derivado de los `CONSUME` / `PRODUCE`.

No levantan Spark: leen lo que cada job declara. Son los que avisan de que la
cadena se ha roto sin necesidad de ejecutar nada.
"""

import sys
from dataclasses import replace

import pytest

from etl_kedro.graph import (
    CicloEnElGrafoError,
    JobDesconocidoError,
    discover_jobs,
    load_job,
    main,
    nombres_de_jobs,
    render,
    render_mermaid,
)
from etl_kedro.jobs.ciudades.datasets import CIUDADES_DEDUP


def test_descubre_los_jobs_del_paquete():
    grafo = discover_jobs()

    assert {"ciudades", "por_ccaa"} <= set(grafo.jobs)


def test_todo_job_declara_consume_y_produce():
    # Un job sin declarar queda invisible en el grafo, que es peor que no estar.
    for nombre, job in discover_jobs().jobs.items():
        assert job.produce, f"{nombre} no declara PRODUCE"
        assert job.consume, f"{nombre} no declara CONSUME"


def test_ningun_dataset_lo_producen_dos_jobs():
    # Dos productores del mismo nombre hacen ambiguo el grafo.
    producidos = [d.nombre for job in discover_jobs().jobs.values() for d in job.produce]

    assert len(producidos) == len(set(producidos))


def test_la_cadena_enlaza_ciudades_con_por_ccaa():
    grafo = discover_jobs()

    assert ("ciudades", "por_ccaa", CIUDADES_DEDUP.nombre) in grafo.aristas


def test_el_productor_de_cada_dataset_es_unico():
    grafo = discover_jobs()

    assert grafo.productor_de[CIUDADES_DEDUP.nombre] == "ciudades"


def test_entradas_externas_y_salidas_finales():
    grafo = discover_jobs()

    # `ciudades_raw` no lo produce nadie: es el origen de la cadena.
    assert "ciudades_raw" in grafo.entradas_externas
    # `poblacion_por_ccaa` no lo consume nadie: es el final.
    assert "poblacion_por_ccaa" in grafo.salidas_finales
    # El intermedio no es ni una cosa ni la otra.
    assert CIUDADES_DEDUP.nombre not in grafo.entradas_externas
    assert CIUDADES_DEDUP.nombre not in grafo.salidas_finales


def test_render_muestra_jobs_y_cadena():
    salida = render(discover_jobs())

    assert "ciudades" in salida
    assert "por_ccaa" in salida
    assert "ciudades -> por_ccaa" in salida
    assert "(de ciudades)" in salida  # marca la procedencia del intermedio


# --- descubrimiento perezoso ---


@pytest.fixture
def sin_jobs_importados(monkeypatch):
    """Descarga los modulos de los jobs y los repone al terminar.

    Con `sys.modules.pop` a pelo, el modulo se reimporta luego como un objeto
    nuevo y cualquier `monkeypatch` que otro test hiciera sobre el viejo deja de
    aplicar. `delitem` restaura el original en el teardown.
    """
    for nombre in nombres_de_jobs():
        monkeypatch.delitem(sys.modules, f"etl_kedro.jobs.{nombre}.job", raising=False)


def test_nombres_de_jobs_no_importa_ninguno(sin_jobs_importados):
    """Listar no debe cargar codigo: con 150 jobs eso se paga en cada ejecucion."""
    nombres = nombres_de_jobs()

    assert {"ciudades", "por_ccaa"} <= set(nombres)
    assert all(f"etl_kedro.jobs.{n}.job" not in sys.modules for n in nombres)


def test_load_job_importa_solo_el_pedido(sin_jobs_importados):
    load_job("ciudades")

    assert "etl_kedro.jobs.ciudades.job" in sys.modules
    assert "etl_kedro.jobs.por_ccaa.job" not in sys.modules


def test_load_job_devuelve_lo_declarado():
    job = load_job("por_ccaa")

    assert job.nombre == "por_ccaa"
    assert job.consume and job.produce


def test_load_job_con_un_nombre_que_no_existe():
    with pytest.raises(JobDesconocidoError, match="No existe el job"):
        load_job("inventado")


def test_el_nombre_del_job_es_el_de_su_carpeta():
    # `nombres_de_jobs` lista carpetas sin importar; si `NOMBRE` no coincidiera,
    # la CLI y el grafo hablarian de jobs distintos.
    for nombre, job in discover_jobs().jobs.items():
        declarado = getattr(job.modulo, "NOMBRE", nombre)
        assert declarado == nombre, f"{nombre}: NOMBRE declarado es {declarado!r}"


# --- orden de ejecucion ---


def test_orden_respeta_las_dependencias():
    orden = discover_jobs().orden

    assert orden.index("ciudades") < orden.index("por_ccaa")


def test_orden_incluye_todos_los_jobs():
    grafo = discover_jobs()

    assert sorted(grafo.orden) == sorted(grafo.jobs)


def test_orden_es_estable():
    # Mismo grafo, mismo orden: la salida no puede bailar entre ejecuciones.
    assert discover_jobs().orden == discover_jobs().orden


def test_orden_detecta_ciclos():
    grafo = discover_jobs()
    # Se cruzan las tuplas: cada uno consume lo que produce el otro.
    ciudades, por_ccaa = grafo.jobs["ciudades"], grafo.jobs["por_ccaa"]
    grafo.jobs["ciudades"] = replace(ciudades, consume=por_ccaa.produce)

    with pytest.raises(CicloEnElGrafoError, match="ciclo"):
        _ = grafo.orden


# --- mermaid ---


def test_mermaid_es_un_flowchart():
    assert render_mermaid(discover_jobs()).startswith("flowchart LR")


def test_mermaid_dibuja_la_cadena_completa():
    salida = render_mermaid(discover_jobs())

    # Origen -> job -> intermedio -> job -> final.
    assert "ciudades_raw[(ciudades_raw)] --> ciudades" in salida
    assert "ciudades --> ciudades_dedup[(ciudades_dedup)]" in salida
    assert "ciudades_dedup[(ciudades_dedup)] --> por_ccaa" in salida
    assert "por_ccaa --> poblacion_por_ccaa[(poblacion_por_ccaa)]" in salida


def test_mermaid_colorea_segun_el_papel_de_cada_nodo():
    # El color sale de entradas_externas/salidas_finales, no esta escrito a mano.
    salida = render_mermaid(discover_jobs())

    assert "class ciudades,por_ccaa job" in salida
    assert "class ciudades_raw externo" in salida
    assert "class poblacion_por_ccaa final" in salida


def test_mermaid_declara_un_nodo_por_job():
    salida = render_mermaid(discover_jobs())

    for nombre in discover_jobs().jobs:
        assert f"{nombre}([{nombre}])" in salida


def test_las_dos_vistas_nombran_los_mismos_datasets():
    # Texto y diagrama salen del mismo grafo: no pueden contradecirse.
    grafo = discover_jobs()
    texto = render(grafo)
    mermaid = render_mermaid(grafo)

    for job in grafo.jobs.values():
        for dataset in job.consume + job.produce:
            assert dataset.nombre in texto
            assert dataset.nombre in mermaid


# --- CLI ---


@pytest.mark.parametrize("argv", [[], ["--format", "text"], ["--format", "mermaid"]])
def test_main_devuelve_cero(argv, capsys):
    assert main(argv) == 0
    assert capsys.readouterr().out.strip()


def test_main_por_defecto_imprime_texto(capsys):
    main([])

    assert "Cadena:" in capsys.readouterr().out


def test_main_con_mermaid_imprime_el_diagrama(capsys):
    main(["--format", "mermaid"])

    assert "flowchart LR" in capsys.readouterr().out


def test_main_rechaza_un_formato_desconocido():
    with pytest.raises(SystemExit):
        main(["--format", "svg"])
