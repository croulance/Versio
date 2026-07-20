.PHONY: help build dev stop restart logs \
        api/logs worker/logs worker-default/logs \
        api/bash api/shell \
        migrate migrations superuser seed urls \
        test format

# ── Meta ──────────────────────────────────────────────────────────────────────

help:
	@echo ""
	@echo "  Versio — available commands"
	@echo ""
	@echo "  Setup"
	@echo "    make build              Build all Docker images"
	@echo "    make dev                Start everything: up, migrate, seed, print URLs + test login"
	@echo "    make stop               Stop all services"
	@echo "    make restart            Restart all services"
	@echo ""
	@echo "  Logs"
	@echo "    make logs               All services"
	@echo "    make api/logs           API only"
	@echo "    make worker/logs        Chunk worker only"
	@echo "    make worker-default/logs Default worker only"
	@echo ""
	@echo "  Django"
	@echo "    make api/bash           Shell into API container"
	@echo "    make api/shell          Django shell_plus"
	@echo "    make migrate            Apply migrations (api + auth)"
	@echo "    make migrations         Create migrations (api + auth)"
	@echo "    make superuser          Create Django superuser (api)"
	@echo "    make seed               Seed sample supplier + templates + demo login"
	@echo "    make urls               Print service URLs + test login"
	@echo ""
	@echo "  Quality"
	@echo "    make test               Run test suite (pytest, inside the shell container)"
	@echo "    make format             Format code (black + isort)"
	@echo ""

# ── Docker ────────────────────────────────────────────────────────────────────

build:
	docker compose build

dev:
	docker compose up -d
	@echo "Waiting for the database..."
	@until docker compose exec -T db pg_isready -U versio > /dev/null 2>&1; do sleep 1; done
	$(MAKE) migrate
	$(MAKE) seed
	$(MAKE) urls

stop:
	docker compose down

restart:
	docker compose restart

logs:
	docker compose logs -f

api/logs:
	docker compose logs -f api

worker/logs:
	docker compose logs -f worker

worker-default/logs:
	docker compose logs -f worker-default

# ── Django ────────────────────────────────────────────────────────────────────

api/bash:
	docker compose exec api bash

api/shell:
	docker compose exec api python manage.py shell

migrate:
	docker compose exec api python manage.py migrate
	docker compose exec auth python manage.py migrate

migrations:
	docker compose exec api python manage.py makemigrations
	docker compose exec auth python manage.py makemigrations

superuser:
	docker compose exec api python manage.py createsuperuser

seed:
	docker compose exec api python manage.py seed
	docker compose exec auth python manage.py seed

urls:
	@echo ""
	@echo "  Versio is running"
	@echo ""
	@echo "  URLs"
	@echo "    Dashboard    http://localhost:8001"
	@echo "    API          http://localhost:8000"
	@echo "    API admin    http://localhost:8000/admin"
	@echo "    Auth         http://localhost:8002"
	@echo "    Auth admin   http://localhost:8002/admin"
	@echo "    RabbitMQ     http://localhost:15672  (versio / versio)"
	@echo "    MinIO        http://localhost:9001   (versio / versio123)"
	@echo ""
	@echo "  Test login (dashboard)"
	@echo "    Email        demo@versio.test"
	@echo "    Password     versio-demo-2026"
	@echo ""
	@echo "  Django admin login (API admin + Auth admin — SupplierAuth has no admin access)"
	@echo "    Username     demo_admin"
	@echo "    Password     versio-admin-2026"
	@echo ""

# ── Quality ───────────────────────────────────────────────────────────────────

test:
	docker compose exec -e PYTHONPATH=/app -w /app shell python -m pytest /tests -v

format:
	docker compose exec api sh -c "black . && isort ."
