"""Agrega la poblacion por comunidad autonoma.

Consume la salida del job de ciudades. La dependencia se declara importando su
dataset: no hay dos rutas sueltas que casualmente coinciden, hay un import que
el IDE navega y mypy verifica.
"""

import logging

from pyspark.sql import SparkSession

from etl_kedro.core.config import Config
from etl_kedro.core.pipeline import ETLPipeline
from etl_kedro.jobs.ciudades.datasets import CIUDADES_DEDUP
from etl_kedro.jobs.por_ccaa import transform
from etl_kedro.jobs.por_ccaa.datasets import CLAVE, POBLACION_POR_CCAA

logger = logging.getLogger(__name__)

NOMBRE = "por_ccaa"

CONSUME = (CIUDADES_DEDUP,)
PRODUCE = (POBLACION_POR_CCAA,)


def run(
    spark: SparkSession,
    input_path: str | None = None,
    output_path: str | None = None,
    key_col: str = CLAVE,
    mode: str = "overwrite",
    config: Config | None = None,
) -> ETLPipeline:
    """Ejecuta el job y devuelve el pipeline resultante."""
    config = config or Config.desde_entorno()
    origen = input_path or CIUDADES_DEDUP.resolver(config)
    destino = output_path or POBLACION_POR_CCAA.resolver(config)

    pipeline = ETLPipeline(spark, name=NOMBRE)

    logger.info("== read == %s", origen)
    pipeline.read_csv(origen)

    logger.info("== aggregate == por %r", key_col)
    pipeline.transform(lambda df: transform.agregar_por_ccaa(df, key_col), name="agregar_por_ccaa")

    logger.info("== write == %s (mode=%s)", destino, mode)
    pipeline.write_csv(destino, mode=mode)
    return pipeline
