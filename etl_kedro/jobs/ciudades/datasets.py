"""Datasets del dominio de ciudades: entrada y salida, con sus esquemas.

Entrada y salida viven juntas a proposito: son las dos mitades del mismo
contrato, y normalmente se conforma una a la otra. Separarlas en carpetas
`input/` y `output/` obliga a abrir dos ficheros para leer una sola idea.

Otro job que consuma esta salida importa la constante de aqui, y ese import es
la dependencia declarada entre ambos:

    from etl_kedro.jobs.ciudades.datasets import CIUDADES_DEDUP
"""

from pyspark.sql.types import (
    DoubleType,
    LongType,
    StringType,
    StructField,
    StructType,
)

from etl_kedro.core.datasets import Dataset

CLAVE = "ciudad"

CIUDADES_ESQUEMA = StructType(
    [
        StructField("ciudad", StringType(), True),
        StructField("habitantes", LongType(), True),
        StructField("provincia", StringType(), True),
        StructField("comunidad_autonoma", StringType(), True),
        StructField("superficie_km2", DoubleType(), True),
    ]
)

CIUDADES_RAW = Dataset(
    nombre="ciudades_raw",
    ruta="resources/ciudades_espana.csv",
    esquema=CIUDADES_ESQUEMA,
)

# Este job solo valida y deduplica, asi que la salida conserva el esquema.
CIUDADES_DEDUP = Dataset(
    nombre="ciudades_dedup",
    ruta="data/ciudades_dedup",
    esquema=CIUDADES_ESQUEMA,
)
