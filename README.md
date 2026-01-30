# dev-nix-sail

Nix template for PySpark/PySail projects with streaming support.

## Structure

```
dev-nix-sail/
├── src/
│   ├── calculator.py      # Math functions
│   ├── dataframes.py      # DataFrame functions
│   ├── main.py            # Interactive demo
│   └── streaming/
│       └── redpanda/            # Kafka-compatible (C++, BSL 1.1)
│           ├── producer.py
│           ├── consumer.py
│           └── consumer_simple.py
├── tests/
│   ├── conftest.py        # Fixtures (spark)
│   ├── test_calculator.py # Unit tests
│   └── test_dataframes.py # DataFrame tests
├── resources/
│   └── ciudades_espana.csv # 100 Spanish cities dataset
├── .ptpython/
│   └── config.py          # ptpython configuration
├── flake.nix              # Nix environment
├── Makefile               # Common commands
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
pip install pysail "pyspark[connect]" pytest ptpython ruff colorlog kafka-python
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
python src/main.py
```

Auto-detects external Sail server. If unavailable, starts an internal one.

### Sail Server

```bash
# Start server
sail spark server --port 50051

# Connect from another terminal
python src/main.py
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

## Streaming with Redpanda

Redpanda is a Kafka-compatible streaming platform (C++, no JVM required).

> **Note:** BSL 1.1 license (free for development and internal production use, not for offering as a managed service).

```bash
make redpanda-start      # Start (requires Docker)
make redpanda-producer   # Terminal 1 - Send numbers
make redpanda-consumer   # Terminal 2 - Sum with PySail
make redpanda-stop       # Stop
```

### How it works

1. **Producer** sends numbers as JSON to topic `numbers`
2. **Consumer** reads continuously and calculates running sum with PySail
3. Results update in real-time as you type numbers

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

## Available Functions

### `src/calculator.py`

| Function     | Description      |
| ------------ | ---------------- |
| `suma(a, b)` | Adds two numbers |

### `src/dataframes.py`

| Function                                   | Description                        |
| ------------------------------------------ | ---------------------------------- |
| `suma_columnas(df, col1, col2, nueva_col)` | Sums two columns and adds result   |

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
