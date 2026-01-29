# Test Sail

Proyecto de Python para aprender y practicar testing con pytest.

## Estructura

```
test-sail/
├── src/
│   ├── calculator.py      # Funciones matemáticas
│   └── dataframes.py      # Funciones de DataFrames
├── tests/
│   ├── conftest.py        # Fixture spark (PySail/PySpark)
│   ├── test_calculator.py # Tests unitarios
│   └── test_dataframes.py # Tests de DataFrames
├── pyproject.toml         # Configuración del proyecto
└── venv/                  # Entorno virtual
```

## Instalación

```bash
# Crear entorno virtual
python3 -m venv venv

# Activar entorno virtual
source venv/bin/activate

# Instalar dependencias
pip install pysail "pyspark[connect]" pytest
```

## Ejecutar tests

```bash
# Con PySail (por defecto, sin Java)
pytest

# Con PySpark (requiere Java)
SPARK_BACKEND=pyspark pytest

# Solo tests unitarios
pytest -m unit

# Con detalle
pytest -v
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

## Fixture disponible

| Fixture | Scope | Descripción |
|---------|-------|-------------|
| `spark` | session | Sesión de Spark (backend según `SPARK_BACKEND`) |

```python
def test_mi_funcion(spark):
    df = spark.createDataFrame([(1, 2)], ["a", "b"])
    # ...
```

**Backends:**
- `pysail` (por defecto): Sin Java, usa Sail como motor
- `pyspark`: Requiere Java instalado

## Añadir nuevos tests

1. Crear función en `src/`
2. Añadir tests en `tests/test_*.py`
3. Ejecutar `pytest -v`
