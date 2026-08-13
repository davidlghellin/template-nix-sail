"""Datasets del dominio de poblacion por comunidad autonoma.

La entrada no se declara aqui: es la salida del job de ciudades, y se importa
de su modulo. Ese import es la dependencia entre los dos jobs.
"""

from pyspark.sql.types import LongType, StringType, StructField, StructType

from etl_kedro.core.datasets import Dataset

CLAVE = "comunidad_autonoma"

POBLACION_POR_CCAA_ESQUEMA = StructType(
    [
        StructField("comunidad_autonoma", StringType(), True),
        StructField("habitantes", LongType(), True),
    ]
)

POBLACION_POR_CCAA = Dataset(
    nombre="poblacion_por_ccaa",
    ruta="data/poblacion_por_ccaa",
    esquema=POBLACION_POR_CCAA_ESQUEMA,
)
