# Структура проекта Task Manager

## Обзор

Task Manager — FastAPI приложение на Python 3.11+ с Clean Architecture.

## Структура директорий

```
task_manager/
├── src/                    # Исходный код приложения
│   ├── api/                # HTTP эндпоинты (роутеры FastAPI)
│   ├── core/               # Конфигурация, настройки, общие утилиты
│   │   └── config.py       # Pydantic Settings (переменные окружения)
│   ├── models/             # Pydantic модели (схемы запросов/ответов)
│   ├── repository/         # Слой доступа к данным (работа с БД)
│   ├── services/           # Бизнес-логика
│   └── main.py             # Точка входа, создание FastAPI app
├── tests/                  # Тесты
│   ├── api/                # Тесты API эндпоинтов
│   └── conftest.py         # Фикстуры pytest
├── rules/                  # Правила разработки для AI-ассистентов
│   ├── code/               # Правила по языкам/технологиям
│   │   └── python.md       # Стиль кода Python
│   └── index.md            # Индекс правил
├── pyproject.toml          # Конфигурация проекта, ruff, pytest
├── requirements.txt        # Зависимости
└── .env                    # Переменные окружения (не в git)
```

## Слои архитектуры

```
┌─────────────────────────────────────┐
│              API Layer              │  ← src/api/ (роутеры, эндпоинты)
├─────────────────────────────────────┤
│           Service Layer             │  ← src/services/ (бизнес-логика)
├─────────────────────────────────────┤
│          Repository Layer           │  ← src/repository/ (доступ к БД)
├─────────────────────────────────────┤
│             Models                  │  ← src/models/ (схемы данных)
└─────────────────────────────────────┘
```

**Правило зависимостей:** верхние слои зависят от нижних, но не наоборот.

## Технологический стек

| Категория | Инструмент | Версия |
|-----------|------------|--------|
| Framework | FastAPI | 0.128.0 |
| Server | Uvicorn | 0.40.0 |
| Validation | Pydantic | 2.12.5 |
| Config | pydantic-settings | 2.12.0 |
| HTTP Client | httpx | 0.28.1 |
| Testing | pytest + pytest-asyncio | 9.0.2 |
| Linter/Formatter | ruff | 0.14.14 |
| Type Checker | ty | 0.0.13 |

## Конфигурация

Настройки загружаются из `.env` через `pydantic-settings`:

```python
# src/core/config.py
class Configs(BaseSettings):
    app_name: str = "Task Manager"
    database_url: str          # обязательно
    secret_key: str            # обязательно
    debug: bool = False
```

## Запуск

```bash
# Установка зависимостей
pip install -r requirements.txt

# Запуск dev-сервера
uvicorn src.main:app --reload

# Тесты
pytest

# Линтер
ruff check src tests
ruff format src tests

# Type check
ty check src
```

## Эндпоинты

| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/health` | Health check |
