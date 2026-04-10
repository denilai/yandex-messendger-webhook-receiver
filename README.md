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

## Локальный стенд (docker-compose): интеграционные тесты

Поднимает 3 сервиса:

- `receiver` (наш сервис)
- `alertmanager` (шлёт webhooks в `receiver`)
- `mock-yandex` (принимает `sendText` вместо настоящего Yandex API)

Запуск:

```bash
docker compose up -d --build
docker compose ps
```

С переопределением env через файл:

```bash
docker compose --env-file .env.real up -d --force-recreate
```

Debug-логи (включая отправляемый JSON в Yandex) проще всего включить так:

```bash
LOG_LEVEL=DEBUG docker compose up -d --force-recreate receiver
docker compose logs -f receiver
```

Проверить, что всё живо:

```bash
curl -i http://localhost:8081/healthz
curl -i http://localhost:18080/_last
```

### Сгенерировать алерты (точечно / массово)

Сервис `alert-generator` собран как контейнер. Его можно запускать on-demand:

```bash
# 1 алерт в чат (matchers am_target="chat" → receiver /v1/alerts/chats/123)
docker compose --profile tools run --rm alert-generator --mode single --count 1 --target chat

# много алертов, чтобы проверить группировку
docker compose --profile tools run --rm alert-generator --mode burst --count 200 --target chat --group-key HighErrorRate

# много уникальных алертов (без группировки по alertname)
docker compose --profile tools run --rm alert-generator --mode spray --count 200 --target chat --group-key HighErrorRate

# резолв (проверить resolved нотификации)
docker compose --profile tools run --rm alert-generator --mode single --count 1 --target chat --status resolved
```

Проверка, что receiver реально вызвал sendText:

```bash
curl -s http://localhost:18080/_last | python -m json.tool
```

### Негативные сценарии (ретраи)

Можно заставить `mock-yandex` возвращать 500/429, чтобы receiver отвечал `503` и Alertmanager ретраил.
Для этого поменяй `MOCK_YANDEX_MODE` в `docker-compose.yml` на `always_500` / `always_429` / `random_500` / `random_429` и перезапусти:

```bash
docker compose up -d --build mock-yandex receiver
```

## Нагрузочные прогоны (vegeta)

Самый простой способ без установки на хост — использовать `vegeta` в контейнере.
Пример direct-нагрузки на receiver: см. `tools/load/README.md`.

## Real Yandex (ручная проверка)

Чтобы проверить доставку в настоящий Yandex Messenger Bot API:

1) Остановить mock или просто переключить receiver на реальный base URL:\n
- `YANDEX_API_BASE=https://botapi.messenger.yandex.net`
- `YANDEX_OAUTH_TOKEN=<real token>`

2) Запустить receiver (локально или через compose) и сгенерировать `single` алерт как выше.

> Для нагрузочных прогонов рекомендуется оставаться на mock, чтобы не упираться в сеть/лимиты внешнего API.

