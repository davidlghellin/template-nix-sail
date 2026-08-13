"""ETL minima de CSV sobre PySpark.

Estructura:

- `core/`  maquinaria reutilizable: pipeline, checks de calidad, sesion, logging
           y el tipo `Dataset`. No sabe de ningun dato concreto.
- `jobs/`  un flujo por carpeta, autocontenido: sus datasets (con esquema), sus
           transformaciones y su orquestacion.
- `main.py` la CLI, que cablea las dos cosas.
"""

from etl_kedro.core.datasets import Dataset
from etl_kedro.core.pipeline import ETLPipeline, PipelineStateError
from etl_kedro.core.quality import (
    QualityCheckError,
    check_non_null_key,
    check_required_columns,
    deduplicate_by_key,
)
from etl_kedro.core.session import BackendError, spark_session

__all__ = [
    "BackendError",
    "Dataset",
    "ETLPipeline",
    "PipelineStateError",
    "QualityCheckError",
    "check_non_null_key",
    "check_required_columns",
    "deduplicate_by_key",
    "spark_session",
]
