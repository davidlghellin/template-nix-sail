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


def test_check_input_exists_ignora_uris():
    # Un `s3://` lo resuelve el motor: comprobarlo en local daria un falso negativo.
    check_input_exists("s3://bucket/datos.csv")  # no lanza


@pytest.mark.parametrize("patron", ["*.csv", "part-?.csv"])
def test_check_input_exists_acepta_un_comodin_que_casa(tmp_path, patron):
    (tmp_path / "part-0.csv").write_text("a\n", encoding="utf-8")

    check_input_exists(str(tmp_path / patron))  # no lanza


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


def test_problema_de_cabecera_rechaza_columnas_sobrantes():
    from pyspark.sql.types import StringType, StructField, StructType

    from etl_kedro.core.datasets import problema_de_cabecera

    esquema = StructType([StructField("a", StringType()), StructField("b", StringType())])

    problema = problema_de_cabecera(esquema, ["a", "b", "extra"])

    assert problema is not None
    assert "extra" in problema


def test_cabecera_csv_ignora_el_bom(tmp_path):
    # Un CSV exportado desde Excel empieza con BOM; los dos motores lo quitan.
    from etl_kedro.core.datasets import cabecera_csv

    path = tmp_path / "bom.csv"
    path.write_bytes("\ufeffciudad,habitantes\nmadrid,1\n".encode())

    assert cabecera_csv(str(path)) == ["ciudad", "habitantes"]


@pytest.mark.parametrize(
    ("a", "b", "solapan"),
    [
        ("/d/x", "/d/x", True),
        ("/d/x/in.csv", "/d/x", True),
        ("/d/x", "/d/x/sub", True),
        ("/d/x", "/d/xy", False),
        ("s3://b/raw", "s3://b/raw/", True),
        ("s3://b/raw", "s3://b/out", False),
    ],
)
def test_rutas_solapadas(a, b, solapan):
    from etl_kedro.core.datasets import rutas_solapadas

    assert rutas_solapadas(a, b) is solapan


def test_rutas_solapadas_con_un_comodin_relativo(tmp_path, monkeypatch):
    # Relativo contra absoluto: antes no se normalizaba el del comodin.
    from etl_kedro.core.datasets import rutas_solapadas

    monkeypatch.chdir(tmp_path)

    assert rutas_solapadas("data/in/*.csv", str(tmp_path / "data" / "in"))


def test_cabecera_csv_de_un_fichero_que_no_es_utf8(tmp_path):
    # Latin-1 con una "n" en los datos: el motor lo lee, la comprobacion no
    # puede reventar con traceback.
    from etl_kedro.core.datasets import cabecera_csv

    path = tmp_path / "latin1.csv"
    path.write_bytes("ciudad,comunidad\nlleida,Catalu\xf1a\n".encode("latin-1"))

    assert cabecera_csv(str(path)) == ["ciudad", "comunidad"]


def test_rutas_solapadas_con_otra_capitalizacion(tmp_path):
    # En un sistema de ficheros que no distingue mayusculas (macOS por defecto)
    # son la misma carpeta, aunque el texto no coincida.
    from etl_kedro.core.datasets import rutas_solapadas

    carpeta = tmp_path / "Solape"
    carpeta.mkdir()
    (carpeta / "entrada.csv").write_text("a\n", encoding="utf-8")
    otra = tmp_path / "solape"
    if not otra.exists():
        pytest.skip("este sistema de ficheros distingue mayusculas")

    assert rutas_solapadas(str(carpeta / "entrada.csv"), str(otra))


def test_problema_de_formato_detecta_partes_del_otro_formato(tmp_path):
    from etl_kedro.core.datasets import problema_de_formato

    parquet = tmp_path / "pq"
    parquet.mkdir()
    (parquet / "abc_0.zst.parquet").write_bytes(b"PAR1")
    (parquet / "_SUCCESS").touch()
    csv = tmp_path / "csv"
    csv.mkdir()
    (csv / "part-0.csv").write_text("a\n", encoding="utf-8")

    assert "tiene parquet" in (problema_de_formato(str(parquet), "csv") or "")
    assert "tiene CSV" in (problema_de_formato(str(csv), "parquet") or "")
    assert problema_de_formato(str(parquet), "parquet") is None
    assert problema_de_formato(str(csv), "csv") is None
    assert problema_de_formato(str(tmp_path / "vacio-no-existe"), "csv") is None


def test_rutas_solapadas_con_un_comodin_en_un_directorio_intermedio(tmp_path):
    # `*/in.csv` casa con `out/in.csv`: escribir en `out` borraria esa entrada.
    from etl_kedro.core.datasets import rutas_solapadas

    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "in.csv").write_text("a\n", encoding="utf-8")
    (tmp_path / "otra").mkdir()

    assert rutas_solapadas(str(tmp_path / "*" / "in.csv"), str(tmp_path / "out"))
    assert not rutas_solapadas(str(tmp_path / "out" / "*.csv"), str(tmp_path / "otra"))


def test_problema_de_cabecera_detecta_columnas_repetidas():
    from pyspark.sql.types import StringType, StructField, StructType

    from etl_kedro.core.datasets import problema_de_cabecera

    esquema = StructType([StructField("a", StringType()), StructField("b", StringType())])

    assert "repite" in (problema_de_cabecera(esquema, ["a", "b", "a"]) or "")


def test_cabecera_csv_no_lee_un_fichero_comprimido(tmp_path):
    # El motor lo descomprime; aqui se leerian bytes de gzip como cabecera.
    import gzip

    from etl_kedro.core.datasets import cabecera_csv

    path = tmp_path / "datos.csv.gz"
    with gzip.open(path, "wt", encoding="utf-8") as f:
        f.write("ciudad,habitantes\nmadrid,1\n")

    assert cabecera_csv(str(path)) is None


def test_check_input_exists_un_comodin_sin_coincidencias_no_existe(tmp_path):
    # Antes pasaba: se leia "nada" y un job que sobrescribe vaciaba su salida.
    from etl_kedro.core.datasets import EntradaNoEncontradaError

    (tmp_path / "ciudades.csv").write_text("a\n", encoding="utf-8")

    check_input_exists(str(tmp_path / "ciudades*.csv"))  # casa: no lanza
    with pytest.raises(EntradaNoEncontradaError, match="Ningun fichero"):
        check_input_exists(str(tmp_path / "ciudadess*.csv"))


def test_cabecera_csv_ignora_ficheros_ocultos_y_con_guion_bajo(tmp_path):
    # Los motores los ignoran; un `._part-0.csv` de macOS se leia como cabecera.
    from etl_kedro.core.datasets import cabecera_csv

    (tmp_path / "._part-0.csv").write_bytes(b"\x00\x05\x16\x07Mac OS X")
    (tmp_path / "_tmp.csv").write_text("basura\n", encoding="utf-8")
    (tmp_path / "part-0.csv").write_text("ciudad,habitantes\nmadrid,1\n", encoding="utf-8")

    assert cabecera_csv(str(tmp_path)) == ["ciudad", "habitantes"]
