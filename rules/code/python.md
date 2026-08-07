# Правила разработки Python кода

## Основные принципы

### 1. Используй принципы SOLID, DRY, KISS, CLEAN CODE, CLEAN Architecture, YAGNI, DDD

### 2. Работа с зависимостями

**Правила для requirements.txt:**
```txt
# Указывай версии зависимостей
fastapi>=0.100.0
sqlalchemy>=2.0.0
```

**❌ НЕ добавляй в requirements.txt:**
- `json` - стандартная библиотека Python
- `datetime` - стандартная библиотека Python  
- `typing` - стандартная библиотека Python
- `logging` - стандартная библиотека Python

**Правила импорта библиотек:**
- Стандартные библиотеки - первыми
- Сторонние библиотеки - вторыми
- Локальные модули - последними
- Разделение пустыми строками между группами

### 3. Работа с базой данных этого проекта

Появится в будущем

### 4. Обработка ошибок

Кастомные HTTP-исключения — в `src/core/exceptions.py`. Базовый класс `AppException` (наследник `HTTPException`), наследники:

| Класс | Код |
|---|---|
| `BadRequestException` | 400 |
| `UnauthorizedException` | 401 |
| `NotFoundException` | 404 |
| `ConflictException` | 409 |

Новые исключения добавляй только туда, наследуй от `AppException`. Не используй «голый» `HTTPException` в сервисах/core.

**Вызов с кастомным описанием через `detail`:**
```python
from src.core.exceptions import NotFoundException, ConflictException

raise NotFoundException()
raise NotFoundException(detail="List not found")
raise ConflictException(detail="The limit for creating custom lists has been reached")
```

**Структура try/except:**
```python
try:
    # Основная логика
    result = some_operation()
    log.info("Операция выполнена успешно", {"result": result})
    return result
except SpecificException as e:
    log.error("Специфическая ошибка", {"error": str(e)})
    # Обработка специфической ошибки
except Exception as e:
    log.error("Неожиданная ошибка", {"error": str(e)})
    # Общая обработка ошибок
    raise
```

### 5. Логирование

**Используй структурированное логирование:**
```python
# Правильно
log.info("Пользователь создан", {
    "user_id": user.id,
    "username": user.name,
    "action": "create_user"
})

# Неправильно
log.info(f"Пользователь {user.name} создан")
```

### 6. Работа с настройками

**Используй переменные окружения и конфиги:**
```python
import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str
    api_key: str
    debug: bool = False
    
    class Config:
        env_file = ".env"

settings = Settings()
```

**Не сохранять секретные ключи в коде**

### 7. Работа с внешними API

**Используй httpx или requests с правильной обработкой:**
```python
import httpx

async def fetch_data(url: str, params: dict) -> dict:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        return response.json()
```

### 8. Типизация

**Используй type hints:**
```python
def process_data(data: dict[str, Any]) -> list[dict[str, Any]] | None:
    """
    Обрабатывает данные.
    
    :param data: Входные данные
    :return: Список обработанных записей или None
    """
    pass
```

### 9. Документация

**Обязательные docstrings:**
Стандарт: reStructuredText (reST). Первая строка — краткое описание (50–60 символов), далее развёрнутое
описание (до 100 символов в строке), затем параметры и выход. Используй метки `:param`, `:returns:`,
а также при необходимости `:raises`.

```python
def function_name(param1: str, param2: int) -> bool:
    """
    Короткое, ёмкое описание функции.

    Подробности бизнес-логики, нюансы и ссылки на внешнюю документацию.
    :param param1: описание первого параметра.
    :param param2: описание второго параметра.
    :returns: что именно возвращает функция.
    :raises ValueError: когда входные данные невалидны.
    """
    ...
```

### 10. Стиль кода

**Кавычки в строках:**

**Правило:** В команде принято использовать двойные кавычки для строк в Python коде.

**Правильно:**
```python
message = "Привет, мир!"
config = {"key": "value", "debug": True}
query = """
    SELECT u.id, u.name
    FROM public.users u
    WHERE u.active = true
"""
```

**Неправильно:**
```python
message = 'Привет, мир!'
config = {'key': 'value', 'debug': True}
```

**Использование f-strings:**

**Правило:** всегда используй f-strings для форматирования строк.

**Правильно:**
```python
user_id = 123
user_name = "Иван"
message = f"Пользователь {user_name} с ID {user_id} создан"
```

**Неправильно:**
```python
# НЕ используй .format()
message = "Пользователь {} с ID {} создан".format(user_name, user_id)
message = "Пользователь {name} с ID {id} создан".format(name=user_name, id=user_id)

# НЕ используй % форматирование
message = "Пользователь %s с ID %d создан" % (user_name, user_id)

# НЕ используй конкатенацию строк
message = "Пользователь " + user_name + " с ID " + str(user_id) + " создан"
```

**Используй именованные аргументы функций:**

**Правило:** Если функция содержит именнованые аргументы, используй имена аргументов, а не только позицию.

**Правильно:**
```python
httpx.get(
    url="https://api.example.com/data",
    params={"limit": 100},
    timeout=30.0,
)
```

**Неправильно:**
```python
# НЕ используй только позиционные аргументы для сложных функций
httpx.get("https://api.example.com/data", {"limit": 100}, None, None, 30.0)  # Неясно
```

## Антипаттерны

### ❌ Что НЕ делать:

1. **Не используй глобальные переменные** без необходимости
2. **Не игнорируй исключения** - всегда логируй
3. **Не используй print()** - только log.*
4. **Не делай SQL запросы без параметров**
5. **Не забывай про таймауты** в HTTP запросах
6. **Не используй синхронные операции** для долгих задач без необходимости
7. **Не добавляй в requirements.txt уже включенные зависимости**

### ✅ Лучшие практики:

1. **Используй контекстные менеджеры** для ресурсов
2. **Группируй связанные операции** в классы
3. **Используй константы** для магических чисел
4. **Валидируй входные данные** в начале функций
5. **Используй enumerate()** вместо range(len())
6. **Используй f-строки** для форматирования
7. **Проверяй зависимости** перед добавлением в requirements.txt

## Проверка зависимостей

Перед добавлением новой зависимости в requirements.txt:

1. **Проверь, что это не стандартная библиотека:**
   - json ❌ 
   - datetime ❌
   - typing ❌
   - logging ❌
   - os ❌
   - pathlib ❌

2. **Проверь, что она действительно нужна**

3. **Используй минимальный набор зависимостей**
