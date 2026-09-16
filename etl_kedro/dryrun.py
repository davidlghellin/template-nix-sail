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
from etl_kedro.core.datasets import (
    Dataset,
    cabecera_csv,
    problema_de_cabecera,
    se_comprueba_en_local,
)
from etl_kedro.graph import CicloEnElGrafoError, Grafo, ProductorDuplicadoError


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


def entradas_de_la_ejecucion(
    grafo: Grafo,
    config: Config,
    jobs: list[str] | None = None,
    input_path: str | None = None,
) -> list[tuple[Dataset, str]]:
    """Lo que tiene que existir antes de lanzar `jobs`, con la ruta que se leera.

    Es lo que consumen los jobs seleccionados y no produce ninguno de ellos. No
    es lo mismo que las entradas externas del grafo entero: lanzado suelto,
    `por_ccaa` necesita la salida de `ciudades`, y no necesita el CSV de origen.

    `input_path` es el `--input` de la CLI, que solo se admite con un job y
    sustituye la ruta de su entrada tal cual, sin resolverla contra la raiz,
    igual que hace el job al leer.
    """
    seleccion = list(grafo.jobs) if jobs is None else jobs
    producidos = {d.nombre for nombre in seleccion for d in grafo.jobs[nombre].produce}
    entradas: dict[str, tuple[Dataset, str]] = {}
    for nombre in seleccion:
        for dataset in grafo.jobs[nombre].consume:
            if dataset.nombre in producidos or dataset.nombre in entradas:
                continue
            entradas[dataset.nombre] = (dataset, input_path or dataset.resolver(config))
    return [entradas[nombre] for nombre in sorted(entradas)]


def revisar_entradas(
    grafo: Grafo,
    config: Config,
    jobs: list[str] | None = None,
    input_path: str | None = None,
) -> list[Problema]:
    """Las entradas de la ejecucion tienen que existir y traer las columnas declaradas."""
    problemas = []
    for dataset, ruta in entradas_de_la_ejecucion(grafo, config, jobs, input_path):
        nombre = dataset.nombre
        if not se_comprueba_en_local(ruta):
            continue  # remoto o con comodines: lo resuelve el motor al leer
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


def revisar(
    grafo: Grafo,
    config: Config,
    jobs: list[str] | None = None,
    input_path: str | None = None,
) -> list[Problema]:
    """Todas las comprobaciones en seco.

    La coherencia de esquemas es una propiedad del grafo entero y se revisa
    siempre sobre todo el. Las entradas, solo las de los `jobs` que se van a
    lanzar: un job suelto no debe fallar el plan por un fichero que no lee.
    """
    problemas: list[Problema] = []
    try:
        grafo.orden
    except (CicloEnElGrafoError, ProductorDuplicadoError) as exc:
        problemas.append(Problema("grafo", str(exc)))
        return problemas  # sin orden no tiene sentido seguir
    problemas.extend(revisar_esquemas(grafo))
    problemas.extend(revisar_entradas(grafo, config, jobs, input_path))
    return problemas


def render_plan(
    grafo: Grafo,
    config: Config,
    jobs: list[str],
    problemas: list[Problema],
    input_path: str | None = None,
    output_path: str | None = None,
) -> str:
    """Pinta el plan de ejecucion con las rutas que de verdad se usarian.

    `input_path` y `output_path` son los `--input`/`--output` de la CLI: si se
    pasan, el plan los muestra en lugar de las rutas del catalogo, que es lo
    que haria la ejecucion.
    """
    lineas = [f"Plan (entorno={config.entorno}, raiz={config.raiz})", ""]
    for posicion, nombre in enumerate(jobs, start=1):
        job = grafo.jobs[nombre]
        lineas.append(f"{posicion}. {nombre}")
        for dataset in job.consume:
            ruta = input_path or dataset.resolver(config)
            lineas.append(f"     lee     {dataset.nombre:<22} {ruta}")
        for dataset in job.produce:
            ruta = output_path or dataset.resolver(config)
            lineas.append(f"     escribe {dataset.nombre:<22} {ruta}")

    lineas.append("")
    if problemas:
        lineas.append(f"{len(problemas)} problema(s):")
        lineas.extend(str(problema) for problema in problemas)
    else:
        lineas.append("Sin problemas: esquemas coherentes y entradas presentes.")
    return "\n".join(lineas)
