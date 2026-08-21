"""Configuracion de logging de la ETL con `logging.config.dictConfig`."""

import logging
import logging.config
from typing import Any

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Los loggers del paquete se llaman `<paquete>.<modulo>`, asi que la config
# tiene que colgar del nombre real del paquete. Derivarlo evita que un
# renombrado deje los logs huerfanos, cayendo al root con otro formato.
PAQUETE = __name__.split(".")[0]

VALID_LOG_LEVELS: tuple[str, ...] = ("DEBUG", "INFO", "WARNING", "ERROR")


def build_logging_config(log_level: str = "INFO") -> dict[str, Any]:
    """Construye el diccionario de configuracion para `dictConfig`.

    Se expone aparte de `setup_logging` para poder inspeccionarlo en tests sin
    tocar el estado global del modulo `logging`.
    """
    level = _normalize_level(log_level)
    return {
        "version": 1,
        # Los loggers de py4j/pyspark ya existen cuando arranca la sesion; no se
        # desactivan para poder subirles el nivel y no perder sus avisos.
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {"format": LOG_FORMAT, "datefmt": DATE_FORMAT},
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "standard",
                "stream": "ext://sys.stderr",
            },
        },
        "root": {"level": level, "handlers": ["console"]},
        "loggers": {
            PAQUETE: {"level": level, "handlers": ["console"], "propagate": False},
            # Spark es muy ruidoso en INFO: se deja en WARNING salvo en DEBUG.
            "py4j": {"level": "DEBUG" if level == "DEBUG" else "WARNING"},
            "pyspark": {"level": "DEBUG" if level == "DEBUG" else "WARNING"},
        },
    }


def setup_logging(log_level: str = "INFO") -> logging.Logger:
    """Configura el logging del proceso y devuelve el logger raiz de la ETL."""
    logging.config.dictConfig(build_logging_config(log_level))
    return logging.getLogger(PAQUETE)


def _normalize_level(log_level: str) -> str:
    level = log_level.upper()
    if level not in VALID_LOG_LEVELS:
        valid = ", ".join(VALID_LOG_LEVELS)
        raise ValueError(f"Nivel de log invalido: {log_level!r}. Validos: {valid}")
    return level
