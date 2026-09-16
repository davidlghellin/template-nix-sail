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


def test_todo_job_produce_algo():
    # Que declare CONSUME y PRODUCE ya lo exige `load_job`. `CONSUME = ()` es
    # valido para un job de origen; uno que no produce nada no aporta a la cadena.
    for nombre, job in discover_jobs().jobs.items():
        assert job.produce, f"{nombre} no produce ningun dataset"


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
    # A igualdad de dependencias, por nombre. Los jobs se insertan al reves para
    # que el test no pase por el orden en que se descubren.
    from etl_kedro.graph import Grafo, Job

    def job_suelto(nombre):
        return Job(nombre=nombre, modulo=None, consume=(), produce=())  # type: ignore[arg-type]

    grafo = Grafo(jobs={"b": job_suelto("b"), "a": job_suelto("a")})

    assert grafo.orden == ["a", "b"]


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
    assert "ds_ciudades_raw[(ciudades_raw)] --> job_ciudades" in salida
    assert "job_ciudades --> ds_ciudades_dedup[(ciudades_dedup)]" in salida
    assert "ds_ciudades_dedup[(ciudades_dedup)] --> job_por_ccaa" in salida
    assert "job_por_ccaa --> ds_poblacion_por_ccaa[(poblacion_por_ccaa)]" in salida


def test_mermaid_colorea_segun_el_papel_de_cada_nodo():
    # El color sale de entradas_externas/salidas_finales, no esta escrito a mano.
    salida = render_mermaid(discover_jobs())

    assert "class job_ciudades,job_por_ccaa job" in salida
    assert "class ds_ciudades_raw externo" in salida
    assert "class ds_poblacion_por_ccaa final" in salida


def test_mermaid_declara_un_nodo_por_job():
    salida = render_mermaid(discover_jobs())

    for nombre in discover_jobs().jobs:
        assert f"job_{nombre}([{nombre}])" in salida


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


def test_un_dataset_con_dos_productores_es_un_error():
    from etl_kedro.graph import Grafo, Job, ProductorDuplicadoError

    def job_falso(nombre):
        return Job(nombre=nombre, modulo=None, consume=(), produce=(CIUDADES_DEDUP,))  # type: ignore[arg-type]

    grafo = Grafo(jobs={"a": job_falso("a"), "b": job_falso("b")})

    with pytest.raises(ProductorDuplicadoError, match="a, b"):
        grafo.productor_de


def test_un_job_sin_declarar_consume_o_produce_no_se_carga(monkeypatch):
    import types

    from etl_kedro.graph import JobMalDeclaradoError

    sin_declarar = types.ModuleType("etl_kedro.jobs.ciudades.job")
    sin_declarar.PRODUCE = ()  # type: ignore[attr-defined]
    monkeypatch.setattr("etl_kedro.graph.importlib.import_module", lambda _: sin_declarar)

    with pytest.raises(JobMalDeclaradoError, match="CONSUME"):
        load_job("ciudades")


def test_un_job_sin_run_no_se_carga(monkeypatch):
    import types

    from etl_kedro.graph import JobMalDeclaradoError

    sin_run = types.ModuleType("etl_kedro.jobs.ciudades.job")
    sin_run.CONSUME = ()  # type: ignore[attr-defined]
    sin_run.PRODUCE = ()  # type: ignore[attr-defined]
    monkeypatch.setattr("etl_kedro.graph.importlib.import_module", lambda _: sin_run)

    with pytest.raises(JobMalDeclaradoError, match="run"):
        load_job("ciudades")


def test_una_carpeta_sin_job_py_no_es_un_job(tmp_path, monkeypatch):
    # Un paquete de utilidades compartidas dentro de `jobs/` no se lista.
    import etl_kedro.jobs

    comun = tmp_path / "comun"
    comun.mkdir()
    (comun / "__init__.py").touch()
    monkeypatch.setattr(etl_kedro.jobs, "__path__", [*etl_kedro.jobs.__path__, str(tmp_path)])

    assert "comun" not in nombres_de_jobs()
    assert "ciudades" in nombres_de_jobs()


def test_main_con_un_grafo_invalido_no_revienta(monkeypatch, capsys):
    from etl_kedro.graph import CicloEnElGrafoError

    def grafo_roto():
        raise CicloEnElGrafoError("Hay un ciclo entre los jobs: a, b")

    monkeypatch.setattr("etl_kedro.graph.discover_jobs", grafo_roto)

    assert main([]) == 1
    assert "ciclo" in capsys.readouterr().err


def test_un_job_sin_init_py_se_lista_y_falla_al_cargar(tmp_path, monkeypatch):
    # Antes desaparecia de `--all` sin avisar; ahora se ve y dice que le falta.
    import etl_kedro.jobs
    from etl_kedro.graph import JobMalDeclaradoError

    ventas = tmp_path / "ventas"
    ventas.mkdir()
    (ventas / "job.py").write_text("CONSUME = ()\nPRODUCE = ()\ndef run(spark): ...\n")
    monkeypatch.setattr(etl_kedro.jobs, "__path__", [*etl_kedro.jobs.__path__, str(tmp_path)])

    assert "ventas" in nombres_de_jobs()
    with pytest.raises(JobMalDeclaradoError, match="__init__.py"):
        load_job("ventas")


def test_mermaid_no_funde_un_job_y_un_dataset_con_el_mismo_nombre():
    from etl_kedro.core.datasets import Dataset
    from etl_kedro.graph import Grafo, Job

    ventas = Dataset("ventas", "data/ventas")
    guion, bajo = Dataset("a-b", "data/x"), Dataset("a_b", "data/y")
    job = Job(nombre="ventas", modulo=None, consume=(guion, bajo), produce=(ventas,))  # type: ignore[arg-type]

    salida = render_mermaid(Grafo(jobs={"ventas": job}))

    assert "job_ventas --> ds_ventas[(ventas)]" in salida
    assert "ds_a_2d_b" in salida and "ds_a_b" in salida
