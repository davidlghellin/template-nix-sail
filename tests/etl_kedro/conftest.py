"""Utilidades comunes a los tests de la ETL."""

from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import pytest

from etl_kedro.core.config import VAR_ENTORNO, VAR_RAIZ
from etl_kedro.jobs.ciudades import job as ciudades_job
from etl_kedro.jobs.ciudades.datasets import CIUDADES_DEDUP, CIUDADES_ESQUEMA, CIUDADES_RAW
from etl_kedro.jobs.por_ccaa import job as por_ccaa_job
from etl_kedro.jobs.por_ccaa.datasets import POBLACION_POR_CCAA


@pytest.fixture(autouse=True)
def sin_configuracion_del_entorno(monkeypatch):
    """Los tests no heredan `ETL_ENV` ni `ETL_DATA_ROOT`.

    El README ensena a exportarlas, y quien lo haya hecho en su shell veria
    fallar la suite por su entorno y no por el codigo. El test que necesite una
    la pone el mismo.
    """
    for variable in (VAR_ENTORNO, VAR_RAIZ):
        monkeypatch.delenv(variable, raising=False)


@pytest.fixture
def reapuntar_cadena(monkeypatch, tmp_path):
    """Devuelve una funcion que lleva la cadena entera a `tmp_path`.

    Hay que cambiar dos cosas, y olvidar la segunda pasa desapercibido:

    - las constantes que usa cada job al leer y escribir;
    - sus `CONSUME`/`PRODUCE`, que son tuplas creadas al importar y guardan
      los datasets originales. De ellas sale la comprobacion de entradas previa
      a Spark: sin reapuntarlas, el test busca `resources/` en el directorio
      actual y solo pasa si pytest se lanza desde la raiz del repo.

    `formato` cambia el de los datasets que produce la cadena: el test e2e
    los declara en parquet para poder comprobar los tipos escritos.

    Rutas absolutas, no `chdir`: PySpark resuelve las relativas contra el
    directorio de la JVM, que se fija al arrancarla.
    """

    def _reapuntar(entrada: str, formato: str = "csv") -> tuple[Path, Path]:
        dedup_ruta, final_ruta = tmp_path / "dedup", tmp_path / "por_ccaa"
        raw = replace(CIUDADES_RAW, ruta=str(entrada))
        dedup = replace(CIUDADES_DEDUP, ruta=str(dedup_ruta), formato=formato)
        final = replace(POBLACION_POR_CCAA, ruta=str(final_ruta), formato=formato)

        monkeypatch.setattr(ciudades_job, "CIUDADES_RAW", raw)
        monkeypatch.setattr(ciudades_job, "CIUDADES_DEDUP", dedup)
        monkeypatch.setattr(ciudades_job, "CONSUME", (raw,))
        monkeypatch.setattr(ciudades_job, "PRODUCE", (dedup,))
        monkeypatch.setattr(por_ccaa_job, "CIUDADES_DEDUP", dedup)
        monkeypatch.setattr(por_ccaa_job, "POBLACION_POR_CCAA", final)
        monkeypatch.setattr(por_ccaa_job, "CONSUME", (dedup,))
        monkeypatch.setattr(por_ccaa_job, "PRODUCE", (final,))
        return dedup_ruta, final_ruta

    return _reapuntar


@pytest.fixture
def cli(spark, monkeypatch):
    """Hace que `main()` use la sesion de la suite y no la pare al terminar.

    Sin esto, en PySpark `getOrCreate` devuelve la sesion compartida y el
    `spark.stop()` del context manager destruye su contexto: cada test que
    llama a `main()` obliga a reconstruir la JVM para el siguiente.
    """

    @contextmanager
    def sesion_de_test(app_name: str = "test"):
        yield spark

    monkeypatch.setattr("etl_kedro.main.spark_session", sesion_de_test)


@pytest.fixture
def escribir_ciudades(tmp_path):
    """Devuelve una funcion que escribe un CSV valido para el dominio ciudades.

    La cabecera sale de `CIUDADES_ESQUEMA`, no de una constante escrita a mano:
    los jobs exigen exactamente las columnas declaradas, y un test que fijara
    las suyas dejaria de representar el contrato en cuanto alguien tocara el
    esquema.
    """
    columnas = CIUDADES_ESQUEMA.fieldNames()

    def _escribir(filas: list[tuple], nombre: str = "ciudades.csv") -> str:
        path = tmp_path / nombre
        lineas = [",".join(columnas)]
        lineas.extend(",".join(str(valor) for valor in fila) for fila in filas)
        path.write_text("\n".join(lineas) + "\n", encoding="utf-8")
        return str(path)

    return _escribir
