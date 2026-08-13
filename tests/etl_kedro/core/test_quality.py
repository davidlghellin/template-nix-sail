"""Tests de los checks de calidad: columnas requeridas, clave y deduplicacion."""

import pytest

from etl_kedro.core.quality import (
    QualityCheckError,
    check_non_null_key,
    check_required_columns,
    deduplicate_by_key,
)

COLUMNAS = ["id", "ciudad", "poblacion"]


@pytest.fixture
def df_ok(spark):
    """DataFrame sin nulos ni duplicados en la clave."""
    return spark.createDataFrame(
        [
            ("1", "madrid", 3200000),
            ("2", "barcelona", 1600000),
            ("3", "valencia", 800000),
        ],
        COLUMNAS,
    )


@pytest.fixture
def df_con_nulos(spark):
    """DataFrame con dos claves nulas."""
    return spark.createDataFrame(
        [
            ("1", "madrid", 3200000),
            (None, "barcelona", 1600000),
            (None, "valencia", 800000),
        ],
        COLUMNAS,
    )


@pytest.fixture
def df_duplicados(spark):
    """DataFrame con la clave `1` repetida tres veces, en orden conocido."""
    return spark.createDataFrame(
        [
            ("1", "madrid-primero", 1),
            ("1", "madrid-medio", 2),
            ("1", "madrid-ultimo", 3),
            ("2", "barcelona", 4),
        ],
        COLUMNAS,
    ).coalesce(1)  # una sola particion: el orden de lectura es determinista


# --- check_required_columns ---


def test_check_required_columns_ok(df_ok):
    resultado = check_required_columns(df_ok, ["id", "ciudad"])

    assert resultado is df_ok  # devuelve el mismo df para encadenar


def test_check_required_columns_ok_lista_vacia(df_ok):
    assert check_required_columns(df_ok, []) is df_ok


def test_check_required_columns_ok_todas(df_ok):
    assert check_required_columns(df_ok, COLUMNAS) is df_ok


def test_check_required_columns_falla_si_falta_una(df_ok):
    with pytest.raises(QualityCheckError) as excinfo:
        check_required_columns(df_ok, ["id", "provincia"])

    assert "provincia" in str(excinfo.value)


def test_check_required_columns_lista_todas_las_que_faltan(df_ok):
    with pytest.raises(QualityCheckError) as excinfo:
        check_required_columns(df_ok, ["provincia", "pais"])

    mensaje = str(excinfo.value)
    assert "provincia" in mensaje
    assert "pais" in mensaje


def test_check_required_columns_distingue_mayusculas(df_ok):
    with pytest.raises(QualityCheckError):
        check_required_columns(df_ok, ["ID"])


# --- check_non_null_key ---


def test_check_non_null_key_ok(df_ok):
    assert check_non_null_key(df_ok, "id") is df_ok


def test_check_non_null_key_falla_con_nulos(df_con_nulos):
    with pytest.raises(QualityCheckError) as excinfo:
        check_non_null_key(df_con_nulos, "id")

    assert "2" in str(excinfo.value)  # cuenta los nulos


def test_check_non_null_key_falla_si_no_existe_la_columna(df_ok):
    with pytest.raises(QualityCheckError) as excinfo:
        check_non_null_key(df_ok, "inexistente")

    assert "inexistente" in str(excinfo.value)


def test_check_non_null_key_sobre_otra_columna(df_con_nulos):
    # Los nulos estan en `id`, no en `ciudad`.
    assert check_non_null_key(df_con_nulos, "ciudad") is df_con_nulos


# --- deduplicate_by_key ---


def test_deduplicate_by_key_deja_una_fila_por_clave(df_duplicados):
    resultado = deduplicate_by_key(df_duplicados, "id")

    assert resultado.count() == 2
    assert sorted(fila["id"] for fila in resultado.collect()) == ["1", "2"]


def test_deduplicate_by_key_conserva_las_columnas(df_duplicados):
    resultado = deduplicate_by_key(df_duplicados, "id")

    assert resultado.columns == COLUMNAS


def test_deduplicate_by_key_keep_first(df_duplicados):
    resultado = deduplicate_by_key(df_duplicados, "id", keep="first")

    ciudades = {fila["id"]: fila["ciudad"] for fila in resultado.collect()}
    assert ciudades["1"] == "madrid-primero"


def test_deduplicate_by_key_keep_last(df_duplicados):
    resultado = deduplicate_by_key(df_duplicados, "id", keep="last")

    ciudades = {fila["id"]: fila["ciudad"] for fila in resultado.collect()}
    assert ciudades["1"] == "madrid-ultimo"


def test_deduplicate_by_key_sin_duplicados_no_cambia_nada(df_ok):
    resultado = deduplicate_by_key(df_ok, "id")

    assert resultado.count() == df_ok.count()


def test_deduplicate_by_key_keep_invalido(df_duplicados):
    with pytest.raises(ValueError, match="keep invalido"):
        deduplicate_by_key(df_duplicados, "id", keep="middle")  # type: ignore[arg-type]


def test_deduplicate_by_key_columna_inexistente(df_duplicados):
    with pytest.raises(QualityCheckError):
        deduplicate_by_key(df_duplicados, "inexistente")


def test_checks_encadenados(df_duplicados):
    resultado = deduplicate_by_key(
        check_non_null_key(check_required_columns(df_duplicados, COLUMNAS), "id"),
        "id",
    )

    assert resultado.count() == 2
