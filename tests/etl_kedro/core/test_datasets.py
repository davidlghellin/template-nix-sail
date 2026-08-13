"""Tests del tipo `Dataset` y de la comprobacion de rutas de entrada."""

import pytest
from pyspark.sql.types import StringType, StructField, StructType

from etl_kedro.core.datasets import Dataset, check_input_exists

ESQUEMA = StructType([StructField("id", StringType(), True)])


@pytest.fixture
def csv_existente(tmp_path):
    path = tmp_path / "datos.csv"
    path.write_text("id\n1\n", encoding="utf-8")
    return str(path)


def test_check_input_exists_ok(csv_existente):
    check_input_exists(csv_existente)  # no lanza


def test_check_input_exists_falla_si_no_existe(tmp_path):
    with pytest.raises(FileNotFoundError, match="No existe la ruta de entrada"):
        check_input_exists(str(tmp_path / "no-existe.csv"))


@pytest.mark.parametrize("path", ["s3://bucket/datos.csv", "datos/*.csv", "datos/part-?.csv"])
def test_check_input_exists_ignora_uris_y_comodines(path):
    # Los resuelve el motor: comprobarlos en local daria un falso negativo.
    check_input_exists(path)  # no lanza


def test_dataset_guarda_nombre_ruta_y_esquema(csv_existente):
    dataset = Dataset(nombre="datos", ruta=csv_existente, esquema=ESQUEMA)

    assert dataset.nombre == "datos"
    assert dataset.esquema == ESQUEMA
    assert dataset.formato == "csv"


def test_dataset_es_inmutable(csv_existente):
    # Un dataset del catalogo no se reconfigura en caliente. mypy ya lo impide
    # en estatico; el ignore comprueba que en ejecucion tambien falla.
    dataset = Dataset(nombre="datos", ruta=csv_existente)

    with pytest.raises(AttributeError):
        dataset.ruta = "otra"  # type: ignore[misc]


def test_dataset_check_exists_ok(csv_existente):
    Dataset(nombre="datos", ruta=csv_existente).check_exists()  # no lanza


def test_dataset_check_exists_falla(tmp_path):
    dataset = Dataset(nombre="datos", ruta=str(tmp_path / "no-existe.csv"))

    with pytest.raises(FileNotFoundError):
        dataset.check_exists()
