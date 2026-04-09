---
phase: 01-alertmanager-yandex-receiver
plan: 02
type: execute
wave: 1
depends_on: []
files_modified:
  - pyproject.toml
  - README.md
  - app/__init__.py
  - app/main.py
  - app/api/__init__.py
  - app/api/v1/__init__.py
  - app/api/v1/alerts.py
  - app/auth/__init__.py
  - app/auth/basic.py
  - app/config/__init__.py
  - app/config/settings.py
  - app/models/__init__.py
  - app/models/alertmanager.py
  - app/models/yandex.py
  - app/services/__init__.py
  - app/services/formatters.py
  - app/services/yandex_client.py
  - tests/conftest.py
  - tests/fixtures/alertmanager_v4_valid.json
  - tests/test_auth.py
  - tests/test_formatting.py
  - tests/test_api.py
autonomous: true

must_haves:
  truths:
    - "Сервис принимает webhook Alertmanager v4 на POST /v1/alerts/users/{login} и доставляет сообщение в Yandex sendText по login."
    - "Сервис принимает webhook Alertmanager v4 на POST /v1/alerts/chats/{chat_id} и доставляет сообщение в Yandex sendText по chat_id."
    - "При неверных/отсутствующих Basic Auth кредах сервис отвечает 401 и включает заголовок WWW-Authenticate: Basic (с realm)."
    - "Текст сообщения формируется детерминированно и не превышает 6000 символов (корректное усечение)."
    - "При временных сбоях доставки в Yandex (timeout/network/429/5xx) входящий webhook получает 503, чтобы Alertmanager мог ретраить."
    - "Конфигурация берётся из env: inbound basic user/pass + yandex oauth token."
    - "Есть README с примерами curl и примером Alertmanager receiver-конфига."
    - "Есть unit-тесты минимум для форматтера и Basic Auth; outbound Yandex замокирован."
  artifacts:
    - path: "app/main.py"
      provides: "FastAPI app + подключение роутов v1"
    - path: "app/api/v1/alerts.py"
      provides: "POST /v1/alerts/users/{login} и /v1/alerts/chats/{chat_id}"
    - path: "app/auth/basic.py"
      provides: "Basic Auth dependency (401 + WWW-Authenticate)"
    - path: "app/models/alertmanager.py"
      provides: "Pydantic модели Alertmanager webhook v4"
    - path: "app/services/formatters.py"
      provides: "render_alertmanager_text(text<=6000) детерминированно"
    - path: "app/services/yandex_client.py"
      provides: "HTTPX клиент Yandex sendText (OAuth header, timeout, error mapping)"
    - path: "README.md"
      provides: "Инструкция запуска, env, curl, пример Alertmanager receiver"
    - path: "tests/test_auth.py"
      provides: "Тесты 401 + WWW-Authenticate"
    - path: "tests/test_formatting.py"
      provides: "Тесты лимита 6000 и детерминизма форматирования"
    - path: "tests/test_api.py"
      provides: "Тесты эндпоинтов + моки outbound Yandex"
  key_links:
    - from: "app/api/v1/alerts.py"
      to: "app/auth/basic.py"
      via: "FastAPI Depends(require_basic_auth)"
      pattern: "Depends\\(require_basic_auth\\)"
    - from: "app/api/v1/alerts.py"
      to: "app/models/alertmanager.py"
      via: "request body model"
      pattern: "AlertmanagerWebhookV4"
    - from: "app/api/v1/alerts.py"
      to: "app/services/formatters.py"
      via: "rendering function"
      pattern: "render_.*\\("
    - from: "app/api/v1/alerts.py"
      to: "app/services/yandex_client.py"
      via: "send_text call"
      pattern: "send_text"
    - from: "app/services/yandex_client.py"
      to: "Yandex Bot API"
      via: "HTTPX POST"
      pattern: "Authorization.*OAuth"
---

<objective>
Реализовать сервис-приёмник webhook Alertmanager v4 с Basic Auth на входе и отправкой уведомлений в Yandex Messenger Bot API методом sendText.

Purpose: обеспечить доставку алертов из Alertmanager в Yandex (пользователю по login или в чат по chat_id) с корректными статус-кодами для ретраев.
Output: рабочий FastAPI сервис (2 эндпоинта), строгая валидация входного JSON, форматирование текста ≤6000, httpx-клиент Yandex, unit-тесты и README.
</objective>

<execution_context>
@~/.cursor/get-shit-done/workflows/execute-plan.md
@~/.cursor/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/01-alertmanager-yandex-receiver/01-RESEARCH.md
</context>

<tasks>

<task type="auto">
  <name>Task 1: Каркас FastAPI + env-конфиг + модели Alertmanager v4 + 2 эндпоинта + клиент Yandex sendText</name>
  <files>
pyproject.toml
app/main.py
app/api/v1/alerts.py
app/auth/basic.py
app/config/settings.py
app/models/alertmanager.py
app/models/yandex.py
app/services/formatters.py
app/services/yandex_client.py
  </files>
  <action>
Создать проект с нуля (репозиторий пустой), целевой стек: Python 3.12 + FastAPI + Pydantic v2 + HTTPX.

1) Dependency management:
   - Создать `pyproject.toml` (PEP 621) с зависимостями:
     - runtime: `fastapi`, `uvicorn[standard]`, `pydantic`, `pydantic-settings`, `httpx`
     - test: `pytest`, `respx`
   - В `pyproject.toml` настроить `pytest` (minversion, addopts) так, чтобы `pytest` запускался без доп. флагов.

2) Typed settings (env config):
   - В `app/config/settings.py` реализовать `Settings` на базе `pydantic-settings`:
     - `basic_auth_username: str`
     - `basic_auth_password: str`
     - `basic_auth_realm: str = "alertmanager-webhook"`
     - `yandex_oauth_token: str`
     - `yandex_api_base: str = "https://botapi.messenger.yandex.net"`
     - `yandex_http_timeout_seconds: float = 5.0`
     - `fail_on_yandex_4xx: bool = False` (см. исследование: по умолчанию не ретраить permanent 4xx)
   - Предусмотреть единый способ получить settings (например, cached dependency).

3) Inbound auth (Basic Auth):
   - В `app/auth/basic.py` реализовать dependency `require_basic_auth(...)` через `fastapi.security.HTTPBasic`.
   - Обязательно:
     - сравнение `secrets.compare_digest`
     - при неверных/отсутствующих кредах — `HTTPException(401)` + `headers={"WWW-Authenticate": 'Basic realm="..."'}`.
   - Dependency должна быть легко применима к обоим эндпоинтам.

4) Alertmanager webhook v4 models (strict JSON):
   - В `app/models/alertmanager.py` описать Pydantic v2 модели, минимум:
     - корневой payload с `version: Literal["4"]`, `status: Literal["firing","resolved"]`, `groupKey`, `receiver`, `truncatedAlerts`, `groupLabels`, `commonLabels`, `commonAnnotations`, `externalURL: str|None`, `alerts: list[Alert]`
     - `Alert`: `status`, `labels`, `annotations`, `startsAt`, `endsAt`, `generatorURL: str|None`, `fingerprint: str|None`
   - Требование “строгий JSON” трактовать как:
     - строгие типы для известных полей (datetime/str/int/literals)
     - отклонять некорректные типы/форматы (Pydantic даст 422)
     - при этом оставить forward-compatibility: `extra="allow"` на моделях (как в research), чтобы новые поля Alertmanager не ломали приём.

5) Text formatter (≤ 6000):
   - В `app/services/formatters.py` реализовать функцию (или класс) `render_alertmanager_text(payload: AlertmanagerWebhookV4) -> str`:
     - шаблон близкий к предложенному в research (FIRING/RESOLVED, alertname, summary/description, group/common labels, список первых K алертов, externalURL, groupKey)
     - детерминированность: стабильный порядок вывода словарей (например, сортировка ключей), фиксированный K (например 3 или 5)
     - жёсткий лимит 6000 символов: если больше — обрезать и добавить суффикс `"\n\n… (truncated to 6000 chars)"`

6) Yandex sendText models + client:
   - В `app/models/yandex.py` описать модели request/response для sendText:
     - request: `text: str`, `login: str|None`, `chat_id: str|None`, `payload_id: str|None`
     - enforce: “ровно один из login/chat_id” (валидация на модели или на уровне вызова клиента)
   - В `app/services/yandex_client.py` реализовать async клиент на `httpx.AsyncClient`:
     - базовый URL из `Settings.yandex_api_base`
     - endpoint sendText согласно research (использовать путь из docs в research; если в docs указан полный URL — сохранить совместимость через base+path)
     - заголовки: `Authorization: OAuth <token>`, `Content-Type: application/json`
     - таймаут через `httpx.Timeout(...)` на основе env
     - обработка ошибок:
       - network/timeout → выбрасывать доменное исключение “temporary” для маппинга в 503
       - 429/5xx → “temporary”
       - 4xx → “permanent” (но дальнейшая политика определяется `fail_on_yandex_4xx`)
     - возвращать `message_id` если Yandex ответил `ok=true`.
   - `payload_id` сформировать детерминированно (минимум): `sha256(groupKey + "|" + status + "|" + receiver)` и/или включить хеш ключевых полей; важно: стабильный результат для одинаковых входов (см. research про дедуп).

7) API endpoints:
   - В `app/api/v1/alerts.py` реализовать:
     - `POST /v1/alerts/users/{login}`:
       - auth dependency обязательна
       - body: `AlertmanagerWebhookV4`
       - форматировать текст, вызвать `send_text(login=login, chat_id=None, text=...)`
     - `POST /v1/alerts/chats/{chat_id}`:
       - аналогично, но `chat_id=...`
   - Маппинг статусов на вход:
     - auth fail → 401 + WWW-Authenticate
     - invalid payload → 422 (стандарт FastAPI/Pydantic)
     - ошибки доставки “temporary” (timeout/network/429/5xx) → 503
     - ошибки доставки “permanent 4xx”:
       - если `fail_on_yandex_4xx=false` → вернуть 202 (и логировать), чтобы Alertmanager не ретраил бесконечно
       - если `true` → вернуть 422/400 (но НЕ 5xx) — ретраи не помогут
   - Ответ при успехе: 202 + JSON вида `{"ok": true, "yandex_message_id": <id|null>}` (или 200 — но придерживаться 202 как “accepted”).

8) App wiring:
   - В `app/main.py` создать `FastAPI(title=..., version=...)`, подключить router `/v1`.
   - Добавить health endpoint `GET /healthz` (без auth) для простоты проверок.

Не добавлять очереди/внутренние ретраи по умолчанию (см. research), но обеспечить корректное различение temporary/permanent ошибок.
  </action>
  <verify>
python -m venv .venv
. .venv/bin/activate
pip install -U pip
pip install -e ".[test]"
python -c "import app; import app.main"
python -c "from app.models.alertmanager import AlertmanagerWebhookV4; print(AlertmanagerWebhookV4.model_validate({'version':'4','status':'firing','groupKey':'g','receiver':'r','truncatedAlerts':0,'groupLabels':{},'commonLabels':{},'commonAnnotations':{},'externalURL':None,'alerts':[]}).version)"
  </verify>
  <done>
- Приложение импортируется, OpenAPI генерируется, `GET /healthz` отвечает 200.
- Оба POST эндпоинта существуют и принимают body как Pydantic-модель Alertmanager v4 (invalid payload → 422).
- Basic Auth при неверных кредах всегда возвращает 401 и включает `WWW-Authenticate: Basic realm="..."`.
- Форматтер гарантирует `len(text) <= 6000` и добавляет суффикс при усечении.
- Клиент Yandex формирует запрос с `Authorization: OAuth ...` и различает temporary/permanent ошибки.
  </done>
</task>

<task type="auto">
  <name>Task 2: Unit/contract тесты (auth, форматирование, API) с моками outbound Yandex</name>
  <files>
tests/conftest.py
tests/fixtures/alertmanager_v4_valid.json
tests/test_auth.py
tests/test_formatting.py
tests/test_api.py
  </files>
  <action>
Добавить тестовый набор на pytest с минимально достаточным покрытием требований.

1) Fixtures:
   - Создать `tests/fixtures/alertmanager_v4_valid.json` — валидный payload Alertmanager v4 (минимум поля из модели) + 1–2 alerts с labels/annotations/startsAt/endsAt.
   - В `tests/conftest.py` добавить fixture, которая читает JSON и валидирует через `AlertmanagerWebhookV4` (гарантия, что фикстура соответствует модели).

2) Auth tests:
   - В `tests/test_auth.py` через FastAPI TestClient/HTTPX (встроенный в FastAPI) проверить:
     - без Authorization → 401 + `WWW-Authenticate` присутствует и содержит `Basic`
     - с неверными кредами → 401 + `WWW-Authenticate`
     - с верными кредами → запрос проходит до обработчика (для этого можно замокать Yandex outbound, чтобы endpoint мог завершиться)

3) Formatting tests:
   - В `tests/test_formatting.py` проверить:
     - детерминированность: два вызова `render_alertmanager_text` на одном payload дают одинаковую строку
     - лимит: с payload, который создаёт очень длинный текст (например, много alerts и длинные annotations), результат `<= 6000` и содержит маркер `(truncated to 6000 chars)`

4) API tests + outbound mock:
   - В `tests/test_api.py` использовать `respx` для мока HTTPX:
     - при `POST /v1/alerts/users/{login}` проверить, что outbound вызывается и body содержит `login`, отсутствует `chat_id`, `text` не пустой, `payload_id` присутствует
     - при `POST /v1/alerts/chats/{chat_id}` аналогично для `chat_id`
     - симулировать временную ошибку:
       - timeout/ConnectError или ответ Yandex 503/429 → inbound ответ 503
     - симулировать permanent 4xx:
       - ответ Yandex 403/400 → при `fail_on_yandex_4xx=false` inbound 202 (и в JSON `ok` может быть true/false по выбранной реализации, но главное: НЕ 5xx)

Важно: outbound Yandex всегда мокируется (никаких реальных сетевых вызовов в тестах).
  </action>
  <verify>
. .venv/bin/activate
pytest -q
  </verify>
  <done>
- Есть тесты, которые подтверждают: 401+WWW-Authenticate, корректное форматирование/усечение, вызов outbound Yandex с правильными полями для обоих эндпоинтов.
- Тесты изолированы (нет реального HTTP наружу).
  </done>
</task>

<task type="auto">
  <name>Task 3: README (запуск, env, curl, пример Alertmanager receiver)</name>
  <files>README.md</files>
  <action>
Сделать минимальную, но практичную документацию:

1) Quickstart:
   - требования: Python 3.12
   - установка: venv + `pip install -e ".[test]"`
   - запуск: `uvicorn app.main:app --host 0.0.0.0 --port 8080`

2) Env vars:
   - перечислить минимум: `BASIC_AUTH_USERNAME`, `BASIC_AUTH_PASSWORD`, `YANDEX_OAUTH_TOKEN`
   - опционально: `BASIC_AUTH_REALM`, `YANDEX_API_BASE`, `YANDEX_HTTP_TIMEOUT_SECONDS`, `FAIL_ON_YANDEX_4XX`
   - показать пример `.env` (без секретов, только placeholders)

3) Примеры curl:
   - `POST /v1/alerts/users/{login}` и `POST /v1/alerts/chats/{chat_id}`
   - обязательно с `-u user:pass`, `-H 'Content-Type: application/json'`, `--data @tests/fixtures/alertmanager_v4_valid.json`
   - ожидаемые коды: 202 на успех, 401 на auth fail

4) Пример конфигурации Alertmanager receiver:
   - показать пример `receivers:` с `webhook_configs:`:
     - `url: http://<host>:8080/v1/alerts/users/<login>` (или chats/<chat_id>)
     - указать как добавить basic auth (в Alertmanager это делается через `http_config` / `basic_auth` — взять формулировку и ключи из оф. доки Alertmanager, чтобы YAML был корректным)

5) Коротко про семантику ретраев:
   - описать: 2xx = success, 503 = временная ошибка для ретраев Alertmanager.
  </action>
  <verify>
. .venv/bin/activate
python -m pip install -e ".[test]"
python -c "import pathlib; print((pathlib.Path('README.md').read_text(encoding='utf-8')[:200]))"
  </verify>
  <done>
- README содержит: быстрый старт, env vars, 2 curl-примера, пример Alertmanager receiver-конфига и пояснение по кодам ответов.
  </done>
</task>

</tasks>

<verification>
- `pytest -q` проходит.
- Ручная sanity-проверка локально:
  - Запустить `uvicorn app.main:app --port 8080`
  - `curl -i http://localhost:8080/healthz` → 200
  - `curl -i -u bad:creds -H 'Content-Type: application/json' --data @tests/fixtures/alertmanager_v4_valid.json http://localhost:8080/v1/alerts/users/test` → 401 + WWW-Authenticate
</verification>

<success_criteria>
- Реализованы оба эндпоинта с Basic Auth и строгой валидацией Alertmanager v4.
- Сообщения форматируются детерминированно и не превышают 6000 символов.
- Outbound в Yandex отправляется через HTTPX с OAuth токеном; временные ошибки мапятся в 503 наружу.
- Есть README с curl и примером конфигурации Alertmanager.
- Есть минимальные unit-тесты (format/auth) и тесты API с моками Yandex.
</success_criteria>

<output>
After completion, create `.planning/phases/01-alertmanager-yandex-receiver/01-02-SUMMARY.md`
</output>

