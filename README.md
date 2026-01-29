# Test Sail

Proyecto de Python para aprender y practicar testing con pytest.

## Estructura

```
test-sail/
├── src/
│   ├── calculator.py          # Funciones matemáticas
│   └── dataframes.py          # Funciones de DataFrames
├── tests/
│   ├── conftest.py            # Fixtures con PySail
│   ├── test_calculator.py     # Tests de calculator
│   ├── test_dataframes.py     # Tests básicos de DataFrames
│   └── test_dataframes_pysail.py # Tests adicionales
├── pyproject.toml             # Configuración del proyecto
└── venv/                      # Entorno virtual
```

## Instalación

```bash
# Crear entorno virtual
python3 -m venv venv

# Activar entorno virtual
source venv/bin/activate

# Instalar dependencias de desarrollo
pip install pytest pyspark "pyspark[connect]" pysail
```

## Ejecutar tests

```bash
# Tests unitarios + PySail (sin Java)
pytest -m "not pyspark"

# Solo tests de PySail
pytest -m pysail

# Solo tests de PySpark (requiere Java)
pytest -m pyspark

# Solo tests unitarios
pytest -m unit

# Con detalle
pytest -m "not pyspark" -v
```

> **Nota:** No se pueden mezclar tests de `pyspark` y `pysail` en la misma ejecución porque Spark no permite tener sesiones locales y remotas simultáneamente.

## Funciones disponibles

### Calculator (`src/calculator.py`)

| Función | Descripción |
|---------|-------------|
| `suma(a, b)` | Suma dos números |

### DataFrames (`src/dataframes.py`)

| Función | Descripción |
|---------|-------------|
| `suma_columnas(df, col1, col2, nueva_col)` | Suma dos columnas y añade el resultado como nueva columna |

## Fixtures disponibles

### PySpark (requiere Java)

| Fixture | Scope | Descripción |
|---------|-------|-------------|
| `spark` | session | Sesión de Spark local |

```python
@pytest.mark.pyspark
def test_mi_funcion(spark):
    df = spark.createDataFrame([(1, 2)], ["a", "b"])
```

### PySail (sin Java)

| Fixture | Scope | Descripción |
|---------|-------|-------------|
| `sail_server` | session | Servidor Spark Connect con Sail |
| `spark_sail` | session | Sesión conectada a Sail |

```python
@pytest.mark.pysail
def test_mi_funcion(spark_sail):
    df = spark_sail.createDataFrame([(1, 2)], ["a", "b"])
```

## Añadir nuevos tests

1. Crear función en `src/calculator.py` o `src/dataframes.py`
2. Añadir tests en `tests/test_*.py`
3. Ejecutar `pytest -v` para verificar
