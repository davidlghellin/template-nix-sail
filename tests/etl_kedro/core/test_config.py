"""Tests de la configuracion por entorno y de como resuelve las rutas."""

import pytest

from etl_kedro.core.config import Config, ConfigError


@pytest.fixture(autouse=True)
def entorno_limpio(monkeypatch):
    """Sin variables heredadas: cada test declara las suyas."""
    monkeypatch.delenv("ETL_ENV", raising=False)
    monkeypatch.delenv("ETL_DATA_ROOT", raising=False)


# --- desde_entorno ---


def test_por_defecto_es_dev_con_raiz_local():
    config = Config.desde_entorno()

    assert config.entorno == "dev"
    assert config.raiz == "."


@pytest.mark.parametrize("entorno", ["dev", "pre", "pro"])
def test_acepta_los_entornos_validos(monkeypatch, entorno):
    monkeypatch.setenv("ETL_ENV", entorno)
    monkeypatch.setenv("ETL_DATA_ROOT", "/datos")

    assert Config.desde_entorno().entorno == entorno


@pytest.mark.parametrize("valor", ["produccion", "PRO", ""])
def test_rechaza_un_entorno_desconocido(monkeypatch, valor):
    monkeypatch.setenv("ETL_ENV", valor)

    with pytest.raises(ConfigError, match="ETL_ENV invalido"):
        Config.desde_entorno()


@pytest.mark.parametrize("entorno", ["pre", "pro"])
def test_fuera_de_dev_la_raiz_es_obligatoria(monkeypatch, entorno):
    # Mas vale no arrancar que escribir en el sitio equivocado.
    monkeypatch.setenv("ETL_ENV", entorno)

    with pytest.raises(ConfigError, match="ETL_DATA_ROOT"):
        Config.desde_entorno()


def test_la_raiz_se_lee_del_entorno(monkeypatch):
    monkeypatch.setenv("ETL_DATA_ROOT", "s3://bucket/zona")

    assert Config.desde_entorno().raiz == "s3://bucket/zona"


# --- resolver ---


def test_en_dev_la_ruta_queda_igual():
    assert Config().resolver("data/salida") == "data/salida"


def test_cuelga_la_ruta_relativa_de_la_raiz():
    config = Config(entorno="pro", raiz="s3://bucket/oro")

    assert config.resolver("data/salida") == "s3://bucket/oro/data/salida"


def test_la_raiz_con_barra_final_no_duplica():
    config = Config(entorno="pro", raiz="s3://bucket/oro/")

    assert config.resolver("data/salida") == "s3://bucket/oro/data/salida"


def test_una_ruta_absoluta_escapa_de_la_raiz():
    config = Config(entorno="pro", raiz="s3://bucket/oro")

    assert config.resolver("/mnt/fijo/datos.csv") == "/mnt/fijo/datos.csv"


def test_un_uri_escapa_de_la_raiz():
    config = Config(entorno="pro", raiz="s3://bucket/oro")

    assert config.resolver("gs://otro/datos.csv") == "gs://otro/datos.csv"
