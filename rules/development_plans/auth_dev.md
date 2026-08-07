# План разработки авторизации

## Статус реализации

| Компонент | Статус | Заметки |
|-----------|--------|---------|
| `POST /auth/sign-up` | ✅ | access + refresh; refresh также в session cookie |
| `POST /auth/sign-in` | ✅ | |
| `POST /auth/refresh` | ✅ | body `RefreshRequest.refresh_token` |
| `POST /auth/logout` | 🟡 | endpoint есть, handler `pass` |
| JWT access (Bearer) | ✅ | `get_current_user_id` + RS256 keys |
| Refresh в Redis | ✅ | `Security.store_refresh_token` |
| SessionMiddleware | ✅ | cookie `SESSION_ID`, `same_site=strict`, `https_only=True` |
| CORSMiddleware | ✅ | |
| Password hashing (argon2) | ✅ | |
| Валидация сложности пароля | ❌ | |
| Rate limiting | ❌ | |
| Email verification | ❌ | |
| Тесты | ✅ частично | `tests/services/test_auth_service.py`, `tests/core/test_security.py` |

---

## Endpoints

| Endpoint | Метод | Статус | Описание | Вход | Выход |
|----------|-------|--------|----------|------|-------|
| `/auth/sign-up` | POST | ✅ | Регистрация | login (email), password | access + refresh (cookie) |
| `/auth/sign-in` | POST | ✅ | Вход | login (email), password | access + refresh |
| `/auth/refresh` | POST | ✅ | Обновление токенов | refresh (body) | новый access + новый refresh |
| `/auth/logout` | POST | 🟡 | Инвалидация сессии | — | stub |

## Middleware

| Middleware | Параметры | Статус |
|------------|-----------|--------|
| `SessionMiddleware` | `secret_key`, `session_cookie="SESSION_ID"`, `same_site="strict"`, `https_only=True` | ✅ |
| `CORSMiddleware` | `allow_origins`, `allow_credentials=True`, `allow_methods`, `allow_headers` | ✅ |

## Структура файлов (факт)

```
src/
├── api/
│   ├── auth.py                 # роутер
│   └── dependencies.py         # get_current_user_id
├── services/
│   └── auth.py                 # бизнес-логика
├── repository/
│   └── user.py                 # работа с БД
├── models/
│   ├── auth.py                 # SignUp/SignIn/Refresh/TokenResponse
│   └── user.py
└── core/
    ├── security.py             # JWT, hash/verify password
    ├── keys.py                 # RSA keys
    └── cache.py                # Redis
```

## Хранение токенов

| Токен | Где хранится | Передача |
|-------|--------------|----------|
| access | localStorage (фронт) | `Authorization: Bearer <token>` |
| refresh | Redis (jti) + опционально session cookie при sign-up | body на `/auth/refresh`; cookie `SESSION_ID` |

## TODO (дальнейшие шаги)

- [ ] Доделать `/auth/logout` — инвалидация refresh в Redis + очистка cookie
- [ ] Валидация пароля (минимум 8 символов, хотя бы одна цифра, хотя бы одна заглавная буква)
- [ ] Rate limiting на auth endpoints (защита от брутфорса)
- [ ] Email verification при регистрации
