# Task Manager

FastAPI-based task management API.

## Setup

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy environment variables
cp .env.example .env
```

## Database

```bash
# Запуск
docker compose up -d

# Остановка
docker compose down

# Остановка + удаление данных (чистый старт)
docker compose down -v && rm -rf db/data && docker compose up -d

# Зайти в psql внутри контейнера
docker exec -it task_manager_db psql -U user -d task_manager
```

## Run

```bash
uvicorn src.main:app --reload
```

## Test

```bash
pytest
```

## Lint

```bash
ruff check src tests
ruff format src tests
```
