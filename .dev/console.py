"""Consola interactiva contra un servidor Sail, con ptpython.

El CLI `sail spark shell` monta el REPL con `code.interact`, sin forma de
cambiarlo. Aqui se levanta el mismo servidor y se entra en ptpython, que da
historial, resaltado y edicion multilinea.
"""

import os
import platform
from pathlib import Path

import pysail
import pyspark
from ptpython.prompt_style import PromptStyle
from ptpython.repl import embed, run_config
from pysail.spark import SparkConnectServer
from pyspark.sql import SparkSession
from pyspark.sql import functions as F


class SailPrompt(PromptStyle):
    """Prompt del proyecto, en lugar de los `>>>` de siempre."""

    def in_prompt(self):
        return [("class:prompt", "⛵ sail ❯ ")]

    def in2_prompt(self, width):
        return [("class:prompt.dots", "...")]

    def out_prompt(self):
        return []


def banner(endpoint: str) -> str:
    """Bienvenida al estilo de la de PySpark, con barco."""
    version, (build_number, build_date) = platform.python_version(), platform.python_build()
    return rf"""
Welcome to
          /|
         / |             ___       _ _
        /  |  /|        / __| __ _(_) |
       /   | / |        \__ \/ _` | | |
      /    |/  |        |___/\__,_|_|_|   version {pysail.__version__}
     /_____|___|
     \___________/      PySpark {pyspark.__version__}
      \_________/

Using Python version {version} ({build_number}, {build_date})
Client connected to the Sail Spark Connect server at {endpoint}
SparkSession available as 'spark', functions as 'F'.
"""


def config_home() -> Path:
    """Directorio de ptpython del proyecto, que fija el devShell."""
    home = os.environ.get("PTPYTHON_CONFIG_HOME")
    return Path(home) if home else Path.home() / ".config" / "ptpython"


def configure(repl) -> None:
    """Carga el config.py del proyecto y le pone el prompt de Sail encima.

    `embed()` no lee el config por su cuenta (solo lo hace el comando
    `ptpython`), y `run_config` ignora PTPYTHON_CONFIG_HOME, asi que hay que
    resolver la ruta a mano.
    """
    config = config_home() / "config.py"
    if config.is_file():
        run_config(repl, str(config))

    # Despues del config, que fija prompt_style = "classic".
    repl.all_prompt_styles["sail"] = SailPrompt()
    repl.prompt_style = "sail"


def main() -> None:
    server = SparkConnectServer()
    server.start(background=True)
    ip, port = server.listening_address

    spark = SparkSession.builder.remote(f"sc://{ip}:{port}").getOrCreate()
    print(banner(f"{ip}:{port}"))

    # Sin history_filename, embed() usa historial en memoria y se pierde al
    # salir. El comando `ptpython` sí lo persiste, de ahí que .gitignore ya
    # cuente con este fichero.
    history = config_home() / "history"
    history.parent.mkdir(parents=True, exist_ok=True)

    try:
        embed(
            {},
            {"spark": spark, "F": F},
            configure=configure,
            history_filename=str(history),
            title="sail",
        )
    finally:
        spark.stop()
        server.stop()


if __name__ == "__main__":
    main()
