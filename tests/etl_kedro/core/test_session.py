"""Tests de la seleccion de backend y de la comprobacion del entorno."""

import pytest

from etl_kedro.core.session import (
    BackendError,
    check_java_available,
    resolve_backend,
    spark_session,
)


@pytest.mark.parametrize("backend", ["pysail", "pyspark"])
def test_resolve_backend_validos(backend):
    assert resolve_backend(backend) == backend


def test_resolve_backend_por_defecto(monkeypatch):
    monkeypatch.delenv("SPARK_BACKEND", raising=False)

    assert resolve_backend() == "pysail"


def test_resolve_backend_lee_el_entorno(monkeypatch):
    monkeypatch.setenv("SPARK_BACKEND", "pyspark")

    assert resolve_backend() == "pyspark"


@pytest.mark.parametrize("valor", ["pysprak", "PYSPARK", "spark", ""])
def test_resolve_backend_rechaza_valores_desconocidos(monkeypatch, valor):
    # Lo importante: un typo no puede caer silenciosamente en pysail.
    monkeypatch.setenv("SPARK_BACKEND", valor)

    with pytest.raises(BackendError, match="SPARK_BACKEND invalido"):
        resolve_backend()


def test_check_java_available_con_java_home(monkeypatch, tmp_path):
    java = tmp_path / "bin" / "java"
    java.parent.mkdir()
    java.touch()
    monkeypatch.setenv("JAVA_HOME", str(tmp_path))

    check_java_available()  # no lanza


def test_check_java_available_usa_el_path_si_no_hay_java_home(monkeypatch):
    monkeypatch.delenv("JAVA_HOME", raising=False)
    monkeypatch.setattr("etl_kedro.core.session.shutil.which", lambda _: "/usr/bin/java")

    check_java_available()  # no lanza


def test_check_java_available_sin_java(monkeypatch):
    monkeypatch.delenv("JAVA_HOME", raising=False)
    monkeypatch.setattr("etl_kedro.core.session.shutil.which", lambda _: None)

    with pytest.raises(BackendError, match="necesita Java"):
        check_java_available()


def test_check_java_available_java_home_que_no_existe(monkeypatch, tmp_path):
    monkeypatch.setenv("JAVA_HOME", str(tmp_path / "no-existe"))
    monkeypatch.setattr("etl_kedro.core.session.shutil.which", lambda _: None)

    with pytest.raises(BackendError, match="necesita Java"):
        check_java_available()


# --- el servidor de Sail se para pase lo que pase ---


class ServidorFalso:
    """Sustituto de `SparkConnectServer` que anota si lo han parado."""

    def __init__(self) -> None:
        self.parado = False

    listening_address = ("127.0.0.1", 15002)

    def start(self, background: bool = False) -> None:
        pass

    def stop(self) -> None:
        self.parado = True


def _falsear_pysail(monkeypatch, servidor, sesion):
    monkeypatch.setenv("SPARK_BACKEND", "pysail")
    monkeypatch.setitem(
        __import__("sys").modules,
        "pysail.spark",
        type("modulo", (), {"SparkConnectServer": lambda: servidor}),
    )
    constructor = type(
        "builder", (), {"remote": lambda self, url: self, "getOrCreate": lambda self: sesion}
    )()
    monkeypatch.setattr(
        "etl_kedro.core.session.SparkSession", type("SparkSession", (), {"builder": constructor})
    )


def test_pysail_para_el_servidor_al_terminar(monkeypatch):
    servidor = ServidorFalso()
    _falsear_pysail(monkeypatch, servidor, type("sesion", (), {"stop": lambda self: None})())

    with spark_session():
        pass

    assert servidor.parado


def test_pysail_para_el_servidor_aunque_falle_el_stop_de_spark(monkeypatch):
    """Si `spark.stop()` lanza, el servidor tiene que pararse igual.

    Con un solo `finally` para las dos llamadas, la excepcion de la primera se
    llevaba por delante la segunda y dejaba un Spark Connect escuchando en su
    puerto, con el proceso sin terminar.
    """
    servidor = ServidorFalso()

    def stop_que_falla(self):
        raise RuntimeError("el stop de spark ha fallado")

    _falsear_pysail(monkeypatch, servidor, type("sesion", (), {"stop": stop_que_falla})())

    with pytest.raises(RuntimeError, match="el stop de spark"):
        with spark_session():
            pass

    assert servidor.parado
