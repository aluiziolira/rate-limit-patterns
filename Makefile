.PHONY: help install test test-quick lint format clean \
	benchmark benchmark-local benchmark-redis benchmark-redis-docker \
	benchmark-latency benchmark-memory benchmark-fairness \
	benchmark-redis-latency benchmark-multi-instance \
	redis-up redis-wait redis-down

REDIS_URL ?= redis://localhost:6379/15
DOCKER_COMPOSE ?= docker compose
POETRY ?= poetry
BENCH_CMD = $(POETRY) run python -m benchmarks.scenarios

help:
	@echo "Available targets:"
	@echo "  install             - Install project dependencies"
	@echo "  test                - Run all tests with coverage"
	@echo "  test-quick          - Run tests without coverage"
	@echo "  lint                - Run ruff + mypy strict"
	@echo "  format              - Auto-format code with ruff"
	@echo "  clean               - Remove cache files"
	@echo "  benchmark           - Run local (non-Redis) benchmarks"
	@echo "  benchmark-local     - Alias for local benchmarks"
	@echo "  benchmark-latency   - Run latency benchmarks"
	@echo "  benchmark-memory    - Run memory benchmarks"
	@echo "  benchmark-fairness  - Run fairness benchmarks"
	@echo "  benchmark-redis     - Run Redis benchmarks (REDIS_URL defaults to $(REDIS_URL))"
	@echo "  benchmark-redis-latency - Run Redis latency benchmark"
	@echo "  benchmark-multi-instance - Run Redis multi-instance benchmark"
	@echo "  benchmark-redis-docker - Run Redis benchmarks using docker-compose"


install:
	$(POETRY) install --with dev

test:
	@echo "Starting Redis..."
	$(DOCKER_COMPOSE) up -d redis
	@echo "Waiting for Redis to be ready..."
	@sleep 2
	@echo "Running tests..."
	@REDIS_URL=redis://localhost:6379/15 $(POETRY) run pytest tests/ -n auto --cov=rate_limit_patterns --cov-report=term-missing --cov-report=html --cov-fail-under=85; \
	RET=$$?; \
	echo "Stopping Redis..."; \
	$(DOCKER_COMPOSE) down; \
	[ $$RET -eq 5 ] || exit $$RET

test-quick:
	$(POETRY) run pytest tests/ -n auto

lint:
	$(POETRY) run ruff check src/ tests/
	$(POETRY) run ruff format --check src/ tests/
	$(POETRY) run mypy src/ --strict

format:
	$(POETRY) run ruff format src/ tests/
	$(POETRY) run ruff check --fix src/ tests/

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name ".coverage" -delete 2>/dev/null || true
	rm -rf htmlcov/ .coverage
	rm -f benchmarks/results/*.json

benchmark: benchmark-local
	@echo "All benchmarks complete. Results in benchmarks/results/"

benchmark-local: benchmark-latency benchmark-memory benchmark-fairness

benchmark-latency:
	@echo "Running latency benchmark..."
	$(BENCH_CMD).latency

benchmark-memory:
	@echo "Running memory benchmark..."
	$(BENCH_CMD).memory

benchmark-fairness:
	@echo "Running fairness benchmark..."
	$(BENCH_CMD).fairness

benchmark-redis: benchmark-redis-latency benchmark-multi-instance

benchmark-redis-latency:
	@echo "Running Redis latency benchmark (REDIS_URL=$(REDIS_URL))..."
	REDIS_URL=$(REDIS_URL) $(BENCH_CMD).redis_latency

benchmark-multi-instance:
	@echo "Running multi-instance benchmark (REDIS_URL=$(REDIS_URL))..."
	REDIS_URL=$(REDIS_URL) $(BENCH_CMD).multi_instance

benchmark-redis-docker:
	@set -e; \
	trap '$(MAKE) redis-down' EXIT; \
	$(MAKE) redis-up; \
	$(MAKE) redis-wait; \
	$(MAKE) benchmark-redis REDIS_URL=$(REDIS_URL)

redis-up:
	@echo "Starting Redis via docker-compose..."
	$(DOCKER_COMPOSE) up -d redis

redis-wait:
	@echo "Waiting for Redis to be ready..."
	@sleep 2

redis-down:
	@echo "Stopping Redis..."
	$(DOCKER_COMPOSE) down
