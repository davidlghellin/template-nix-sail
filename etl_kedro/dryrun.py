"""Comprueba el plan de `--all` sin ejecutar nada ni arrancar Spark.

Responde a dos preguntas que solo se contestan bien antes de lanzar:

- **En que orden y contra que rutas** correria en este entorno. Con la raiz
  configurable, "que escribiria en pro" deja de ser evidente.
- **Si los esquemas cuadran** entre quien produce y quien consume, y si los
  ficheros de entrada tienen las columnas que el dataset declara.

La cabecera de un CSV se lee con Python, sin motor: es instantaneo y caza el
fallo mas comun, que el fichero de origen haya cambiado de columnas.
"""

import inspect
from dataclasses import dataclass

from etl_kedro.core.config import Config
from etl_kedro.core.datasets import (
    Dataset,
    EntradaNoEncontradaError,
    cabecera_csv,
    check_input_exists,
    problema_de_cabecera,
    problema_de_formato,
    rutas_solapadas,
    se_comprueba_en_local,
)
from etl_kedro.graph import Grafo, GrafoError


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
        formatos = {d.formato for _, d in declaraciones}
        jobs = ", ".join(sorted({job for job, _ in declaraciones}))
        if len(rutas) > 1:
            problemas.append(
                Problema(nombre, f"declarado con rutas distintas en {jobs}: {sorted(rutas)}")
            )
        elif len(formatos) > 1:
            # Uno escribiria parquet y el otro lo leeria como CSV.
            problemas.append(
                Problema(nombre, f"declarado con formatos distintos en {jobs}: {sorted(formatos)}")
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
        # La misma regla que la ejecucion: un comodin que no casa con nada es
        # una entrada que no existe; un URI no se puede mirar en seco.
        try:
            check_input_exists(ruta)
        except EntradaNoEncontradaError:
            problemas.append(Problema(nombre, f"no existe la entrada: {ruta}"))
            continue
        if not se_comprueba_en_local(ruta):
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
    problema_formato = problema_de_formato(ruta, dataset.formato)
    if problema_formato:
        return [Problema(nombre, problema_formato)]
    if dataset.esquema is None or dataset.formato != "csv":
        return []
    cabecera = cabecera_csv(ruta)
    if cabecera is None:
        return []
    problema = problema_de_cabecera(dataset.esquema, cabecera)
    return [Problema(nombre, problema)] if problema else []


def revisar_solapes(
    grafo: Grafo,
    config: Config,
    jobs: list[str] | None = None,
    input_path: str | None = None,
    output_path: str | None = None,
) -> list[Problema]:
    """Ningun job puede escribir donde lee.

    Spark lee en diferido: con `overwrite` la escritura vacia el destino antes
    de que se lea el origen. Si coinciden, o uno esta dentro del otro, en Sail
    la ejecucion falla con la entrada ya borrada y en PySpark la sustituye en
    silencio por la salida.
    """
    problemas = []
    for nombre in list(grafo.jobs) if jobs is None else jobs:
        job = grafo.jobs[nombre]
        for salida in job.produce:
            destino = output_path or salida.resolver(config)
            for entrada in job.consume:
                origen = input_path or entrada.resolver(config)
                if rutas_solapadas(origen, destino):
                    problemas.append(
                        Problema(
                            nombre,
                            f"escribe {destino} encima de lo que lee ({origen}): "
                            "la entrada se perderia",
                        )
                    )
    return problemas


def revisar_clave(grafo: Grafo, jobs: list[str], key_col: str) -> list[Problema]:
    """La `--key-col` tiene que existir en lo que lee cada job que la usa.

    Sin esto el dry-run daba por bueno un plan que la ejecucion corta con un
    fallo de calidad nada mas leer.
    """
    problemas = []
    for nombre in jobs:
        job = grafo.jobs[nombre]
        if "key_col" not in inspect.signature(job.modulo.run).parameters:
            problemas.append(Problema(nombre, "no admite --key-col"))
            continue
        for dataset in job.consume:
            if dataset.esquema is not None and key_col not in dataset.esquema.fieldNames():
                problemas.append(
                    Problema(
                        nombre,
                        f"--key-col {key_col!r} no es una columna de {dataset.nombre}: "
                        f"{dataset.esquema.fieldNames()}",
                    )
                )
    return problemas


def revisar(
    grafo: Grafo,
    config: Config,
    jobs: list[str] | None = None,
    input_path: str | None = None,
    output_path: str | None = None,
    key_col: str | None = None,
) -> list[Problema]:
    """Todas las comprobaciones en seco.

    La coherencia de esquemas es una propiedad del grafo entero y se revisa
    siempre sobre todo el. Las entradas, solo las de los `jobs` que se van a
    lanzar: un job suelto no debe fallar el plan por un fichero que no lee.
    """
    problemas: list[Problema] = []
    try:
        grafo.orden
    except GrafoError as exc:
        problemas.append(Problema("grafo", str(exc)))
        return problemas  # sin orden no tiene sentido seguir
    problemas.extend(revisar_esquemas(grafo))
    problemas.extend(revisar_solapes(grafo, config, jobs, input_path, output_path))
    problemas.extend(revisar_entradas(grafo, config, jobs, input_path))
    if key_col:
        problemas.extend(revisar_clave(grafo, list(grafo.jobs) if jobs is None else jobs, key_col))
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
