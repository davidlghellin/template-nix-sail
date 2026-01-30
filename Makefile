.PHONY: help test test-sail test-spark lint fix build clean demo \
        redpanda-start redpanda-stop redpanda-producer redpanda-consumer

# Default target
help:
	@echo "⛵ Template Nix Sail - Available commands"
	@echo ""
	@echo "Testing:"
	@echo "  make test        Run tests with PySail (default)"
	@echo "  make test-sail   Run tests with PySail"
	@echo "  make test-spark  Run tests with PySpark (requires Java)"
	@echo ""
	@echo "Linting:"
	@echo "  make lint        Check code with ruff"
	@echo "  make fix         Auto-fix and format code"
	@echo ""
	@echo "Build:"
	@echo "  make build       Build wheel package"
	@echo "  make clean       Remove build artifacts"
	@echo ""
	@echo "Demo:"
	@echo "  make demo        Run interactive demo"
	@echo ""
	@echo "Streaming (Redpanda - requires Docker):"
	@echo "  make redpanda-start     Start Redpanda"
	@echo "  make redpanda-stop      Stop Redpanda"
	@echo "  make redpanda-producer  Run producer"
	@echo "  make redpanda-consumer  Run consumer with PySail"

# Testing
test: test-sail

test-sail:
	SPARK_BACKEND=pysail pytest -v

test-spark:
	SPARK_BACKEND=pyspark pytest -v

# Linting
lint:
	ruff check .

fix:
	ruff check --fix . && ruff format .

# Build
build:
	python -m build

clean:
	rm -rf dist/ build/ *.egg-info src/*.egg-info .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

# Demo
demo:
	python src/main.py

# Redpanda
redpanda-start:
	rpk container start

redpanda-stop:
	rpk container stop

redpanda-producer:
	python src/streaming/redpanda/producer.py

redpanda-consumer:
	python src/streaming/redpanda/consumer.py
