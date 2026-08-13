"""Utilidades comunes a los tests de la ETL."""

from contextlib import contextmanager

import pytest

from etl_kedro.jobs.ciudades.datasets import CIUDADES_ESQUEMA


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

    La cabecera sale de `CIUDADES_ESQUEMA`, no de una constante escrita a mano.
    Los jobs leen con el esquema declarado y un esquema explicito se aplica
    **por posicion**, asi que un test que fijara las columnas por su cuenta
    dejaria de representar el contrato en cuanto alguien tocara el esquema.
    """
    columnas = CIUDADES_ESQUEMA.fieldNames()

    def _escribir(filas: list[tuple], nombre: str = "ciudades.csv") -> str:
        path = tmp_path / nombre
        lineas = [",".join(columnas)]
        lineas.extend(",".join(str(valor) for valor in fila) for fila in filas)
        path.write_text("\n".join(lineas) + "\n", encoding="utf-8")
        return str(path)

    return _escribir
