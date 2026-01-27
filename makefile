# AI Freelance Automation — Makefile
# Fully autonomous AI freelancer system
# Compatible with GNU Make. Tested on Linux/macOS.

SHELL := /bin/bash
PYTHON := python3
PIP := pip3
VENV := .venv
SOURCE_DIR := .
REQUIREMENTS := requirements.txt
REQUIREMENTS_DEV := requirements-dev.txt
REQUIREMENTS_PROD := requirements-prod.txt
REQUIREMENTS_GPU := requirements-gpu.txt

# Colors for output
RED := \033[0;31m
GREEN := \033[0;32m
YELLOW := \033[0;33m
BLUE := \033[0;34m
NC := \033[0m  # No Color

# Default target
.PHONY: help
help:
	@echo "$(GREEN)AI Freelance Automation — Development & Deployment Toolkit$(NC)"
	@echo "Usage: make <target>"
	@echo ""
	@echo "$(BLUE)Environment Setup$(NC)"
	@echo "  venv             Create virtual environment"
	@echo "  deps             Install base dependencies"
	@echo "  deps-dev         Install dev dependencies"
	@echo "  deps-prod        Install production dependencies"
	@echo "  deps-gpu         Install GPU-enabled dependencies"
	@echo ""
	@echo "$(BLUE)Development$(NC)"
	@echo "  lint             Run linters (flake8, pylint)"
	@echo "  typecheck        Run mypy type checking"
	@echo "  test             Run all tests (unit, integration, e2e)"
	@echo "  test-unit        Run unit tests"
	@echo "  test-integration Run integration tests"
	@echo "  test-e2e         Run end-to-end tests"
	@echo "  coverage         Generate test coverage report"
	@echo ""
	@echo "$(BLUE)Database & Data$(NC)"
	@echo "  migrate          Run database migrations"
	@echo "  reset-db         Reset and reinitialize database"
	@echo ""
	@echo "$(BLUE)Security & Compliance$(NC)"
	@echo "  security-scan    Run Bandit security scan"
	@echo "  audit-deps       Audit dependencies for vulnerabilities"
	@echo ""
	@echo "$(BLUE)Build & Deployment$(NC)"
	@echo "  build            Build application (local)"
	@echo "  docker-build     Build Docker images"
	@echo "  docker-run       Run in Docker (dev mode)"
	@echo "  docker-prod      Run in Docker (production mode)"
	@echo "  deploy           Deploy to production (via script)"
	@echo ""
	@echo "$(BLUE)Maintenance$(NC)"
	@echo "  clean            Remove temporary files and caches"
	@echo "  backup           Create manual backup"
	@echo "  health-check     Run system health diagnostics"
	@echo ""
	@echo "$(BLUE)Monitoring & Logs$(NC)"
	@echo "  logs             Tail application logs"
	@echo "  metrics          Launch monitoring dashboard (Grafana/Prometheus)"
	@echo ""
	@echo "$(BLUE)Miscellaneous$(NC)"
	@echo "  run              Start the autonomous system (local)"
	@echo "  cli              Launch CLI interface"
	@echo "  docs             Generate documentation"
	@echo "  help             Show this help"

# === Environment Setup ===

.PHONY: venv
venv:
	@if [ ! -d "$(VENV)" ]; then \
		echo "$(BLUE)Creating virtual environment...$(NC)"; \
		$(PYTHON) -m venv $(VENV); \
	fi
	@echo "$(GREEN)Virtual environment ready at $(VENV)$(NC)"

.PHONY: deps
deps: venv
	@echo "$(BLUE)Installing base dependencies...$(NC)"
	@$(VENV)/bin/$(PIP) install -r $(REQUIREMENTS)

.PHONY: deps-dev
deps-dev: deps
	@echo "$(BLUE)Installing development dependencies...$(NC)"
	@$(VENV)/bin/$(PIP) install -r $(REQUIREMENTS_DEV)

.PHONY: deps-prod
deps-prod: venv
	@echo "$(BLUE)Installing production dependencies...$(NC)"
	@$(VENV)/bin/$(PIP) install -r $(REQUIREMENTS_PROD)

.PHONY: deps-gpu
deps-gpu: deps-prod
	@echo "$(BLUE)Installing GPU dependencies...$(NC)"
	@$(VENV)/bin/$(PIP) install -r $(REQUIREMENTS_GPU)

# === Development ===

.PHONY: lint
lint: deps-dev
	@echo "$(BLUE)Running linters...$(NC)"
	@$(VENV)/bin/flake8 $(SOURCE_DIR)
	@$(VENV)/bin/pylint --rcfile=pylintrc $(SOURCE_DIR)/core $(SOURCE_DIR)/services $(SOURCE_DIR)/platforms

.PHONY: typecheck
typecheck: deps-dev
	@echo "$(BLUE)Running type checker...$(NC)"
	@$(VENV)/bin/mypy --config-file=mypy.ini $(SOURCE_DIR)

.PHONY: test-unit
test-unit: deps-dev
	@echo "$(BLUE)Running unit tests...$(NC)"
	@$(VENV)/bin/pytest tests/unit -v --tb=short

.PHONY: test-integration
test-integration: deps-dev
	@echo "$(BLUE)Running integration tests...$(NC)"
	@$(VENV)/bin/pytest tests/integration -v --tb=short

.PHONY: test-e2e
test-e2e: deps-dev
	@echo "$(BLUE)Running end-to-end tests...$(NC)"
	@$(VENV)/bin/pytest tests/e2e -v --tb=long

.PHONY: test
test: test-unit test-integration test-e2e

.PHONY: coverage
coverage: deps-dev
	@echo "$(BLUE)Generating coverage report...$(NC)"
	@$(VENV)/bin/pytest --cov=core --cov=services --cov=platforms --cov-report=html --cov-report=term tests/

# === Database ===

.PHONY: migrate
migrate: deps-prod
	@echo "$(BLUE)Running database migrations...$(NC)"
	@$(VENV)/bin/alembic upgrade head

.PHONY: reset-db
reset-db: deps-prod
	@echo "$(YELLOW)⚠️  Resetting database! This will delete all data.$(NC)"
	@read -p "Continue? (y/N): " confirm && [ "$$confirm" = "y" ] || exit 1
	@$(VENV)/bin/alembic downgrade base
	@$(VENV)/bin/alembic upgrade head
	@echo "$(GREEN)Database reset complete.$(NC)"

# === Security ===

.PHONY: security-scan
security-scan: deps-dev
	@echo "$(BLUE)Running security scan (Bandit)...$(NC)"
	@$(VENV)/bin/bandit -c bandit.yml -r $(SOURCE_DIR)

.PHONY: audit-deps
audit-deps: deps-dev
	@echo "$(BLUE)Auditing dependencies...$(NC)"
	@$(VENV)/bin/safety check -r $(REQUIREMENTS) -r $(REQUIREMENTS_PROD)

# === Build & Deployment ===

.PHONY: build
build: deps-prod
	@echo "$(GREEN)Build successful (local).$(NC)"

.PHONY: docker-build
docker-build:
	@echo "$(BLUE)Building Docker images...$(NC)"
	docker-compose -f docker/docker-compose.yml build

.PHONY: docker-run
docker-run: docker-build
	@echo "$(BLUE)Starting in Docker (development)...$(NC)"
	docker-compose -f docker/docker-compose.dev.yml up

.PHONY: docker-prod
docker-prod: docker-build
	@echo "$(GREEN)Starting in Docker (production)...$(NC)"
	docker-compose -f docker/docker-compose.prod.yml up -d

.PHONY: deploy
deploy:
	@echo "$(BLUE)Deploying to production...$(NC)"
	@scripts/deployment/deploy_production.py

# === Maintenance ===

.PHONY: clean
clean:
	@echo "$(BLUE)Cleaning temporary files...$(NC)"
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@rm -rf logs/*.log logs/*/*.log
	@rm -rf ai/temp/*
	@echo "$(GREEN)Cleanup complete.$(NC)"

.PHONY: backup
backup:
	@echo "$(BLUE)Creating manual backup...$(NC)"
	@scripts/maintenance/backup_system.py --manual

.PHONY: health-check
health-check: deps-prod
	@echo "$(BLUE)Running system health diagnostics...$(NC)"
	@scripts/maintenance/health_check.py

# === Monitoring & Logs ===

.PHONY: logs
logs:
	@echo "$(BLUE)Tailing application logs...$(NC)"
	@tail -f logs/app/application.log

.PHONY: metrics
metrics:
	@echo "$(GREEN)Launching monitoring stack...$(NC)"
	docker-compose -f docker/docker-compose.monitoring.yml up -d
	@echo "Grafana: http://localhost:3000"
	@echo "Prometheus: http://localhost:9090"

# === Misc ===

.PHONY: run
run: deps-prod
	@echo "$(GREEN)🚀 Starting AI Freelance Automation System...$(NC)"
	@$(VENV)/bin/python main.py

.PHONY: cli
cli: deps-prod
	@$(VENV)/bin/python cli.py

.PHONY: docs
docs:
	@echo "$(BLUE)Generating documentation...$(NC)"
	@sphinx-build -b html docs/user docs/_build/html
	@echo "User docs: docs/_build/html/index.html"
