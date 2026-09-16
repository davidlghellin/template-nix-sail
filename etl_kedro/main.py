"""CLI de la ETL: parsea argumentos, cablea el job y traduce fallos a codigos.

Uso (la clave por defecto es `ciudad`, la del dataset de ciudades):

    python -m etl_kedro.main --input resources/ciudades_espana.csv --output /tmp/out
"""

import argparse
import inspect
import logging
import sys
from collections.abc import Sequence

from pyspark.sql import SparkSession

from etl_kedro.core.config import Config, ConfigError
from etl_kedro.core.datasets import check_input_exists
from etl_kedro.core.logging_conf import VALID_LOG_LEVELS, setup_logging
from etl_kedro.core.quality import QualityCheckError
from etl_kedro.core.session import BackendError, spark_session
from etl_kedro.dryrun import entradas_de_la_ejecucion, render_plan, revisar, revisar_solapes
from etl_kedro.graph import Grafo, GrafoError, discover_jobs, load_job, nombres_de_jobs

logger = logging.getLogger("etl_kedro.main")

WRITE_MODES = ("overwrite", "append")
JOB_POR_DEFECTO = "ciudades"

# Codigos de salida del proceso.
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_QUALITY = 2
EXIT_BACKEND = 3
EXIT_INPUT = 4
EXIT_CONFIG = 5
EXIT_DRY_RUN = 6


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parsea los argumentos de la CLI."""
    parser = argparse.ArgumentParser(
        prog="etl-kedro",
        description="ETL de CSV con PySpark: lectura, checks de calidad y escritura.",
    )
    # `nombres_de_jobs` lista los subpaquetes sin importarlos: lanzar un job no
    # debe cargar los otros 149.
    parser.add_argument(
        "--job",
        default=JOB_POR_DEFECTO,
        choices=nombres_de_jobs(),
        help=f"Job a ejecutar (por defecto: {JOB_POR_DEFECTO})",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Ejecuta todos los jobs en orden de dependencia, con sus rutas declaradas",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Muestra el plan y revisa esquemas y entradas, sin ejecutar ni arrancar Spark",
    )
    # Sobrescriben lo declarado en los datasets del job; sin ellos se usan sus
    # rutas del catalogo, que es lo unico que tiene sentido al lanzar la cadena.
    parser.add_argument("--input", help="Sobrescribe la ruta de entrada del job")
    parser.add_argument("--output", help="Sobrescribe la ruta de salida del job")
    parser.add_argument(
        "--mode",
        default="overwrite",
        choices=WRITE_MODES,
        help="Modo de escritura (por defecto: overwrite)",
    )
    parser.add_argument(
        "--key-col",
        help="Columna clave; por defecto la declarada por el job",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=VALID_LOG_LEVELS,
        help="Nivel de log (por defecto: INFO)",
    )
    args = parser.parse_args(argv)

    if args.all and (args.input or args.output):
        parser.error("--all usa las rutas declaradas: no admite --input ni --output")
    # Por lo mismo que las rutas: la clave es de cada job. En `ciudades` es la
    # columna por la que se deduplica y en `por_ccaa` la columna agrupada, que
    # es su salida: una sola clave para toda la cadena rompe al menos uno.
    if args.all and args.key_col:
        parser.error("--all usa la clave de cada job: no admite --key-col")
    # En la cadena, append acumularia tambien los datasets intermedios: el job
    # siguiente leeria todas las ejecuciones anteriores y las volveria a sumar.
    if args.all and args.mode == "append":
        parser.error("--all reescribe la cadena entera: no admite --mode append")
    return args


def ejecutar_job(
    spark: SparkSession,
    nombre: str,
    args: argparse.Namespace,
    config: Config,
) -> None:
    """Lanza un job por nombre, pasando solo lo que el usuario haya pedido.

    Lo que no se especifica no se pasa: cada job aplica entonces su propio valor
    por defecto (su clave, sus rutas) en vez de recibir un `None` que le obligue
    a tratarlo como centinela.

    No hace falta distinguir `--all`: al parsear ya se rechaza combinarlo con
    `--input`/`--output`, asi que en ese caso no hay rutas que pasar.
    """
    modulo = load_job(nombre).modulo
    opciones: dict[str, object] = {"mode": args.mode, "config": config}
    if args.key_col:
        opciones["key_col"] = args.key_col
    if args.input:
        opciones["input_path"] = args.input
    if args.output:
        opciones["output_path"] = args.output

    logger.info("--- job %s ---", nombre)
    modulo.run(spark, **opciones)


def main(argv: Sequence[str] | None = None) -> int:
    """Punto de entrada de la CLI. Devuelve el codigo de salida del proceso."""
    args = parse_args(argv)
    setup_logging(args.log_level)

    try:
        config = Config.desde_entorno()
        # El grafo completo solo hace falta para la cadena o para el plan; para
        # un job suelto se importa unicamente ese.
        if args.all or args.dry_run:
            grafo = discover_jobs()
            a_ejecutar = grafo.orden if args.all else [args.job]
        else:
            grafo = Grafo(jobs={args.job: load_job(args.job)})
            a_ejecutar = [args.job]

        # Solo los jobs que la usan admiten clave. En `por_ccaa` la columna
        # agrupada es su salida, y otra no cumpliria nunca el esquema: se
        # rechaza aqui y no despues de que Spark haya hecho todo el trabajo.
        if args.key_col:
            for nombre in a_ejecutar:
                if "key_col" not in inspect.signature(grafo.jobs[nombre].modulo.run).parameters:
                    raise ConfigError(f"el job {nombre!r} no admite --key-col")

        if args.dry_run:
            problemas = revisar(grafo, config, a_ejecutar, args.input, args.output)
            print(render_plan(grafo, config, a_ejecutar, problemas, args.input, args.output))
            return EXIT_DRY_RUN if problemas else EXIT_OK

        solapes = revisar_solapes(grafo, config, a_ejecutar, args.input, args.output)
        if solapes:
            raise ConfigError("; ".join(f"[{p.donde}] {p.mensaje}" for p in solapes))

        logger.info("ETL iniciada: jobs=%s", ", ".join(a_ejecutar))
        # Antes de la sesion: no tiene sentido arrancar Spark para descubrir que
        # una entrada no esta. Se comprueban todas las de esta ejecucion, las de
        # `--input` y las del catalogo, y no las que produce un job anterior de
        # la misma cadena, que aun no existen.
        for _, ruta in entradas_de_la_ejecucion(grafo, config, a_ejecutar, args.input):
            check_input_exists(ruta)
        with spark_session() as spark:
            for nombre in a_ejecutar:
                ejecutar_job(spark, nombre, args, config)
    # Los fallos de dato y de entorno son esperables y se explican solos: basta
    # el mensaje. El traceback se reserva para lo que si es un bug.
    except QualityCheckError as exc:
        logger.error("La ETL ha fallado en un check de calidad: %s", exc)
        return EXIT_QUALITY
    except BackendError as exc:
        logger.error("No se ha podido iniciar el backend: %s", exc)
        return EXIT_BACKEND
    except ConfigError as exc:
        logger.error("Configuracion invalida: %s", exc)
        return EXIT_CONFIG
    except GrafoError as exc:
        # El grafo se construye antes de poder revisar el plan, asi que un ciclo
        # o un job mal declarado llega aqui y no a `revisar`. En el dry-run se
        # cuenta como lo que es, un problema del plan.
        if args.dry_run:
            print(f"1 problema(s):\n  [grafo] {exc}")
            return EXIT_DRY_RUN
        logger.error("El grafo de jobs no es valido: %s", exc)
        return EXIT_CONFIG
    except FileNotFoundError as exc:
        logger.error("Entrada no encontrada: %s", exc)
        return EXIT_INPUT
    except Exception:
        logger.exception("La ETL ha fallado")
        return EXIT_ERROR

    logger.info("ETL finalizada correctamente")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
