# dev-nix-sail

Nix-configured development environment for Sail/PySpark.

## Structure

```
dev-nix-sail/
├── devel0pez/             # Library: demos and compatibility base case
│   ├── calculator.py      # Math functions
│   ├── dataframes.py      # DataFrame functions
│   ├── caso_base.py       # Compatibility base case (schemas + ETL)
│   └── main.py            # Interactive demo
├── etl_kedro/             # CSV ETL, estilo Kedro (see README_ETL_KEDRO.md)
│   ├── main.py            # argparse CLI
│   ├── core/              # reusable machinery: pipeline, quality, session
│   └── jobs/ciudades/     # one flow per folder: datasets, transform, job
├── tests/
│   ├── conftest.py        # Fixtures (spark), shared by every subpackage
│   ├── devel0pez/
│   │   ├── test_calculator.py # Unit tests
│   │   ├── test_dataframes.py # DataFrame tests
│   │   ├── test_caso_base.py  # Base case: expressions, join, schema
│   │   └── test_caso_base_catalogo.py # Base case end to end: catalog + insertInto
│   └── etl_kedro/
│       ├── test_main.py       # CLI: args and exit codes
│       ├── core/              # pipeline, quality, datasets, session
│       └── jobs/ciudades/     # the ciudades job end to end
├── resources/
│   └── ciudades_espana.csv # 100 Spanish cities dataset
├── .ptpython/
│   └── config.py          # ptpython configuration
├── flake.nix              # Nix environment
└── pyproject.toml         # Project configuration
```

## Installation

### With Nix (recommended)

```bash
nix develop
```

### With pip

```bash
python -m venv venv
source venv/bin/activate
pip install pysail "pyspark[connect]" pytest ptpython ruff colorlog
```

## Usage

### Tests

```bash
# With PySail (default, no Java required)
pytest -v

# With PySpark (requires Java)
SPARK_BACKEND=pyspark pytest -v

# Unit tests only
pytest -m unit -v
```

### Shell Aliases

Available after `nix develop`:

| Alias | Command                         |
| ----- | ------------------------------- |
| `t`   | `pytest -v`                     |
| `ts`  | `SPARK_BACKEND=pysail pytest -v`|
| `tp`  | `SPARK_BACKEND=pyspark pytest -v`|
| `r`   | `ruff check .`                  |
| `rf`  | `ruff check --fix . && ruff format .` |

### History Search

Press `Ctrl+R` for fzf fuzzy history search in bash.

### Demo

```bash
python devel0pez/main.py
```

Auto-detects external Sail server. If unavailable, starts an internal one.

### Sail Server

```bash
# Start server
sail spark server --port 50051

# Connect from another terminal
python devel0pez/main.py
```

### Interactive Terminal

```bash
ptpython
```

Features (via `.ptpython/config.py`):
- Fuzzy completion (Tab)
- Auto-suggest from history (accept with →)
- History search (Ctrl+R)
- Syntax highlighting
- Monokai color scheme

```python
>>> from pyspark.sql import SparkSession
>>> spark = SparkSession.builder.remote("sc://localhost:50051").getOrCreate()
>>> spark.sql("SELECT 1 + 1").show()
```

## Linter

```bash
ruff check .        # Check errors
ruff check --fix .  # Auto-fix
ruff format .       # Format code
```

## Backends

| Backend | Variable                | Java | Description              |
| ------- | ----------------------- | ---- | ------------------------ |
| PySail  | `SPARK_BACKEND=pysail`  | No   | Rust engine, fast        |
| PySpark | `SPARK_BACKEND=pyspark` | Yes  | Traditional Spark w/ JVM |

The `pyspark` backend uses `JAVA_HOME` before `PATH`. If your shell exports one
(SDKMAN, for instance) pointing to a JDK older than 17, Spark fails to start with
`JAVA_GATEWAY_EXITED`; `unset JAVA_HOME` to fall back to the JDK 17 from the Nix
shell.

## Available Functions

### `devel0pez/calculator.py`

| Function     | Description      |
| ------------ | ---------------- |
| `suma(a, b)` | Adds two numbers |

### `devel0pez/dataframes.py`

| Function                                   | Description                        |
| ------------------------------------------ | ---------------------------------- |
| `suma_columnas(df, col1, col2, nueva_col)` | Sums two columns and adds result   |

### `devel0pez/caso_base.py`

Shape of a real ETL, used as the compatibility base case between backends: two
source tables with an explicit `StructType`, a `CASE` + `DISTINCT` filter, a
`LEFT JOIN` qualified by DataFrame (both tables repeat column names), a decimal
aggregate, and a positional conform to the target schema for `insertInto`.

| Function                          | Description                                       |
| --------------------------------- | ------------------------------------------------- |
| `filtrar_y_deduplicar(t2, corte)` | Filter by date/type + `CASE` normalization + `DISTINCT` |
| `unir_y_agregar(t1, t2, audit)`   | `LEFT JOIN` + `coalesce` + `groupBy`/`sum`        |
| `conformar(df, schema)`           | Orders and casts to the target schema             |
| `etl(t1, t2, corte, audit)`       | Full pipeline, from the sources to `TABLE_OUT`    |

The expected values are Spark's: they were captured with `SPARK_BACKEND=pyspark`
and the output (schema + rows) was compared against PySail.

## Build

```bash
python -m build
```

Generates in `dist/`:
- `dev_nix_sail-0.1.0-py3-none-any.whl` (wheel)
- `dev_nix_sail-0.1.0.tar.gz` (sdist)

## Fixture

```python
def test_my_function(spark):
    df = spark.createDataFrame([(1, 2)], ["a", "b"])
    # ...
```

Backend is selected via `SPARK_BACKEND` (pysail by default).
