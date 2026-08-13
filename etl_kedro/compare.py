"""Corre la misma ETL en los dos backends y compara lo que producen.

Es la pregunta que da sentido a esta plantilla: *¿Sail devuelve lo mismo que
PySpark?* Aqui se responde sobre la ETL entera, no sobre una funcion suelta.

Cada backend corre en **su propio proceso** y contra **su propia raiz de
datos**. En el mismo proceso no se puede: PySail se usa por Spark Connect
(`sc://`) y PySpark levanta una JVM local, y `getOrCreate` devolveria la sesion
que ya hubiera en pie.

Se escribe en **parquet**, no en CSV. Un CSV convierte todo a texto, asi que un
`bigint` y un `int` salen identicos y la comparacion daria un falso verde.
Parquet guarda el esquema junto a los datos, de modo que una sola lectura
compara las dos mitades:

- **el esquema**, que es el del DataFrame tal y como lo dejo cada motor;
- **los datos**, fila a fila.

La comparacion la hace pyarrow, sin Spark: leer parquet no necesita motor, y
asi el veredicto no depende de ninguno de los dos implicados.

    python -m etl_kedro.compare
"""

import argparse
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pyarrow.parquet as pq

from etl_kedro.core.config import Config
from etl_kedro.core.session import VALID_BACKENDS
from etl_kedro.graph import Grafo, discover_jobs

logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_FALLO_AL_EJECUTAR = 1
EXIT_DIFERENCIAS = 7


@dataclass(frozen=True)
class Diferencia:
    """Algo en lo que los dos backends no coinciden."""

    dataset: str
    concepto: str
    detalle: str

    def __str__(self) -> str:
        return f"  [{self.dataset}] {self.concepto}: {self.detalle}"


def preparar_raiz(grafo: Grafo, raiz: Path) -> None:
    """Copia las entradas externas dentro de la raiz de este backend.

    Cada backend escribe en su propia raiz para no pisarse, y las rutas de los
    datasets son relativas a ella: sus entradas tienen que estar dentro. Se
    copian las que declara el grafo, no una lista escrita a mano.
    """
    dev = Config()
    externas = set(grafo.entradas_externas)
    for job in grafo.jobs.values():
        for dataset in job.consume:
            if dataset.nombre not in externas:
                continue
            if "://" in dataset.ruta or dataset.ruta.startswith("/"):
                continue  # escapa de la raiz: los dos backends leen lo mismo
            origen = Path(dev.resolver(dataset.ruta))
            destino = raiz / dataset.ruta
            destino.parent.mkdir(parents=True, exist_ok=True)
            if origen.is_dir():
                shutil.copytree(origen, destino, dirs_exist_ok=True)
            else:
                shutil.copy2(origen, destino)


def ejecutar(backend: str, raiz: Path) -> subprocess.CompletedProcess:
    """Lanza la cadena entera con un backend, escribiendo parquet en `raiz`."""
    entorno = {
        **os.environ,
        "SPARK_BACKEND": backend,
        "ETL_ENV": "pro",  # exige raiz explicita: sin sorpresas de ruta
        "ETL_DATA_ROOT": str(raiz),
        "ETL_OUTPUT_FORMAT": "parquet",
    }
    return subprocess.run(
        [sys.executable, "-m", "etl_kedro.main", "--all", "--log-level", "WARNING"],
        env=entorno,
        capture_output=True,
        text=True,
    )


def comparar_dataset(nombre: str, ruta_a: Path, ruta_b: Path, backends: tuple[str, str]) -> list:
    """Compara esquema y filas de un dataset escrito por los dos backends."""
    a, b = backends
    diferencias: list[Diferencia] = []
    for backend, ruta in ((a, ruta_a), (b, ruta_b)):
        if not ruta.exists():
            diferencias.append(Diferencia(nombre, "salida", f"{backend} no ha escrito {ruta}"))
    if diferencias:
        return diferencias

    tabla_a = pq.read_table(ruta_a)
    tabla_b = pq.read_table(ruta_b)

    campos_a = {campo.name: campo for campo in tabla_a.schema}
    campos_b = {campo.name: campo for campo in tabla_b.schema}
    if list(campos_a) != list(campos_b):
        diferencias.append(
            Diferencia(nombre, "columnas", f"{a}={list(campos_a)} vs {b}={list(campos_b)}")
        )
    for columna in campos_a.keys() & campos_b.keys():
        tipo_a, tipo_b = campos_a[columna].type, campos_b[columna].type
        if tipo_a != tipo_b:
            diferencias.append(
                Diferencia(nombre, f"tipo de {columna!r}", f"{a}={tipo_a} vs {b}={tipo_b}")
            )

    # Las filas se ordenan antes de comparar: el orden de salida de Spark
    # depende de las particiones y no es parte del contrato.
    filas_a = sorted(tabla_a.to_pylist(), key=repr)
    filas_b = sorted(tabla_b.to_pylist(), key=repr)
    if len(filas_a) != len(filas_b):
        diferencias.append(
            Diferencia(nombre, "numero de filas", f"{a}={len(filas_a)} vs {b}={len(filas_b)}")
        )
    elif filas_a != filas_b:
        for fila_a, fila_b in zip(filas_a, filas_b):
            if fila_a != fila_b:
                diferencias.append(Diferencia(nombre, "fila", f"{a}={fila_a} vs {b}={fila_b}"))
    return diferencias


def render(
    grafo: Grafo,
    resultados: dict[str, list[Diferencia]],
    backends: tuple[str, str],
) -> str:
    """Pinta el informe de la comparacion."""
    a, b = backends
    lineas = [f"Comparando {a} vs {b}", ""]
    for nombre in sorted(resultados):
        diferencias = resultados[nombre]
        marca = "OK  " if not diferencias else "DIFF"
        lineas.append(f"  {marca}  {nombre}")
        lineas.extend(f"      {d.concepto}: {d.detalle}" for d in diferencias)

    total = sum(len(d) for d in resultados.values())
    lineas.append("")
    if total:
        lineas.append(f"{total} diferencia(s) entre backends.")
    else:
        lineas.append("Identico en los dos backends: mismo esquema y mismas filas.")
    return "\n".join(lineas)


def main(argv: Sequence[str] | None = None) -> int:
    """Corre la ETL en los dos backends y compara sus salidas."""
    parser = argparse.ArgumentParser(
        prog="etl-kedro-compare",
        description="Corre la ETL en los dos backends y compara esquemas y datos.",
    )
    parser.add_argument(
        "--backends",
        nargs=2,
        default=list(VALID_BACKENDS),
        metavar=("A", "B"),
        help=f"Los dos backends a comparar (por defecto: {' '.join(VALID_BACKENDS)})",
    )
    parser.add_argument(
        "--workdir",
        help="Donde escribir las salidas (por defecto: un temporal que se borra)",
    )
    args = parser.parse_args(argv)
    backends = (args.backends[0], args.backends[1])

    grafo = discover_jobs()
    temporal = tempfile.mkdtemp(prefix="etl-compare-") if not args.workdir else None
    base = Path(args.workdir or temporal or ".")
    try:
        raices = {}
        for backend in backends:
            raiz = base / backend
            raiz.mkdir(parents=True, exist_ok=True)
            preparar_raiz(grafo, raiz)
            print(f"Ejecutando la cadena con {backend}...")
            resultado = ejecutar(backend, raiz)
            if resultado.returncode != 0:
                print(f"\n{backend} ha fallado (codigo {resultado.returncode}):\n")
                print(resultado.stderr.strip() or resultado.stdout.strip())
                return EXIT_FALLO_AL_EJECUTAR
            raices[backend] = raiz

        producidos = sorted(
            {
                dataset.nombre: dataset for job in grafo.jobs.values() for dataset in job.produce
            }.values(),
            key=lambda dataset: dataset.nombre,
        )
        resultados = {
            dataset.nombre: comparar_dataset(
                dataset.nombre,
                raices[backends[0]] / dataset.ruta,
                raices[backends[1]] / dataset.ruta,
                backends,
            )
            for dataset in producidos
        }
        print()
        print(render(grafo, resultados, backends))
        return EXIT_DIFERENCIAS if any(resultados.values()) else EXIT_OK
    finally:
        if temporal:
            shutil.rmtree(temporal, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
