"""Test e2e de la cadena: el catalogo declara tipos y la salida los cumple.

Los tests de cada job comprueban su logica; este comprueba el **contrato**: que
lo que acaba escrito en disco tiene exactamente el `StructType` que declara su
dataset, despues de pasar por lectura, transformaciones y escritura reales.

Se escribe en parquet a proposito. Un CSV convierte todo a texto, asi que un
`bigint` y un `int` salen identicos y el test daria verde sin comprobar nada de
tipos. Parquet guarda el esquema junto a los datos, que es lo que aqui importa.
"""

import pytest

from etl_kedro.jobs.ciudades.datasets import CIUDADES_DEDUP
from etl_kedro.jobs.por_ccaa.datasets import POBLACION_POR_CCAA
from etl_kedro.main import EXIT_OK, main


@pytest.fixture
def cadena_ejecutada(cli, reapuntar_cadena, escribir_ciudades):
    """Corre `--all` en parquet sobre `tmp_path` y devuelve donde quedo cada dataset."""
    entrada = escribir_ciudades(
        [
            ("madrid", 3000000, "Madrid", "Comunidad de Madrid", 604.3),
            ("madrid", 999, "Madrid", "Comunidad de Madrid", 604.3),
            ("alcobendas", 100000, "Madrid", "Comunidad de Madrid", 45.0),
            ("barcelona", 1600000, "Barcelona", "Cataluna", 101.4),
        ]
    )
    # Declarados en parquet: un CSV convierte todo a texto y no dejaria nada
    # de tipos que comprobar.
    dedup, final = reapuntar_cadena(entrada, formato="parquet")

    assert main(["--all"]) == EXIT_OK
    return {CIUDADES_DEDUP.nombre: str(dedup), POBLACION_POR_CCAA.nombre: str(final)}


@pytest.mark.parametrize("dataset", [CIUDADES_DEDUP, POBLACION_POR_CCAA], ids=lambda d: d.nombre)
def test_la_salida_cumple_el_esquema_declarado(spark, cadena_ejecutada, dataset):
    """Lo escrito tiene el StructType del catalogo: nombres, tipos y nulabilidad.

    Es la comprobacion que hace innecesario fiarse de `inferSchema`: si la
    salida cuadra con lo declarado, cuadra igual la ejecute quien la ejecute.
    """
    escrito = spark.read.parquet(cadena_ejecutada[dataset.nombre])

    assert escrito.schema == dataset.esquema


def test_los_tipos_no_dependen_del_motor(spark, cadena_ejecutada):
    """Ningun tipo queda "a lo que salga": todos son los declarados.

    Sin esquema explicito, la inferencia de un CSV depende del motor que lo lea
    (los enteros son el caso tipico), y el mismo codigo produce esquemas
    distintos segun donde corra.
    """
    for nombre, ruta in cadena_ejecutada.items():
        tipos = dict(spark.read.parquet(ruta).dtypes)
        assert "habitantes" in tipos
        assert tipos["habitantes"] == "bigint", f"{nombre}: habitantes es {tipos['habitantes']}"


def test_los_datos_llegan_bien_hasta_el_final(spark, cadena_ejecutada):
    # `madrid` estaba duplicada: el primer job la deduplica y el segundo agrega.
    filas = spark.read.parquet(cadena_ejecutada[POBLACION_POR_CCAA.nombre]).collect()

    assert {fila["comunidad_autonoma"]: fila["habitantes"] for fila in filas} == {
        "Comunidad de Madrid": 3100000,
        "Cataluna": 1600000,
    }
