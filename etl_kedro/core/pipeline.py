"""Pipeline ETL minimo sobre CSV: leer, transformar y escribir."""

import logging
from collections.abc import Callable
from typing import Any

from pyspark.sql import DataFrame, SparkSession

from etl_kedro.core.config import Config
from etl_kedro.core.datasets import (
    Dataset,
    cabecera_csv,
    check_input_exists,
    problema_de_cabecera,
)
from etl_kedro.core.quality import QualityCheckError

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

    def read_dataset(
        self,
        dataset: Dataset,
        config: Config | None = None,
        path: str | None = None,
    ) -> "ETLPipeline":
        """Lee un dataset del catalogo: comprueba la ruta y aplica su esquema.

        Es la forma de leer que deberian usar los jobs, en vez de `read_csv` a
        pelo, porque hace valer lo que el dataset declara:

        - **La ruta se comprueba antes de leer.** Sin esto una ruta mal escrita
          se lee como un DataFrame vacio y el fallo aparece luego como "faltan
          columnas requeridas", que manda a depurar el esquema en vez de la ruta.
        - **El esquema declarado se pasa al lector.** Evita `inferSchema`, que
          hace doble pasada sobre el fichero y no infiere igual en los dos
          backends (PySpark da `int` donde Sail da `bigint`).
        - **La cabecera se contrasta con el esquema antes de leer**, para poder
          fallar con un `QualityCheckError` que diga que columna sobra o falta.
          Dejarselo al motor tambien corta, pero con un error de parseo suelto
          que sale como bug (codigo 1) en vez de como fallo de dato (codigo 2).

        `enforceSchema=False` deja ademas que el motor contraste la cabecera por
        su cuenta. PySpark lo respeta; Sail lo ignora, asi que es la
        comprobacion de arriba la que iguala el comportamiento de los dos.
        """
        ruta = path if path is not None else dataset.resolver(config)
        check_input_exists(ruta)
        formato = (config or Config()).formato_de(dataset.nombre, dataset.formato)
        if formato == "parquet":
            # Parquet ya lleva su esquema dentro: no hay cabecera que contrastar
            # ni tipos que inferir.
            logger.info("Leyendo parquet de %s", ruta)
            self._df = self.spark.read.parquet(ruta)
            logger.info("Parquet leido con columnas %s", self._df.columns)
            return self

        opciones: dict[str, Any] = {}
        if dataset.esquema is not None:
            cabecera = cabecera_csv(ruta)
            if cabecera is not None:
                problema = problema_de_cabecera(dataset.esquema, cabecera)
                if problema:
                    raise QualityCheckError(f"[{dataset.nombre}] {problema}")
            opciones = {
                "schema": dataset.esquema,
                "inferSchema": False,
                "enforceSchema": False,
            }
        return self.read_csv(ruta, **opciones)

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

    def write_dataset(
        self,
        dataset: Dataset,
        config: Config | None = None,
        path: str | None = None,
        mode: str = "overwrite",
    ) -> "ETLPipeline":
        """Escribe en la ruta y el formato que declara el dataset.

        Simetrico de `read_dataset`: el catalogo manda tambien al escribir, en
        vez de que cada job elija formato por su cuenta. El entorno puede
        forzarlo (`ETL_OUTPUT_FORMAT`), que es como `etl_kedro.compare` obtiene
        parquet de una cadena que normalmente escribe CSV.
        """
        ruta = path if path is not None else dataset.resolver(config)
        formato = (config or Config()).formato_de(dataset.nombre, dataset.formato)
        if formato == "parquet":
            logger.info("Escribiendo parquet en %s (mode=%s)", ruta, mode)
            self.df.write.parquet(ruta, mode=mode)
            logger.info("Escritura completada en %s", ruta)
            return self
        return self.write_csv(ruta, mode=mode)

    def count(self) -> int:
        """Numero de filas del DataFrame actual."""
        return self.df.count()
