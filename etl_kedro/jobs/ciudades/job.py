"""Orquestacion del job de ciudades: lee, valida, deduplica y escribe.

`CONSUME` y `PRODUCE` declaran la posicion de este job en la cadena. Un job que
consuma `CIUDADES_DEDUP` lo importa de `etl_kedro.jobs.ciudades.datasets`, y con eso
la dependencia queda escrita en el codigo en vez de escondida en dos rutas que
casualmente coinciden.
"""

import logging

from pyspark.sql import SparkSession

from etl_kedro.core.config import Config
from etl_kedro.core.pipeline import ETLPipeline
from etl_kedro.jobs.ciudades import transform
from etl_kedro.jobs.ciudades.datasets import CIUDADES_DEDUP, CIUDADES_RAW, CLAVE

logger = logging.getLogger(__name__)

NOMBRE = "ciudades"

CONSUME = (CIUDADES_RAW,)
PRODUCE = (CIUDADES_DEDUP,)


def run(
    spark: SparkSession,
    input_path: str | None = None,
    output_path: str | None = None,
    key_col: str = CLAVE,
    mode: str = "overwrite",
    config: Config | None = None,
) -> ETLPipeline:
    """Ejecuta el job de punta a punta y devuelve el pipeline resultante.

    Sin rutas explicitas usa las declaradas en los datasets del dominio; la CLI
    las sobrescribe para poder apuntar a otro fichero sin tocar el catalogo.
    """
    config = config or Config.desde_entorno()
    origen = input_path or CIUDADES_RAW.resolver(config)
    destino = output_path or CIUDADES_DEDUP.resolver(config)

    pipeline = ETLPipeline(spark, name=NOMBRE)

    logger.info("== read == %s", origen)
    pipeline.read_dataset(CIUDADES_RAW, config, path=input_path)

    logger.info("== validate == clave %r", key_col)
    pipeline.transform(lambda df: transform.validar(df, key_col), name="validar")

    logger.info("== dedup == por %r", key_col)
    # Cada `count()` es una accion de Spark que recorre el fichero entero. Solo
    # se pagan si el log va a salir: con --log-level WARNING no se emite la
    # linea, asi que contar seria trabajo tirado.
    contar = logger.isEnabledFor(logging.INFO)
    rows_before = pipeline.count() if contar else 0
    pipeline.transform(lambda df: transform.deduplicar(df, key_col), name="deduplicar")
    if contar:
        rows_after = pipeline.count()
        logger.info(
            "Deduplicado: %d filas -> %d filas (%d duplicados eliminados)",
            rows_before,
            rows_after,
            rows_before - rows_after,
        )

    logger.info("== write == %s (mode=%s)", destino, mode)
    pipeline.write_dataset(CIUDADES_DEDUP, config, path=output_path, mode=mode)
    return pipeline
