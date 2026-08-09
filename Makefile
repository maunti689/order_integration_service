.PHONY: up down seed test lint format clean

up:
	docker compose up --build

down:
	docker compose down

seed:
	docker compose exec api python -m scripts.seed_demo

test:
	pytest --cov=app --cov-report=term-missing

lint:
	ruff check .
	ruff format --check .

format:
	ruff check --fix .
	ruff format .

clean:
	docker compose down --volumes --remove-orphans
