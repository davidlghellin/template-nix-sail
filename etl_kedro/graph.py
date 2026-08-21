"""Deriva y pinta la cadena de jobs a partir de sus `CONSUME` / `PRODUCE`.

La foto global no se mantiene a mano: se descubre recorriendo `etl_kedro.jobs` y
leyendo lo que cada job declara. Con 300 jobs sigue estando al dia, que es
justo lo que un fichero central escrito a mano no consigue.

    python -m etl_kedro.graph
"""

import argparse
import importlib
import pkgutil
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from types import ModuleType

import etl_kedro.jobs
from etl_kedro.core.datasets import Dataset


@dataclass(frozen=True)
class Job:
    """Un job descubierto, con lo que declara consumir y producir."""

    nombre: str
    modulo: ModuleType
    consume: tuple[Dataset, ...]
    produce: tuple[Dataset, ...]


@dataclass
class Grafo:
    """Jobs, quien produce cada dataset y las aristas entre jobs."""

    jobs: dict[str, Job] = field(default_factory=dict)

    @property
    def productor_de(self) -> dict[str, str]:
        """Dataset -> nombre del job que lo produce."""
        return {dataset.nombre: job.nombre for job in self.jobs.values() for dataset in job.produce}

    @property
    def aristas(self) -> list[tuple[str, str, str]]:
        """(job_origen, job_destino, dataset) por cada dependencia real."""
        productor = self.productor_de
        return sorted(
            (productor[dataset.nombre], job.nombre, dataset.nombre)
            for job in self.jobs.values()
            for dataset in job.consume
            if dataset.nombre in productor
        )

    @property
    def entradas_externas(self) -> list[str]:
        """Datasets que se consumen y no produce nadie: el origen de la cadena."""
        productor = self.productor_de
        return sorted(
            {
                dataset.nombre
                for job in self.jobs.values()
                for dataset in job.consume
                if dataset.nombre not in productor
            }
        )

    @property
    def salidas_finales(self) -> list[str]:
        """Datasets que se producen y no consume nadie: el final de la cadena."""
        consumidos = {dataset.nombre for job in self.jobs.values() for dataset in job.consume}
        return sorted(
            {
                dataset.nombre
                for job in self.jobs.values()
                for dataset in job.produce
                if dataset.nombre not in consumidos
            }
        )

    @property
    def orden(self) -> list[str]:
        """Jobs en orden de ejecucion: nadie corre antes que quien le da de comer.

        Orden topologico (Kahn) sobre las aristas. A igualdad de dependencias se
        ordena por nombre, para que la salida sea estable entre ejecuciones.
        """
        pendientes = {
            nombre: {origen for origen, destino, _ in self.aristas if destino == nombre}
            for nombre in self.jobs
        }
        orden: list[str] = []
        while pendientes:
            listos = sorted(n for n, deps in pendientes.items() if not deps - set(orden))
            if not listos:
                ciclo = ", ".join(sorted(pendientes))
                raise CicloEnElGrafoError(f"Hay un ciclo entre los jobs: {ciclo}")
            for nombre in listos:
                orden.append(nombre)
                del pendientes[nombre]
        return orden


class CicloEnElGrafoError(RuntimeError):
    """Los jobs se consumen en circulo y no hay orden de ejecucion posible."""


class JobDesconocidoError(RuntimeError):
    """Se ha pedido un job que no existe como subpaquete de `etl_kedro.jobs`."""


def nombres_de_jobs() -> list[str]:
    """Nombres de los jobs disponibles, **sin importar ninguno**.

    Solo lista los subpaquetes de `etl_kedro.jobs`. Es lo que usa la CLI para validar
    `--job`: con 150 jobs, importarlos todos para lanzar uno cuesta tiempo en
    cada ejecucion y hace que un efecto colateral en el import de cualquiera
    penalice a todos.
    """
    return sorted(info.name for info in pkgutil.iter_modules(etl_kedro.jobs.__path__) if info.ispkg)


def load_job(nombre: str) -> Job:
    """Importa un solo job y lee lo que declara.

    El nombre del job es el de su carpeta: asi se puede listar sin importar.
    """
    if nombre not in nombres_de_jobs():
        raise JobDesconocidoError(
            f"No existe el job {nombre!r}. Hay: {', '.join(nombres_de_jobs())}"
        )
    modulo = importlib.import_module(f"etl_kedro.jobs.{nombre}.job")
    return Job(
        nombre=nombre,
        modulo=modulo,
        consume=tuple(getattr(modulo, "CONSUME", ())),
        produce=tuple(getattr(modulo, "PRODUCE", ())),
    )


def discover_jobs() -> Grafo:
    """Importa todos los jobs y construye el grafo.

    Solo hace falta cuando de verdad se necesita la foto completa: dibujar el
    grafo o resolver el orden de `--all`. Para ejecutar un job suelto, `load_job`.
    """
    return Grafo(jobs={nombre: load_job(nombre) for nombre in nombres_de_jobs()})


def render(grafo: Grafo) -> str:
    """Pinta el grafo como texto."""
    lineas: list[str] = []
    productor = grafo.productor_de

    for nombre in sorted(grafo.jobs):
        job = grafo.jobs[nombre]
        lineas.append(nombre)
        for dataset in job.consume:
            origen = productor.get(dataset.nombre)
            procedencia = f"  (de {origen})" if origen else "  (externo)"
            lineas.append(f"  <- {dataset.nombre:<22} {dataset.ruta}{procedencia}")
        for dataset in job.produce:
            lineas.append(f"  -> {dataset.nombre:<22} {dataset.ruta}")
        lineas.append("")

    lineas.append("Cadena:")
    if grafo.aristas:
        for origen, destino, via in grafo.aristas:
            lineas.append(f"  {origen} -> {destino}   ({via})")
    else:
        lineas.append("  (ningun job consume la salida de otro)")

    lineas.append("")
    lineas.append(f"Entradas externas: {', '.join(grafo.entradas_externas) or '-'}")
    lineas.append(f"Salidas finales:   {', '.join(grafo.salidas_finales) or '-'}")
    return "\n".join(lineas)


def _node_id(nombre: str) -> str:
    """Identificador seguro para Mermaid a partir de un nombre de dataset o job."""
    return "".join(char if char.isalnum() else "_" for char in nombre)


def render_mermaid(grafo: Grafo) -> str:
    """Pinta el grafo como diagrama Mermaid.

    Se genera de los mismos `CONSUME`/`PRODUCE` que la version texto, asi que no
    se puede desincronizar del codigo. GitHub renderiza Mermaid nativo en
    markdown: pegado en un README o en la descripcion de un PR se ve como
    diagrama, sin instalar nada.
    """
    externas = set(grafo.entradas_externas)
    finales = set(grafo.salidas_finales)

    lineas = ["flowchart LR"]
    for nombre in sorted(grafo.jobs):
        job = grafo.jobs[nombre]
        job_id = _node_id(nombre)
        lineas.append(f"    {job_id}([{nombre}])")
        for dataset in job.consume:
            lineas.append(f"    {_node_id(dataset.nombre)}[({dataset.nombre})] --> {job_id}")
        for dataset in job.produce:
            lineas.append(f"    {job_id} --> {_node_id(dataset.nombre)}[({dataset.nombre})]")

    lineas.append("")
    lineas.append("    classDef job fill:#2d6a9f,stroke:#1b3f5e,color:#fff")
    lineas.append("    classDef externo fill:#7a5c2e,stroke:#4a3619,color:#fff")
    lineas.append("    classDef final fill:#2f6b4f,stroke:#1c4130,color:#fff")

    jobs_ids = ",".join(_node_id(nombre) for nombre in sorted(grafo.jobs))
    if jobs_ids:
        lineas.append(f"    class {jobs_ids} job")
    if externas:
        lineas.append(f"    class {','.join(_node_id(n) for n in sorted(externas))} externo")
    if finales:
        lineas.append(f"    class {','.join(_node_id(n) for n in sorted(finales))} final")

    return "\n".join(lineas)


def main(argv: Sequence[str] | None = None) -> int:
    """Imprime la cadena de jobs, en texto o como diagrama Mermaid."""
    parser = argparse.ArgumentParser(
        prog="etl-kedro-graph",
        description="Muestra la cadena de jobs derivada de sus CONSUME/PRODUCE.",
    )
    parser.add_argument(
        "--format",
        default="text",
        choices=("text", "mermaid"),
        help="Formato de salida (por defecto: text)",
    )
    args = parser.parse_args(argv)

    grafo = discover_jobs()
    print(render(grafo) if args.format == "text" else render_mermaid(grafo))
    return 0


if __name__ == "__main__":
    sys.exit(main())
