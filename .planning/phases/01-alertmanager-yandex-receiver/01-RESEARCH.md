# Phase 1: Alertmanager → Yandex Messenger Receiver - Research

**Researched:** 2026-04-09  
**Domain:** Webhook receiver (Prometheus Alertmanager) → Yandex Messenger Bot API (sendText)  
**Confidence:** HIGH

## Summary

Нужно реализовать небольшой HTTP-сервис, который принимает webhook от Prometheus Alertmanager (формат `webhook_config`, протокол v4) на двух эндпоинтах и пересылает уведомление в Yandex Messenger Bot API методом `sendText`. Входные вебхуки защищаются HTTP Basic Auth; при ошибке аутентификации сервис обязан отвечать `401` и отдавать заголовок `WWW-Authenticate: Basic` (и желательно `realm`), чтобы поведение было стандартным и совместимым с клиентами.

Ключевой момент — корректно выбрать коды ответов на входящий webhook: Alertmanager считает **2xx успешными**, а **5xx — “временной ошибкой” и будет ретраить**. Ошибки валидации входного JSON, неверный `login/chat_id`, невозможность доставить сообщение из‑за логики/политик лучше трактовать как **4xx/2xx без ретраев** (в зависимости от того, хотим ли мы, чтобы Alertmanager прекратил попытки), тогда как ошибки сети/таймауты/5xx/429 на стороне Yandex лучше поднимать как **5xx** наружу, чтобы Alertmanager сам повторил доставку.

**Primary recommendation:** использовать **Python 3.12 + FastAPI + Pydantic v2 + HTTPX**, реализовать строгие модели Alertmanager v4, адаптер в `sendText` с лимитом 6000 символов, и управлять ретраями через осмысленную маппинг-таблицу статусов (2xx/4xx/5xx) с учётом поведения Alertmanager.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python | 3.12 | runtime | актуальная стабильная ветка, хорошие perf/typing |
| FastAPI | latest | HTTP API (ASGI) | стандарт де-факто для небольших API в Python, отличная интеграция со схемами/валидацией |
| Pydantic | v2 | модели + валидация JSON | быстрые модели, удобные типы времени, строгая валидация |
| Uvicorn | latest | ASGI server | стандартный раннер для FastAPI |
| HTTPX | latest | исходящие HTTP запросы | async-клиент, удобный таймаут/ретраи/трассировка |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| tenacity | latest | ретраи исходящих запросов к Yandex | если нужно ретраить внутри сервиса (обычно лучше положиться на ретраи Alertmanager) |
| pytest | latest | юнит-тесты | всегда |
| respx | latest | мок HTTPX | контракт/юнит тесты исходящих запросов |
| schemathesis | latest | контракт-тесты OpenAPI | по желанию, для regression на входном API |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| FastAPI | Go (chi/fiber) | проще статическая сборка/дистрибуция, но больше boilerplate и ниже скорость прототипирования |
| HTTPX | aiohttp | тоже ок, но HTTPX обычно проще для тестов/MockTransport/respx |

**Installation:**

```bash
python -m venv .venv
. .venv/bin/activate
pip install fastapi uvicorn pydantic httpx
pip install -D pytest respx
```

## Architecture Patterns

### Recommended Project Structure

```
app/
├── __init__.py
├── main.py                 # FastAPI app + роутинг
├── api/
│   ├── __init__.py
│   └── v1/
│       ├── __init__.py
│       └── alerts.py       # эндпоинты /v1/alerts/...
├── auth/
│   ├── __init__.py
│   └── basic.py            # входная Basic Auth (dependency)
├── config/
│   ├── __init__.py
│   └── settings.py         # env → typed settings
├── models/
│   ├── __init__.py
│   ├── alertmanager.py     # Pydantic модели входного webhook v4
│   └── yandex.py           # модели sendText request/response
├── services/
│   ├── __init__.py
│   ├── formatters.py       # форматирование текста + truncation 6000
│   └── yandex_client.py    # HTTPX клиент к Bot API
└── observability/
    ├── __init__.py
    └── logging.py          # структурные логи/корреляция (опционально)
tests/
├── test_auth.py
├── test_models_alertmanager.py
├── test_formatting.py
└── test_api_contract.py    # проверка статусов/headers, моки Yandex
```

### Pattern 1: Dependency-based Auth (FastAPI HTTPBasic)
**What:** Basic Auth реализуется как `Depends()` dependency и единообразно применяется к обоим эндпоинтам.  
**When to use:** всегда, т.к. требование фазы — входящие вебхуки через Basic Auth.  
**Example:**

```python
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import secrets

security = HTTPBasic(realm="alertmanager-webhook")

def require_basic_auth(
    credentials: HTTPBasicCredentials = Depends(security),
) -> None:
    ok_user = secrets.compare_digest(credentials.username, EXPECTED_USER)
    ok_pass = secrets.compare_digest(credentials.password, EXPECTED_PASS)
    if not (ok_user and ok_pass):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
            headers={"WWW-Authenticate": 'Basic realm="alertmanager-webhook"'},
        )
```

**Source:** FastAPI docs “HTTP Basic Auth” (`https://fastapi.tiangolo.com/advanced/security/http-basic-auth`).

### Pattern 2: “Return 5xx to retry” contract with Alertmanager
**What:** если сервис *не смог* переслать сообщение из‑за временной ошибки (таймаут, 5xx/429 от Yandex, DNS, сетевой сбой), возвращаем **5xx** на входящий webhook, чтобы Alertmanager повторил доставку.  
**When to use:** ошибки, которые “скорее всего пройдут” при повторе.  
**Source:** Alertmanager webhook notifier source (`https://github.com/prometheus/alertmanager/blob/main/notify/webhook/webhook.go`) + конфиг-док (`https://prometheus.io/docs/alerting/latest/configuration/`) — 2xx success, 5xx recoverable.

### Anti-Patterns to Avoid
- **Делать 200 при недоставке в Yandex:** Alertmanager прекратит ретраи, и уведомление будет потеряно.
- **Отвечать 500 на невалидный входной JSON:** Alertmanager будет ретраить “плохие” данные бесконечно/долго, создавая шум.
- **Слать `chat_id` и `login` одновременно в Yandex:** API допускает “хотя бы один”, но задача требует “ровно один”, лучше строго валидировать.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Basic Auth headers | ручной парсинг `Authorization:` | `fastapi.security.HTTPBasic` | корректный `WWW-Authenticate`, OpenAPI, edge cases base64 |
| JSON schema validation | ad-hoc `dict`-логика | Pydantic модели | строгая валидация, понятные ошибки 422/400 |
| HTTP client | `requests` в async app | `httpx.AsyncClient` | async, таймауты, удобные тесты |

**Key insight:** большинство сложностей не в “принять JSON”, а в корректной валидации, статус-кодах для ретраев и тестируемой интеграции HTTP.

## Common Pitfalls

### Pitfall 1: Неправильные статус-коды → неправильные ретраи Alertmanager
**What goes wrong:** сервис возвращает 200 при фактической недоставке, либо возвращает 500 на ошибки клиента.  
**Why it happens:** путаница между “ошибка входного запроса” и “ошибка доставки”.  
**How to avoid:** фиксировать таблицу маппинга статусов (см. ниже) + тесты на неё.  
**Warning signs:** повторяющиеся алерты “пропадают” или, наоборот, бесконечно ретраятся при одинаковом 4xx.

### Pitfall 2: Длина `text` > 6000 → ошибка Yandex
**What goes wrong:** Bot API возвращает ошибку, хотя входной webhook валиден.  
**How to avoid:** жёсткое ограничение длины и детерминированное усечение с “хвостом” (`…\n(truncated)`), чтобы повторное форматирование было стабильным.

### Pitfall 3: Дедупликация/идемпотентность при ретраях
**What goes wrong:** Alertmanager ретраит один и тот же webhook, и в чат улетает дубликат.  
**How to avoid:** использовать `payload_id` Yandex `sendText` как idempotency key, сформированный из `groupKey` + `status` + хеша содержимого/времени (детерминированно).  
**Source:** Yandex sendText docs — `payload_id` “запросы с одинаковым ID трактуются как дубликаты” (`https://yandex.ru/dev/messenger/doc/ru/api-requests/message-send-text`).

## API Contract (Receiver)

### Endpoints
- `POST /v1/alerts/users/{login}`
  - **Path param**: `login` (string, required) — адресат в Yandex `sendText.login`.
- `POST /v1/alerts/chats/{chat_id}`
  - **Path param**: `chat_id` (string, required) — адресат в Yandex `sendText.chat_id`.

### Auth
- **Scheme:** HTTP Basic Auth
- **On failure:** `401 Unauthorized` + header `WWW-Authenticate: Basic realm="alertmanager-webhook"`

### Request body
- **Content-Type:** `application/json`
- **Schema:** Alertmanager webhook payload v4 (см. “Models”).

### Success response (рекомендуемо)
- `202 Accepted` (или `200 OK`) — принято и успешно доставлено в Yandex (или успешно поставлено в очередь на доставку).
- JSON-ответ можно минимизировать (например `{"ok": true}`), но для наблюдаемости полезно вернуть `{"ok": true, "yandex_message_id": ...}` если Yandex вернул `message_id`.

### Error mapping (важно для ретраев Alertmanager)

| Situation | Receiver response | Rationale |
|----------|-------------------|-----------|
| Bad/missing BasicAuth | 401 + `WWW-Authenticate` | клиент должен исправить креды |
| Невалидный JSON/не проходит модель Alertmanager v4 | 400/422 | ретраи не помогут |
| `login/chat_id` в path пустой/невалидный | 400 | ретраи не помогут |
| Yandex ответил 400/403/404 (логика/доступ/бот не участник чата) | 200/202 **или** 422 | зависит от политики: чаще лучше **200**, чтобы Alertmanager не ретраил навсегда то, что не исправится само |
| Yandex ответил 429/5xx, таймаут, network error | 503 | временная ошибка → пусть Alertmanager ретраит |

## Models

### Alertmanager webhook v4 (Pydantic)

**Source (официально):** `https://prometheus.io/docs/alerting/latest/configuration/` (раздел webhook receiver).

Рекомендуемая схема (ключевые поля):
- `version: Literal["4"]`
- `groupKey: str`
- `truncatedAlerts: int`
- `status: Literal["firing","resolved"]`
- `receiver: str`
- `groupLabels/commonLabels/commonAnnotations: dict[str,str]`
- `externalURL: str | None`
- `alerts: list[Alert]`, где `Alert`:
  - `status: Literal["firing","resolved"]`
  - `labels: dict[str,str]`
  - `annotations: dict[str,str]`
  - `startsAt/endsAt: datetime`
  - `generatorURL: str | None`
  - `fingerprint: str | None`

**Валидация:** включить “строгий режим” по возможности, но оставить forward-compatible поля через `extra="allow"` (Alertmanager может добавлять поля; лишние поля нам не мешают).

### Yandex sendText models

**Request:**
- `text: str` (required, max 6000)
- **ровно один** из:
  - `login: str`
  - `chat_id: str`
- `payload_id: str | None` (strongly recommended for idempotency)

**Response (200):**
- `ok: bool`
- `message_id: int`

**Source:** `https://yandex.ru/dev/messenger/doc/ru/api-requests/message-send-text`

## Text Formatting Rules (≤ 6000)

### Goals
- 1 сообщение должно быть информативным “с первого экрана”.
- Должно быть одинаково читаемо для `firing` и `resolved`.
- Должно быть детерминированно (чтобы `payload_id` и dedup работали).

### Proposed template

```
[{STATUS_UPPER}] {ALERTNAME}  ({N_FIRING} firing / {N_RESOLVED} resolved)

Summary: {summary-or-common-summary}
Description: {description-or-common-description}

Group: {groupLabels}
Common: {commonLabels}

Alerts:
{for each alert up to K}
- {alert.labels.instance|?} {alert.labels.job|?} {alert.labels.severity|?}
  startsAt={startsAt} endsAt={endsAt}
  {alert.annotations.summary|?}
  {alert.generatorURL|?}
{if truncatedAlerts>0 or alerts>K}
… (+{X} more)

Alertmanager: {externalURL|?}
GroupKey: {groupKey}
```

Где:
- `STATUS_UPPER`: `FIRING` / `RESOLVED`
- `ALERTNAME`: из `commonLabels.alertname` либо из первого алерта
- `K`: ограничение числа перечисляемых алертов (например 3–5), чтобы не “взорвать” лимит.

### Truncation strategy
- Формировать полный текст, затем если `len(text) > 6000`:
  - жёстко обрезать до `6000 - len(suffix)` и добавить суффикс, например:
    - `\n\n… (truncated to 6000 chars)`
- Стараться обрезать “снизу” (последние алерты/детали), сохраняя заголовок + Summary/Description.

## Config (env)

Минимально:
- `APP_HOST=0.0.0.0`
- `APP_PORT=8080`
- `LOG_LEVEL=INFO`
- `BASIC_AUTH_USERNAME=...`
- `BASIC_AUTH_PASSWORD=...`
- `BASIC_AUTH_REALM=alertmanager-webhook` (optional)
- `YANDEX_OAUTH_TOKEN=...`
- `YANDEX_API_BASE=https://botapi.messenger.yandex.net` (optional)
- `YANDEX_HTTP_TIMEOUT_SECONDS=5` (or 10)

Управление поведением ретраев/ответов:
- `FAIL_ON_YANDEX_4XX=false` (если `true`, возвращать 4xx на вход при 4xx от Yandex; если `false`, возвращать 200 и логировать)
- `YANDEX_PAYLOAD_ID_MODE=groupkey_status_hash` (policy)

## “Задел под OAuth2” (архитектурно)

Хотя сейчас для Bot API используется статический заголовок `Authorization: OAuth <token>`, стоит сразу отделить “источник токена” от клиента:

- интерфейс `TokenProvider.get_token() -> str`
  - `StaticTokenProvider` (сейчас, читает `YANDEX_OAUTH_TOKEN`)
  - `OAuth2ClientCredentialsProvider` (позже, если понадобится получать/обновлять токен автоматически: кэширование access token до expiry, синхронизация конкурентных refresh)

Такой слой позволит добавить OAuth2 без переписывания `yandex_client.py`.

## Error Handling / Retries

### Внутренние ретраи (рекомендуемая политика)
- **Не делать агрессивные ретраи внутри сервиса** по умолчанию: Alertmanager уже умеет ретраить webhook при 5xx, а дополнительный retry внутри может усиливать нагрузку и дубли.
- Исключение: *очень короткий* retry (1 попытка) на transient network error к Yandex, если это критично, но тогда `payload_id` обязателен.

### Ретраи Alertmanager (что учитывать)
- Alertmanager считает 2xx success, 5xx recoverable и ретраит с backoff.
- Следовательно:
  - при `httpx.TimeoutException`, `ConnectError`, `ReadError` → отдавать 503;
  - при Yandex 429/5xx → отдавать 503;
  - при ошибках формата входа → 400/422.

## Testing Recommendations

### Unit tests
- **Модели Alertmanager:** прогон валидного примера payload v4 (из официального примера/fixtures) + негативные кейсы (нет `alerts`, неверный `status`, неверный RFC3339).
- **Форматтер текста:** детерминизм, корректная подстановка полей, стабильное truncation до 6000.
- **Auth:** неверные креды → 401 и `WWW-Authenticate` присутствует и содержит realm.

### Integration-ish (contract) tests
- **API контракт:** с `TestClient`/`httpx.AsyncClient(app=...)` проверить:
  - `POST /v1/alerts/users/{login}` вызывает `sendText` с `login`, без `chat_id`;
  - `POST /v1/alerts/chats/{chat_id}` вызывает `sendText` с `chat_id`, без `login`;
  - на ошибках Yandex 5xx/timeout → 503.
- **Моки Yandex:** через `respx` (перехват HTTPX) — проверка заголовка `Authorization: OAuth ...`, `Content-Type`, body и `payload_id`.

### Property/Regression
- Набор “реальных” входных payload’ов (с приватными данными удалёнными) как fixtures, чтобы не сломать форматирование при изменениях.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| ad-hoc dict parsing | Pydantic models (v2) | 2023+ | меньше багов валидации, проще тестировать |
| без idempotency | `payload_id` для dedup | доступно в Bot API | меньше дублей при ретраях |

## Open Questions

1. **Политика обработки Yandex 4xx (например “Bot is not a member of the chat”)**
   - What we know: Bot API возвращает `{"ok": false, "description": ...}` и HTTP статус (дока говорит “соответствующий статус HTTP”).
   - What's unclear: какие статусы конкретно для каждого кейса, и хотим ли мы ретраить/не ретраить.
   - Recommendation: по умолчанию **не ретраить** (отдавать 200/202 на вход, логировать как permanent failure) и включить флагом `FAIL_ON_YANDEX_4XX=true` строгий режим для “раннего обнаружения”.

2. **Нужна ли очередь/асинхронная доставка**
   - What we know: задача не требует брокера.
   - Recommendation: стартовать без очереди; если понадобятся гарантии/буфер — добавить outbox/queue на следующей фазе.

## Sources

### Primary (HIGH confidence)
- Prometheus Alertmanager configuration (webhook receiver + payload v4): `https://prometheus.io/docs/alerting/latest/configuration/`
- FastAPI HTTP Basic Auth (401 + WWW-Authenticate + realm): `https://fastapi.tiangolo.com/advanced/security/http-basic-auth`
- Yandex Messenger Bot API `sendText` (URL/headers/body/6000 chars + `payload_id`): `https://yandex.ru/dev/messenger/doc/ru/api-requests/message-send-text`
- Alertmanager webhook retry assumptions (2xx ok, 5xx recoverable): `https://github.com/prometheus/alertmanager/blob/main/notify/webhook/webhook.go`

### Secondary (MEDIUM confidence)
- Обсуждение ретраев 5xx vs 4xx (Prometheus Users): `https://groups.google.com/g/prometheus-users/c/9fqrJy-0phI`

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — зрелые библиотеки, официальные доки
- Architecture: HIGH — прямое соответствие требованиям и стандартным паттернам FastAPI/Alertmanager
- Pitfalls: HIGH — подтверждено поведением Alertmanager (исходники/доки) и ограничениями Yandex

**Research date:** 2026-04-09  
**Valid until:** 2026-05-09

