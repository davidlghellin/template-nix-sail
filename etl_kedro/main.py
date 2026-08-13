"""CLI de la ETL: parsea argumentos, cablea el job y traduce fallos a codigos.

Uso (la clave por defecto es `ciudad`, la del dataset de ciudades):

    python -m etl_kedro.main --input resources/ciudades_espana.csv --output /tmp/out
"""

import argparse
import logging
import sys
from collections.abc import Sequence

from pyspark.sql import SparkSession

from etl_kedro.core.config import Config, ConfigError
from etl_kedro.core.datasets import check_input_exists
from etl_kedro.core.logging_conf import VALID_LOG_LEVELS, setup_logging
from etl_kedro.core.quality import QualityCheckError
from etl_kedro.core.session import BackendError, spark_session
from etl_kedro.dryrun import render_plan, revisar
from etl_kedro.graph import Grafo, discover_jobs, load_job, nombres_de_jobs

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
    return args


def ejecutar_job(
    spark: SparkSession,
    nombre: str,
    args: argparse.Namespace,
    config: Config,
    usar_rutas: bool,
) -> None:
    """Lanza un job por nombre, pasando solo lo que el usuario haya pedido.

    Lo que no se especifica no se pasa, para que cada job aplique su propio
    valor por defecto (su clave, sus rutas) en vez de heredar el de otro.
    """
    modulo = load_job(nombre).modulo
    opciones: dict[str, object] = {"mode": args.mode, "config": config}
    if args.key_col:
        opciones["key_col"] = args.key_col
    if usar_rutas:
        opciones["input_path"] = args.input
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

        if args.dry_run:
            problemas = revisar(grafo, config)
            print(render_plan(grafo, config, a_ejecutar, problemas))
            return EXIT_DRY_RUN if problemas else EXIT_OK

        logger.info("ETL iniciada: jobs=%s", ", ".join(a_ejecutar))
        # Antes de la sesion: no tiene sentido arrancar Spark para descubrir que
        # la ruta esta mal escrita. En la cadena, cada job valida la suya al leer.
        if args.input:
            check_input_exists(args.input)
        with spark_session() as spark:
            for nombre in a_ejecutar:
                ejecutar_job(spark, nombre, args, config, usar_rutas=not args.all)
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
