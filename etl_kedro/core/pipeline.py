"""Pipeline ETL minimo sobre CSV: leer, transformar y escribir."""

import logging
import os
from collections.abc import Callable
from typing import Any

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import StructType

from etl_kedro.core.config import Config
from etl_kedro.core.datasets import (
    Dataset,
    EntradaNoEncontradaError,
    cabecera_csv,
    check_input_exists,
    problema_de_cabecera,
    problema_de_formato,
    se_comprueba_en_local,
    sin_datos,
)
from etl_kedro.core.quality import QualityCheckError

logger = logging.getLogger(__name__)

TransformFunc = Callable[[DataFrame], DataFrame]

# Por defecto se lee con cabecera e inferencia de tipos; para cargas reales
# conviene pasar un `schema` explicito via kwargs y evitar la doble pasada.
DEFAULT_READ_OPTIONS: dict[str, Any] = {"header": True, "inferSchema": True}
DEFAULT_WRITE_OPTIONS: dict[str, Any] = {"header": True}


def _tipos_distintos(declarado: StructType, real: StructType) -> str | None:
    """Mensaje si alguna columna sale con otro tipo que el declarado.

    Se comparan tipos y no nulabilidad: un agregado o un join marcan columnas
    como anulables aunque no lleguen nulos, y eso no cambia lo que se escribe.
    Importa sobre todo en parquet, que guarda el tipo con el dato; en CSV todo
    acaba en texto, pero quien lo lea despues aplicara el esquema declarado.
    """
    reales = {campo.name: campo.dataType for campo in real.fields}
    distintos = [
        f"{campo.name}: declarado {campo.dataType.simpleString()}, "
        f"sale {reales[campo.name].simpleString()}"
        for campo in declarado.fields
        if campo.name in reales and reales[campo.name] != campo.dataType
    ]
    return f"columnas con otro tipo: {'; '.join(distintos)}" if distintos else None


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
        - **Las columnas se toman por nombre, no por posicion.** Pasar el
          esquema al lector de CSV lo aplica por posicion: un fichero con dos
          columnas cambiadas de sitio saldria cruzado, y `enforceSchema=False`,
          que en PySpark lo evita, Sail lo ignora. Leyendo la cabecera y
          seleccionando cada columna declarada por su nombre, el orden del
          fichero da igual en los dos motores, y vale tambien para comodines y
          `s3://`, donde no se puede mirar la cabecera antes.
        - **Faltan o sobran columnas: `QualityCheckError`**, que sale como fallo
          de dato (codigo 2) y no como un error del motor (codigo 1).
        - **Los tipos son los declarados.** En CSV cada columna llega como texto
          y se convierte con `try_cast`: un valor que no encaja queda nulo, como
          con el lector permisivo de siempre. En parquet los tipos vienen en el
          fichero y tienen que coincidir.
        """
        ruta = path if path is not None else dataset.resolver(config)
        check_input_exists(ruta)
        # Antes de leer, y por tanto antes de escribir nada.
        problema = problema_de_formato(ruta, dataset.formato)
        if problema:
            raise QualityCheckError(f"[{dataset.nombre}] {problema}")

        esquema = dataset.esquema
        if esquema is None:
            if dataset.formato == "parquet":
                self._df = self.spark.read.parquet(ruta)
                return self
            return self.read_csv(ruta)

        if sin_datos(ruta):
            logger.info("%s no tiene datos: se lee vacio con el esquema declarado", ruta)
            self._df = self.spark.createDataFrame([], esquema)
            return self

        logger.info("Leyendo %s de %s", dataset.formato, ruta)
        if dataset.formato == "csv":
            # Donde se puede, la cabecera se mira con Python antes que con el
            # motor: una columna repetida la colapsa Sail (y luego falla al
            # leer) y la renombra PySpark, asi que las columnas que devuelven no
            # sirven para verla. Es la misma comprobacion que hace el dry-run.
            # Con comodines o `s3://` no hay fichero que abrir: decide el motor.
            cabecera = cabecera_csv(ruta)
            if cabecera is not None:
                problema = problema_de_cabecera(esquema, cabecera)
                if problema:
                    raise QualityCheckError(f"[{dataset.nombre}] {problema}")
        if dataset.formato == "parquet":
            crudo = self.spark.read.parquet(ruta)
        else:
            crudo = self.spark.read.csv(ruta, header=True, inferSchema=False)
        if not crudo.columns and not se_comprueba_en_local(ruta):
            # Sin columnas y sin poder mirar la ruta (un `s3://`): o no existe o
            # no tiene nada. No se da por un dataset vacio, que en un job que
            # sobrescribe vaciaria su salida por una ruta mal escrita. Uno local
            # sin cabecera (0 bytes) cae al contraste de columnas.
            raise EntradaNoEncontradaError(f"No se ha leido nada de la entrada: {ruta}")

        problema = problema_de_cabecera(esquema, crudo.columns)
        if dataset.formato == "parquet":
            problema = problema or _tipos_distintos(esquema, crudo.schema)
        if problema:
            raise QualityCheckError(f"[{dataset.nombre}] {problema}")

        self._df = crudo.select(
            *[F.col(campo.name).try_cast(campo.dataType).alias(campo.name) for campo in esquema]
        )
        logger.info("Leido con columnas %s", self._df.columns)
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

    def write_dataset(
        self,
        dataset: Dataset,
        config: Config | None = None,
        path: str | None = None,
        mode: str = "overwrite",
    ) -> "ETLPipeline":
        """Escribe en la ruta y el formato que declara el dataset.

        Simetrico de `read_dataset`: el catalogo manda tambien al escribir, en
        vez de que cada job elija formato por su cuenta.
        """
        ruta = path if path is not None else dataset.resolver(config)
        # El esquema declarado es el contrato del dataset tambien para quien lo
        # lee despues. Se contrasta antes de escribir para que una salida que no
        # lo cumple no llegue al disco:
        # p.ej. un agregado por otra clave que deja `provincia` donde el
        # catalogo promete `comunidad_autonoma`.
        if dataset.esquema is not None:
            problema = problema_de_cabecera(dataset.esquema, self.df.columns) or _tipos_distintos(
                dataset.esquema, self.df.schema
            )
            if problema:
                raise QualityCheckError(
                    f"[{dataset.nombre}] la salida no cumple el esquema declarado: {problema}"
                )
        if dataset.formato == "parquet":
            logger.info("Escribiendo parquet en %s (mode=%s)", ruta, mode)
            self.df.write.parquet(ruta, mode=mode)
            logger.info("Escritura completada en %s", ruta)
        else:
            self.write_csv(ruta, mode=mode)
        # Sail no escribe nada para un DataFrame vacio en una ruta nueva, ni el
        # directorio; PySpark crea un directorio con la cabecera. Sin esto, en
        # Sail el siguiente job de la cadena falla con "no existe la entrada"
        # donde en PySpark lee cero filas.
        if se_comprueba_en_local(ruta) and not os.path.exists(ruta):
            os.makedirs(ruta)
        return self

    def count(self) -> int:
        """Numero de filas del DataFrame actual."""
        return self.df.count()
