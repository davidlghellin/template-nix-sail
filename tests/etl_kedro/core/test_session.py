"""Tests de la seleccion de backend y de la comprobacion del entorno."""

import pytest

from etl_kedro.core.session import BackendError, check_java_available, resolve_backend


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
