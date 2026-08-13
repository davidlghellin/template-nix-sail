"""Test end to end de la demo `devel0pez.main`."""

import logging
from pathlib import Path

import pytest

from devel0pez import main as demo

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def demo_ejecutada(spark, monkeypatch, capsys, caplog):
    """Ejecuta `main()` una vez y devuelve todo lo que ha impreso.

    Dos ajustes, y los dos por el mismo motivo: `main()` monta y desmonta su
    propia sesion, y aqui no queremos ni lo uno ni lo otro.

    - `get_spark_session` devuelve la sesion de la suite, en vez de arrancar un
      servidor nuevo (o conectarse al externo del puerto 50051, que puede estar
      o no estar levantado y haria el test no determinista).
    - `stop()` se neutraliza: `main()` la para al terminar y dejaria sin sesion
      a todos los tests que vengan detras.

    El `chdir` es porque el script lee el CSV con una ruta relativa.

    Se juntan dos capturas: las tablas de `show()` salen por stdout, pero los
    logs no los ve `capsys`. El modulo engancha su handler de colorlog a
    `sys.stderr` en el import, antes de que pytest lo sustituya, asi que sus
    mensajes hay que recogerlos por el logger con `caplog`.
    """
    monkeypatch.chdir(REPO_ROOT)
    monkeypatch.setattr(spark, "stop", lambda: None)
    monkeypatch.setattr(demo, "get_spark_session", lambda: (spark, None))
    caplog.set_level(logging.INFO, logger=demo.__name__)

    demo.main()

    return capsys.readouterr().out + caplog.text


def test_demo_lee_las_100_ciudades(demo_ejecutada):
    assert "Total cities: 100" in demo_ejecutada


def test_demo_recorre_todas_las_etapas(demo_ejecutada):
    for etapa in (
        "Reading Spanish cities CSV",
        "Top 10 most populated cities",
        "Population by autonomous community",
        "Population density",
        "Done!",
    ):
        assert etapa in demo_ejecutada, f"falta la etapa {etapa!r}"


def test_demo_imprime_las_tablas(demo_ejecutada):
    assert "ciudad" in demo_ejecutada  # cabecera de show()
    assert "Madrid" in demo_ejecutada  # la mas poblada, sale en el top 10
    assert "densidad" in demo_ejecutada  # columna calculada
