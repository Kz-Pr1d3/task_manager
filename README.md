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
