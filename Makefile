.PHONY: help install test test-quick lint format clean

help:
	@echo "Available targets:"
	@echo "  install             - Install project dependencies"
	@echo "  test                - Run all tests with coverage"
	@echo "  test-quick          - Run tests without coverage"
	@echo "  lint                - Run ruff + mypy strict"
	@echo "  format              - Auto-format code with ruff"
	@echo "  clean               - Remove cache files"


install:
	poetry install --with dev

test:
	poetry run pytest tests/ -n auto --cov=rate_limit_patterns --cov-report=term-missing --cov-report=html

test-quick:
	poetry run pytest tests/ -n auto

lint:
	poetry run ruff check src/ tests/
	poetry run ruff format --check src/ tests/
	poetry run mypy src/ --strict

format:
	poetry run ruff format src/ tests/
	poetry run ruff check --fix src/ tests/

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name ".coverage" -delete 2>/dev/null || true
	rm -rf htmlcov/ .coverage
