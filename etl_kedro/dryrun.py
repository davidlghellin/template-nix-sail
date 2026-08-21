"""Comprueba el plan de `--all` sin ejecutar nada ni arrancar Spark.

Responde a dos preguntas que solo se contestan bien antes de lanzar:

- **En que orden y contra que rutas** correria en este entorno. Con la raiz
  configurable, "que escribiria en pro" deja de ser evidente.
- **Si los esquemas cuadran** entre quien produce y quien consume, y si los
  ficheros de entrada tienen las columnas que el dataset declara.

La cabecera de un CSV se lee con Python, sin motor: es instantaneo y caza el
fallo mas comun, que el fichero de origen haya cambiado de columnas.
"""

from dataclasses import dataclass
from pathlib import Path

from etl_kedro.core.config import Config
from etl_kedro.core.datasets import Dataset, cabecera_csv, problema_de_cabecera
from etl_kedro.graph import CicloEnElGrafoError, Grafo


@dataclass(frozen=True)
class Problema:
    """Algo que impediria, o estropearia, la ejecucion."""

    donde: str
    mensaje: str

    def __str__(self) -> str:
        return f"  [{self.donde}] {self.mensaje}"


def _declaraciones(grafo: Grafo) -> dict[str, list[tuple[str, Dataset]]]:
    """Dataset -> todas las veces que se declara, y desde que job."""
    por_nombre: dict[str, list[tuple[str, Dataset]]] = {}
    for job in grafo.jobs.values():
        for dataset in job.consume + job.produce:
            por_nombre.setdefault(dataset.nombre, []).append((job.nombre, dataset))
    return por_nombre


def revisar_esquemas(grafo: Grafo) -> list[Problema]:
    """Un mismo dataset no puede declararse con dos esquemas o dos rutas.

    Si el consumidor importa el dataset del productor, esto se cumple solo: es
    el mismo objeto. Salta cuando alguien lo redeclara por su cuenta en vez de
    importarlo, que es como se rompe la cadena sin que se note.
    """
    problemas = []
    for nombre, declaraciones in sorted(_declaraciones(grafo).items()):
        esquemas = {id(d.esquema) for _, d in declaraciones}
        rutas = {d.ruta for _, d in declaraciones}
        jobs = ", ".join(sorted({job for job, _ in declaraciones}))
        if len(rutas) > 1:
            problemas.append(
                Problema(nombre, f"declarado con rutas distintas en {jobs}: {sorted(rutas)}")
            )
        elif len(esquemas) > 1:
            problemas.append(
                Problema(
                    nombre,
                    f"declarado con esquemas distintos en {jobs}: "
                    "importa el dataset del job que lo produce en vez de redeclararlo",
                )
            )
    return problemas


def revisar_entradas(grafo: Grafo, config: Config) -> list[Problema]:
    """Las entradas externas tienen que existir y traer las columnas declaradas."""
    problemas = []
    externas = set(grafo.entradas_externas)
    for nombre, declaraciones in sorted(_declaraciones(grafo).items()):
        if nombre not in externas:
            continue
        dataset = declaraciones[0][1]
        ruta = dataset.resolver(config)
        if "://" in ruta:
            continue  # remoto: no se comprueba en seco
        if not Path(ruta).exists():
            problemas.append(Problema(nombre, f"no existe la entrada: {ruta}"))
            continue
        problemas.extend(_revisar_cabecera(nombre, dataset, ruta))
    return problemas


def _revisar_cabecera(nombre: str, dataset: Dataset, ruta: str) -> list[Problema]:
    """Compara la cabecera del CSV con las columnas del esquema declarado.

    Es la misma comprobacion que hace `ETLPipeline.read_dataset` al leer: aqui
    se lista como problema del plan y alli corta la ejecucion. Una sola
    implementacion, para que el dry-run no pueda dar por bueno lo que luego
    falla al ejecutar.
    """
    if dataset.esquema is None or dataset.formato != "csv":
        return []
    cabecera = cabecera_csv(ruta)
    if cabecera is None:
        return []
    problema = problema_de_cabecera(dataset.esquema, cabecera)
    return [Problema(nombre, problema)] if problema else []


def revisar(grafo: Grafo, config: Config) -> list[Problema]:
    """Todas las comprobaciones en seco."""
    problemas: list[Problema] = []
    try:
        grafo.orden
    except CicloEnElGrafoError as exc:
        problemas.append(Problema("grafo", str(exc)))
        return problemas  # sin orden no tiene sentido seguir
    problemas.extend(revisar_esquemas(grafo))
    problemas.extend(revisar_entradas(grafo, config))
    return problemas


def render_plan(grafo: Grafo, config: Config, jobs: list[str], problemas: list[Problema]) -> str:
    """Pinta el plan de ejecucion con las rutas ya resueltas."""
    lineas = [f"Plan (entorno={config.entorno}, raiz={config.raiz})", ""]
    for posicion, nombre in enumerate(jobs, start=1):
        job = grafo.jobs[nombre]
        lineas.append(f"{posicion}. {nombre}")
        for dataset in job.consume:
            lineas.append(f"     lee     {dataset.nombre:<22} {dataset.resolver(config)}")
        for dataset in job.produce:
            lineas.append(f"     escribe {dataset.nombre:<22} {dataset.resolver(config)}")

    lineas.append("")
    if problemas:
        lineas.append(f"{len(problemas)} problema(s):")
        lineas.extend(str(problema) for problema in problemas)
    else:
        lineas.append("Sin problemas: esquemas coherentes y entradas presentes.")
    return "\n".join(lineas)
