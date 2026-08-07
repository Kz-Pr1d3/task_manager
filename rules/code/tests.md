# Правила написания тестов

Стиль выведен из текущей папки `tests/`. При добавлении тестов следуй ему, а не придумывай параллельный подход.

## Структура

Зеркаль `src/`:

```
tests/
  conftest.py              # общие фикстуры (client, тестовые константы)
  api/
  core/
  repository/
    conftest.py            # pool, репозитории
  services/
```

- Новый слой в `src/` → соответствующая папка в `tests/`.
- Слоёвые фикстуры — в `tests/<layer>/conftest.py`.
- Кросс-слоевые константы/клиенты — в корневом `tests/conftest.py`.

## Именование

Формат: `test__{что_тестируем}__{сценарий}`

```python
async def test__get_by_email__success(...): ...
async def test__get_by_email__not_exists(...): ...
async def test__create_custom_list__limit_reached(...): ...
```

Двойное подчёркивание — разделитель секций имени. Сценарий короткий и говорящий: `success`, `empty`, `not_exists`, `limit_reached`.

## Async

В проекте `asyncio_mode = "auto"` (`pyproject.toml`). Не вешай `@pytest.mark.asyncio` без нужды — достаточно `async def test__...`.

## Фикстуры > моки

**Главный принцип:** не создавать бездумных моков. Предпочитай продуманные переиспользуемые фикстуры.

### ✅ Делай так

1. **Реальные зависимости там, где это дёшево и стабильно**
   - repository → реальный pool (`create_pool`) + реальный репозиторий
   - core/security → прямые вызовы функций, без моков
   - api → `TestClient(app)` через фикстуру `client`

2. **Setup/teardown через `yield`-фикстуры**, а не копипасту в каждом тесте:

```python
@pytest.fixture
async def create_list_data(base_repo: BaseRepository, test_user_id: int):
    await base_repo.query(insert_sql, test_user_id)
    yield
    await base_repo.query(cleanup_sql, test_user_id)
    # при необходимости — починить serial/sequences
```

3. **Выноси тестовые константы в фикстуры** (`test_user_id`, `test_user_email`, SQL-хелперы вроде `select_three_rows`).

4. **Слоёвые объекты — фикстуры**, не ручная сборка в каждом тесте:

```python
@pytest.fixture
async def list_repo(create_pool) -> ListRepository:
    return ListRepository(pool=create_pool.pool)
```

### ❌ Не делай так

```python
# Бездумный модульный AsyncMock «чтобы тест зелёный»
user_repo = AsyncMock(return_value=1)
redis = AsyncMock(return_value=True)

async def test__create_user__success():
    service = AuthService(repository=user_repo, redis_client=redis)
    ...
```

Мок допустим только когда:
- зависимость реально внешняя/дорогая (сторонний API, брокер) **и**
- фикстура с реальной зависимостью невозможна/нестабильна **и**
- мок описывает явный контракт (специфичные `return_value`/`side_effect` на методы, не «всё True»).

Если чистый тест без костылей не получается — **остановись и спроси пользователя**, не маскируй проблему моками.

## Стиль тела теста

1. Arrange через фикстуры в сигнатуре, не через глобальное состояние.
2. Вызовы с именованными аргументами (`user_id=...`, `email=...`).
3. Assert на конкретные поля/значения, не только «truthy»:

```python
assert custom_list.name == test_list_name
assert custom_list.user_id == test_user_id
assert custom_list.position == 1
```

4. Для негативных сценариев — отдельный тест (`__empty`, `__not_exists`, `__limit_reached`).
5. Cleanup: предпочтительно в фикстуре; если тест сам создаёт данные — чисти после assert (и sequences при необходимости).

## Уровни тестов в проекте

| Слой | Подход |
|------|--------|
| `repository` | Интеграция с БД, pool + repo-фикстуры, данные через SQL-setup |
| `core` | Юнит без I/O, прямые вызовы |
| `api` | HTTP через `TestClient` |
| `services` | Реальные/фикстурные зависимости; моки — исключение, см. выше |

## Чеклист перед коммитом теста

- [ ] Имя в формате `test__…__…`
- [ ] Нет нового мока «для галочки» — есть фикстура или осознанное исключение
- [ ] Фикстура переиспользуема (лежит в нужном `conftest.py`)
- [ ] Данные после теста не текут (cleanup / yield-teardown)
- [ ] Если тест грязный/хрупкий — эскалировать пользователю, а не «замокать и забыть»
