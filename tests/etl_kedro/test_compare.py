"""Tests de la CLI del comparador."""

import pytest

from etl_kedro.compare import main


def test_rechaza_un_backend_que_no_existe(monkeypatch):
    # Tiene que fallar al parsear, antes de copiar datos o lanzar un subproceso.
    monkeypatch.setattr(
        "etl_kedro.compare.ejecutar",
        lambda *_: pytest.fail("no deberia lanzar ningun backend"),
    )

    with pytest.raises(SystemExit):
        main(["--backends", "pysail", "pysprak"])
