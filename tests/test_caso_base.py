"""Caso base de compatibilidad: mismas asserciones contra PySail y PySpark.

Los valores esperados son los que produce Spark 4.x real: se capturaron
ejecutando el mismo codigo con `SPARK_BACKEND=pyspark` y se comparo la salida
(esquema + filas) contra PySail.
"""

from datetime import date, datetime
from decimal import Decimal

import pytest

from src.caso_base import (
    AUDIT,
    CORTE,
    FILAS_1,
    FILAS_2,
    TABLE_1,
    TABLE_2,
    TABLE_OUT,
    conformar,
    etl,
    filtrar_y_deduplicar,
    unir_y_agregar,
)


@pytest.fixture
def t1(spark):
    return spark.createDataFrame(FILAS_1, TABLE_1)


@pytest.fixture
def t2(spark):
    return spark.createDataFrame(FILAS_2, TABLE_2)


def por_clave(df, columna="OUT_COL_3"):
    return {r[columna]: r for r in df.collect()}


# --- expresiones ---


def test_filtra_normaliza_y_deduplica(t2):
    filas = filtrar_y_deduplicar(t2, CORTE).collect()

    # 0227 -> 0182 deja dos filas identicas que distinct colapsa; C9 es AUT y se filtra.
    assert len(filas) == 1
    assert filas[0]["TABLE_2_COL_2"] == "0182"
    assert filas[0]["TABLE_2_COL_4"] == "P1"


def test_left_join_conserva_la_fila_sin_pareja(t1, t2):
    filas = por_clave(unir_y_agregar(t1, filtrar_y_deduplicar(t2, CORTE), AUDIT))

    assert filas["C1"]["OUT_COL_4"] == "P1"
    assert filas["C2"]["OUT_COL_4"] == "SIN_MATCH"


def test_agregado_conserva_la_escala_del_decimal(t1, t2):
    filas = por_clave(unir_y_agregar(t1, filtrar_y_deduplicar(t2, CORTE), AUDIT))

    assert filas["C1"]["OUT_COL_5"] == Decimal("300.75")
    assert filas["C2"]["OUT_COL_5"] == Decimal("10.00")


def test_conformar_ordena_y_castea_al_esquema_destino(t1, t2):
    salida = etl(t1, t2, CORTE, AUDIT)

    assert salida.columns == [f.name for f in TABLE_OUT.fields]
    assert [f.dataType for f in salida.schema.fields] == [f.dataType for f in TABLE_OUT.fields]

    filas = por_clave(salida)
    # El cast timestamp -> date no desplaza el dia.
    assert filas["C1"]["OUT_COL_7"] == date(2024, 12, 31)
    assert filas["C1"]["OUT_COL_6"] == datetime(2025, 1, 20, 15, 4, 31)


def test_conformar_detecta_columnas_que_faltan(t1):
    with pytest.raises(ValueError, match="faltan columnas"):
        conformar(t1, TABLE_OUT)


def test_nullability_de_la_salida(t1, t2):
    # coalesce y lit no admiten nulo; el resto viene de las tablas de origen.
    nulos = {f.name: f.nullable for f in etl(t1, t2, CORTE, AUDIT).schema.fields}

    assert nulos["OUT_COL_4"] is False
    assert nulos["OUT_COL_6"] is False
    assert nulos["OUT_COL_1"] is True
    assert nulos["OUT_COL_5"] is True


# --- join con nombres de columna repetidos ---


def test_join_cualificado_por_dataframe(spark):
    esquema = "COL_A string, COL_B string"
    a = spark.createDataFrame([("k1", "izq")], esquema)
    b = spark.createDataFrame([("k1", "der")], esquema)

    fila = (
        a.join(b, b["COL_A"] == a["COL_A"], "inner")
        .select(
            a["COL_A"].alias("CLAVE"),
            a["COL_B"].alias("IZQ"),
            b["COL_B"].alias("DER"),
        )
        .first()
    )

    assert (fila["CLAVE"], fila["IZQ"], fila["DER"]) == ("k1", "izq", "der")
