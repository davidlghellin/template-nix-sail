"""Pipeline ETL minimo sobre CSV: leer, transformar y escribir."""

import logging
from collections.abc import Callable
from typing import Any

from pyspark.sql import DataFrame, SparkSession

logger = logging.getLogger(__name__)

TransformFunc = Callable[[DataFrame], DataFrame]

# Por defecto se lee con cabecera e inferencia de tipos; para cargas reales
# conviene pasar un `schema` explicito via kwargs y evitar la doble pasada.
DEFAULT_READ_OPTIONS: dict[str, Any] = {"header": True, "inferSchema": True}
DEFAULT_WRITE_OPTIONS: dict[str, Any] = {"header": True}


class PipelineStateError(RuntimeError):
    """Se ha pedido una operacion que necesita un DataFrame y aun no hay ninguno."""


class ETLPipeline:
    """Encadena lectura, transformaciones y escritura sobre un unico DataFrame.

    Cada metodo devuelve el propio pipeline, de modo que la ETL se escribe como
    `pipeline.read_csv(...).transform(...).write_csv(...)`.
    """

    def __init__(self, spark: SparkSession, name: str = "etl") -> None:
        self.spark = spark
        self.name = name
        self._df: DataFrame | None = None

    @property
    def df(self) -> DataFrame:
        """DataFrame actual. Lanza `PipelineStateError` si no se ha leido nada."""
        if self._df is None:
            raise PipelineStateError(
                f"El pipeline {self.name!r} no tiene DataFrame: llama antes a read_csv()"
            )
        return self._df

    @property
    def has_data(self) -> bool:
        """True si ya hay un DataFrame cargado."""
        return self._df is not None

    def read_csv(self, path: str, **kwargs: Any) -> "ETLPipeline":
        """Lee un CSV. Los `kwargs` sobrescriben las opciones por defecto."""
        options = {**DEFAULT_READ_OPTIONS, **kwargs}
        logger.info("Leyendo CSV de %s (opciones: %s)", path, options)
        self._df = self.spark.read.csv(path, **options)
        logger.info("CSV leido con columnas %s", self._df.columns)
        return self

    def transform(self, transform_func: TransformFunc, name: str | None = None) -> "ETLPipeline":
        """Aplica `transform_func` al DataFrame actual y guarda el resultado.

        `name` es la etiqueta que sale en el log; sin ella se usa el nombre de
        la funcion, que para una lambda es un inutil `<lambda>`.
        """
        label = name or getattr(transform_func, "__name__", repr(transform_func))
        logger.info("Aplicando transformacion %s", label)
        self._df = transform_func(self.df)
        return self

    def write_csv(self, path: str, mode: str = "overwrite", **kwargs: Any) -> "ETLPipeline":
        """Escribe el DataFrame actual como CSV en `path`."""
        options = {**DEFAULT_WRITE_OPTIONS, **kwargs}
        logger.info("Escribiendo CSV en %s (mode=%s, opciones=%s)", path, mode, options)
        self.df.write.csv(path, mode=mode, **options)
        logger.info("Escritura completada en %s", path)
        return self

    def count(self) -> int:
        """Numero de filas del DataFrame actual."""
        return self.df.count()
