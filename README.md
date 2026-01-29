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
# Ejecutar todos los tests
pytest

# Con detalle
pytest -v

# Un archivo específico
pytest tests/test_calculator.py

# Un test específico
pytest tests/test_calculator.py::test_suma_positivos
```

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

Las fixtures usan PySail como backend (no requiere Java).

| Fixture | Scope | Descripción |
|---------|-------|-------------|
| `sail_server` | session | Servidor Spark Connect con Sail |
| `spark` | session | Sesión de Spark conectada a Sail |

```python
def test_mi_funcion(spark):
    df = spark.createDataFrame([(1, 2)], ["a", "b"])
    # ...
```

## Añadir nuevos tests

1. Crear función en `src/calculator.py` o `src/dataframes.py`
2. Añadir tests en `tests/test_*.py`
3. Ejecutar `pytest -v` para verificar
