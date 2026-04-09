# Alertmanager → Yandex Messenger receiver

Небольшой сервис на **FastAPI**, который принимает webhook от **Prometheus Alertmanager (payload v4)** и доставляет сообщение в **Yandex Messenger Bot API** методом `sendText`.

## Быстрый старт

Требования: **Python 3.12**

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -U pip
pip install -r requirements.txt
```

Запуск:

```bash
export BASIC_AUTH_USERNAME=user
export BASIC_AUTH_PASSWORD=pass
export YANDEX_OAUTH_TOKEN=token

uvicorn app.main:app --host 0.0.0.0 --port 8080
```

Проверка:

```bash
curl -i http://localhost:8080/healthz
```

## Переменные окружения

Обязательные:

- `BASIC_AUTH_USERNAME`
- `BASIC_AUTH_PASSWORD`
- `YANDEX_OAUTH_TOKEN`

Опциональные:

- `BASIC_AUTH_REALM` (по умолчанию `alertmanager-webhook`)
- `YANDEX_API_BASE` (по умолчанию `https://botapi.messenger.yandex.net`)
- `YANDEX_HTTP_TIMEOUT_SECONDS` (по умолчанию `5.0`)
- `FAIL_ON_YANDEX_4XX` (по умолчанию `false`)

## Примеры curl

Отправка пользователю (по `login`):

```bash
curl -i \
  -u user:pass \
  -H 'Content-Type: application/json' \
  --data @tests/fixtures/alertmanager_v4_valid.json \
  http://localhost:8080/v1/alerts/users/test
```

Отправка в чат (по `chat_id`):

```bash
curl -i \
  -u user:pass \
  -H 'Content-Type: application/json' \
  --data @tests/fixtures/alertmanager_v4_valid.json \
  http://localhost:8080/v1/alerts/chats/123
```

Ожидаемые коды:

- `202` — принято (доставлено или зафиксирована permanent-ошибка без ретраев)
- `401` — неверные/отсутствующие креды Basic Auth (с `WWW-Authenticate: Basic realm="..."`)
- `503` — временная ошибка доставки в Yandex (Alertmanager может ретраить)

## Пример Alertmanager receiver

Пример (ориентир; точные ключи см. в официальной документации Alertmanager в разделе `webhook_configs`):

```yaml
receivers:
  - name: yandex
    webhook_configs:
      - url: "http://receiver:8080/v1/alerts/users/test"
        http_config:
          basic_auth:
            username: "user"
            password: "pass"
```

## Семантика ретраев

- **2xx** на входящем webhook означает успех для Alertmanager.
- **5xx** (например `503`) означает временную ошибку — Alertmanager будет ретраить с backoff.

