# ARD: Alertmanager -> Yandex Messenger Receiver

## 1. Бизнес-контекст

### Бизнес-задача
- Обеспечить стабильную доставку алертов из Prometheus Alertmanager в Yandex Messenger.
- Гарантировать предсказуемое поведение при ошибках за счет корректной семантики кодов ответа для ретраев Alertmanager.
- Зафиксировать единый и актуальный источник знаний по сервису `receiver`.

### Заказчик/стейкхолдер
- Инициатор: команда эксплуатации/наблюдаемости платформы мониторинга.
- Основные потребители: дежурные инженеры, SRE, разработчики сервисов, подключенных к Alertmanager.

### Customer Journey (оператор/дежурный)
1. Alertmanager формирует webhook payload v4 по событию `firing` или `resolved`.
2. Alertmanager вызывает `receiver` по endpoint для пользователя или чата.
3. `receiver` валидирует Basic Auth и структуру payload.
4. `receiver` форматирует сообщение и отправляет его в Yandex Bot API.
5. При временной ошибке `receiver` возвращает `503`, Alertmanager выполняет retry.
6. При успехе (или permanent 4xx, если configured ignore) `receiver` возвращает `202`.

---

## 2. Границы и scope

### Включено
- Только runtime-сервис `receiver` (`app/*`).
- Вход: Alertmanager webhook v4.
- Выход: Yandex Messenger Bot API `sendText`.
- `receiver` реализует только механизм доставки уведомления и маппинг ошибок/кодов ответа.
- Вся доменная логика формирования набора алертов (grouping, filtering, silencing, routing) остается на стороне Alertmanager.

---

## 3. High-level архитектура

```mermaid
flowchart LR
    AM[Prometheus Alertmanager] -->|POST webhook v4| R[Receiver FastAPI]
    R -->|Basic Auth + Validation + Formatting| R
    R -->|POST sendText| YM[Yandex Messenger Bot API]
    R -->|/metrics| P[Prometheus]
```

Ключевые компоненты `receiver`:
- `app/api/v1/alerts.py` - входные endpoint'ы `/v1/alerts/users/{login}` и `/v1/alerts/chats/{chat_id}`.
- `app/auth/basic.py` - inbound Basic Auth с `WWW-Authenticate`.
- `app/models/alertmanager.py` - строгие типизированные модели payload v4 (`extra=allow` для forward compatibility).
- `app/services/formatters.py` - детерминированный рендер текста + truncation до 6000 символов.
- `app/services/yandex_client.py` - outbound HTTP-клиент к `sendText`, классификация temporary/permanent ошибок.
- `app/metrics.py` - prometheus-метрики.

---

## 4. Принцип работы (to-be / фактическая реализация)

```mermaid
flowchart TD
    A["Webhook request"] --> B{"Basic Auth valid?"}
    B -->|no| C["401 + WWW-Authenticate"]
    B -->|yes| D{"Payload v4 valid?"}
    D -->|no| E["422 validation error"]
    D -->|yes| F["Render text (max 6000 chars)"]
    F --> G["Send to Yandex sendText"]
    G --> H{"Yandex result"}
    H -->|success| I["202 Accepted (ok=true)"]
    H -->|"temporary error (timeout/network/429/5xx)"| J["503 for Alertmanager retry"]
    H -->|"permanent 4xx"| K{"FAIL_ON_YANDEX_4XX"}
    K -->|true| L["422"]
    K -->|false| M["202 Accepted (ok=false)"]
```

### Поведение endpoint'ов
- `POST /v1/alerts/users/{login}` -> outbound `sendText` с `login`.
- `POST /v1/alerts/chats/{chat_id}` -> outbound `sendText` с `chat_id`.
- На успешную обработку возвращается `202` и JSON `{ "ok": bool, "yandex_message_id": int | null }`.
- Сервис не принимает решений о группировке/фильтрации/подавлении уведомлений; он обрабатывает payload, уже подготовленный Alertmanager.

### Retry-контракт
- `2xx` на входе = Alertmanager считает отправку успешной.
- `503` на входе = временная ошибка, Alertmanager повторяет доставку.
- Permanent `4xx` от Yandex по умолчанию не ретраится (`202`, configurable через `FAIL_ON_YANDEX_4XX=true`).

---

## 5. Sequence-диаграмма

```mermaid
sequenceDiagram
    participant AM as Alertmanager
    participant R as Receiver API
    participant F as Formatter
    participant Y as YandexClient
    participant YM as Yandex Bot API

    AM->>R: POST /v1/alerts/... (BasicAuth + payload v4)
    R->>R: check Basic Auth
    R->>R: validate payload model
    R->>F: render_alertmanager_text(payload)
    F-->>R: text (<=6000)
    R->>Y: send_text(target, text, payload_id)
    Y->>YM: POST /bot/v1/messages/sendText
    YM-->>Y: HTTP response
    Y-->>R: success | temporary | permanent
    R-->>AM: 202 | 503 | 422
```

---

## 6. ER-диаграмма (логическая модель данных)

Сервис stateless, постоянного хранилища нет. Ниже логические сущности входного/выходного контракта.

```mermaid
erDiagram
    ALERTMANAGER_WEBHOOK_V4 ||--|{ ALERT_V4 : contains
    ALERTMANAGER_WEBHOOK_V4 {
        string version
        string status
        string groupKey
        string receiver
        int truncatedAlerts
        map groupLabels
        map commonLabels
        map commonAnnotations
        string externalURL
    }
    ALERT_V4 {
        string status
        map labels
        map annotations
        datetime startsAt
        datetime endsAt
        string generatorURL
        string fingerprint
    }
    YANDEX_SENDTEXT_REQUEST {
        string text
        string login
        string chat_id
        string payload_id
    }
    YANDEX_SENDTEXT_RESPONSE {
        bool ok
        int message_id
    }
```

Бизнес-правило:
- В `YANDEX_SENDTEXT_REQUEST` должен быть указан ровно один target: `login` xor `chat_id`.

---

## 7. API и контракты

### Inbound API (`receiver`)
- `POST /v1/alerts/users/{login}`
- `POST /v1/alerts/chats/{chat_id}`
- Auth: HTTP Basic (`BASIC_AUTH_USERNAME`, `BASIC_AUTH_PASSWORD`).
- Body: Alertmanager webhook payload version `4`.

### Outbound API (Yandex)
- `POST {YANDEX_API_BASE}/bot/v1/messages/sendText`
- Header: `Authorization: OAuth <YANDEX_OAUTH_TOKEN>`
- Body: `text`, target (`login` или `chat_id`), `payload_id`.

### Идемпотентность
- `payload_id` формируется детерминированно из `target_kind`, `target_value`, итогового `text` и канонизированного JSON payload (с сортировкой ключей).
- Повтор идентичного сообщения для того же target приводит к идентичному `payload_id`.
- Изменение текста, target или содержимого payload приводит к новому `payload_id`.

---

## 8. Эксплуатация, нагрузка, мониторинг

### Конфигурация (env)
- Обязательные: `BASIC_AUTH_USERNAME`, `BASIC_AUTH_PASSWORD`, `YANDEX_OAUTH_TOKEN`.
- Опциональные: `BASIC_AUTH_REALM`, `YANDEX_API_BASE`, `YANDEX_HTTP_TIMEOUT_SECONDS`, `FAIL_ON_YANDEX_4XX`, шаблоны сообщения и параметры логирования.

### Наблюдаемость
- Healthcheck: `GET /healthz`.
- Метрики: `GET /metrics`.
- Основные счетчики:
  - `receiver_webhook_requests_total`
  - `receiver_webhook_alerts_total`
  - `receiver_yandex_send_total`
  - `receiver_yandex_send_latency_seconds`
  - `receiver_render_failures_total`

### Масштабирование
- Сервис stateless; горизонтально масштабируется через реплики.
- Узкое место при росте нагрузки: outbound канал в Yandex API и его rate limiting (`429`).
- При `503` retry-нагрузка переносится в Alertmanager backoff-механику.

### Нагрузочные целевые показатели (для текущей версии)
- Контекст: один экземпляр `receiver` обслуживает несколько receiver-конфигураций в Alertmanager (разные маршруты/чаты), поэтому нагрузка суммируется на одном ingress.
- Baseline (sustained): `50 RPS` в течение 30 минут без деградации по SLO.
- Peak burst: `120 RPS` в течение 5 минут с контролируемой деградацией (рост `503` допустим в пределах порога).
- Soak: `20-30 RPS` в течение 4-8 часов для проверки стабильности.

Целевые SLO/SLI:
- Inbound success rate (`2xx`): `>=99.5%` на окне 15 минут (исключая осознанные permanent-ошибки доставки).
- Inbound latency: `p50 <120ms`, `p95 <400ms`, `p99 <900ms`.
- Доля ответов `503`: `<1%` в baseline; в peak допускается до `3-5%`.
- `delivery_gap` (принято сервисом, но не доставлено): целевой `0`, допустимо кратковременно `<0.1%`.

Критерий адекватности:
- Решение считается адекватным для production-старта при выполнении baseline + peak без лавинообразного роста ретраев Alertmanager и без устойчивой деградации latency.

---

## 9. Ограничения и особенности

1. Нет собственной очереди/outbox: доставка синхронная в рамках HTTP-запроса.
2. Нет персистентного хранения отправок/дедупа внутри сервиса.
3. `payload_id` рассчитывается на основе канонизированного payload + target + итогового текста; при больших payload это добавляет небольшой CPU-overhead на сериализацию/хэширование.
4. Поведение permanent `4xx` настраивается флагом и может отличаться между окружениями.
5. Ошибка шаблона сообщения не роняет запрос: используется fallback-формат.
6. Шаблонизация сообщения на стороне Alertmanager для `webhook_config` не используется: для webhook receiver это не предусмотрено как механизм message templating, и advanced-паттерны в этом контуре сознательно не применяются на текущем этапе ([Prometheus docs: webhook_config](https://prometheus.io/docs/alerting/latest/configuration/#webhook_config)).

---

## 10. Результаты тестирования (зафиксировано)

Проверка выполнена локально в виртуальном окружении:

- Команда: `.venv/bin/pytest -q`
- Результат: `10 passed in 0.50s`
- Покрытые сценарии:
  - Basic Auth: отсутствующие/неверные креды -> `401` + `WWW-Authenticate`.
  - Endpoint users/chats: корректный вызов outbound `sendText` с нужным target-полем.
  - Error mapping:
    - temporary ошибки Yandex -> `503`;
    - permanent `4xx` -> `202` по умолчанию;
    - permanent `4xx` -> `422` при `FAIL_ON_YANDEX_4XX=true`.
  - Форматирование: детерминизм и ограничение длины до 6000 символов.

---

## 11. Checklist соответствия ARD-процессу

- Бизнес-контекст: зафиксирован.
- Техническое решение и high-level архитектура: зафиксированы.
- Диаграммы: high-level, flowchart, sequence, ER.
- Сущности и API контракты: зафиксированы.
- Эксплуатационные комментарии: добавлены (конфиг, мониторинг, масштабирование, ограничения).
- Результаты тестирования: зафиксированы с фактическим запуском.

---

## 12. Open items для финализации в `deploy/service/.doc`

Для полного соответствия корпоративному шаблону перед переносом в единый репозиторий документации нужно уточнить:
- Конкретного бизнес-заказчика (роль/команда/ФИО).
- Целевые SLO/SLA по доставке и допустимой задержке.
- Финальную политику по permanent `4xx` (глобально для всех окружений или per-env).
- Требования к аудиту отправок (нужна ли персистентная история доставки).
